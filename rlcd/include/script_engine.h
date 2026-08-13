#pragma once

#include <Arduino.h>

#include "sensors.h"

class St7305Rlcd;

// Pure runtime host — expose board capabilities to Lua (no product UI).
struct ScriptHost {
  St7305Rlcd *display = nullptr;

  bool (*readSensors)(SensorReading &out) = nullptr;
  bool (*beep)(uint16_t freqHz, uint16_t ms) = nullptr;
  bool (*playPcm)(const int16_t *samples, size_t count) = nullptr;
  uint32_t (*sampleRate)() = nullptr;
  void (*setPa)(bool on) = nullptr;
  bool (*audioReady)() = nullptr;

  bool (*keyDown)() = nullptr;
  bool (*bootDown)() = nullptr;

  int (*wifiRssi)() = nullptr;
  void (*wifiIp)(char *out, size_t n) = nullptr;
  void (*wifiSsid)(char *out, size_t n) = nullptr;

  bool (*emitEvent)(const char *name, const char *jsonData) = nullptr;
  void (*onSensors)(const SensorReading &r) = nullptr;
};

void scriptEngineBegin(const ScriptHost &host);

bool scriptEngineLoadLua(const char *scriptId, const char *luaSource, const char *mode,
                         uint32_t everyMs);

void scriptEngineStop(const char *reason = "stopped");
void scriptEngineTick();
bool scriptEngineIsRunning();
const char *scriptEngineScriptId();
const char *scriptEngineState();
const char *scriptEngineLastError();
const char *scriptEngineLanguage();

bool scriptEngineInvokeJson(const char *json);
