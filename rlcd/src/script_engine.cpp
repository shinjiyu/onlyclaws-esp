#include "script_engine.h"

#include <Adafruit_GFX.h>
#include <ArduinoJson.h>
#include <EspLuaEngine.h>
#include <Fonts/FreeMonoBold12pt7b.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "board_pins.h"
#include "ble_ctrl.h"
#include "pad_ctrl.h"
#include "panel_display.h"

#include <qrcode.h>

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
bool gSleepRequested = false;
SensorReading gVars{};
bool gHasVars = false;

// Scratch for PCM decode (PSRAM preferred).
int16_t *gPcmBuf = nullptr;
size_t gPcmCap = 0;

void setError(const char *msg) {
  gError = msg ? msg : "error";
  gState = "error";
  Serial.printf("[lua] error: %s\n", gError.c_str());
}

PanelDisplay *lcd() { return gHost.display; }

int b64Val(char c) {
  if (c >= 'A' && c <= 'Z') return c - 'A';
  if (c >= 'a' && c <= 'z') return c - 'a' + 26;
  if (c >= '0' && c <= '9') return c - '0' + 52;
  if (c == '+') return 62;
  if (c == '/') return 63;
  return -1;
}

// Decode base64 into out; returns byte count or 0 on failure.
size_t b64Decode(const char *in, uint8_t *out, size_t outMax) {
  if (!in || !out) return 0;
  size_t n = 0;
  int val = 0, valb = -8;
  for (const char *p = in; *p; ++p) {
    if (*p == '=' || *p == '\n' || *p == '\r' || *p == ' ') continue;
    int d = b64Val(*p);
    if (d < 0) return 0;
    val = (val << 6) + d;
    valb += 6;
    if (valb >= 0) {
      if (n >= outMax) return 0;
      out[n++] = (uint8_t)((val >> valb) & 0xFF);
      valb -= 8;
    }
  }
  return n;
}

bool ensurePcmCap(size_t samples) {
  if (gPcmCap >= samples) return true;
  if (gPcmBuf) free(gPcmBuf);
  gPcmBuf = (int16_t *)heap_caps_malloc(samples * sizeof(int16_t),
                                        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!gPcmBuf) gPcmBuf = (int16_t *)malloc(samples * sizeof(int16_t));
  gPcmCap = gPcmBuf ? samples : 0;
  return gPcmBuf != nullptr;
}

// ---- sensors / time / log / emit / stop / sleep ----

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

