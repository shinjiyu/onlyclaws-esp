#pragma once

#include <Arduino.h>
#include <stddef.h>
#include <stdint.h>

// Joint radians as reported/commanded by Waveshare-style stacks:
// base, shoulder, elbow, hand/wrist.
struct ArmPose {
  float q[4];
};

struct ArmDriver {
  virtual ~ArmDriver() = default;
  virtual bool begin() = 0;
  virtual bool feedback(ArmPose &out) = 0;
  // Stream a target; spd is servo steps/s (0 = firmware default / max).
  virtual bool stream(const ArmPose &target, int spd) = 0;
  virtual bool stop() = 0;
  virtual const char *name() const = 0;
};

// Linked when OC_CAP_ARM=1: arm_roarm (BOARD_ROARM) or arm_stub (dev).
ArmDriver *armDriver();
bool armPluginBegin();
