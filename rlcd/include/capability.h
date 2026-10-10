#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#include "oc_features.h"

// Runtime view of the compile-time plugins in oc_features.h.
// Reported as meta.capabilities[] and used to gate invoke tools.

inline constexpr bool ocCapCore() { return true; }
inline constexpr bool ocCapPanel() { return OC_HAS_PANEL != 0; }
inline constexpr bool ocCapAudio() { return OC_HAS_AUDIO != 0; }
inline constexpr bool ocCapBle() { return OC_HAS_BLE != 0; }
inline constexpr bool ocCapSensors() { return OC_HAS_SENSORS != 0; }
inline constexpr bool ocCapArm() { return OC_HAS_ARM != 0; }

// Fill meta.capabilities as a JSON array of strings.
void capabilityFillJson(JsonArray out);

// True if an invoke tool name is allowed on this binary.
bool capabilityAllowsTool(const char *tool);