int l_millis(lua_State *L) {
  lua_pushinteger(L, (lua_Integer)millis());
  return 1;
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

int l_emit(lua_State *L) {
  const char *name = luaL_optstring(L, 1, "event");
  String data = "{}";
  if (lua_istable(L, 2)) {
    DynamicJsonDocument doc(768);
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
  }
  bool ok = gHost.emitEvent && gHost.emitEvent(name, data.c_str());
  lua_pushboolean(L, ok ? 1 : 0);
  return 1;
}

// ---- audio ----

int l_beep(lua_State *L) {
  const int freq = luaL_optinteger(L, 1, 880);
  const int ms = luaL_optinteger(L, 2, 100);
  if (!gHost.beep) {
    lua_pushboolean(L, 0);
    return 1;
  }
  lua_pushboolean(L, gHost.beep((uint16_t)constrain(freq, 20, 8000),
                                (uint16_t)constrain(ms, 1, 5000))
                         ? 1
                         : 0);
  return 1;
}

int l_audio_ready(lua_State *L) {
  lua_pushboolean(L, gHost.audioReady && gHost.audioReady() ? 1 : 0);
  return 1;
}

int l_sample_rate(lua_State *L) {
  lua_pushinteger(L, gHost.sampleRate ? (lua_Integer)gHost.sampleRate() : 16000);
  return 1;
}

int l_pa(lua_State *L) {
  if (gHost.setPa) gHost.setPa(lua_toboolean(L, 1));
  return 0;
}

int l_play_pcm_b64(lua_State *L) {
  const char *b64 = luaL_checkstring(L, 1);
  if (!gHost.playPcm) {
    lua_pushboolean(L, 0);
    return 1;
  }
  // Max ~2s @ 16kHz int16 = 64000 bytes
  constexpr size_t kMaxBytes = 64000;
  uint8_t *raw = (uint8_t *)heap_caps_malloc(kMaxBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!raw) raw = (uint8_t *)malloc(kMaxBytes);
  if (!raw) {
    lua_pushboolean(L, 0);
    return 1;
  }
  size_t n = b64Decode(b64, raw, kMaxBytes);
  if (n < 2 || (n & 1)) {
    free(raw);
    lua_pushboolean(L, 0);
    return 1;
  }
  size_t samples = n / 2;
  if (!ensurePcmCap(samples)) {
    free(raw);
    lua_pushboolean(L, 0);
    return 1;
  }
  memcpy(gPcmBuf, raw, n);
  free(raw);
  bool ok = gHost.playPcm(gPcmBuf, samples);
  lua_pushboolean(L, ok ? 1 : 0);
  return 1;
}

// ---- input / net ----

int l_key(lua_State *L) {
  lua_pushboolean(L, gHost.keyDown && gHost.keyDown() ? 1 : 0);
  return 1;
}

int l_boot(lua_State *L) {
  lua_pushboolean(L, gHost.bootDown && gHost.bootDown() ? 1 : 0);
  return 1;
}

int l_wifi_rssi(lua_State *L) {
  lua_pushinteger(L, gHost.wifiRssi ? gHost.wifiRssi() : 0);
  return 1;
}

int l_wifi_ip(lua_State *L) {
  char buf[48] = {0};
  if (gHost.wifiIp) gHost.wifiIp(buf, sizeof(buf));
  lua_pushstring(L, buf);
  return 1;
}

int l_wifi_ssid(lua_State *L) {
  char buf[40] = {0};
  if (gHost.wifiSsid) gHost.wifiSsid(buf, sizeof(buf));
  lua_pushstring(L, buf);
  return 1;
}

// http_request(method, url [, body [, timeout_ms]]) -> status, body
// status is HTTP code, or -1 on transport / missing host hook.
int l_http_request(lua_State *L) {
  const char *method = luaL_checkstring(L, 1);
  const char *url = luaL_checkstring(L, 2);
  const char *body = luaL_optstring(L, 3, "");
  uint32_t timeoutMs = (uint32_t)luaL_optinteger(L, 4, 8000);
  if (timeoutMs < 500) timeoutMs = 500;
  if (timeoutMs > 30000) timeoutMs = 30000;

  if (!gHost.httpRequest) {
    lua_pushinteger(L, -1);
    lua_pushstring(L, "http unavailable");
    return 2;
  }

  int status = -1;
  String resp;
  bool ok = gHost.httpRequest(method, url, body, &status, &resp, timeoutMs);
  if (!ok && status >= 0) {
    // Host may set status even when treating non-2xx as failure; still return it.
  }
  if (!ok && status < 0) {
    lua_pushinteger(L, -1);
    lua_pushstring(L, resp.length() ? resp.c_str() : "http failed");
    return 2;
  }
  // Cap what we push into Lua (PSRAM devices can still OOM on huge pages).
  const size_t kMax = 8192;
  if (resp.length() > kMax) resp.remove(kMax);
  lua_pushinteger(L, status);
  lua_pushlstring(L, resp.c_str(), resp.length());
  return 2;
}

int l_ble_dir(lua_State *L) {
  char d = padCtrlDir();
  if (d == 0) {
    lua_pushnil(L);
  } else {
    lua_pushlstring(L, &d, 1);
  }
  return 1;
}

int l_ble_connected(lua_State *L) {
  // true if BLE linked OR LAN pad was used recently / any link flag
  lua_pushboolean(L, (bleCtrlConnected() || padCtrlLinked()) ? 1 : 0);
  return 1;
}

int l_ble_restart(lua_State *L) {
  lua_pushboolean(L, padCtrlTakeRestart() ? 1 : 0);
  return 1;
}

// ---- graphics ----

int l_gfx_w(lua_State *L) {
  lua_pushinteger(L, LCD_WIDTH);
  return 1;
}
int l_gfx_h(lua_State *L) {
  lua_pushinteger(L, LCD_HEIGHT);
  return 1;
}

int l_gfx_clear(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) return 0;
  d->fillScreen((uint16_t)luaL_optinteger(L, 1, 0));
  return 0;
}

int l_gfx_pixel(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) return 0;
  d->drawPixel((int16_t)luaL_checkinteger(L, 1), (int16_t)luaL_checkinteger(L, 2),
               (uint16_t)luaL_optinteger(L, 3, 1));
  return 0;
}

