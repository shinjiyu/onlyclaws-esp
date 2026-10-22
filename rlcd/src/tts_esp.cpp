#include "tts_esp.h"

#include "oc_features.h"
#include "tts_voice.h"

#if OC_HAS_TTS

#include <Arduino.h>
#include <esp_heap_caps.h>
#include <string.h>

#include "audio_es8311.h"
#include "audio_plugin.h"
#include "esp_tts.h"
#include "esp_tts_voice_template.h"

extern "C" {
extern const uint8_t voice_xiaoxin_start[];
extern const uint8_t voice_xiaoxin_end[];
}

namespace {

esp_tts_handle_t gTts = nullptr;
bool gInitTried = false;
int16_t *gOut = nullptr;
size_t gOutCap = 0;
bool gBusy = false;

bool ensureTts() {
  if (gTts) return true;
  if (gInitTried) return false;
  gInitTried = true;
  const size_t n = (size_t)(voice_xiaoxin_end - voice_xiaoxin_start);
  Serial.printf("[tts] voice %u bytes\n", (unsigned)n);
  if (n < 1024) {
    Serial.println("[tts] voice blob missing");
    return false;
  }
  esp_tts_voice_t *voice =
      esp_tts_voice_set_init(&esp_tts_voice_template, (void *)voice_xiaoxin_start);
  if (!voice) {
    Serial.println("[tts] voice init failed");
    return false;
  }
  gTts = esp_tts_create(voice);
  if (!gTts) Serial.println("[tts] create failed");
  return gTts != nullptr;
}

bool ensureOut(size_t samples) {
  if (gOut && gOutCap >= samples) return true;
  int16_t *p = (int16_t *)heap_caps_malloc(samples * sizeof(int16_t),
                                           MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!p) p = (int16_t *)malloc(samples * sizeof(int16_t));
  if (!p) return false;
  free(gOut);
  gOut = p;
  gOutCap = samples;
  return true;
}

}  // namespace

bool ttsSpeak(const char *text, const char *voiceName) {
  TtsVoiceId id = TTS_VOICE_GIRL;
  if (!ttsParseVoice(voiceName, &id)) {
    Serial.printf("[tts] unknown voice\n");
    return false;
  }
  return ttsSpeakTuned(text, ttsTuneDefaults(id));
}

namespace {

void raiseToTarget(int16_t *buf, size_t n, int32_t *peakOut, int32_t *gainOut) {
  int32_t peak = 0;
  for (size_t i = 0; i < n; ++i) {
    const int32_t a = buf[i] < 0 ? -(int32_t)buf[i] : (int32_t)buf[i];
    if (a > peak) peak = a;
  }
  constexpr int32_t kTarget = 28000;
  constexpr int32_t kMaxGain = 8;
  int32_t gain = 1;
  if (peak > 0) {
    gain = kTarget / peak;
    if (gain < 1) gain = 1;
    if (gain > kMaxGain) gain = kMaxGain;
    if (gain > 1) {
      for (size_t i = 0; i < n; ++i) {
        int32_t s = (int32_t)buf[i] * gain;
        if (s > 32767) s = 32767;
        if (s < -32768) s = -32768;
        buf[i] = (int16_t)s;
      }
    }
  }
  if (peakOut) *peakOut = peak;
  if (gainOut) *gainOut = gain;
}

}  // namespace

