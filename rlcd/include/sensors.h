#pragma once

#include <Arduino.h>

struct SensorReading {
  bool okTemp = false;
  bool okBattery = false;
  float tempC = NAN;
  float humidity = NAN;
  float batteryV = NAN;
  int batteryPct = -1;
};

bool sensorsBegin();
bool sensorsRead(SensorReading &out);
