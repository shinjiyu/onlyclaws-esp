#include <Adafruit_GFX.h>
#include <Arduino.h>
#include <ArduinoJson.h>
#include <Fonts/FreeMonoBold12pt7b.h>
#include <Fonts/FreeMonoBold18pt7b.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <esp_mac.h>
#include <esp_netif.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <math.h>
#include <string.h>

#include "api_config.h"
#include "audio_es8311.h"
#include "ble_ctrl.h"
#include "board_pins.h"
#include "http_pad.h"
#include "cloud_config.h"
#include "device_secrets.h"
#include "panel_display.h"
#include "script_engine.h"
#include "sensors.h"
#ifdef BOARD_PANEL_EPAPER
#include "epd397_panel.h"
#else
#include "st7305_rlcd.h"
#endif
#include "wifi_ap_prov.h"
#include "wifi_store.h"

namespace {
constexpr const char *FW_VERSION = "agent-runtime-0.13.1";
constexpr uint32_t STATUS_INTERVAL_MS = 60UL * 1000UL;
constexpr size_t FRAME_BYTES = LCD_WIDTH * LCD_HEIGHT / 8;

#ifdef BOARD_PANEL_EPAPER
Epd397Panel display;
#else
St7305Rlcd display;
#endif
WiFiClientSecure tls;
uint8_t *frameBuf = nullptr;
String lastShownId;
uint32_t lastSensorMs = 0;
SensorReading lastSensors{};
String statusLine1 = "OnlyClaws";
String statusLine2 = "runtime";

String macSuffix() {
  uint8_t mac[6] = {};
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char buf[13];
  snprintf(buf, sizeof(buf), "%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2],
           mac[3], mac[4], mac[5]);
  return String(buf);
}

void forcePublicDns() {
  esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
  if (!netif) return;
  esp_netif_dns_info_t dns{};
  dns.ip.type = ESP_IPADDR_TYPE_V4;
  dns.ip.u_addr.ip4.addr = ESP_IP4TOADDR(223, 5, 5, 5);
  esp_netif_set_dns_info(netif, ESP_NETIF_DNS_MAIN, &dns);
  dns.ip.u_addr.ip4.addr = ESP_IP4TOADDR(8, 8, 8, 8);
  esp_netif_set_dns_info(netif, ESP_NETIF_DNS_BACKUP, &dns);
}

bool bootButtonHeld(uint32_t ms = 1500) {
  if (digitalRead(PIN_BOOT_BTN) != LOW) return false;
  const uint32_t start = millis();
  while (digitalRead(PIN_BOOT_BTN) == LOW) {
    if (millis() - start >= ms) return true;
    delay(10);
  }
  return false;
}

bool ensureFrameBuf() {
  if (frameBuf) return true;
  frameBuf = (uint8_t *)heap_caps_malloc(FRAME_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!frameBuf) frameBuf = (uint8_t *)malloc(FRAME_BYTES);
  return frameBuf != nullptr;
}

void drawStatus(const char *title, const char *line2, const char *line3 = nullptr) {
  display.fillScreen(0);
  display.drawRect(4, 4, LCD_WIDTH - 8, LCD_HEIGHT - 8, 1);
  display.setTextColor(1);
  display.setFont(&FreeMonoBold18pt7b);
  display.setCursor(24, 48);
  display.print(title);
  display.setFont(&FreeMonoBold12pt7b);
  display.setCursor(24, 96);
  display.print(line2);
  if (line3) {
    display.setCursor(24, 132);
    display.print(line3);
  }
  display.setCursor(24, 180);
  display.print("MAC ");
  display.print(macSuffix());
  display.setCursor(24, 216);
  display.print(FW_VERSION);
  display.flush();
}

void drawRuntimeHud(bool forceSensors = false) {
  if (forceSensors || millis() - lastSensorMs > 30000) {
    SensorReading r;
    if (sensorsRead(r)) lastSensors = r;
    lastSensorMs = millis();
  }
  char line3[48];
  snprintf(line3, sizeof(line3), "script %s", scriptEngineState());
  drawStatus(statusLine1.c_str(), statusLine2.c_str(), line3);
}

void drawPortalHint() {
  drawStatus("WiFi Setup", "1) Join OC-Setup-*", "2) http://192.168.4.1/");
}

void drawBitmapFrame() {
  if (!frameBuf) return;
  // 1-bit framebuffer already matches panel geometry.
  display.drawBitmap(0, 0, frameBuf, LCD_WIDTH, LCD_HEIGHT, 1, 0);
  display.flush();
}

bool connectWifiWith(const WifiCreds &c, uint32_t timeoutMs = 20000) {
  if (!c.ssid.length()) return false;
  Serial.printf("WiFi connecting SSID=%s\n", c.ssid.c_str());
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(c.ssid.c_str(), c.pass.c_str());
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) {
    delay(300);
    Serial.print('.');
  }
  Serial.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi failed");
    return false;
  }
  forcePublicDns();
  Serial.printf("WiFi OK ip=%s rssi=%d\n", WiFi.localIP().toString().c_str(),
                WiFi.RSSI());
  return true;
}

