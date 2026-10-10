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

// Charging estimate for boards whose charger status never reaches a GPIO
// (RLCD-4.2: the CHG LED is wired to the charger only). Feed one averaged
// cell reading about every 30 s. Signals, strongest first:
//   cell at/above kFullMv          -> not charging (charger in CV / done)
//   USB host present (SOF ticking) -> charging
//   jump between two samples       -> plugged in / unplugged
//   slope across the window        -> slow drift up or down
// A wall charger with no data lines is only seen through the voltage.
class OcChargeTrend {
 public:
  static constexpr int kWindow = 20;  // ~10 min at 30 s
  static constexpr int kHalf = 5;
  static constexpr int kStepMv = 40;
  static constexpr int kSlopeMv = 8;
  static constexpr int kFullMv = 4150;

  bool update(int mv, bool usbHost) {
    const bool hasPrev = n_ > 0;
    const int prev = hasPrev ? at(n_ - 1) : mv;
    const int step = mv - prev;
    if (hasPrev && step <= -kStepMv) n_ = 0;  // unplugged: drop stale highs
    push(mv);
    if (mv >= kFullMv) {
      charging_ = false;
    } else if (usbHost || (hasPrev && step >= kStepMv)) {
      charging_ = true;
    } else if (hasPrev && step <= -kStepMv) {
      charging_ = false;
    } else if (n_ >= kWindow) {
      const int d = avg(n_ - kHalf) - avg(0);
      if (d >= kSlopeMv) charging_ = true;
      else if (d <= -kSlopeMv) charging_ = false;
    }
    return charging_;
  }
  bool charging() const { return charging_; }

 private:
  // i-th oldest sample, 0 <= i < n_.
  int at(int i) const { return buf_[(head_ + kWindow - n_ + i) % kWindow]; }
  int avg(int from) const {
    long sum = 0;
    for (int i = 0; i < kHalf; ++i) sum += at(from + i);
    return (int)(sum / kHalf);
  }
  void push(int mv) {
    buf_[head_] = mv;
    head_ = (head_ + 1) % kWindow;
    if (n_ < kWindow) ++n_;
  }

  int buf_[kWindow] = {};
  int head_ = 0;
  int n_ = 0;
  bool charging_ = false;
};
