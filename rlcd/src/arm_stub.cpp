#include "arm_driver.h"

#include "capability.h"

#ifndef BOARD_ROARM

#if OC_CAP_ARM

namespace {

class ArmStub final : public ArmDriver {
 public:
  bool begin() override {
    pose_.q[0] = 0.f;
    pose_.q[1] = 0.f;
    pose_.q[2] = 1.57f;
    pose_.q[3] = 3.14f;
    return true;
  }
  bool feedback(ArmPose &out) override {
    out = pose_;
    return true;
  }
  bool stream(const ArmPose &target, int /*spd*/) override {
    pose_ = target;
    return true;
  }
  bool stop() override { return true; }
  const char *name() const override { return "arm-stub"; }

 private:
  ArmPose pose_{};
};

ArmStub gArm;

}  // namespace

ArmDriver *armDriver() { return &gArm; }

bool armPluginBegin() { return gArm.begin(); }

#else

ArmDriver *armDriver() { return nullptr; }

bool armPluginBegin() { return false; }

#endif

#endif  // !BOARD_ROARM
