#pragma once

#include <Arduino.h>

#include "sensors.h"

// JSON tools script (MVP). Agents deploy this; device runs local loop.
// See server/static/agent-api.md § Script format.

struct ScriptHost {
  bool (*readSensors)(SensorReading &out);
  bool (*beep)(uint16_t freqHz, uint16_t ms);
  void (*wave)();
  void (*react)();
  void (*dialog)(const char *title);
  // Upload one event to cloud; returns false if network fail.
  bool (*emitEvent)(const char *name, const char *jsonData);
  // Optional: refresh HUD after sensors.
  void (*onSensors)(const SensorReading &r);
};

void scriptEngineBegin(const ScriptHost &host);
bool scriptEngineLoad(const char *scriptId, const char *jsonSource);
void scriptEngineStop(const char *reason = "stopped");
void scriptEngineTick();  // call from loop()
bool scriptEngineIsRunning();
const char *scriptEngineScriptId();
const char *scriptEngineState();  // idle|running|error|stopped
const char *scriptEngineLastError();

// One-shot remote invoke: {"tools":[ {"tool":"beep",...}, ... ]}
bool scriptEngineInvokeJson(const char *json);