bool ensureWifiConnected() {
  if (bootButtonHeld()) {
    drawPortalHint();
    if (!wifiApProvision(0)) return false;
  }
  for (int attempt = 0; attempt < 3; ++attempt) {
    WifiCreds creds;
    if (!wifiStoreLoad(creds)) {
      drawPortalHint();
      if (!wifiApProvision(0)) return false;
      continue;
    }
    drawStatus("Connecting", creds.ssid.c_str());
    if (connectWifiWith(creds)) return true;
    drawPortalHint();
    if (!wifiApProvision(0)) return false;
  }
  return WiFi.status() == WL_CONNECTED;
}

String apiUrl(const char *suffix) { return apiDeviceUrl(suffix); }
String absoluteUrl(const char *pathOrUrl) { return apiAbsoluteUrl(pathOrUrl); }

SemaphoreHandle_t httpMutex = nullptr;
bool httpLock() {
  if (!httpMutex) httpMutex = xSemaphoreCreateMutex();
  return httpMutex && xSemaphoreTake(httpMutex, pdMS_TO_TICKS(60000)) == pdTRUE;
}
void httpUnlock() {
  if (httpMutex) xSemaphoreGive(httpMutex);
}

bool httpJson(const char *method, const String &url, const String &body, String &out,
              uint32_t timeoutMs) {
  if (WiFi.status() != WL_CONNECTED) return false;
  if (!httpLock()) return false;
  HTTPClient http;
  http.setTimeout(timeoutMs);
  http.setReuse(false);
  tls.setInsecure();
  tls.setTimeout(timeoutMs);
  Serial.printf("%s heap=%u %s\n", method, ESP.getFreeHeap(), url.c_str());
  bool ok = false;
  if (http.begin(tls, url)) {
    http.addHeader("Authorization", String("Bearer ") + apiDeviceToken());
    http.addHeader("Content-Type", "application/json");
    int code = (strcmp(method, "GET") == 0) ? http.GET() : http.POST(body);
    out = http.getString();
    http.end();
    if (code < 200 || code >= 300) Serial.printf("HTTP %d\n", code);
    else ok = true;
  }
  httpUnlock();
  return ok;
}

