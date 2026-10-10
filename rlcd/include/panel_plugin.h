#pragma once

#include "oc_battery.h"
#include "script_engine.h"

// 1bpp panel (ST7305 or ePaper). Stubs when OC_PLUGIN_PANEL is off:
// gfx.* no-ops, status stays on Serial.

void panelPluginBegin(const char *fwVersion);
const char *panelPluginName();
bool panelPluginSlow();
void panelPluginAttach(ScriptHost &host);
void panelPluginDrawStatus(const char *title, const char *line2, const char *line3 = nullptr,
                           const char *line4 = nullptr);
// Full-frame cloud bitmap. False when there is no panel or the download fails.
bool panelPluginShowAsset(const String &url);

// Battery badge, drawn top-right on every flush. On by default.
// True if the visible badge changed (caller may panelPluginRefresh()).
bool panelPluginSetBattery(const OcBattery &b);
void panelPluginSetBadge(bool on);
// Re-push the current canvas (redraws the badge).
void panelPluginRefresh();