int l_gfx_line(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) return 0;
  d->drawLine((int16_t)luaL_checkinteger(L, 1), (int16_t)luaL_checkinteger(L, 2),
              (int16_t)luaL_checkinteger(L, 3), (int16_t)luaL_checkinteger(L, 4),
              (uint16_t)luaL_optinteger(L, 5, 1));
  return 0;
}

int l_gfx_rect(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) return 0;
  d->drawRect((int16_t)luaL_checkinteger(L, 1), (int16_t)luaL_checkinteger(L, 2),
              (int16_t)luaL_checkinteger(L, 3), (int16_t)luaL_checkinteger(L, 4),
              (uint16_t)luaL_optinteger(L, 5, 1));
  return 0;
}

int l_gfx_fill_rect(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) return 0;
  d->fillRect((int16_t)luaL_checkinteger(L, 1), (int16_t)luaL_checkinteger(L, 2),
              (int16_t)luaL_checkinteger(L, 3), (int16_t)luaL_checkinteger(L, 4),
              (uint16_t)luaL_optinteger(L, 5, 1));
  return 0;
}

int l_gfx_circle(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) return 0;
  d->drawCircle((int16_t)luaL_checkinteger(L, 1), (int16_t)luaL_checkinteger(L, 2),
                (int16_t)luaL_checkinteger(L, 3), (uint16_t)luaL_optinteger(L, 4, 1));
  return 0;
}

int l_gfx_fill_circle(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) return 0;
  d->fillCircle((int16_t)luaL_checkinteger(L, 1), (int16_t)luaL_checkinteger(L, 2),
                (int16_t)luaL_checkinteger(L, 3), (uint16_t)luaL_optinteger(L, 4, 1));
  return 0;
}

int l_gfx_text(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) return 0;
  int16_t x = (int16_t)luaL_checkinteger(L, 1);
  int16_t y = (int16_t)luaL_checkinteger(L, 2);
  const char *s = luaL_checkstring(L, 3);
  uint16_t color = (uint16_t)luaL_optinteger(L, 4, 1);
  d->setFont(&FreeMonoBold12pt7b);
  d->setTextColor(color);
  d->setCursor(x, y);
  d->print(s);
  return 0;
}

int l_gfx_flush(lua_State *L) {
  (void)L;
  PanelDisplay *d = lcd();
  if (d) d->flush();
  return 0;
}

int l_panel_slow(lua_State *L) {
  PanelDisplay *d = lcd();
  lua_pushboolean(L, (d && d->slowPanel()) ? 1 : 0);
  return 1;
}

// gfx_qr(x, y, scale, text [, color=1]) -> modules (0 on fail)
// Encodes text as QR. Uses ECC_M + 4-module quiet zone (WeChat-friendly).
int l_gfx_qr(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) {
    lua_pushinteger(L, 0);
    return 1;
  }
  int16_t ox = (int16_t)luaL_checkinteger(L, 1);
  int16_t oy = (int16_t)luaL_checkinteger(L, 2);
  int scale = (int)luaL_optinteger(L, 3, 6);
  const char *text = luaL_checkstring(L, 4);
  uint16_t fg = (uint16_t)luaL_optinteger(L, 5, 1);
  uint16_t bg = fg ? 0 : 1;
  if (scale < 2) scale = 2;
  if (scale > 14) scale = 14;
  if (!text || !text[0]) {
    lua_pushinteger(L, 0);
    return 1;
  }

  // Prefer medium ECC so reflective LCD noise / camera blur still decode.
  QRCode qr;
  uint8_t *buf = nullptr;
  int ver = 0;
  for (int v = 2; v <= 6; ++v) {
    size_t need = (size_t)qrcode_getBufferSize(v);
    uint8_t *tmp = (uint8_t *)malloc(need);
    if (!tmp) break;
    if (qrcode_initText(&qr, tmp, v, ECC_MEDIUM, text) == 0) {
      buf = tmp;
      ver = v;
      break;
    }
    free(tmp);
  }
  // Fallback: ECC_LOW if text is long.
  if (!buf) {
    for (int v = 1; v <= 8; ++v) {
      size_t need = (size_t)qrcode_getBufferSize(v);
      uint8_t *tmp = (uint8_t *)malloc(need);
      if (!tmp) break;
      if (qrcode_initText(&qr, tmp, v, ECC_LOW, text) == 0) {
        buf = tmp;
        ver = v;
        break;
      }
      free(tmp);
    }
  }
  if (!buf || ver == 0) {
    lua_pushinteger(L, 0);
    return 1;
  }

  // Spec quiet zone is 4 modules; WeChat is picky if this is too thin.
  const int quiet = 4;
  const int side = qr.size + quiet * 2;
  const int16_t px = (int16_t)(side * scale);
  // Light pad behind QR (critical for scanners).
  d->fillRect(ox, oy, px, px, bg);
  for (uint8_t y = 0; y < qr.size; ++y) {
    for (uint8_t x = 0; x < qr.size; ++x) {
      if (!qrcode_getModule(&qr, x, y)) continue;
      d->fillRect((int16_t)(ox + (x + quiet) * scale),
                  (int16_t)(oy + (y + quiet) * scale), (int16_t)scale, (int16_t)scale, fg);
    }
  }
  free(buf);
  lua_pushinteger(L, qr.size);
  return 1;
}

