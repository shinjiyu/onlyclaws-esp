#include "voice_proc.h"

#include <stdlib.h>
#include <string.h>

namespace {
int16_t abs16(int16_t v) { return v < 0 ? (int16_t)-v : v; }

uint32_t frameEnergy(const int16_t *p, size_t n) {
  uint64_t acc = 0;
  for (size_t i = 0; i < n; ++i) {
    const int32_t v = p[i];
    acc += (uint64_t)(v * v);
  }
  return (uint32_t)(acc / (n ? n : 1));
}
}  // namespace

VoiceProcessResult voiceProcessInPlace(int16_t *samples, size_t *inoutCount,
                                       uint32_t sampleRate) {
  VoiceProcessResult r{};
  if (!samples || !inoutCount || !*inoutCount) return r;
  size_t n = *inoutCount;

  // DC block (simple 1-pole)
  int32_t prevX = 0;
  int32_t prevY = 0;
  for (size_t i = 0; i < n; ++i) {
    const int32_t x = samples[i];
    const int32_t y = x - prevX + ((prevY * 15) / 16);
    prevX = x;
    prevY = y;
    if (y > 32767) samples[i] = 32767;
    else if (y < -32768) samples[i] = -32768;
    else samples[i] = (int16_t)y;
  }

  // Soft noise gate by short frames (~10ms) — tuned for ES7210 near-field levels
  const size_t frame = sampleRate / 100;
  const uint32_t gate = 220u * 220u;
  for (size_t i = 0; i + frame <= n; i += frame) {
    if (frameEnergy(samples + i, frame) < gate) {
      memset(samples + i, 0, frame * sizeof(int16_t));
    }
  }

  // Find voiced span
  const size_t win = frame ? frame : 160;
  const uint32_t voiceThr = 350u * 350u;
  size_t first = 0;
  size_t last = n;
  bool found = false;
  for (size_t i = 0; i + win <= n; i += win) {
    if (frameEnergy(samples + i, win) >= voiceThr) {
      first = i;
      found = true;
      break;
    }
  }
  if (found) {
    for (size_t i = 0; i + win <= n; i += win) {
      const size_t at = n - win - i;
      if (frameEnergy(samples + at, win) >= voiceThr) {
        last = at + win;
        break;
      }
    }
    if (last > first) {
      const size_t keep = last - first;
      if (first > 0) memmove(samples, samples + first, keep * sizeof(int16_t));
      n = keep;
    }
  }

  int16_t peak = 0;
  uint64_t acc = 0;
  for (size_t i = 0; i < n; ++i) {
    const int16_t a = abs16(samples[i]);
    if (a > peak) peak = a;
    acc += (uint32_t)a * (uint32_t)a;
  }
  r.samples = n;
  r.peak = peak;
  r.rms = n ? (uint32_t)(acc / n) : 0;
  r.voiced = found && peak >= 200;
  *inoutCount = n;
  return r;
}
