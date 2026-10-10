#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_netif.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <string.h>

#include "api_config.h"
#include "arm_driver.h"
#include "arm_usb_serial.h"
#include "audio_plugin.h"
#include "ble_ctrl.h"
#include "board_pins.h"
#include "capability.h"
#include "claude_buddy.h"
#include "cloud_http.h"
#include "http_pad.h"
#include "cloud_config.h"
#include "device_secrets.h"
#include "oc_features.h"
#include "panel_plugin.h"
#include "script_engine.h"
#include "sensors.h"
#include "wifi_ap_prov.h"
#include "wifi_store.h"

namespace {
constexpr const char *FW_VERSION = "agent-runtime-0.17.0";
constexpr uint32_t STATUS_INTERVAL_MS = 60UL * 1000UL;
constexpr uint32_t BATTERY_INTERVAL_MS = 30UL * 1000UL;

// Lua http.* uses its own TLS session so it cannot starve cloud pending/status.
WiFiClientSecure tlsLua;
String lastShownId;
uint32_t lastSensorMs = 0;
SensorReading lastSensors{};
String statusLine1 = "OnlyClaws";
String statusLine2 = "runtime";
OcBattery battery{};
uint32_t lastBatteryMs = 0;
bool bootWasDown = false;
bool hudVisible = false;
char hudClaudeLine[48] = "";

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
  if (PIN_BOOT_BTN < 0 || digitalRead(PIN_BOOT_BTN) != LOW) return false;
  const uint32_t start = millis();
  while (digitalRead(PIN_BOOT_BTN) == LOW) {
    if (millis() - start >= ms) return true;
    delay(10);
  }
  return false;
}

void drawStatus(const char *title, const char *line2, const char *line3 = nullptr) {
  hudVisible = false;
  panelPluginDrawStatus(title, line2, line3);
}

void drawRuntimeHud(bool forceSensors = false) {
  if (claudeBuddyOwnsScreen()) return;
  if (forceSensors || millis() - lastSensorMs > 30000) {
    SensorReading r;
    if (sensorsRead(r)) lastSensors = r;
    lastSensorMs = millis();
  }
  char line3[48];
  snprintf(line3, sizeof(line3), "script %s", scriptEngineState());
  claudeBuddySummary(hudClaudeLine, sizeof(hudClaudeLine));
  panelPluginDrawStatus(statusLine1.c_str(), statusLine2.c_str(), line3,
                        hudClaudeLine[0] ? hudClaudeLine : nullptr);
  hudVisible = true;
}

// Keep the HUD's Claude line current while nothing else owns the panel.
void refreshHudClaudeLine() {
  if (!hudVisible || scriptEngineIsRunning() || claudeBuddyOwnsScreen()) return;
  char now[sizeof(hudClaudeLine)];
  claudeBuddySummary(now, sizeof(now));
  if (strcmp(now, hudClaudeLine) != 0) drawRuntimeHud(false);
}

// Badge refresh: always on fast panels; on e-ink only when no script owns it.
void pollBattery() {
  if (millis() - lastBatteryMs < BATTERY_INTERVAL_MS) return;
  lastBatteryMs = millis();
  OcBattery b;
  sensorsBattery(b);
  battery = b;
  if (!panelPluginSetBattery(b) || claudeBuddyOwnsScreen()) return;
  if (!panelPluginSlow() || !scriptEngineIsRunning()) panelPluginRefresh();
}

// Script load/stop hands the panel back to framework defaults.
void resetFrameworkUi() {
  panelPluginSetBadge(true);
  claudeBuddySetTakeover(true);
}

