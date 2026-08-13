#include "script_engine.h"

#include <ArduinoJson.h>
#include <math.h>
#include <string.h>

namespace {
ScriptHost gHost{};
String gSource;
String gScriptId;
String gState = "idle";
String gError;
String gMode = "once";  // once | loop
uint32_t gEveryMs = 1000;
uint32_t gMaxIters = 0;
uint32_t gIters = 0;
uint32_t gNextDueMs = 0;
int gStepIndex = 0;
bool gInStart = true;
SensorReading gVars{};
bool gHasVars = false;

constexpr size_t kDocCap = 12288;

bool setError(const char *msg) {
  gError = msg ? msg : "error";
  gState = "error";
  return false;
}

float metaValue(const char *key) {
  if (!key) return NAN;
  if (!strcmp(key, "temp_c")) return gHasVars && gVars.okTemp ? gVars.tempC : NAN;
  if (!strcmp(key, "humidity"))
    return gHasVars && gVars.okTemp ? gVars.humidity : NAN;
  if (!strcmp(key, "battery_v"))
    return gHasVars && gVars.okBattery ? gVars.batteryV : NAN;
  if (!strcmp(key, "battery_pct"))
    return gHasVars && gVars.okBattery ? (float)gVars.batteryPct : NAN;
  return NAN;
}

bool evalCond(JsonObject cond) {
  const char *meta = cond["meta"] | "";
  const char *op = cond["op"] | "gt";
  float value = cond["value"] | NAN;
  float cur = metaValue(meta);
  if (isnan(cur) || isnan(value)) return false;
  if (!strcmp(op, "gt")) return cur > value;
  if (!strcmp(op, "gte")) return cur >= value;
  if (!strcmp(op, "lt")) return cur < value;
  if (!strcmp(op, "lte")) return cur <= value;
  if (!strcmp(op, "eq")) return fabsf(cur - value) < 0.0001f;
  if (!strcmp(op, "neq")) return fabsf(cur - value) >= 0.0001f;
  return false;
}

bool runTool(JsonObject step) {
  const char *tool = step["tool"] | "";
  if (!tool[0]) return setError("missing tool");

  if (!strcmp(tool, "sensors.read")) {
    if (!gHost.readSensors) return setError("no sensors");
    SensorReading r;
    if (!gHost.readSensors(r)) return setError("sensors.read failed");
    gVars = r;
    gHasVars = true;
    if (gHost.onSensors) gHost.onSensors(r);
    return true;
  }
  if (!strcmp(tool, "beep")) {
    if (!gHost.beep) return setError("no beep");
    uint16_t freq = step["freq"] | 880;
    uint16_t ms = step["ms"] | 100;
    if (ms > 2000) ms = 2000;
    return gHost.beep(freq, ms);
  }
  if (!strcmp(tool, "wave")) {
    if (gHost.wave) gHost.wave();
    return true;
  }
  if (!strcmp(tool, "react")) {
    if (gHost.react) gHost.react();
    return true;
  }
  if (!strcmp(tool, "dialog")) {
    const char *title = step["title"] | "";
    if (gHost.dialog) gHost.dialog(title);
    return true;
  }
  if (!strcmp(tool, "sleep")) {
    uint32_t ms = step["ms"] | 0;
    if (ms > 60000) ms = 60000;
    gNextDueMs = millis() + ms;
    return true;
  }
  if (!strcmp(tool, "emit")) {
    if (!gHost.emitEvent) return setError("no emit");
    const char *name = step["name"] | "event";
    String data = "{}";
    if (!step["data"].isNull()) {
      serializeJson(step["data"], data);
    } else {
      // Convenience: attach last sensor snapshot.
      DynamicJsonDocument d(256);
      JsonObject o = d.to<JsonObject>();
      if (gHasVars && gVars.okTemp) {
        o["temp_c"] = gVars.tempC;
        o["humidity"] = gVars.humidity;
      }
      if (gHasVars && gVars.okBattery) {
        o["battery_v"] = gVars.batteryV;
        o["battery_pct"] = gVars.batteryPct;
      }
      data = "";
      serializeJson(o, data);
    }
    return gHost.emitEvent(name, data.c_str());
  }
  if (!strcmp(tool, "stop")) {
    scriptEngineStop("script stop");
    return true;
  }
  if (!strcmp(tool, "if")) {
    JsonObject when = step["when"].as<JsonObject>();
    if (when.isNull()) when = step["cond"].as<JsonObject>();
    JsonArray thenArr = step["then"].as<JsonArray>();
    JsonArray elseArr = step["else"].as<JsonArray>();
    const bool ok = !when.isNull() && evalCond(when);
    JsonArray arr = ok ? thenArr : elseArr;
    if (arr.isNull()) return true;
    for (JsonObject s : arr) {
      if (!runTool(s)) return false;
      if (gState != "running") return true;
    }
    return true;
  }
  return setError("unknown tool");
}

bool runArray(JsonArray arr) {
  if (arr.isNull()) return true;
  for (JsonObject step : arr) {
    if (gState != "running") return true;
    if (!runTool(step)) return false;
    // Cooperative yield after each tool.
    yield();
  }
  return true;
}

bool parseAndArm(const char *jsonSource) {
  DynamicJsonDocument doc(kDocCap);
  DeserializationError err = deserializeJson(doc, jsonSource);
  if (err) return setError("bad script json");
  gMode = doc["mode"] | "once";
  gEveryMs = doc["every_ms"] | 1000;
  if (gEveryMs < 200) gEveryMs = 200;
  if (gEveryMs > 3600000UL) gEveryMs = 3600000UL;
  gMaxIters = doc["max_iters"] | 0;
  gIters = 0;
  gStepIndex = 0;
  gInStart = true;
  gNextDueMs = 0;
  gError = "";
  gState = "running";
  return true;
}
}  // namespace

