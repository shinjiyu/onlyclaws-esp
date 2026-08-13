#pragma once

#include <Arduino.h>

#include "sensors.h"

// Pure runtime host: whitelist hardware/network APIs exposed to Lua.
struct ScriptHost {
  bool (*readSensors)(SensorReading &out);
  bool (*beep)(uint16_t freqHz, uint16_t ms);
  void (*displayText)(const char *line1, const char *line2);
  bool (*emitEvent)(const char *name, const char *jsonData);
  void (*onSensors)(const SensorReading &r);
};

void scriptEngineBegin(const ScriptHost &host);

// Load Lua source. mode: "once" | "loop". every_ms used between on_loop calls.
bool scriptEngineLoadLua(const char *scriptId, const char *luaSource, const char *mode,
                         uint32_t everyMs);

void scriptEngineStop(const char *reason = "stopped");
void scriptEngineTick();
bool scriptEngineIsRunning();
const char *scriptEngineScriptId();
const char *scriptEngineState();  // idle|running|error|stopped
const char *scriptEngineLastError();
const char *scriptEngineLanguage();  // lua

// Remote one-shot tools (JSON): {"tools":[{"tool":"beep",...}, ...]}
bool scriptEngineInvokeJson(const char *json);