// Lua-facing HTTP: any URL, no OnlyClaws device bearer. Returns false only on
// transport failure (statusOut stays < 0). Non-2xx still returns true with code.
bool hostHttpRequest(const char *method, const char *url, const char *reqBody, int *statusOut,
                     String *respOut, uint32_t timeoutMs) {
  if (statusOut) *statusOut = -1;
  if (respOut) *respOut = "";
  if (!method || !url || !url[0]) {
    if (respOut) *respOut = "bad args";
    return false;
  }
  if (WiFi.status() != WL_CONNECTED) {
    if (respOut) *respOut = "wifi down";
    return false;
  }
  if (!httpLock()) {
    if (respOut) *respOut = "http busy";
    return false;
  }

  HTTPClient http;
  http.setTimeout(timeoutMs);
  http.setReuse(false);

  const bool isHttps = strncmp(url, "https://", 8) == 0;
  const bool isHttp = strncmp(url, "http://", 7) == 0;
  bool began = false;
  if (isHttps) {
    tls.setInsecure();
    tls.setTimeout(timeoutMs);
    began = http.begin(tls, url);
  } else if (isHttp) {
    began = http.begin(url);
  } else {
    httpUnlock();
    if (respOut) *respOut = "url must be http(s)";
    return false;
  }

  bool transportOk = false;
  if (began) {
    String m = method;
    m.toUpperCase();
    http.addHeader("Content-Type", "application/json");
    http.addHeader("User-Agent", "OnlyClaws-ESP-Lua/1");
    int code = -1;
    if (m == "GET") {
      code = http.GET();
    } else if (m == "POST") {
      code = http.POST(reqBody ? reqBody : "");
    } else if (m == "PUT") {
      code = http.PUT(reqBody ? reqBody : "");
    } else if (m == "DELETE") {
      code = http.sendRequest("DELETE", (uint8_t *)nullptr, 0);
    } else {
      http.end();
      httpUnlock();
      if (respOut) *respOut = "method not allowed";
      return false;
    }
    String body = http.getString();
    http.end();
    if (code > 0) {
      transportOk = true;
      if (statusOut) *statusOut = code;
      if (respOut) *respOut = body;
    } else {
      if (respOut) *respOut = "http transport error";
    }
    Serial.printf("lua-http %s %d %s\n", m.c_str(), code, url);
  } else {
    if (respOut) *respOut = "http begin failed";
  }
  httpUnlock();
  return transportOk;
}

bool downloadAsset(const String &url) {
  if (!ensureFrameBuf() || WiFi.status() != WL_CONNECTED) return false;
  if (!httpLock()) return false;
  HTTPClient http;
  http.setTimeout(45000);
  http.setReuse(false);
  tls.setInsecure();
  tls.setTimeout(30000);
  bool ok = false;
  if (http.begin(tls, url)) {
    http.addHeader("Authorization", String("Bearer ") + apiDeviceToken());
    if (http.GET() == 200) {
      WiFiClient *stream = http.getStreamPtr();
      size_t got = 0;
      const uint32_t t0 = millis();
      while (got < FRAME_BYTES && millis() - t0 < 45000) {
        size_t avail = stream->available();
        if (!avail) {
          if (!http.connected()) break;
          delay(2);
          yield();
          continue;
        }
        got += stream->readBytes(frameBuf + got, min(avail, FRAME_BYTES - got));
      }
      ok = got == FRAME_BYTES;
    }
    http.end();
  }
  httpUnlock();
  return ok;
}

bool emitDeviceEvent(const char *name, const char *jsonData) {
  DynamicJsonDocument doc(768);
  doc["name"] = name ? name : "event";
  doc["script_id"] = scriptEngineScriptId();
  if (jsonData && jsonData[0]) {
    DynamicJsonDocument data(512);
    if (!deserializeJson(data, jsonData)) doc["data"] = data.as<JsonVariant>();
    else doc["data"] = jsonData;
  } else {
    doc.createNestedObject("data");
  }
  String body;
  serializeJson(doc, body);
  String out;
  return httpJson("POST", apiUrl("/events"), body, out, 12000);
}

