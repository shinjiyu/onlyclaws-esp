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
#include "board_pins.h"
#include "character_ui.h"
#include "cloud_config.h"
#include "device_secrets.h"
#include "script_engine.h"
#include "sensors.h"
#include "st7305_rlcd.h"
#include "wifi_ap_prov.h"
#include "wifi_store.h"

namespace {
constexpr const char *FW_VERSION = "rlcd-agent-0.8.0";
constexpr uint32_t STATUS_INTERVAL_MS = 60UL * 1000UL;
constexpr size_t FRAME_BYTES = LCD_WIDTH * LCD_HEIGHT / 8;

St7305Rlcd display;
WiFiClientSecure tls;
uint8_t *frameBuf = nullptr;
String lastShownId;
uint32_t lastStatusMs = 0;
uint32_t lastSensorMs = 0;
SensorReading lastSensors{};
bool sceneActive = false;

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
  sceneActive = false;
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
  display.display();
}

void drawPortalHint() {
  sceneActive = false;
  display.fillScreen(0);
  display.drawRect(4, 4, LCD_WIDTH - 8, LCD_HEIGHT - 8, 1);
  display.setTextColor(1);
  display.setFont(&FreeMonoBold18pt7b);
  display.setCursor(24, 48);
  display.print("WiFi Setup");
  display.setFont(&FreeMonoBold12pt7b);
  display.setCursor(24, 96);
  display.print("1) Join RLCD-Setup-*");
  display.setCursor(24, 132);
  display.print("2) Pass 12345678");
  display.setCursor(24, 168);
  display.print("3) Open captive page");
  display.setCursor(24, 204);
  display.print("or http://192.168.4.1/");
  display.display();
}

void refreshHud() {
  CharacterHud h;
  h.tempC = lastSensors.okTemp ? lastSensors.tempC : NAN;
  h.humidity = lastSensors.okTemp ? lastSensors.humidity : NAN;
  h.batteryV = lastSensors.okBattery ? lastSensors.batteryV : NAN;
  h.batteryPct = lastSensors.okBattery ? lastSensors.batteryPct : -1;
  h.rssi = WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
  static char ssidBuf[33];
  if (WiFi.status() == WL_CONNECTED) {
    strncpy(ssidBuf, WiFi.SSID().c_str(), sizeof(ssidBuf) - 1);
    ssidBuf[sizeof(ssidBuf) - 1] = 0;
    h.ssid = ssidBuf;
  } else {
    h.ssid = "offline";
  }
  characterSetHud(h);
}

void showCharacterScene(bool force = false) {
  sceneActive = true;
  refreshHud();
  const uint32_t now = millis();
  characterTick(now);
  if (force || characterNeedsRedraw(now)) {
    characterRender(display);
    display.display();
  }
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
    Serial.println("BOOT held -> SoftAP web provision");
    drawPortalHint();
    if (!wifiApProvision(0)) return false;
  }

  for (int attempt = 0; attempt < 3; ++attempt) {
    WifiCreds creds;
    if (!wifiStoreLoad(creds)) {
      Serial.println("No NVS WiFi -> SoftAP web provision");
      drawPortalHint();
      if (!wifiApProvision(0)) return false;
      continue;
    }
    Serial.printf("WiFi from NVS ssid=%s\n", creds.ssid.c_str());
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
    if (code < 200 || code >= 300) {
      Serial.printf("HTTP %d\n", code);
    } else {
      ok = true;
    }
  }
  httpUnlock();
  return ok;
}

bool downloadAsset(const String &url) {
  if (!ensureFrameBuf() || WiFi.status() != WL_CONNECTED) return false;
  if (!httpLock()) return false;
  HTTPClient http;
  http.setTimeout(45000);
  http.setReuse(false);
  tls.setInsecure();
  tls.setTimeout(30000);
  Serial.printf("GET asset heap=%u %s\n", ESP.getFreeHeap(), url.c_str());
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
      Serial.printf("asset got=%u need=%u\n", (unsigned)got, (unsigned)FRAME_BYTES);
      ok = got == FRAME_BYTES;
    }
    http.end();
  }
  httpUnlock();
  return ok;
}

void updateSensors(bool redrawHud = true) {
  SensorReading r;
  if (sensorsRead(r)) {
    lastSensors = r;
    Serial.printf("[sensors] temp=%.1fC rh=%.0f%% bat=%.2fV (%d%%)\n", r.tempC,
                  r.humidity, r.batteryV, r.batteryPct);
  }
  lastSensorMs = millis();
  if (redrawHud) refreshHud();
}

