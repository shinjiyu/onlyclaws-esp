#pragma once

#include <stddef.h>
#include <stdint.h>

// Two child timbres from one concatenative voice (Espressif 小新 small).
// Girl steps through the syllables faster (higher, shorter). Boy steps slower.
// Same recording, flat delivery. Not two separately recorded children.

enum TtsVoiceId { TTS_VOICE_GIRL = 0, TTS_VOICE_BOY = 1 };

// nullptr and "" are girl. Unknown names return false.
bool ttsParseVoice(const char *name, TtsVoiceId *out);
float ttsPitchRatio(TtsVoiceId id);

// What `say` plays when the caller only names a voice.
struct TtsTune {
  int speed;      // esp-tts 0..5, 0 slowest
  float pitch;    // 1.0 is the recorded syllable
  int stretch;    // 1 = as synthesized, 2 = twice as long
  int volumeDb;   // DAC, 0 is full scale
};

TtsTune ttsTuneDefaults(TtsVoiceId id);
TtsTune ttsClampTune(int speed, float pitch, int stretch, int volumeDb);
uint8_t ttsDacFromDb(int volumeDb);

// How many output samples a shift of `nIn` at `ratio` produces.
size_t ttsPitchOutCount(size_t nIn, float ratio);
// Linear resample. ratio > 1 raises pitch and shortens. Returns samples written.
size_t ttsPitchShift(const int16_t *in, size_t nIn, float ratio, int16_t *out,
                     size_t outCap);

// Pitch-preserving 2x time stretch (WSOLA). Output is about twice as long.
size_t ttsTimeStretch2x(const int16_t *in, size_t nIn, int16_t *out, size_t outCap);
