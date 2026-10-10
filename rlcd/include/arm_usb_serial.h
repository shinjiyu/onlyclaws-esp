#pragma once

#include <Arduino.h>

#if OC_CAP_ARM
// USB Serial JSON host path (Mac ↔ ESP), bypasses cloud pending.
// One JSON object per line. See arm_usb_serial.cpp.
void armUsbSerialPoll();
#else
inline void armUsbSerialPoll() {}
#endif