bool emitDeviceEvent(const char *name, const char *jsonData) {
  DynamicJsonDocument doc(768);
  doc["name"] = name ? name : "event";
  doc["script_id"] = scriptEngineScriptId();
  if (jsonData && jsonData[0]) {
    DynamicJsonDocument data(512);
    if (!deserializeJson(data, jsonData)) {
      doc["data"] = data.as<JsonVariant>();
    } else {
      doc["data"] = jsonData;
    }
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
void hostWave() { characterWave(); }
void hostReact() { characterReact(); }
void hostDialog(const char *title) {
  characterSetDialog(title && title[0] ? title : "script", nullptr, 0, 30000);
  showCharacterScene(true);
}
void hostOnSensors(const SensorReading &r) {
  lastSensors = r;
  refreshHud();
}

void postStatus() {
  updateSensors(false);
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
  if (scriptEngineLastError()[0]) meta["script_error"] = scriptEngineLastError();
  meta["api_host"] = apiConfigGet().host;
  String body;
  serializeJson(doc, body);
  String out;
  if (httpJson("POST", apiUrl("/status"), body, out, 15000)) {
    Serial.println("status ok");
  }
}

void ackMessage(const String &messageId, bool ok, uint32_t ms) {
  String body = String("{\"message_id\":\"") + messageId +
                "\",\"ok\":" + (ok ? "true" : "false") + ",\"ms\":" + String(ms) +
                "}";
  String out;
  httpJson("POST", apiUrl("/ack"), body, out, 15000);
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
    postStatus();
    ok = true;
    ackMessage(id, ok, millis() - t0);
    if (ok) lastShownId = id;
    return ok;
  }

  if (!strcmp(type, "script")) {
    String scriptId = msg["title"] | "";
    String body = msg["body"] | "";
    // body may be raw script JSON, or {"script_id","source"}
    if (body.startsWith("{")) {
      DynamicJsonDocument wrap(16384);
      if (!deserializeJson(wrap, body) && !wrap["source"].isNull()) {
        if (wrap["script_id"]) scriptId = wrap["script_id"].as<String>();
        body = "";
        serializeJson(wrap["source"], body);
      }
    }
    ok = scriptEngineLoad(scriptId.c_str(), body.c_str());
    if (ok) {
      characterSetDialog(scriptId.length() ? scriptId.c_str() : "script", nullptr, 0,
                         20000);
      showCharacterScene(true);
      if (audioIsReady()) audioPlayBeep(660, 80);
      postStatus();
    }
    ackMessage(id, ok, millis() - t0);
    if (ok) lastShownId = id;
    return ok;
  }

  if (!strcmp(type, "invoke")) {
    String body = msg["body"] | "";
    ok = scriptEngineInvokeJson(body.c_str());
    showCharacterScene(true);
    ackMessage(id, ok, millis() - t0);
    if (ok) lastShownId = id;
    return ok;
  }

  String title = msg["title"] | "";
  String body = msg["body"] | "";
  if (!title.length() && body.length()) title = body.substring(0, 24);

  JsonObject actions = msg["actions"].as<JsonObject>();
  const bool doBeep = actions.isNull() ? true : (actions["beep"] | true);
  const bool doWave = actions.isNull() ? false : (actions["wave"] | false);
  const bool doReact = actions.isNull() ? true : (actions["react"] | true);

  String asset = absoluteUrl(msg["asset_path"] | "");
  const bool hasAsset = asset.length() > 0;
  if (hasAsset) {
    ok = downloadAsset(asset);
  } else {
    ok = title.length() > 0 || doBeep || doWave || doReact;
  }

  if (ok) {
    if (hasAsset || title.length()) {
      characterSetDialog(title.c_str(),
                         hasAsset && frameBuf ? frameBuf : nullptr,
                         hasAsset ? FRAME_BYTES : 0, 60000);
    }
    if (doWave) characterWave();
    if (doReact) characterReact();
    showCharacterScene(true);
    if (doBeep && audioIsReady()) audioPlayBeep(880, 100);
    if (doWave) {
      for (int i = 0; i < 6; ++i) {
        characterTick(millis());
        characterRender(display);
        display.display();
        delay(100);
      }
      showCharacterScene(true);
    }
  }
  ackMessage(id, ok, millis() - t0);
  if (ok) lastShownId = id;
  return ok;
}

// KEY via interrupt — HTTPS must not eat short presses.
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

void doWaveAndBeep() {
  Serial.println("[ui] KEY short -> wave+beep");
  characterWave();
  if (audioIsReady()) {
    const bool ok = audioPlayBeep(1000, 140);
    Serial.printf("[ui] beep %s pa=%d\n", ok ? "ok" : "fail",
                  digitalRead(PIN_AUDIO_PA));
  } else {
    Serial.println("[ui] audio not ready");
  }
  for (int i = 0; i < 8; ++i) {
    characterTick(millis());
    characterRender(display);
    display.display();
    delay(100);
  }
  showCharacterScene(true);
}

void setupImpl() {
  Serial.begin(115200);
  delay(400);
  Serial.println();
  Serial.println("=== ESP32-S3-RLCD-4.2 agent platform ===");
  apiConfigBegin();
  Serial.printf("fw=%s device=%s cloud=%s%s heap=%u psram=%u\n", FW_VERSION,
                apiConfigGet().deviceId.c_str(), apiConfigGet().host.c_str(),
                apiConfigGet().pathPrefix.c_str(), ESP.getFreeHeap(),
                ESP.getFreePsram());

  pinMode(PIN_KEY_BTN, INPUT_PULLUP);
  pinMode(PIN_BOOT_BTN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_KEY_BTN), onKeyIsr, CHANGE);

  if (!display.begin()) {
    Serial.println("[lcd] begin failed");
  }
  ensureFrameBuf();
  sensorsBegin();
  characterBegin();

  ScriptHost host{};
  host.readSensors = hostReadSensors;
  host.beep = hostBeep;
  host.wave = hostWave;
  host.react = hostReact;
  host.dialog = hostDialog;
  host.emitEvent = emitDeviceEvent;
  host.onSensors = hostOnSensors;
  scriptEngineBegin(host);

  if (audioBegin(16000)) {
    Serial.println("[audio] boot chime");
    audioPlayBeep(880, 120);
  } else {
    Serial.println("[audio] init skipped/failed");
  }

  while (!ensureWifiConnected()) delay(1000);

  updateSensors();
  showCharacterScene(true);
  postStatus();
  lastStatusMs = millis();

  Serial.println("[diag] forced wave+beep self-test");
  doWaveAndBeep();

  Serial.println(
      "ready. KEY short=wave+beep; hold=WiFi; cloud=invoke/script/push.");
  xTaskCreatePinnedToCore(netTask, "net", 8192, nullptr, 1, nullptr, 0);
  Serial.printf("[diag] KEY raw=%d (1=released)\n", digitalRead(PIN_KEY_BTN));
}

