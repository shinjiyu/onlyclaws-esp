#pragma once

#include <Arduino.h>

#include "oc_battery.h"

struct SensorReading {
  bool okTemp = false;
  bool okBattery = false;
  float tempC = NAN;
  float humidity = NAN;
  float batteryV = NAN;
  int batteryPct = -1;
  bool charging = false;
};

bool sensorsBegin();
bool sensorsRead(SensorReading &out);
// Battery only (ADC divider or TG28/AXP2101 fuel gauge). Cheap; no SHTC3.
bool sensorsBattery(OcBattery &out);
