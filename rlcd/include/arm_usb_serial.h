#pragma once

#include <Arduino.h>

#include "oc_features.h"

#if OC_HAS_ARM
// USB Serial JSON host path (Mac ↔ ESP), bypasses cloud pending.
// One JSON object per line. See arm_usb_serial.cpp.
void armUsbSerialPoll();
#else
inline void armUsbSerialPoll() {}
#endif
