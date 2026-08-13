#include "wake_word.h"

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <math.h>
#include <string.h>

#include "audio_es8311.h"

namespace {
constexpr const char *kPhrase = "嘿小爪";
constexpr int kFrame = 256;
constexpr uint32_t kCooldownMs = 4500;
constexpr uint32_t kRearmHoldMs = 1200;

TaskHandle_t task = nullptr;
volatile bool paused = true;
volatile bool triggered = false;
volatile bool listening = false;
uint32_t lastTrigMs = 0;
uint32_t rearmAtMs = 0;

enum class St : uint8_t { Idle, Syl, Gap };
St st = St::Idle;
uint8_t sylCount = 0;
uint32_t patternStartMs = 0;
uint32_t speechMs = 0;
uint32_t silenceMs = 0;
float noiseFloor = 200.0f;
uint32_t patternPeak = 0;
uint32_t patternVoicedMs = 0;

uint32_t frameRms(const int16_t *mono, size_t n) {
  uint64_t acc = 0;
  for (size_t i = 0; i < n; ++i) {
    const int32_t v = mono[i];
    acc += (uint64_t)(v * v);
  }
  return (uint32_t)sqrtf((float)(acc / (n ? n : 1)));
}

float speechiness(const int16_t *mono, size_t n) {
  if (!n) return 0;
  int32_t prev = mono[0];
  uint64_t full = 0;
  uint64_t hp = 0;
  for (size_t i = 0; i < n; ++i) {
    const int32_t x = mono[i];
    const int32_t y = x - prev;
    prev = x;
    full += (uint64_t)(x * x);
    hp += (uint64_t)(y * y);
  }
  if (!full) return 0;
  return (float)hp / (float)full;
}

void resetPattern() {
  st = St::Idle;
  sylCount = 0;
  speechMs = 0;
  silenceMs = 0;
  patternStartMs = 0;
  patternPeak = 0;
  patternVoicedMs = 0;
}

float voiceThreshold() {
  // Harder than ambient — reduces random chatter / TV false wakes.
  float thr = noiseFloor * 1.85f + 350.0f;
  const float cap = noiseFloor + 1600.0f;
  if (thr > cap) thr = cap;
  if (thr < 700.0f) thr = 700.0f;
  return thr;
}

bool acceptPattern(uint32_t now) {
  const uint32_t dur = now - patternStartMs;
  if (sylCount < 3) return false;
  if (dur < 550 || dur > 2100) return false;          // real phrase timing
  if (patternVoicedMs < 180 || patternVoicedMs > 1200) return false;
  if (patternPeak < (uint32_t)(voiceThreshold() * 1.35f)) return false;
  return true;
}

// Strict 3-beat detector for 「嘿 / 小 / 爪」
bool feedFrame(uint32_t rms, float speech, uint32_t now) {
  const float thr = voiceThreshold();
  // Need both energy rise and speech-like high-frequency content.
  const bool voiced = (float)rms > thr && speech > 0.10f;
  const uint32_t dt = 16;

  if (!voiced) {
    noiseFloor = noiseFloor * 0.975f + (float)rms * 0.025f;
    if (noiseFloor < 100.0f) noiseFloor = 100.0f;
    if (noiseFloor > 1800.0f) noiseFloor = 1800.0f;
  }

  if (st == St::Idle) {
    if (voiced) {
      st = St::Syl;
      sylCount = 0;
      speechMs = dt;
      silenceMs = 0;
      patternStartMs = now;
      patternPeak = rms;
      patternVoicedMs = dt;
    }
    return false;
  }

  if (now - patternStartMs > 2100) {
    resetPattern();
    return false;
  }

  if (st == St::Syl) {
    if (voiced) {
      speechMs += dt;
      patternVoicedMs += dt;
      silenceMs = 0;
      if (rms > patternPeak) patternPeak = rms;
      if (speechMs > 380) resetPattern();  // one long sound ≠ syllables
    } else {
      silenceMs += dt;
      // Syllable must be a short burst, then a clear gap.
      if (speechMs >= 55 && speechMs <= 380 && silenceMs >= 35) {
        sylCount++;
        if (sylCount >= 3) {
          const bool ok = acceptPattern(now);
          resetPattern();
          return ok;
        }
        st = St::Gap;
        speechMs = 0;
        silenceMs = 0;
      } else if (silenceMs > 220) {
        resetPattern();
      }
    }
  } else if (st == St::Gap) {
    if (!voiced) {
      silenceMs += dt;
      if (silenceMs > 380) resetPattern();
    } else {
      st = St::Syl;
      speechMs = dt;
      silenceMs = 0;
      patternVoicedMs += dt;
      if (rms > patternPeak) patternPeak = rms;
    }
  }
  return false;
}

void wakeTask(void *) {
  int16_t mono[kFrame];
  uint32_t logMs = 0;
  uint32_t lockFail = 0;
  for (;;) {
    if (paused || !audioMicReady()) {
      listening = false;
      vTaskDelay(pdMS_TO_TICKS(40));
      continue;
    }
    listening = true;

    if (!audioLockI2S(80)) {
      lockFail++;
      vTaskDelay(pdMS_TO_TICKS(5));
      continue;
    }
    const size_t n = audioMicReadMono(mono, kFrame);
    audioUnlockI2S();

    if (!n) {
      vTaskDelay(pdMS_TO_TICKS(5));
      continue;
    }

    const uint32_t now = millis();
    if (now < rearmAtMs || now - lastTrigMs < kCooldownMs) {
      const uint32_t rms = frameRms(mono, n);
      if (rms < (uint32_t)noiseFloor) {
        noiseFloor = noiseFloor * 0.88f + (float)rms * 0.12f;
      }
      resetPattern();
      continue;
    }

    const uint32_t rms = frameRms(mono, n);
    const float sp = speechiness(mono, n);

    if (now - logMs > 2000) {
      Serial.printf("[wake] rms=%u speech=%.2f thr=%.0f noise=%.0f\n",
                    (unsigned)rms, sp, voiceThreshold(), noiseFloor);
      lockFail = 0;
      logMs = now;
    }

    if (feedFrame(rms, sp, now)) {
      triggered = true;
      lastTrigMs = now;
      Serial.printf("[wake] detected \"%s\" rms=%u peak-ok thr=%.0f\n", kPhrase,
                    (unsigned)rms, voiceThreshold());
      resetPattern();
    }
  }
}

void resumeListening() {
  if (!audioMicReady()) return;
  resetPattern();
  triggered = false;

  float noiseMin = 1.0e9f;
  int frames = 0;
  int16_t mono[kFrame];
  delay(180);
  const uint32_t until = millis() + 450;
  while (millis() < until) {
    if (!audioLockI2S(50)) {
      delay(5);
      continue;
    }
    const size_t n = audioMicReadMono(mono, kFrame);
    audioUnlockI2S();
    if (!n) continue;
    const float r = (float)frameRms(mono, n);
    if (r < noiseMin) noiseMin = r;
    frames++;
  }
  if (frames > 0 && noiseMin < 1.0e8f) {
    noiseFloor = noiseMin * 1.2f;
    if (noiseFloor < 120.0f) noiseFloor = 120.0f;
    if (noiseFloor > 1600.0f) noiseFloor = 1600.0f;
  }

  rearmAtMs = millis() + kRearmHoldMs;
  Serial.printf("[wake] armed noise=%.0f thr=%.0f\n", noiseFloor, voiceThreshold());
  paused = false;
}
}  // namespace

bool wakeWordBegin() {
  if (!audioMicReady()) {
    Serial.println("[wake] mic not ready");
    return false;
  }
  paused = false;
  lastTrigMs = millis() - kCooldownMs;
  rearmAtMs = millis() + 800;
  if (!task) {
    xTaskCreatePinnedToCore(wakeTask, "wake", 4096, nullptr, 2, &task, 1);
  }
  Serial.printf("[wake] listening for \"%s\" (3 clear beats)\n", kPhrase);
  return true;
}

void wakeWordPause() {
  paused = true;
  resetPattern();
  for (int i = 0; i < 50 && listening; ++i) delay(4);
}

void wakeWordResume() { resumeListening(); }

bool wakeWordConsumeTrigger() {
  if (!triggered) return false;
  triggered = false;
  return true;
}

bool wakeWordIsListening() { return listening && !paused; }

const char *wakeWordPhrase() { return kPhrase; }

bool wakeWordLockI2S(uint32_t ms) { return audioLockI2S(ms); }
void wakeWordUnlockI2S() { audioUnlockI2S(); }
