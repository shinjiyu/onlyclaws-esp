#pragma once

#include <Arduino.h>
#include <stddef.h>
#include <stdint.h>

enum AudioCue : uint8_t {
  AUDIO_CUE_RECORD_START = 0,
  AUDIO_CUE_RECORD_END,
  AUDIO_CUE_OK,
  AUDIO_CUE_FAIL,
  AUDIO_CUE_UPLOAD_OK,
};

bool audioBegin(uint32_t sampleRate = 16000);
void audioEnd();
bool audioIsReady();
bool audioMicReady();

void audioSetPa(bool on);

bool audioLockI2S(uint32_t ms = 1000);
void audioUnlockI2S();

bool audioPlayBeep(uint16_t freqHz = 880, uint16_t ms = 180);
bool audioPlayDemo();
bool audioPlayPcm(const int16_t *samples, size_t count);
bool audioSpeakCue(AudioCue cue);
size_t audioRecordPcm(int16_t *out, size_t count);
// Caller must hold audioLockI2S. Writes silence TX to keep duplex clocks.
size_t audioMicReadMono(int16_t *out, size_t maxFrames);

uint32_t audioSampleRate();