bool hostReadSensors(SensorReading &out) { return sensorsRead(out); }
bool hostBeep(uint16_t freq, uint16_t ms) {
  return audioIsReady() && audioPlayBeep(freq, ms);
}
bool hostPlayPcm(const int16_t *samples, size_t count) {
  return audioIsReady() && audioPlayPcm(samples, count);
}
uint32_t hostSampleRate() { return audioSampleRate(); }
void hostSetPa(bool on) { audioSetPa(on); }
bool hostAudioReady() { return audioIsReady(); }
bool hostKeyDown() { return digitalRead(PIN_KEY_BTN) == LOW; }
bool hostBootDown() { return digitalRead(PIN_BOOT_BTN) == LOW; }
int hostWifiRssi() { return WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0; }
void hostWifiIp(char *out, size_t n) {
  if (!out || !n) return;
  if (WiFi.status() != WL_CONNECTED) {
    out[0] = 0;
    return;
  }
  String ip = WiFi.localIP().toString();
  strncpy(out, ip.c_str(), n - 1);
  out[n - 1] = 0;
}
void hostWifiSsid(char *out, size_t n) {
  if (!out || !n) return;
  String ssid = WiFi.SSID();
  strncpy(out, ssid.c_str(), n - 1);
  out[n - 1] = 0;
}
void hostOnSensors(const SensorReading &r) { lastSensors = r; }

void postStatus() {
  SensorReading r;
  if (sensorsRead(r)) lastSensors = r;
  lastSensorMs = millis();
  DynamicJsonDocument doc(768);
  doc["ip"] = WiFi.localIP().toString();
  doc["rssi"] = WiFi.RSSI();
  doc["fw"] = FW_VERSION;
  JsonObject meta = doc.createNestedObject("meta");
  if (lastSensors.okTemp) {
    meta["temp_c"] = lastSensors.tempC;
    meta["humidity"] = lastSensors.humidity;
  }
  if (lastSensors.okBattery) {
    meta["battery_v"] = lastSensors.batteryV;
    meta["battery_pct"] = lastSensors.batteryPct;
  }
  meta["script_id"] = scriptEngineScriptId();
  meta["script_state"] = scriptEngineState();
  meta["script_lang"] = scriptEngineLanguage();
  if (scriptEngineLastError()[0]) meta["script_error"] = scriptEngineLastError();
  meta["api_host"] = apiConfigGet().host;
  String body;
  serializeJson(doc, body);
  String out;
  if (httpJson("POST", apiUrl("/status"), body, out, 15000)) Serial.println("status ok");
}

void ackMessage(const String &messageId, bool ok, uint32_t ms) {
  String body = String("{\"message_id\":\"") + messageId +
                "\",\"ok\":" + (ok ? "true" : "false") + ",\"ms\":" + String(ms) + "}";
  String out;
  httpJson("POST", apiUrl("/ack"), body, out, 15000);
}

bool loadLuaFromEnvelope(const String &scriptIdIn, const String &bodyIn) {
  String scriptId = scriptIdIn;
  String mode = "loop";
  uint32_t everyMs = 1000;
  String lua;

  DynamicJsonDocument wrap(16384);
  if (!deserializeJson(wrap, bodyIn)) {
    if (wrap["script_id"]) scriptId = wrap["script_id"].as<String>();
    if (wrap["mode"]) mode = wrap["mode"].as<String>();
    if (!wrap["every_ms"].isNull()) everyMs = wrap["every_ms"].as<uint32_t>();
    const char *lang = wrap["language"] | "lua";
    if (strcmp(lang, "lua") != 0) {
      Serial.printf("[script] unsupported language=%s\n", lang);
      return false;
    }
    if (wrap["source"].is<const char *>()) {
      lua = wrap["source"].as<const char *>();
    } else if (wrap["source"].is<String>()) {
      lua = wrap["source"].as<String>();
    } else if (!wrap["source"].isNull()) {
      // Reject JSON-tools objects; framework is Lua-only now.
      return false;
    }
  } else {
    // Raw Lua source in body
    lua = bodyIn;
  }
  if (!lua.length()) return false;
  return scriptEngineLoadLua(scriptId.c_str(), lua.c_str(), mode.c_str(), everyMs);
}

