#pragma once

#include <Arduino.h>
#include <stddef.h>
#include <stdint.h>

// Minimal ES8311 + I2S audio template for ESP32-S3-ePaper-3.97.
// Requires speaker on MX1.25 header for audible output.

bool audioBegin(uint32_t sampleRate = 16000);
void audioEnd();
bool audioIsReady();

// Enable/disable speaker amp (PA).
void audioSetPa(bool on);

// Play a short beep (blocking).
bool audioPlayBeep(uint16_t freqHz = 880, uint16_t ms = 180);

// Play a short demo melody (~1.6s). Returns false if any note fails.
bool audioPlayDemo();

// Play mono int16 PCM at current sample rate (blocking write).
bool audioPlayPcm(const int16_t *samples, size_t count);

// Record stub: fills buffer with mic samples (blocking). Returns samples read.
size_t audioRecordPcm(int16_t *out, size_t count);

uint32_t audioSampleRate();
