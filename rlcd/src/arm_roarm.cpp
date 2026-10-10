#include "arm_driver.h"

#include "capability.h"

#if OC_CAP_ARM && defined(BOARD_ROARM)

#include <math.h>

#include "arm_ctl.h"
#include "board_pins.h"
#include "sts_bus.h"

namespace {

constexpr uint8_t ID_BASE = 11;
constexpr uint8_t ID_SHOULDER_DRIVE = 12;
constexpr uint8_t ID_SHOULDER_DRIVEN = 13;
constexpr uint8_t ID_ELBOW = 14;
constexpr uint8_t ID_HAND = 15;
constexpr int MIDDLE = 2047;
constexpr int POS_RANGE = 4096;
constexpr uint8_t DEFAULT_ACC = 20;

int posFromRad(double rad) {
  return (int)lround((rad / (2.0 * M_PI)) * POS_RANGE);
}

double radFromSteps(int steps, int joint) {
  switch (joint) {
    case 0:
      return -(steps * 2.0 * M_PI / POS_RANGE) + M_PI;
    case 1:
      return (steps * 2.0 * M_PI / POS_RANGE) - M_PI;
    case 2:
      return (steps * 2.0 * M_PI / POS_RANGE) - (M_PI / 2.0);
    default:
      return steps * 2.0 * M_PI / POS_RANGE;
  }
}

int clampi(int v, int lo, int hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

class ArmRoArm final : public ArmDriver {
 public:
  bool begin() override {
    armCtlBegin();
    ArmCtlGuard g(500);
    if (!g.ok) return false;
    if (!sts::begin(Serial1, PIN_SERVO_RX, PIN_SERVO_TX, 1000000)) return false;
    delay(50);
    // Bus bring-up probe (half-duplex echo drain is critical for reads).
    for (uint8_t id : {ID_BASE, ID_SHOULDER_DRIVE, ID_SHOULDER_DRIVEN, ID_ELBOW, ID_HAND}) {
      bool ok = sts::ping(id);
      Serial.printf("[arm] ping id=%u %s\n", id, ok ? "ok" : "fail");
    }
    // Best-effort torque on; ignore failures so bring-up still reports ready.
    sts::enableTorque(ID_BASE, true);
    sts::enableTorque(ID_SHOULDER_DRIVE, true);
    sts::enableTorque(ID_SHOULDER_DRIVEN, true);
    sts::enableTorque(ID_ELBOW, true);
    sts::enableTorque(ID_HAND, true);
    ArmPose p{};
    if (feedbackUnlocked(p)) {
      last_ = p;
      Serial.printf("[arm] feedback q=%.3f %.3f %.3f %.3f\n", p.q[0], p.q[1], p.q[2],
                    p.q[3]);
    } else {
      Serial.printf("[arm] feedback fail err=%d\n", sts::lastError());
    }
    ready_ = true;
    return true;
  }

  bool feedback(ArmPose &out) override {
    ArmCtlGuard g;
    if (!g.ok) return false;
    return feedbackUnlocked(out);
  }

  bool stream(const ArmPose &target, int spd) override {
    ArmCtlGuard g;
    if (!g.ok || !ready_) return false;
    return streamUnlocked(target, spd);
  }

  bool stop() override {
    ArmCtlGuard g;
    if (!g.ok) return false;
    ArmPose p = last_;
    feedbackUnlocked(p);
    return streamUnlocked(p, 200);
  }

  const char *name() const override { return "roarm-m2-sts"; }

 private:
  bool feedbackUnlocked(ArmPose &out) {
    int16_t b = 0, s = 0, e = 0, h = 0;
    if (!sts::readPos(ID_BASE, b)) return false;
    if (!sts::readPos(ID_SHOULDER_DRIVE, s)) return false;
    if (!sts::readPos(ID_ELBOW, e)) return false;
    if (!sts::readPos(ID_HAND, h)) return false;
    out.q[0] = (float)radFromSteps(b, 0);
    out.q[1] = (float)radFromSteps(s, 1);
    out.q[2] = (float)radFromSteps(e, 2);
    out.q[3] = (float)radFromSteps(h, 3);
    last_ = out;
    return true;
  }

  bool streamUnlocked(const ArmPose &target, int spd) {
    uint16_t speed = spd > 0 ? (uint16_t)constrain(spd, 1, 4000) : 600;
    uint8_t acc = DEFAULT_ACC;

    // Match Waveshare RoArmM2_*JointCtrlRad encodings.
    double base = -constrain((double)target.q[0], -M_PI, M_PI);
    int basePos = posFromRad(base) + MIDDLE;

    double shoulder = constrain((double)target.q[1], -M_PI / 2, M_PI / 2);
    int shoulderDelta = posFromRad(shoulder);
    int shoulderDrive = MIDDLE + shoulderDelta;
    int shoulderDriven = MIDDLE - shoulderDelta;

    int elbowPos = clampi(posFromRad((double)target.q[2]) + 1024, 512, 3071);
    int handPos = clampi(posFromRad((double)target.q[3]), 700, 3396);

    bool ok = true;
    ok &= sts::writePosEx(ID_BASE, (int16_t)basePos, speed, acc);
    ok &= sts::writePosEx(ID_SHOULDER_DRIVE, (int16_t)shoulderDrive, speed, acc);
    ok &= sts::writePosEx(ID_SHOULDER_DRIVEN, (int16_t)shoulderDriven, speed, acc);
    ok &= sts::writePosEx(ID_ELBOW, (int16_t)elbowPos, speed, acc);
    ok &= sts::writePosEx(ID_HAND, (int16_t)handPos, speed, acc);
    if (ok) last_ = target;
    return ok;
  }

  bool ready_ = false;
  ArmPose last_{};
};

ArmRoArm gArm;

}  // namespace

ArmDriver *armDriver() { return &gArm; }

bool armPluginBegin() { return gArm.begin(); }

#endif  // OC_CAP_ARM && BOARD_ROARM
