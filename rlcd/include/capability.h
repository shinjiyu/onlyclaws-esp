#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

// Compile-time product capabilities (PlatformIO -DOC_CAP_*=0|1).
// Defaults keep today's panel products working when flags are omitted.

#ifndef OC_CAP_PANEL
#define OC_CAP_PANEL 1
#endif
#ifndef OC_CAP_AUDIO
#define OC_CAP_AUDIO 1
#endif
#ifndef OC_CAP_BLE
#define OC_CAP_BLE 1
#endif
#ifndef OC_CAP_SENSORS
#define OC_CAP_SENSORS 1
#endif
#ifndef OC_CAP_ARM
#define OC_CAP_ARM 0
#endif

// Core is always present when this firmware runs.
inline constexpr bool ocCapCore() { return true; }
inline constexpr bool ocCapPanel() { return OC_CAP_PANEL != 0; }
inline constexpr bool ocCapAudio() { return OC_CAP_AUDIO != 0; }
inline constexpr bool ocCapBle() { return OC_CAP_BLE != 0; }
inline constexpr bool ocCapSensors() { return OC_CAP_SENSORS != 0; }
inline constexpr bool ocCapArm() { return OC_CAP_ARM != 0; }

// Fill meta.capabilities as a JSON array of strings.
void capabilityFillJson(JsonArray out);

// True if an invoke tool name is allowed on this binary.
bool capabilityAllowsTool(const char *tool);