void loopImpl() {
  // Long-press detected while held (ISR only marks short on release).
  if (keyHeld && keyLongArmed && (millis() - keyDownAtMs > 1500)) {
    keyLongArmed = false;
    keyLongPending = true;
  }

  if (keyLongPending) {
    keyLongPending = false;
    keyShortPending = false;
    Serial.println("KEY held -> SoftAP web provision");
    drawPortalHint();
    if (wifiApProvision(0)) {
      WifiCreds creds;
      if (wifiStoreLoad(creds) && connectWifiWith(creds)) {
        showCharacterScene(true);
        postStatus();
      }
    } else if (WiFi.status() == WL_CONNECTED) {
      showCharacterScene(true);
    }
    while (digitalRead(PIN_KEY_BTN) == LOW) delay(20);
  }

  if (keyShortPending) {
    keyShortPending = false;
    doWaveAndBeep();
  }

  if (netJsonReady) {
    netJsonReady = false;
    handlePayload(String(netJsonBuf));
  }

  scriptEngineTick();

  if (WiFi.status() != WL_CONNECTED) {
    WifiCreds creds;
    if (wifiStoreLoad(creds) && connectWifiWith(creds, 15000)) {
      showCharacterScene(true);
      postStatus();
    } else {
      drawPortalHint();
      wifiApProvision(0);
    }
    delay(500);
    return;
  }

  if (millis() - lastSensorMs > 30000) {
    updateSensors();
    if (sceneActive) showCharacterScene(true);
  }

  if (sceneActive) {
    showCharacterScene(false);
  }

  static uint32_t lastKeyLog = 0;
  if (millis() - lastKeyLog > 5000) {
    lastKeyLog = millis();
    Serial.printf("[diag] key=%d held=%d\n", digitalRead(PIN_KEY_BTN),
                  (int)keyHeld);
  }
  delay(15);
}
}  // namespace

void setup() { setupImpl(); }
void loop() { loopImpl(); }
