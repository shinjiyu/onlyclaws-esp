#include "panel_plugin.h"

#include <string.h>
#include <esp_heap_caps.h>
#include <esp_mac.h>

#include "api_config.h"
#include "board_pins.h"
#include "cloud_http.h"
#include "oc_features.h"

#include <WiFi.h>

#if OC_HAS_PANEL
#include <Adafruit_GFX.h>
#include <Fonts/FreeMonoBold12pt7b.h>
#include <Fonts/FreeMonoBold18pt7b.h>
#ifdef BOARD_PANEL_EPAPER
#include "epd397_panel.h"
#else
#include "st7305_rlcd.h"
#endif
#endif

namespace {
#if OC_HAS_PANEL
constexpr size_t FRAME_BYTES = (size_t)LCD_WIDTH * (size_t)LCD_HEIGHT / 8;

#ifdef BOARD_PANEL_EPAPER
Epd397Panel display;
#else
St7305Rlcd display;
#endif

uint8_t *frameBuf = nullptr;
const char *fwVersion = "";

struct CachedBmp {
  char name[65] = {0};
  int w = 0;
  int h = 0;
  uint8_t *data = nullptr;
  size_t n = 0;
  uint32_t used = 0;
};

CachedBmp gBmpCache[8];
uint32_t gBmpClock = 1;

bool ensureFrameBuf() {
  if (frameBuf) return true;
  if (!FRAME_BYTES) return false;
  frameBuf = (uint8_t *)heap_caps_malloc(FRAME_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!frameBuf) frameBuf = (uint8_t *)malloc(FRAME_BYTES);
  return frameBuf != nullptr;
}

String macSuffix() {
  uint8_t mac[6] = {};
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char buf[13];
  snprintf(buf, sizeof(buf), "%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3],
           mac[4], mac[5]);
  return String(buf);
}

bool bitmapNameOk(const char *name) {
  if (!name || !name[0]) return false;
  const size_t n = strlen(name);
  if (n > 64) return false;
  for (size_t i = 0; i < n; ++i) {
    const char c = name[i];
    const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                    (c >= '0' && c <= '9') || c == '_' || c == '-';
    if (!ok) return false;
  }
  return true;
}

CachedBmp *cacheFind(const char *name) {
  for (auto &c : gBmpCache) {
    if (c.data && strcmp(c.name, name) == 0) {
      c.used = ++gBmpClock;
      return &c;
    }
  }
  return nullptr;
}

CachedBmp *cacheVictim() {
  CachedBmp *oldest = &gBmpCache[0];
  for (auto &c : gBmpCache) {
    if (!c.data) return &c;
    if (c.used < oldest->used) oldest = &c;
  }
  return oldest;
}

bool hostFetchBitmap(const char *name, ScriptHost::BitmapView *out) {
  if (out) *out = {};
  if (!out || !bitmapNameOk(name) || WiFi.status() != WL_CONNECTED) return false;
  if (CachedBmp *hit = cacheFind(name)) {
    out->w = hit->w;
    out->h = hit->h;
    out->data = hit->data;
    out->n = hit->n;
    return true;
  }
  const String url = apiDeviceUrl((String("/bitmaps/") + name).c_str());
  int w = 0, h = 0;
  uint8_t *raw = nullptr;
  size_t got = 0;
  if (!cloudHttpGetBitmap(url, &w, &h, &raw, &got)) return false;

  CachedBmp *slot = cacheVictim();
  if (slot->data) free(slot->data);
  strncpy(slot->name, name, sizeof(slot->name) - 1);
  slot->name[sizeof(slot->name) - 1] = 0;
  slot->w = w;
  slot->h = h;
  slot->data = raw;
  slot->n = got;
  slot->used = ++gBmpClock;
  out->w = w;
  out->h = h;
  out->data = raw;
  out->n = got;
  Serial.printf("[bmp] %s %dx%d %u\n", name, w, h, (unsigned)got);
  return true;
}
#endif
}  // namespace

void panelPluginBegin(const char *fw) {
#if OC_HAS_PANEL
  fwVersion = fw ? fw : "";
  display.begin();
#ifndef BOARD_PANEL_EPAPER
  ensureFrameBuf();
#endif
  Serial.printf("[panel] %s %dx%d\n", display.panelName(), LCD_WIDTH, LCD_HEIGHT);
#else
  (void)fw;
  Serial.println("[panel] none");
#endif
}

const char *panelPluginName() {
#if OC_HAS_PANEL
  return display.panelName();
#else
  return "none";
#endif
}

bool panelPluginSlow() {
#if OC_HAS_PANEL
  return display.slowPanel();
#else
  return false;
#endif
}

void panelPluginAttach(ScriptHost &host) {
#if OC_HAS_PANEL
  host.display = &display;
  host.fetchBitmap = hostFetchBitmap;
#else
  host.display = nullptr;
  host.fetchBitmap = nullptr;
#endif
}

void panelPluginDrawStatus(const char *title, const char *line2, const char *line3) {
#if OC_HAS_PANEL
  display.fillScreen(0);
  display.drawRect(4, 4, LCD_WIDTH - 8, LCD_HEIGHT - 8, 1);
  display.setTextColor(1);
  display.setFont(&FreeMonoBold18pt7b);
  display.setCursor(24, 48);
  display.print(title ? title : "");
  display.setFont(&FreeMonoBold12pt7b);
  display.setCursor(24, 96);
  display.print(line2 ? line2 : "");
  if (line3) {
    display.setCursor(24, 132);
    display.print(line3);
  }
  display.setCursor(24, 180);
  display.print("MAC ");
  display.print(macSuffix());
  display.setCursor(24, 216);
  display.print(fwVersion);
  display.flush();
#else
  (void)title;
  (void)line2;
  (void)line3;
#endif
}

bool panelPluginShowAsset(const String &url) {
#if OC_HAS_PANEL
  if (!url.length() || !ensureFrameBuf()) return false;
  if (!cloudHttpGetExact(url, frameBuf, FRAME_BYTES, 45000)) return false;
  display.drawBitmap(0, 0, frameBuf, LCD_WIDTH, LCD_HEIGHT, 1, 0);
  display.flush();
  return true;
#else
  (void)url;
  return false;
#endif
}
