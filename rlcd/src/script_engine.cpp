#include "script_engine.h"

#include <ArduinoJson.h>
#include <EspLuaEngine.h>
#include <math.h>
#include <string.h>

namespace {
ScriptHost gHost{};
EspLuaEngine *gLua = nullptr;
String gSource;
String gScriptId;
String gState = "idle";
String gError;
String gMode = "once";
uint32_t gEveryMs = 1000;
uint32_t gNextDueMs = 0;
bool gStartDone = false;
SensorReading gVars{};
bool gHasVars = false;
bool gSleepRequested = false;

void setError(const char *msg) {
  gError = msg ? msg : "error";
  gState = "error";
  Serial.printf("[lua] error: %s\n", gError.c_str());
}

int l_beep(lua_State *L) {
  const int freq = luaL_optinteger(L, 1, 880);
  const int ms = luaL_optinteger(L, 2, 100);
  if (!gHost.beep) {
    lua_pushboolean(L, 0);
    return 1;
  }
  uint16_t f = (uint16_t)constrain(freq, 100, 8000);
  uint16_t m = (uint16_t)constrain(ms, 1, 2000);
  lua_pushboolean(L, gHost.beep(f, m) ? 1 : 0);
  return 1;
}

int l_sensors(lua_State *L) {
  lua_newtable(L);
  if (!gHost.readSensors) return 1;
  SensorReading r;
  if (!gHost.readSensors(r)) return 1;
  gVars = r;
  gHasVars = true;
  if (gHost.onSensors) gHost.onSensors(r);
  if (r.okTemp) {
    lua_pushnumber(L, r.tempC);
    lua_setfield(L, -2, "temp_c");
    lua_pushnumber(L, r.humidity);
    lua_setfield(L, -2, "humidity");
  }
  if (r.okBattery) {
    lua_pushnumber(L, r.batteryV);
    lua_setfield(L, -2, "battery_v");
    lua_pushinteger(L, r.batteryPct);
    lua_setfield(L, -2, "battery_pct");
  }
  return 1;
}

int l_emit(lua_State *L) {
  const char *name = luaL_optstring(L, 1, "event");
  String data = "{}";
  if (lua_istable(L, 2)) {
    // Minimal table→JSON for flat string/number/bool fields.
    DynamicJsonDocument doc(512);
    JsonObject o = doc.to<JsonObject>();
    lua_pushnil(L);
    while (lua_next(L, 2) != 0) {
      if (lua_type(L, -2) == LUA_TSTRING) {
        const char *k = lua_tostring(L, -2);
        if (lua_isboolean(L, -1)) o[k] = (bool)lua_toboolean(L, -1);
        else if (lua_isinteger(L, -1)) o[k] = (long)lua_tointeger(L, -1);
        else if (lua_isnumber(L, -1)) o[k] = (double)lua_tonumber(L, -1);
        else if (lua_isstring(L, -1)) o[k] = lua_tostring(L, -1);
      }
      lua_pop(L, 1);
    }
    data = "";
    serializeJson(o, data);
  } else if (gHasVars) {
    DynamicJsonDocument doc(256);
    JsonObject o = doc.to<JsonObject>();
    if (gVars.okTemp) {
      o["temp_c"] = gVars.tempC;
      o["humidity"] = gVars.humidity;
    }
    if (gVars.okBattery) {
      o["battery_v"] = gVars.batteryV;
      o["battery_pct"] = gVars.batteryPct;
    }
    data = "";
    serializeJson(o, data);
  }
  bool ok = gHost.emitEvent && gHost.emitEvent(name, data.c_str());
  lua_pushboolean(L, ok ? 1 : 0);
  return 1;
}

int l_display(lua_State *L) {
  const char *a = luaL_optstring(L, 1, "");
  const char *b = luaL_optstring(L, 2, "");
  if (gHost.displayText) gHost.displayText(a, b);
  return 0;
}

int l_log(lua_State *L) {
  const int n = lua_gettop(L);
  Serial.print("[lua] ");
  for (int i = 1; i <= n; ++i) {
    if (i > 1) Serial.print(' ');
    if (lua_isstring(L, i) || lua_isnumber(L, i)) Serial.print(lua_tostring(L, i));
    else Serial.print(lua_typename(L, lua_type(L, i)));
  }
  Serial.println();
  return 0;
}

int l_sleep(lua_State *L) {
  uint32_t ms = (uint32_t)luaL_optinteger(L, 1, 0);
  if (ms > 60000) ms = 60000;
  gNextDueMs = millis() + ms;
  gSleepRequested = true;
  return 0;
}

int l_stop(lua_State *L) {
  (void)L;
  scriptEngineStop("script stop");
  return 0;
}

int l_millis(lua_State *L) {
  lua_pushinteger(L, (lua_Integer)millis());
  return 1;
}

bool bindApis() {
  if (!gLua) return false;
  bool ok = true;
  ok &= gLua->registerFunction("beep", l_beep);
  ok &= gLua->registerFunction("sensors", l_sensors);
  ok &= gLua->registerFunction("emit", l_emit);
  ok &= gLua->registerFunction("display", l_display);
  ok &= gLua->registerFunction("log", l_log);
  ok &= gLua->registerFunction("sleep", l_sleep);
  ok &= gLua->registerFunction("stop", l_stop);
  ok &= gLua->registerFunction("millis", l_millis);
  // Namespace table: oc.*
  const char *boot =
      "oc = oc or {}\n"
      "oc.beep = beep\n"
      "oc.sensors = sensors\n"
      "oc.emit = emit\n"
      "oc.display = display\n"
      "oc.log = log\n"
      "oc.sleep = sleep\n"
      "oc.stop = stop\n"
      "oc.millis = millis\n";
  ok &= gLua->executeScript(boot);
  return ok;
}

bool hasGlobalFn(const char *fn) {
  if (!gLua || !gLua->getLuaState()) return false;
  lua_State *L = gLua->getLuaState();
  lua_getglobal(L, fn);
  const bool ok = lua_isfunction(L, -1);
  lua_pop(L, 1);
  return ok;
}

bool callGlobal(const char *fn) {
  if (!gLua || !gLua->getLuaState()) return false;
  if (!hasGlobalFn(fn)) return true;
  lua_State *L = gLua->getLuaState();
  lua_getglobal(L, fn);
  gSleepRequested = false;
  if (lua_pcall(L, 0, 1, 0) != LUA_OK) {
    const char *err = lua_tostring(L, -1);
    setError(err ? err : "lua pcall failed");
    lua_pop(L, 1);
    return false;
  }
  if (lua_isnumber(L, -1)) {
    uint32_t ms = (uint32_t)lua_tointeger(L, -1);
    if (ms > 0) {
      if (ms > 60000) ms = 60000;
      gNextDueMs = millis() + ms;
      gSleepRequested = true;
    }
  }
  lua_pop(L, 1);
  return gState == "running";
}

bool resetEngine() {
  if (gLua) {
    delete gLua;
    gLua = nullptr;
  }
  gLua = new EspLuaEngine();
  if (!gLua) {
    setError("lua alloc failed");
    return false;
  }
  if (!bindApis()) {
    setError(gLua->getLastError());
    return false;
  }
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

bool scriptEngineLoadLua(const char *scriptId, const char *luaSource, const char *mode,
                         uint32_t everyMs) {
  if (!luaSource || !luaSource[0]) {
    setError("empty lua");
    return false;
  }
  if (!resetEngine()) return false;
  gScriptId = scriptId ? scriptId : "";
  gSource = luaSource;
  gMode = (mode && !strcmp(mode, "once")) ? "once" : "loop";
  gEveryMs = everyMs < 50 ? 50 : (everyMs > 3600000UL ? 3600000UL : everyMs);
  gStartDone = false;
  gNextDueMs = 0;
  gError = "";
  gState = "running";

  if (!gLua->executeScript(luaSource)) {
    setError(gLua->getLastError());
    return false;
  }
  Serial.printf("[lua] loaded id=%s mode=%s every=%u bytes=%u\n", gScriptId.c_str(),
                gMode.c_str(), (unsigned)gEveryMs, (unsigned)gSource.length());
  return true;
}

void scriptEngineStop(const char *reason) {
  gState = "stopped";
  if (reason && reason[0]) gError = reason;
  Serial.printf("[lua] stop: %s\n", gError.c_str());
}

void scriptEngineTick() {
  if (gState != "running") return;
  const uint32_t now = millis();
  if (gNextDueMs && (int32_t)(now - gNextDueMs) < 0) return;
  gNextDueMs = 0;

  if (!gStartDone) {
    gStartDone = true;
    if (!callGlobal("on_start")) return;
    if (gState != "running") return;
    if (!callGlobal("setup")) return;
    if (gState != "running") return;
  }

  const char *fn = nullptr;
  if (hasGlobalFn("on_loop")) fn = "on_loop";
  else if (hasGlobalFn("loop")) fn = "loop";

  if (fn) {
    gSleepRequested = false;
    if (!callGlobal(fn)) return;
    if (gState != "running") return;
    if (!gSleepRequested) {
      if (gMode == "loop") gNextDueMs = millis() + gEveryMs;
      else scriptEngineStop("done");
    }
    return;
  }

  // Top-level-only script already ran at load.
  if (gMode == "loop") {
    if (!gLua->executeScript(gSource.c_str())) {
      setError(gLua->getLastError());
      return;
    }
    gNextDueMs = millis() + gEveryMs;
  } else {
    scriptEngineStop("done");
  }
}

bool scriptEngineIsRunning() { return gState == "running"; }
const char *scriptEngineScriptId() { return gScriptId.c_str(); }
const char *scriptEngineState() { return gState.c_str(); }
const char *scriptEngineLastError() { return gError.c_str(); }
const char *scriptEngineLanguage() { return "lua"; }

bool scriptEngineInvokeJson(const char *json) {
  if (!json || !json[0]) return false;
  DynamicJsonDocument doc(4096);
  if (deserializeJson(doc, json)) return false;
  JsonArray tools = doc["tools"].as<JsonArray>();
  if (tools.isNull() && doc.is<JsonArray>()) tools = doc.as<JsonArray>();

  auto runOne = [&](JsonObject step) -> bool {
    const char *tool = step["tool"] | "";
    if (!strcmp(tool, "beep")) {
      if (!gHost.beep) return false;
      return gHost.beep(step["freq"] | 880, step["ms"] | 100);
    }
    if (!strcmp(tool, "sensors.read") || !strcmp(tool, "sensors")) {
      if (!gHost.readSensors) return false;
      SensorReading r;
      if (!gHost.readSensors(r)) return false;
      gVars = r;
      gHasVars = true;
      if (gHost.onSensors) gHost.onSensors(r);
      return true;
    }
    if (!strcmp(tool, "display")) {
      if (gHost.displayText)
        gHost.displayText(step["title"] | step["line1"] | "", step["line2"] | "");
      return true;
    }
    if (!strcmp(tool, "emit")) {
      if (!gHost.emitEvent) return false;
      String data = "{}";
      if (!step["data"].isNull()) serializeJson(step["data"], data);
      return gHost.emitEvent(step["name"] | "event", data.c_str());
    }
    return false;
  };

  if (tools.isNull()) {
    JsonObject one = doc.as<JsonObject>();
    if (one.isNull() || !one["tool"]) return false;
    return runOne(one);
  }
  for (JsonObject step : tools) {
    if (!runOne(step)) return false;
  }
  return true;
}
