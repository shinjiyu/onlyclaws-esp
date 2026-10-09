#pragma once

#include "script_engine.h"

// 1bpp panel (ST7305 or ePaper). Stubs when OC_PLUGIN_PANEL is off:
// gfx.* no-ops, status stays on Serial.

void panelPluginBegin(const char *fwVersion);
const char *panelPluginName();
bool panelPluginSlow();
void panelPluginAttach(ScriptHost &host);
void panelPluginDrawStatus(const char *title, const char *line2, const char *line3 = nullptr);
// Full-frame cloud bitmap. False when there is no panel or the download fails.
bool panelPluginShowAsset(const String &url);