bool handlePayload(const String &json) {
  DynamicJsonDocument doc(16384);
  if (deserializeJson(doc, json)) return false;
  if (!doc["success"].as<bool>() || doc["message"].isNull()) return false;
  JsonObject msg = doc["message"].as<JsonObject>();
  String id = msg["id"] | "";
  if (!id.length() || lastShownId == id) return true;

  const char *type = msg["type"] | "bitmap";
  Serial.printf("new message id=%s type=%s\n", id.c_str(), type);
  const uint32_t t0 = millis();
  bool ok = false;

  if (!strcmp(type, "script_stop")) {
    scriptEngineStop("remote stop");
    statusLine1 = "OnlyClaws";
    statusLine2 = "script stopped";
    if (!display.slowPanel()) drawRuntimeHud(true);
    postStatus();
    ok = true;
  } else if (!strcmp(type, "script")) {
    String scriptId = msg["title"] | "";
    String body = msg["body"] | "";
    ok = loadLuaFromEnvelope(scriptId, body);
    if (ok) {
      statusLine1 = "script";
      statusLine2 = scriptId.length() ? scriptId : "running";
      // Skip HUD overlay on slow panels — script will paint next tick.
      if (!display.slowPanel()) drawRuntimeHud(false);
      if (audioIsReady()) audioPlayBeep(660, 80);
      postStatus();
    }
  } else if (!strcmp(type, "invoke")) {
    ok = scriptEngineInvokeJson(msg["body"] | "");
    drawRuntimeHud(false);
  } else {
    // Optional bitmap push (framework display surface, not character UI).
    JsonObject actions = msg["actions"].as<JsonObject>();
    const bool doBeep = actions.isNull() ? false : (actions["beep"] | false);
    String asset = absoluteUrl(msg["asset_path"] | "");
    String title = msg["title"] | "";
    if (asset.length()) {
      ok = downloadAsset(asset);
      if (ok) drawBitmapFrame();
    } else if (title.length()) {
      statusLine1 = title;
      statusLine2 = msg["body"] | "";
      drawRuntimeHud(false);
      ok = true;
    } else {
      ok = doBeep;
    }
    if (doBeep && audioIsReady()) audioPlayBeep(880, 100);
  }

  ackMessage(id, ok, millis() - t0);
  if (ok) lastShownId = id;
  return ok;
}

volatile uint32_t keyDownAtMs = 0;
volatile bool keyHeld = false;
volatile bool keyShortPending = false;
volatile bool keyLongPending = false;
volatile bool keyLongArmed = false;

void IRAM_ATTR onKeyIsr() {
  const bool down = digitalRead(PIN_KEY_BTN) == LOW;
  const uint32_t now = millis();
  if (down) {
    keyDownAtMs = now;
    keyHeld = true;
    keyLongArmed = true;
  } else {
    if (keyHeld) {
      const uint32_t held = now - keyDownAtMs;
      if (held >= 25 && held < 1500) keyShortPending = true;
    }
    keyHeld = false;
    keyLongArmed = false;
  }
}

char netJsonBuf[16384];
volatile bool netJsonReady = false;

void netTask(void *) {
  uint32_t lastStatus = 0;
  for (;;) {
    if (WiFi.status() != WL_CONNECTED) {
      vTaskDelay(pdMS_TO_TICKS(200));
      continue;
    }
    if (!netJsonReady) {
      String out;
      if (httpJson("GET", apiUrl("/pending"), "", out, 6000)) {
        if (out.length() && out.length() < sizeof(netJsonBuf) - 1) {
          memcpy(netJsonBuf, out.c_str(), out.length() + 1);
          netJsonReady = true;
        }
      }
    }
    if (millis() - lastStatus > STATUS_INTERVAL_MS) {
      postStatus();
      lastStatus = millis();
    }
    vTaskDelay(pdMS_TO_TICKS(2500));
  }
}