bool ttsSpeakTuned(const char *text, const TtsTune &requested) {
  if (!text || !text[0]) return false;
  if (gBusy) return false;
  if (!audioPluginReady()) {
    Serial.println("[tts] audio not ready");
    return false;
  }
  if (!ensureTts()) return false;

  const TtsTune tune =
      ttsClampTune(requested.speed, requested.pitch, requested.stretch, requested.volumeDb);

  gBusy = true;
  const bool parsed = esp_tts_parse_chinese(gTts, text) != 0;
  if (!parsed) {
    Serial.printf("[tts] parse failed\n");
    esp_tts_stream_reset(gTts);
    gBusy = false;
    return false;
  }

  constexpr size_t kMaxSrc = 16000 * 12;
  int16_t *src = (int16_t *)heap_caps_malloc(kMaxSrc * sizeof(int16_t),
                                             MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!src) src = (int16_t *)malloc(kMaxSrc * sizeof(int16_t));
  if (!src) {
    esp_tts_stream_reset(gTts);
    gBusy = false;
    return false;
  }

  size_t n = 0;
  while (n < kMaxSrc) {
    int len = 0;
    short *pcm = esp_tts_stream_play(gTts, &len, tune.speed);
    if (len <= 0 || !pcm) break;
    size_t take = (size_t)len;
    if (n + take > kMaxSrc) take = kMaxSrc - n;
    memcpy(src + n, pcm, take * sizeof(int16_t));
    n += take;
    if ((size_t)len > take) break;
  }
  esp_tts_stream_reset(gTts);

  bool ok = false;
  int16_t *pitched = nullptr;
  int16_t *play = src;
  size_t playN = n;
  const bool shift = tune.pitch < 0.985f || tune.pitch > 1.015f;
  if (shift && n > 0) {
    const size_t need = ttsPitchOutCount(n, tune.pitch);
    pitched = (int16_t *)heap_caps_malloc(need * sizeof(int16_t),
                                          MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!pitched) pitched = (int16_t *)malloc(need * sizeof(int16_t));
    if (!pitched) {
      Serial.println("[tts] empty or no ram");
      free(src);
      gBusy = false;
      return false;
    }
    playN = ttsPitchShift(src, n, tune.pitch, pitched, need);
    play = pitched;
  }

  if (playN > 0 && tune.stretch >= 2) {
    const size_t stretchCap = playN * 2 + 512;
    if (!ensureOut(stretchCap)) {
      Serial.println("[tts] empty or no ram");
      free(pitched);
      free(src);
      gBusy = false;
      return false;
    }
    playN = ttsTimeStretch2x(play, playN, gOut, gOutCap);
    play = gOut;
  }

  if (playN > 0) {
    int32_t peak = 0;
    int32_t gain = 1;
    raiseToTarget(play, playN, &peak, &gain);
    Serial.printf("[tts] spd=%d pitch=%.2f stretch=%d vol=%d src=%u play=%u peak=%d gain=%d\n",
                  tune.speed, tune.pitch, tune.stretch, tune.volumeDb, (unsigned)n,
                  (unsigned)playN, (int)peak, (int)gain);
    audioSetDacVolume(ttsDacFromDb(tune.volumeDb));
    ok = audioPlayPcm(play, playN);
    audioSetDacVolume(0x9A);
  } else {
    Serial.println("[tts] empty or no ram");
  }
  free(pitched);
  free(src);
  gBusy = false;
  return ok;
}

void ttsBootDemo() {
  Serial.println("[tts] boot girl");
  ttsSpeak("我是童女", "girl");
  delay(180);
  Serial.println("[tts] boot boy");
  ttsSpeak("我是童男", "boy");
}

void ttsSerialPoll() {
  static char line[192];
  static size_t n = 0;
  while (Serial.available() > 0) {
    const int c = Serial.read();
    if (c < 0) break;
    if (c == '\r') continue;
    if (c != '\n') {
      if (n + 1 < sizeof(line)) line[n++] = (char)c;
      continue;
    }
    line[n] = 0;
    n = 0;
    if (strncmp(line, "say", 3) != 0) continue;
    const char *rest = line + 3;
    if (*rest != ' ' && *rest != 0) continue;
    while (*rest == ' ') ++rest;
    if (!*rest) continue;

    char tok[32];
    size_t i = 0;
    while (rest[i] && rest[i] != ' ' && i + 1 < sizeof(tok)) {
      tok[i] = rest[i];
      ++i;
    }
    tok[i] = 0;
    const char *text = rest;
    const char *voice = "girl";
    TtsVoiceId id;
    if (rest[i] == ' ' && ttsParseVoice(tok, &id)) {
      voice = tok;
      text = rest + i + 1;
      while (*text == ' ') ++text;
    }
    if (!*text) continue;
    ttsSpeak(text, voice);
  }
}

#else

bool ttsSpeak(const char *text, const char *voice) {
  (void)text;
  (void)voice;
  return false;
}

bool ttsSpeakTuned(const char *text, const TtsTune &tune) {
  (void)text;
  (void)tune;
  return false;
}

void ttsBootDemo() {}
void ttsSerialPoll() {}

#endif