// Full-frame 1bpp MONO_HLSB (400x300/8 = 15000 bytes), base64.
int l_gfx_blit_b64(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) {
    lua_pushboolean(L, 0);
    return 1;
  }
  const char *b64 = luaL_checkstring(L, 1);
  const size_t need = d->frameBytes();
  uint8_t *raw = (uint8_t *)heap_caps_malloc(need, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!raw) raw = (uint8_t *)malloc(need);
  if (!raw) {
    lua_pushboolean(L, 0);
    return 1;
  }
  size_t n = b64Decode(b64, raw, need);
  bool ok = false;
  if (n == need) ok = d->showGxBitmap(raw, n);
  free(raw);
  lua_pushboolean(L, ok ? 1 : 0);
  return 1;
}

// Convenience: two-line status (still available).
int l_display(lua_State *L) {
  PanelDisplay *d = lcd();
  if (!d) return 0;
  const char *a = luaL_optstring(L, 1, "");
  const char *b = luaL_optstring(L, 2, "");
  d->fillScreen(0);
  d->drawRect(4, 4, LCD_WIDTH - 8, LCD_HEIGHT - 8, 1);
  d->setFont(&FreeMonoBold12pt7b);
  d->setTextColor(1);
  d->setCursor(24, 48);
  d->print(a);
  d->setCursor(24, 84);
  d->print(b);
  d->flush();
  return 0;
}

