#pragma once

#include <Arduino.h>

// Shared STS/arm access: host invoke preempts Lua motion (see ROARM-PRODUCT.md).

void armCtlBegin();

// Serialize bus ops (Lua + invoke). Returns false on timeout.
bool armCtlLock(uint32_t timeoutMs = 200);
void armCtlUnlock();

// Host (cloud invoke) claims control; Lua stream/move fail until cleared.
void armCtlHostPreempt();
bool armCtlIsPreempted();
void armCtlClearPreempt();

struct ArmCtlGuard {
  bool ok;
  explicit ArmCtlGuard(uint32_t timeoutMs = 200) : ok(armCtlLock(timeoutMs)) {}
  ~ArmCtlGuard() {
    if (ok) armCtlUnlock();
  }
  ArmCtlGuard(const ArmCtlGuard &) = delete;
  ArmCtlGuard &operator=(const ArmCtlGuard &) = delete;
};