void scriptEngineBegin(const ScriptHost &host) {
  gHost = host;
  gState = "idle";
  gScriptId = "";
  gSource = "";
  gError = "";
}

bool scriptEngineLoad(const char *scriptId, const char *jsonSource) {
  if (!jsonSource || !jsonSource[0]) return setError("empty script");
  gScriptId = scriptId ? scriptId : "";
  gSource = jsonSource;
  if (!parseAndArm(jsonSource)) return false;
  Serial.printf("[script] load id=%s mode=%s every=%u\n", gScriptId.c_str(),
                gMode.c_str(), (unsigned)gEveryMs);
  return true;
}

void scriptEngineStop(const char *reason) {
  gState = "stopped";
  if (reason && reason[0]) gError = reason;
  Serial.printf("[script] stop: %s\n", gError.c_str());
}

void scriptEngineTick() {
  if (gState != "running") return;
  const uint32_t now = millis();
  if (gNextDueMs && (int32_t)(now - gNextDueMs) < 0) return;
  gNextDueMs = 0;

  DynamicJsonDocument doc(kDocCap);
  if (deserializeJson(doc, gSource)) {
    setError("script reparse failed");
    return;
  }

  if (gInStart) {
    gInStart = false;
    if (!runArray(doc["on_start"].as<JsonArray>())) return;
    if (gState != "running") return;
  }

  JsonArray steps = doc["steps"].as<JsonArray>();
  if (steps.isNull()) steps = doc["loop"].as<JsonArray>();
  if (!runArray(steps)) return;
  if (gState != "running") return;

  gIters++;
  if (gMaxIters > 0 && gIters >= gMaxIters) {
    scriptEngineStop("max_iters");
    return;
  }
  if (gMode == "loop") {
    gNextDueMs = millis() + gEveryMs;
  } else {
    scriptEngineStop("done");
  }
}

bool scriptEngineIsRunning() { return gState == "running"; }
const char *scriptEngineScriptId() { return gScriptId.c_str(); }
const char *scriptEngineState() { return gState.c_str(); }
const char *scriptEngineLastError() { return gError.c_str(); }

bool scriptEngineInvokeJson(const char *json) {
  if (!json || !json[0]) return false;
  DynamicJsonDocument doc(4096);
  if (deserializeJson(doc, json)) return false;
  JsonArray tools = doc["tools"].as<JsonArray>();
  if (tools.isNull() && doc.is<JsonArray>()) tools = doc.as<JsonArray>();
  if (tools.isNull()) {
    // single tool object
    JsonObject one = doc.as<JsonObject>();
    if (one.isNull() || !one["tool"]) return false;
    const bool was = (gState == "running");
    String prev = gState;
    gState = "running";
    const bool ok = runTool(one);
    if (!was) gState = prev == "error" ? "idle" : prev;
    return ok;
  }
  const bool was = (gState == "running");
  String prev = gState;
  gState = "running";
  bool ok = true;
  for (JsonObject step : tools) {
    if (!runTool(step)) {
      ok = false;
      break;
    }
  }
  if (!was) gState = (gState == "error") ? "error" : (prev.length() ? prev : "idle");
  return ok;
}