bool bindApis() {
  if (!gLua) return false;
  bool ok = true;
  ok &= gLua->registerFunction("sensors", l_sensors);
  ok &= gLua->registerFunction("log", l_log);
  ok &= gLua->registerFunction("millis", l_millis);
  ok &= gLua->registerFunction("sleep", l_sleep);
  ok &= gLua->registerFunction("stop", l_stop);
  ok &= gLua->registerFunction("emit", l_emit);
  ok &= gLua->registerFunction("beep", l_beep);
  ok &= gLua->registerFunction("audio_ready", l_audio_ready);
  ok &= gLua->registerFunction("sample_rate", l_sample_rate);
  ok &= gLua->registerFunction("pa", l_pa);
  ok &= gLua->registerFunction("play_pcm", l_play_pcm_b64);
  ok &= gLua->registerFunction("key", l_key);
  ok &= gLua->registerFunction("boot", l_boot);
  ok &= gLua->registerFunction("wifi_rssi", l_wifi_rssi);
  ok &= gLua->registerFunction("wifi_ip", l_wifi_ip);
  ok &= gLua->registerFunction("wifi_ssid", l_wifi_ssid);
  ok &= gLua->registerFunction("http_request", l_http_request);
  ok &= gLua->registerFunction("ble_dir", l_ble_dir);
  ok &= gLua->registerFunction("ble_connected", l_ble_connected);
  ok &= gLua->registerFunction("ble_restart", l_ble_restart);
  ok &= gLua->registerFunction("display", l_display);
  ok &= gLua->registerFunction("gfx_w", l_gfx_w);
  ok &= gLua->registerFunction("gfx_h", l_gfx_h);
  ok &= gLua->registerFunction("gfx_clear", l_gfx_clear);
  ok &= gLua->registerFunction("gfx_pixel", l_gfx_pixel);
  ok &= gLua->registerFunction("gfx_line", l_gfx_line);
  ok &= gLua->registerFunction("gfx_rect", l_gfx_rect);
  ok &= gLua->registerFunction("gfx_fill_rect", l_gfx_fill_rect);
  ok &= gLua->registerFunction("gfx_circle", l_gfx_circle);
  ok &= gLua->registerFunction("gfx_fill_circle", l_gfx_fill_circle);
  ok &= gLua->registerFunction("gfx_text", l_gfx_text);
  ok &= gLua->registerFunction("gfx_flush", l_gfx_flush);
  ok &= gLua->registerFunction("panel_slow", l_panel_slow);
  ok &= gLua->registerFunction("gfx_qr", l_gfx_qr);
  ok &= gLua->registerFunction("gfx_blit", l_gfx_blit_b64);

  const char *boot = R"LUA(
oc = oc or {}
gfx = gfx or {}
audio = audio or {}
input = input or {}
net = net or {}
ble = ble or {}

oc.sensors = sensors; oc.log = log; oc.millis = millis; oc.sleep = sleep
oc.stop = stop; oc.emit = emit; oc.display = display
oc.beep = beep; oc.play_pcm = play_pcm; oc.key = key

audio.beep = beep; audio.ready = audio_ready; audio.sample_rate = sample_rate
audio.pa = pa; audio.play_pcm = play_pcm

input.key = key; input.boot = boot

ble.dir = ble_dir; ble.connected = ble_connected; ble.restart = ble_restart

net.rssi = wifi_rssi; net.ip = wifi_ip; net.ssid = wifi_ssid
net.http = http_request
http = http or {}
http.request = http_request
http.get = function(url, timeout_ms)
  return http_request("GET", url, "", timeout_ms or 8000)
end
http.post = function(url, body, timeout_ms)
  return http_request("POST", url, body or "", timeout_ms or 8000)
end

gfx.W = gfx_w(); gfx.H = gfx_h()
gfx.clear = gfx_clear; gfx.pixel = gfx_pixel; gfx.line = gfx_line
gfx.rect = gfx_rect; gfx.fill_rect = gfx_fill_rect
gfx.circle = gfx_circle; gfx.fill_circle = gfx_fill_circle
gfx.text = gfx_text; gfx.flush = gfx_flush; gfx.blit = gfx_blit
gfx.qr = gfx_qr
gfx.slow = panel_slow
)LUA";
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
  DynamicJsonDocument doc(8192);
  if (deserializeJson(doc, json)) return false;
  JsonArray tools = doc["tools"].as<JsonArray>();
  if (tools.isNull() && doc.is<JsonArray>()) tools = doc.as<JsonArray>();

  auto runOne = [&](JsonObject step) -> bool {
    const char *tool = step["tool"] | "";
    if (!strcmp(tool, "beep")) {
      return gHost.beep &&
             gHost.beep(step["freq"] | 880, step["ms"] | 100);
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
      // Use convenience two-line helper via temporary lua-less path
      PanelDisplay *d = lcd();
      if (!d) return false;
      d->fillScreen(0);
      d->setFont(&FreeMonoBold12pt7b);
      d->setTextColor(1);
      d->setCursor(24, 48);
      d->print(step["title"] | step["line1"] | "");
      d->setCursor(24, 84);
      d->print(step["line2"] | "");
      d->flush();
      return true;
    }
    if (!strcmp(tool, "gfx.flush")) {
      if (lcd()) lcd()->flush();
      return true;
    }
    if (!strcmp(tool, "gfx.clear")) {
      if (lcd()) lcd()->fillScreen(step["color"] | 0);
      return true;
    }
    if (!strcmp(tool, "emit")) {
      if (!gHost.emitEvent) return false;
      String data = "{}";
      if (!step["data"].isNull()) serializeJson(step["data"], data);
      return gHost.emitEvent(step["name"] | "event", data.c_str());
    }
    if (!strcmp(tool, "play_pcm") && step["b64"]) {
      // Reuse lua binding path
      if (!gLua && !resetEngine()) return false;
      lua_State *L = gLua->getLuaState();
      lua_getglobal(L, "play_pcm");
      lua_pushstring(L, step["b64"] | "");
      if (lua_pcall(L, 1, 1, 0) != LUA_OK) {
        lua_pop(L, 1);
        return false;
      }
      bool ok = lua_toboolean(L, -1);
      lua_pop(L, 1);
      return ok;
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
