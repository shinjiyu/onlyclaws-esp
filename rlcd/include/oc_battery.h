#pragma once

#include <stddef.h>
#include <stdio.h>

// Battery state shared by sensors (producer), panel badge and Claude Buddy
// status (consumers). Pure C++ so host tests can include it.
struct OcBattery {
  bool sensed = false;    // board can measure a battery at all
  bool present = false;   // a cell is connected
  int pct = -1;           // 0..100, -1 unknown
  int mv = -1;            // cell voltage, -1 unknown
  bool charging = false;  // only known with a PMU (TG28 / AXP2101)
  bool usb = false;       // external power known present
};

// Single Li-ion cell, coarse curve (3.30 V empty, 4.15 V full).
inline int ocBatteryPctFromMv(int mv) {
  if (mv <= 3300) return 0;
  if (mv >= 4150) return 100;
  if (mv < 3600) return (mv - 3300) * 20 / 300;
  if (mv < 3900) return 20 + (mv - 3600) * 50 / 300;
  return 70 + (mv - 3900) * 30 / 250;
}

// Badge text: "87%", "87%+" (charging), "USB" (sensed, no cell), "" (no badge).
inline void ocBatteryLabel(const OcBattery &b, char *out, size_t n) {
  if (!out || !n) return;
  out[0] = 0;
  if (!b.sensed) return;
  if (!b.present || b.pct < 0) {
    snprintf(out, n, "USB");
    return;
  }
  const int pct = b.pct > 100 ? 100 : b.pct;
  snprintf(out, n, b.charging ? "%d%%+" : "%d%%", pct);
}

inline bool ocBatterySame(const OcBattery &a, const OcBattery &b) {
  return a.sensed == b.sensed && a.present == b.present && a.pct == b.pct &&
         a.charging == b.charging;
}
