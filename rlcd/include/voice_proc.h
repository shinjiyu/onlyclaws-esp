#pragma once

#include <stddef.h>
#include <stdint.h>

struct VoiceProcessResult {
  size_t samples = 0;     // kept samples after trim
  int16_t peak = 0;
  uint32_t rms = 0;
  bool voiced = false;    // passed energy gate
};

// In-place: DC block + soft noise gate + trim leading/trailing silence.
// Returns stats; may shrink *inoutCount.
VoiceProcessResult voiceProcessInPlace(int16_t *samples, size_t *inoutCount,
                                       uint32_t sampleRate);
