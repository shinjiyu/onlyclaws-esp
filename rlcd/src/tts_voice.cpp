#include "tts_voice.h"

#include <stdint.h>
#include <string.h>

namespace {

void lowerAscii(char *s) {
  for (; *s; ++s) {
    if (*s >= 'A' && *s <= 'Z') *s = (char)(*s - 'A' + 'a');
  }
}

bool isBoy(const char *s) {
  return !strcmp(s, "boy") || !strcmp(s, "tongnan") || !strcmp(s, "male") ||
         !strcmp(s, "童男");
}

bool isGirl(const char *s) {
  return !strcmp(s, "girl") || !strcmp(s, "tongnv") || !strcmp(s, "female") ||
         !strcmp(s, "xiaoxin") || !strcmp(s, "童女");
}

}  // namespace

bool ttsParseVoice(const char *name, TtsVoiceId *out) {
  if (!out) return false;
  if (!name || !name[0]) {
    *out = TTS_VOICE_GIRL;
    return true;
  }
  char buf[32];
  size_t n = 0;
  while (name[n] && n + 1 < sizeof(buf)) {
    buf[n] = name[n];
    ++n;
  }
  if (name[n]) return false;
  buf[n] = 0;
  lowerAscii(buf);
  if (isBoy(buf)) {
    *out = TTS_VOICE_BOY;
    return true;
  }
  if (isGirl(buf)) {
    *out = TTS_VOICE_GIRL;
    return true;
  }
  return false;
}

float ttsPitchRatio(TtsVoiceId id) {
  return id == TTS_VOICE_BOY ? 0.78f : 1.19f;
}

namespace {

int clampInt(int v, int lo, int hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

}  // namespace

TtsTune ttsTuneDefaults(TtsVoiceId id) {
  TtsTune t;
  if (id == TTS_VOICE_BOY) {
    t.speed = 4;
    t.pitch = ttsPitchRatio(id);
    t.stretch = 2;
    t.volumeDb = -12;
    return t;
  }
  t.speed = 2;
  t.pitch = ttsPitchRatio(id);
  t.stretch = 1;
  t.volumeDb = -10;
  return t;
}

TtsTune ttsClampTune(int speed, float pitch, int stretch, int volumeDb) {
  TtsTune t;
  t.speed = clampInt(speed, 0, 5);
  if (!(pitch > 0.f)) pitch = 1.f;
  if (pitch < 0.70f) pitch = 0.70f;
  if (pitch > 1.40f) pitch = 1.40f;
  t.pitch = pitch;
  t.stretch = stretch <= 1 ? 1 : 2;
  t.volumeDb = clampInt(volumeDb, -36, 0);
  return t;
}

uint8_t ttsDacFromDb(int volumeDb) {
  volumeDb = clampInt(volumeDb, -36, 0);
  const int steps = (-volumeDb) * 2;
  int reg = 0xBF - steps;
  if (reg < 0) reg = 0;
  if (reg > 0xBF) reg = 0xBF;
  return (uint8_t)reg;
}

size_t ttsPitchOutCount(size_t nIn, float ratio) {
  if (nIn == 0 || !(ratio > 0.f)) return 0;
  if (nIn == 1) return 1;
  return (size_t)((double)(nIn - 1) / (double)ratio) + 1;
}

size_t ttsPitchShift(const int16_t *in, size_t nIn, float ratio, int16_t *out,
                     size_t outCap) {
  if (!in || !out || outCap == 0) return 0;
  size_t need = ttsPitchOutCount(nIn, ratio);
  if (need > outCap) need = outCap;
  if (nIn == 0) return 0;
  for (size_t i = 0; i < need; ++i) {
    const double pos = (double)i * (double)ratio;
    size_t i0 = (size_t)pos;
    if (i0 >= nIn - 1) {
      out[i] = in[nIn - 1];
      continue;
    }
    const double frac = pos - (double)i0;
    double s = (1.0 - frac) * (double)in[i0] + frac * (double)in[i0 + 1];
    if (s > 32767.0) s = 32767.0;
    if (s < -32768.0) s = -32768.0;
    out[i] = (int16_t)s;
  }
  return need;
}

size_t ttsTimeStretch2x(const int16_t *in, size_t nIn, int16_t *out, size_t outCap) {
  // Synthesis hop is twice the analysis hop, so the waveform period stays put
  // while the utterance lasts twice as long.
  constexpr int kWin = 480;
  constexpr int kSynthHop = 320;
  constexpr int kAnaHop = 160;
  constexpr int kOverlap = kWin - kSynthHop;
  constexpr int kSeek = 80;
  if (!in || !out || nIn < (size_t)kWin || outCap < (size_t)kWin) return 0;

  memcpy(out, in, (size_t)kWin * sizeof(int16_t));
  size_t outN = (size_t)kWin;
  size_t ana = 0;
  while (outN + (size_t)kSynthHop <= outCap) {
    const size_t ideal = ana + (size_t)kAnaHop;
    if (ideal + (size_t)kSeek + (size_t)kWin > nIn) break;
    int bestD = 0;
    int64_t best = INT64_MIN;
    for (int d = -kSeek; d <= kSeek; d += 4) {
      const int pos = (int)ideal + d;
      if (pos < 0 || (size_t)pos + (size_t)kWin > nIn) continue;
      int64_t score = 0;
      for (int i = 0; i < kOverlap; i += 4) {
        score += (int32_t)out[outN - (size_t)kOverlap + (size_t)i] *
                 (int32_t)in[(size_t)pos + (size_t)i];
      }
      if (score > best) {
        best = score;
        bestD = d;
      }
    }
    const size_t pos = (size_t)((int)ideal + bestD);
    for (int i = 0; i < kOverlap; ++i) {
      const int32_t mixed =
          ((kOverlap - i) * (int32_t)out[outN - (size_t)kOverlap + (size_t)i] +
           i * (int32_t)in[pos + (size_t)i]) /
          kOverlap;
      out[outN - (size_t)kOverlap + (size_t)i] = (int16_t)mixed;
    }
    for (int i = kOverlap; i < kWin; ++i) {
      out[outN - (size_t)kOverlap + (size_t)i] = in[pos + (size_t)i];
    }
    outN += (size_t)kSynthHop;
    ana = pos;
  }
  return outN;
}
