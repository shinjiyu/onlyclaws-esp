#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <GxEPD2_BW.h>
#include <Fonts/FreeMonoBold12pt7b.h>
#include <Fonts/FreeMonoBold18pt7b.h>
#include <ArduinoJson.h>
#include <esp_netif.h>
#include <esp_heap_caps.h>

#include "audio_es8311.h"
#include "board_pins.h"
#include "device_secrets.h"
#include "wifi_ap_prov.h"
#include "wifi_secrets.h"
#include "wifi_store.h"

constexpr uint16_t PANEL_W = 800;
constexpr uint16_t PANEL_H = 480;
constexpr size_t FRAME_BYTES = PANEL_W * PANEL_H / 8;
constexpr uint32_t STATUS_INTERVAL_MS = 10UL * 60UL * 1000UL;
constexpr uint8_t FULL_REFRESH_EVERY = 12;
constexpr const char *FW_VERSION = "epaper-agent-0.3.2";

using EpdDriver = GxEPD2_397_GDEM0397T81;
GxEPD2_BW<EpdDriver, EpdDriver::HEIGHT> display(
    EpdDriver(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY));

WiFiClientSecure tls;
uint32_t lastStatusMs = 0;
String lastShownId;
bool displayReady = false;
uint8_t *frameBuf = nullptr;
uint8_t partialCount = 0;

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

WifiCreds resolveWifiCreds() {
  WifiCreds c;
  if (wifiStoreLoad(c)) {
    Serial.printf("WiFi from NVS ssid=%s\n", c.ssid.c_str());
    return c;
  }
  c.ssid = WIFI_SSID;
  c.pass = WIFI_PASS;
  Serial.printf("WiFi from secrets ssid=%s\n", c.ssid.c_str());
  return c;
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
  Serial.printf("WiFi OK ip=%s rssi=%d heap=%u psram=%u\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI(),
                ESP.getFreeHeap(), ESP.getFreePsram());
  return true;
}

bool ensureFrameBuf() {
  if (frameBuf) return true;
  frameBuf = (uint8_t *)heap_caps_malloc(
      FRAME_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!frameBuf) frameBuf = (uint8_t *)malloc(FRAME_BYTES);
  if (!frameBuf) {
    Serial.println("frame buffer alloc failed");
    return false;
  }
  return true;
}

void initDisplay() {
  if (displayReady) return;
  SPI.begin(PIN_EPD_SCLK, -1, PIN_EPD_MOSI, PIN_EPD_CS);
  display.init(115200);
  display.epd2.selectFastFullUpdate(true);
  display.setRotation(0);
  displayReady = true;
}

String apiUrl(const char *suffix) {
  String url = "https://";
  url += EPD_API_HOST;
  url += EPD_API_BASE;
  url += suffix;
  return url;
}

String absoluteUrl(const char *pathOrUrl) {
  if (!pathOrUrl || !pathOrUrl[0]) return "";
  if (strncmp(pathOrUrl, "http://", 7) == 0 ||
      strncmp(pathOrUrl, "https://", 8) == 0) {
    return String(pathOrUrl);
  }
  String url = "https://";
  url += EPD_API_HOST;
  if (pathOrUrl[0] != '/') url += '/';
  url += pathOrUrl;
  return url;
}