void drawPortalHint() {
  drawStatus("WiFi Setup", "1) Join OC-Setup-*", "2) http://192.168.4.1/");
  Serial.println("[wifi] setup: join OC-Setup-* then open http://192.168.4.1/");
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

SemaphoreHandle_t httpLuaMutex = nullptr;

bool httpChannelLock(SemaphoreHandle_t *slot, uint32_t waitMs) {
  if (!slot) return false;
  if (!*slot) *slot = xSemaphoreCreateMutex();
  return *slot && xSemaphoreTake(*slot, pdMS_TO_TICKS(waitMs)) == pdTRUE;
}
void httpChannelUnlock(SemaphoreHandle_t slot) {
  if (slot) xSemaphoreGive(slot);
}

bool httpJson(const char *method, const String &url, const String &body, String &out,
              uint32_t timeoutMs) {
  return cloudHttpJson(method, url, body, out, timeoutMs);
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
  // Lua channel is independent of cloud pending/status (own TLS + mutex).
  if (!httpChannelLock(&httpLuaMutex, 5000)) {
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
    tlsLua.setInsecure();
    tlsLua.setTimeout(timeoutMs);
    began = http.begin(tlsLua, url);
  } else if (isHttp) {
    began = http.begin(url);
  } else {
    httpChannelUnlock(httpLuaMutex);
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
      httpChannelUnlock(httpLuaMutex);
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
  httpChannelUnlock(httpLuaMutex);
  return transportOk;
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
bool hostKeyDown() { return PIN_KEY_BTN >= 0 && digitalRead(PIN_KEY_BTN) == LOW; }
bool hostBootDown() { return PIN_BOOT_BTN >= 0 && digitalRead(PIN_BOOT_BTN) == LOW; }
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
  DynamicJsonDocument doc(1024);
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
    meta["charging"] = lastSensors.charging;
  }
  meta["script_id"] = scriptEngineScriptId();
  meta["script_state"] = scriptEngineState();
  meta["script_lang"] = scriptEngineLanguage();
  if (scriptEngineLastError()[0]) meta["script_error"] = scriptEngineLastError();
  meta["api_host"] = apiConfigGet().host;
  meta["panel"] = panelPluginName();
  meta["audio"] = audioPluginName();
#if defined(BOARD_ROARM)
  meta["product"] = "roarm-m2";
#elif defined(BOARD_PANEL_EPAPER)
  meta["product"] = "epaper-397";
#elif defined(BOARD_PANEL_RLCD)
  meta["product"] = "rlcd-42";
#else
  meta["product"] = "s3-bare";
#endif
  if (ocCapArm() && armDriver()) meta["arm"] = armDriver()->name();
  JsonArray caps = meta.createNestedArray("capabilities");
  capabilityFillJson(caps);
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
    resetFrameworkUi();
    statusLine1 = "OnlyClaws";
    statusLine2 = "script stopped";
    if (!panelPluginSlow()) drawRuntimeHud(true);
    postStatus();
    ok = true;
  } else if (!strcmp(type, "script")) {
    String scriptId = msg["title"] | "";
    String body = msg["body"] | "";
    resetFrameworkUi();
    ok = loadLuaFromEnvelope(scriptId, body);
    if (ok) {
      statusLine1 = "script";
      statusLine2 = scriptId.length() ? scriptId : "running";
      // Skip HUD overlay on slow panels — script will paint next tick.
      if (!panelPluginSlow()) drawRuntimeHud(false);
      if (audioPluginReady()) audioPluginBeep(660, 80);
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
      ok = panelPluginShowAsset(asset);
      if (ok) hudVisible = false;
    } else if (title.length()) {
      statusLine1 = title;
      statusLine2 = msg["body"] | "";
      drawRuntimeHud(false);
      ok = true;
    } else {
      ok = doBeep;
    }
    if (doBeep) audioPluginBeep(880, 100);
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
  if (PIN_KEY_BTN >= 0) {
    pinMode(PIN_KEY_BTN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(PIN_KEY_BTN), onKeyIsr, CHANGE);
  }
  if (PIN_BOOT_BTN >= 0 && PIN_BOOT_BTN != PIN_KEY_BTN) pinMode(PIN_BOOT_BTN, INPUT_PULLUP);

  panelPluginBegin(FW_VERSION);
  sensorsBegin();
  sensorsBattery(battery);
  panelPluginSetBattery(battery);
  lastBatteryMs = millis();

  ScriptHost host{};
  panelPluginAttach(host);
  audioPluginAttach(host);
  host.readSensors = hostReadSensors;
  host.keyDown = hostKeyDown;
  host.bootDown = hostBootDown;
  host.wifiRssi = hostWifiRssi;
  host.wifiIp = hostWifiIp;
  host.wifiSsid = hostWifiSsid;
  host.httpRequest = hostHttpRequest;
  host.emitEvent = emitDeviceEvent;
  host.onSensors = hostOnSensors;
  scriptEngineBegin(host);

  if (ocCapArm()) {
    if (armPluginBegin()) {
      Serial.printf("[arm] %s ready\n", armDriver() ? armDriver()->name() : "?");
    } else {
      Serial.println("[arm] begin failed");
    }
  }

  if (audioPluginBegin(16000)) audioPluginBeep(880, 80);

  Serial.printf("fw=%s panel=%s audio=%s device=%s cloud=%s%s heap=%u\n", FW_VERSION,
                panelPluginName(), audioPluginName(), apiConfigGet().deviceId.c_str(),
                apiConfigGet().host.c_str(), apiConfigGet().pathPrefix.c_str(),
                ESP.getFreeHeap());

  while (!ensureWifiConnected()) delay(1000);

  // ESP32 requires WiFi modem sleep when BLE is also on (else abort).
  WiFi.setSleep(true);
#if OC_HAS_BLE
  bleCtrlBegin();
  ClaudeBuddyHooks buddy;
  buddy.display = host.display;
  buddy.send = bleCtrlUartSend;
  buddy.secure = bleCtrlUartSecure;
  buddy.forgetBonds = bleCtrlForgetBonds;
  buddy.beep = audioPluginBeep;
  buddy.deviceName = bleCtrlName();
  claudeBuddyBegin(buddy);
  bleCtrlSetUartRx(claudeBuddyFeed);
  bleCtrlSetPairing(claudeBuddyPasskey);
#else
  Serial.println("[ble] off");
#endif
  // HTTP D-pad only drives snake/panel games; skip it on headless arm builds.
  if (!ocCapArm()) httpPadBegin(80);

  statusLine1 = "OnlyClaws";
  statusLine2 = WiFi.localIP().toString();
  drawRuntimeHud(true);
  postStatus();

  Serial.printf("ready. pad http://%s/ panel=%s audio=%s\n",
                WiFi.localIP().toString().c_str(), panelPluginName(), audioPluginName());
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
    while (PIN_KEY_BTN >= 0 && digitalRead(PIN_KEY_BTN) == LOW) delay(20);
  }

  pollBattery();
  claudeBuddyPoll(battery);
  refreshHudClaudeLine();

  if (keyShortPending) {
    keyShortPending = false;
    if (!claudeBuddyButton(true) && audioPluginReady()) audioPluginBeep(1000, 120);
  }
  const bool bootDown = hostBootDown();
  if (bootDown && !bootWasDown && claudeBuddyOwnsScreen()) claudeBuddyButton(false);
  bootWasDown = bootDown;

  if (netJsonReady) {
    netJsonReady = false;
    handlePayload(String(netJsonBuf));
  }

  armUsbSerialPoll();
  // A Claude card owns the panel; the script resumes when it closes.
  if (!claudeBuddyOwnsScreen()) scriptEngineTick();

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
