#include "cloud_http.h"

#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <string.h>

#include "api_config.h"

namespace {
WiFiClientSecure tlsCloud;
SemaphoreHandle_t httpCloudMutex = nullptr;

bool lockCloud(uint32_t waitMs) {
  if (!httpCloudMutex) httpCloudMutex = xSemaphoreCreateMutex();
  return httpCloudMutex &&
         xSemaphoreTake(httpCloudMutex, pdMS_TO_TICKS(waitMs)) == pdTRUE;
}

void unlockCloud() {
  if (httpCloudMutex) xSemaphoreGive(httpCloudMutex);
}
}  // namespace

bool cloudHttpJson(const char *method, const String &url, const String &body, String &out,
                   uint32_t timeoutMs) {
  if (WiFi.status() != WL_CONNECTED) return false;
  if (!lockCloud(20000)) return false;
  HTTPClient http;
  http.setTimeout(timeoutMs);
  http.setReuse(false);
  tlsCloud.setInsecure();
  tlsCloud.setTimeout(timeoutMs);
  Serial.printf("%s heap=%u %s\n", method, ESP.getFreeHeap(), url.c_str());
  bool ok = false;
  if (http.begin(tlsCloud, url)) {
    http.addHeader("Authorization", String("Bearer ") + apiDeviceToken());
    http.addHeader("Content-Type", "application/json");
    int code = (strcmp(method, "GET") == 0) ? http.GET() : http.POST(body);
    out = http.getString();
    http.end();
    if (code < 200 || code >= 300) Serial.printf("HTTP %d\n", code);
    else ok = true;
  }
  unlockCloud();
  return ok;
}

bool cloudHttpGetExact(const String &url, uint8_t *dst, size_t need, uint32_t timeoutMs) {
  if (!dst || !need || WiFi.status() != WL_CONNECTED) return false;
  if (!lockCloud(20000)) return false;
  HTTPClient http;
  http.setTimeout(timeoutMs);
  http.setReuse(false);
  tlsCloud.setInsecure();
  tlsCloud.setTimeout(timeoutMs > 30000 ? 30000 : timeoutMs);
  bool ok = false;
  if (http.begin(tlsCloud, url)) {
    http.addHeader("Authorization", String("Bearer ") + apiDeviceToken());
    if (http.GET() == 200) {
      WiFiClient *stream = http.getStreamPtr();
      size_t got = 0;
      const uint32_t t0 = millis();
      while (got < need && millis() - t0 < timeoutMs) {
        size_t avail = stream->available();
        if (!avail) {
          if (!http.connected()) break;
          delay(2);
          yield();
          continue;
        }
        got += stream->readBytes(dst + got, min(avail, need - got));
      }
      ok = got == need;
    }
    http.end();
  }
  unlockCloud();
  return ok;
}

bool cloudHttpGetBitmap(const String &url, int *w, int *h, uint8_t **data, size_t *n) {
  if (w) *w = 0;
  if (h) *h = 0;
  if (data) *data = nullptr;
  if (n) *n = 0;
  if (!w || !h || !data || !n || WiFi.status() != WL_CONNECTED) return false;
  if (!lockCloud(20000)) return false;

  bool ok = false;
  int width = 0, height = 0;
  uint8_t *raw = nullptr;
  size_t got = 0;
  HTTPClient http;
  http.setTimeout(20000);
  http.setReuse(false);
  tlsCloud.setInsecure();
  tlsCloud.setTimeout(20000);
  Serial.printf("GET bitmap %s\n", url.c_str());
  if (http.begin(tlsCloud, url)) {
    const char *hdrKeys[] = {"X-Width", "X-Height"};
    http.collectHeaders(hdrKeys, 2);
    http.addHeader("Authorization", String("Bearer ") + apiDeviceToken());
    const int code = http.GET();
    if (code == 200) {
      width = http.header("X-Width").toInt();
      height = http.header("X-Height").toInt();
      const bool dimsOk =
          width >= 8 && height >= 1 && width <= 800 && height <= 480 && (width % 8) == 0;
      const size_t need = dimsOk ? (size_t)width / 8 * (size_t)height : 0;
      if (need > 0 && need <= (800 * 480 / 8)) {
        raw = (uint8_t *)heap_caps_malloc(need, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!raw) raw = (uint8_t *)malloc(need);
        WiFiClient *stream = http.getStreamPtr();
        const uint32_t t0 = millis();
        while (raw && got < need && millis() - t0 < 20000) {
          const size_t avail = stream->available();
          if (!avail) {
            if (!http.connected()) break;
            delay(2);
            yield();
            continue;
          }
          got += stream->readBytes(raw + got, min(avail, need - got));
        }
        ok = raw && got == need;
      }
    } else {
      Serial.printf("bitmap HTTP %d\n", code);
    }
    http.end();
  }
  unlockCloud();
  if (!ok) {
    free(raw);
    return false;
  }
  *w = width;
  *h = height;
  *data = raw;
  *n = got;
  return true;
}