void setupImpl() {
  Serial.begin(115200);
  delay(400);
  Serial.println();
  Serial.println("=== OnlyClaws ESP runtime (Lua) ===");
  apiConfigBegin();
  Serial.printf("fw=%s panel=%s device=%s cloud=%s%s heap=%u\n", FW_VERSION,
                display.panelName(), apiConfigGet().deviceId.c_str(),
                apiConfigGet().host.c_str(), apiConfigGet().pathPrefix.c_str(),
                ESP.getFreeHeap());

  pinMode(PIN_KEY_BTN, INPUT_PULLUP);
  pinMode(PIN_BOOT_BTN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_KEY_BTN), onKeyIsr, CHANGE);

  display.begin();
#ifndef BOARD_PANEL_EPAPER
  ensureFrameBuf();
#endif
  sensorsBegin();

  ScriptHost host{};
  host.display = &display;
  host.readSensors = hostReadSensors;
  host.beep = hostBeep;
  host.playPcm = hostPlayPcm;
  host.sampleRate = hostSampleRate;
  host.setPa = hostSetPa;
  host.audioReady = hostAudioReady;
  host.keyDown = hostKeyDown;
  host.bootDown = hostBootDown;
  host.wifiRssi = hostWifiRssi;
  host.wifiIp = hostWifiIp;
  host.wifiSsid = hostWifiSsid;
  host.httpRequest = hostHttpRequest;
  host.emitEvent = emitDeviceEvent;
  host.onSensors = hostOnSensors;
  scriptEngineBegin(host);

  if (audioBegin(16000)) audioPlayBeep(880, 80);

  while (!ensureWifiConnected()) delay(1000);

  // ESP32 requires WiFi modem sleep when BLE is also on (else abort).
  WiFi.setSleep(true);
#ifndef BOARD_PANEL_EPAPER
  // NimBLE + TLS + 800x480 panel leave too little internal heap for mbedTLS.
  bleCtrlBegin("OC-Snake");
#else
  Serial.println("[ble] skipped on ePaper (heap)");
#endif
  httpPadBegin(80);

  statusLine1 = "OnlyClaws";
  statusLine2 = WiFi.localIP().toString();
  drawRuntimeHud(true);
  postStatus();

  Serial.printf("ready. pad http://%s/", WiFi.localIP().toString().c_str());
#ifndef BOARD_PANEL_EPAPER
  Serial.print("  BLE=OC-Snake");
#endif
  Serial.println();
  xTaskCreatePinnedToCore(netTask, "net", 8192, nullptr, 1, nullptr, 0);
}

void loopImpl() {
  if (keyHeld && keyLongArmed && (millis() - keyDownAtMs > 1500)) {
    keyLongArmed = false;
    keyLongPending = true;
  }

  if (keyLongPending) {
    keyLongPending = false;
    keyShortPending = false;
    drawPortalHint();
    if (wifiApProvision(0)) {
      WifiCreds creds;
      if (wifiStoreLoad(creds) && connectWifiWith(creds)) {
        drawRuntimeHud(true);
        postStatus();
      }
    } else if (WiFi.status() == WL_CONNECTED) {
      drawRuntimeHud(true);
    }
    while (digitalRead(PIN_KEY_BTN) == LOW) delay(20);
  }

  if (keyShortPending) {
    keyShortPending = false;
    if (audioIsReady()) audioPlayBeep(1000, 120);
  }

  if (netJsonReady) {
    netJsonReady = false;
    handlePayload(String(netJsonBuf));
  }

  scriptEngineTick();

  if (WiFi.status() != WL_CONNECTED) {
    WifiCreds creds;
    if (wifiStoreLoad(creds) && connectWifiWith(creds, 15000)) {
      drawRuntimeHud(true);
      postStatus();
    } else {
      drawPortalHint();
      wifiApProvision(0);
    }
    delay(500);
    return;
  }

  delay(15);
}
}  // namespace

void setup() { setupImpl(); }
void loop() { loopImpl(); }
