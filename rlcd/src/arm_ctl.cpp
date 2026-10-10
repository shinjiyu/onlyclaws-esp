#include "arm_ctl.h"

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

namespace {

SemaphoreHandle_t gMux = nullptr;
volatile bool gPreempt = false;

}  // namespace

void armCtlBegin() {
  if (!gMux) gMux = xSemaphoreCreateMutex();
  gPreempt = false;
}

bool armCtlLock(uint32_t timeoutMs) {
  if (!gMux) armCtlBegin();
  if (!gMux) return false;
  TickType_t ticks =
      timeoutMs == 0 ? portMAX_DELAY : pdMS_TO_TICKS(timeoutMs);
  return xSemaphoreTake(gMux, ticks) == pdTRUE;
}

void armCtlUnlock() {
  if (gMux) xSemaphoreGive(gMux);
}

void armCtlHostPreempt() { gPreempt = true; }

bool armCtlIsPreempted() { return gPreempt; }

void armCtlClearPreempt() { gPreempt = false; }
