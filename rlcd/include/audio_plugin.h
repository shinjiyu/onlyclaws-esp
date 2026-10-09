#pragma once

#include "script_engine.h"

// ES8311 playback. Stubs when OC_PLUGIN_AUDIO is off, so the core still links.

bool audioPluginBegin(uint32_t sampleRate = 16000);
bool audioPluginReady();
bool audioPluginBeep(uint16_t freqHz, uint16_t ms);
void audioPluginAttach(ScriptHost &host);
const char *audioPluginName();