bool httpJson(const char *method, const String &url, const String &body,
              String &out, uint32_t timeoutMs) {
  if (WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  http.setTimeout(timeoutMs);
  http.setReuse(false);
  tls.setInsecure();
  tls.setTimeout(20000);
  Serial.printf("%s heap=%u %s\n", method, ESP.getFreeHeap(), url.c_str());
  if (!http.begin(tls, url)) return false;
  http.addHeader("Authorization", String("Bearer ") + EPD_DEVICE_TOKEN);
  http.addHeader("Content-Type", "application/json");
  int code = (strcmp(method, "GET") == 0) ? http.GET() : http.POST(body);
  out = http.getString();
  http.end();
  if (code < 200 || code >= 300) {
    Serial.printf("HTTP %d\n", code);
    return false;
  }
  return true;
}

bool downloadAsset(const String &url) {
  if (!ensureFrameBuf() || WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  http.setTimeout(45000);
  http.setReuse(false);
  tls.setInsecure();
  tls.setTimeout(30000);
  Serial.printf("GET asset heap=%u %s\n", ESP.getFreeHeap(), url.c_str());
  if (!http.begin(tls, url)) return false;
  http.addHeader("Authorization", String("Bearer ") + EPD_DEVICE_TOKEN);
  if (http.GET() != 200) {
    http.end();
    return false;
  }
  WiFiClient *stream = http.getStreamPtr();
  size_t got = 0;
  while (http.connected() && got < FRAME_BYTES) {
    size_t avail = stream->available();
    if (!avail) {
      delay(1);
      continue;
    }
    got += stream->readBytes(frameBuf + got, min(avail, FRAME_BYTES - got));
  }
  http.end();
  return got == FRAME_BYTES;
}

void showBitmap(bool fullRefresh) {
  initDisplay();
  const bool usePartial = !fullRefresh;
  Serial.printf("refresh mode=%s\n", usePartial ? "partial" : "full");
  display.setFullWindow();
  display.writeImage(frameBuf, 0, 0, PANEL_W, PANEL_H);
  display.refresh(usePartial);
  display.epd2.writeImageAgain(frameBuf, 0, 0, PANEL_W, PANEL_H);
  display.hibernate();
  partialCount = usePartial ? (uint8_t)(partialCount + 1) : 0;
}

void showBootAscii(const char *title, const char *body) {
  initDisplay();
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.fillRect(0, 0, display.width(), 56, GxEPD_BLACK);
    display.setTextColor(GxEPD_WHITE);
    display.setFont(&FreeMonoBold18pt7b);
    display.setCursor(20, 38);
    display.print(title);
    display.setTextColor(GxEPD_BLACK);
    display.setFont(&FreeMonoBold12pt7b);
    display.setCursor(20, 100);
    display.print(body);
  } while (display.nextPage());
  display.hibernate();
  partialCount = 0;
}

void postStatus() {
  String body = String("{\"ip\":\"") + WiFi.localIP().toString() +
                "\",\"rssi\":" + String(WiFi.RSSI()) + ",\"fw\":\"" + FW_VERSION +
                "\"}";
  String out;
  if (httpJson("POST", apiUrl("/status"), body, out, 20000)) {
    Serial.println("status ok");
  }
}

void ackMessage(const String &messageId, bool ok, uint32_t ms) {
  String body = String("{\"message_id\":\"") + messageId +
                "\",\"ok\":" + (ok ? "true" : "false") + ",\"ms\":" + String(ms) +
                "}";
  String out;
  httpJson("POST", apiUrl("/ack"), body, out, 20000);
}

bool handlePayload(const String &json) {
  DynamicJsonDocument doc(4096);
  if (deserializeJson(doc, json)) return false;
  if (!doc["success"].as<bool>() || doc["message"].isNull()) return false;
  JsonObject msg = doc["message"].as<JsonObject>();
  String id = msg["id"] | "";
  if (!id.length() || lastShownId == id) return true;

  bool fullRefresh = msg["full_refresh"] | false;
  if (partialCount >= FULL_REFRESH_EVERY) fullRefresh = true;

  Serial.printf("new message id=%s\n", id.c_str());
  const uint32_t t0 = millis();
  bool ok = false;
  String asset = absoluteUrl(msg["asset_path"] | "");
  if (asset.length()) {
    ok = downloadAsset(asset);
    if (ok) showBitmap(fullRefresh);
  }
  ackMessage(id, ok, millis() - t0);
  if (ok) lastShownId = id;
  return ok;
}

void pollOnce() {
  String out;
  if (!httpJson("GET", apiUrl("/poll?timeout=25"), "", out, 35000)) {
    delay(2000);
    return;
  }
  handlePayload(out);
}

bool bootButtonHeld(uint32_t windowMs = 1500) {
  pinMode(PIN_BOOT_BTN, INPUT_PULLUP);
  const uint32_t start = millis();
  bool held = false;
  while (millis() - start < windowMs) {
    if (digitalRead(PIN_BOOT_BTN) == LOW) held = true;
    delay(10);
  }
  return held;
}

bool ensureWifiConnected() {
  const bool forcePortal = bootButtonHeld();
  auto showPortalHint = []() {
    showBootAscii("WiFi Setup",
                  "1) Join WiFi EPD-Setup-*\n2) Pass 12345678\n3) Open captive page");
  };

  if (forcePortal) {
    Serial.println("BOOT held -> SoftAP web provision");
    showPortalHint();
    if (!wifiApProvision(0)) return false;
  }

  for (int attempt = 0; attempt < 3; ++attempt) {
    WifiCreds creds = resolveWifiCreds();
    if (connectWifiWith(creds)) return true;
    Serial.println("WiFi failed -> SoftAP web provision");
    showPortalHint();
    if (!wifiApProvision(0)) return false;
  }
  return WiFi.status() == WL_CONNECTED;
}

void setup() {
  Serial.begin(115200);
  delay(400);
  Serial.println();
  Serial.println("=== ePaper remote agent 0.3.2 ===");
  Serial.printf("boot heap=%u psram=%u\n", ESP.getFreeHeap(),
                ESP.getFreePsram());
  ensureFrameBuf();

  // Audio smoke test: synth melody (needs speaker on MX1.25 to hear).
  if (audioBegin(16000)) {
    audioPlayDemo();
  } else {
    Serial.println("audio template init skipped/failed");
  }

  while (!ensureWifiConnected()) {
    delay(1000);
  }

  if (audioIsReady()) {
    Serial.println("[audio] online chime");
    audioPlayBeep(1320, 140);
  }

  postStatus();
  lastStatusMs = millis();
  showBootAscii("ePaper", "Online. Waiting...");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    WifiCreds creds = resolveWifiCreds();
    if (!connectWifiWith(creds, 15000)) {
      showBootAscii("WiFi Setup", "Join EPD-Setup-* hotspot");
      wifiApProvision(0);
    }
    delay(500);
    return;
  }

  if (millis() - lastStatusMs > STATUS_INTERVAL_MS) {
    postStatus();
    lastStatusMs = millis();
  }

  pollOnce();
}
