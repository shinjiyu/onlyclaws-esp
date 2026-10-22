#pragma once

#include "tts_voice.h"

// Device speech. Stubs (return false / no-op) when OC_PLUGIN_TTS is off.
bool ttsSpeak(const char *text, const char *voice);
bool ttsSpeakTuned(const char *text, const TtsTune &tune);
void ttsBootDemo();
void ttsSerialPoll();
