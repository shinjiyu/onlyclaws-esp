#include "api_config.h"

#include <Preferences.h>
#include <esp_mac.h>
#include <stdio.h>

#include "cloud_config.h"
#include "device_secrets.h"

namespace {
Preferences prefs;
ApiConfig gCfg;
constexpr const char *NS = "cloud";

String chipMacId() {
  uint8_t mac[6] = {};
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char buf[13];
  snprintf(buf, sizeof(buf), "%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2],
           mac[3], mac[4], mac[5]);
  return String(buf);
}

void applyDefaults() {
  gCfg.host = CLOUD_API_HOST;
  gCfg.pathPrefix = CLOUD_API_PATH_PREFIX;
  gCfg.deviceId = EPD_DEVICE_ID;
  gCfg.deviceToken = EPD_DEVICE_TOKEN;
#ifdef EPD_API_HOST
  if (String(EPD_API_HOST).length()) gCfg.host = EPD_API_HOST;
#endif
}

void loadOverrides() {
  applyDefaults();
  if (!prefs.begin(NS, true)) return;
  String host = prefs.getString("host", "");
  String prefix = prefs.getString("prefix", "");
  String did = prefs.getString("device_id", "");
  String tok = prefs.getString("token", "");
  prefs.end();
  if (host.length()) gCfg.host = host;
  if (prefix.length()) gCfg.pathPrefix = prefix;
  if (did.length()) gCfg.deviceId = did;
  if (tok.length()) gCfg.deviceToken = tok;
  if (gCfg.pathPrefix.length() && gCfg.pathPrefix[0] != '/') {
    gCfg.pathPrefix = String("/") + gCfg.pathPrefix;
  }
  while (gCfg.pathPrefix.length() > 1 && gCfg.pathPrefix.endsWith("/")) {
    gCfg.pathPrefix.remove(gCfg.pathPrefix.length() - 1);
  }
}
}  // namespace

void apiConfigBegin() {
  loadOverrides();
  // device_secrets.h is per-workstation, not per-board. Only apply flash
  // creds when they belong to this chip's MAC, and drop NVS creds copied
  // from another board.
  const String mac = chipMacId();
  const String flashId = String(EPD_DEVICE_ID);
  const String flashTok = String(EPD_DEVICE_TOKEN);
  const bool placeholder = !flashTok.length() || flashTok == "your_device_token";
  const bool flashForChip = !placeholder && flashId.equalsIgnoreCase(mac);

  if (!gCfg.deviceId.equalsIgnoreCase(mac)) {
    Serial.printf("[cloud] ignore creds id=%s (this mac=%s)\n", gCfg.deviceId.c_str(),
                  mac.c_str());
    gCfg.deviceId = mac;
    gCfg.deviceToken = "";
  }

  if (flashForChip &&
      (!gCfg.deviceId.equalsIgnoreCase(flashId) || gCfg.deviceToken != flashTok)) {
    gCfg.deviceId = flashId;
    gCfg.deviceToken = flashTok;
    apiConfigSave(gCfg);
    Serial.printf("[cloud] refreshed NVS creds for device=%s\n", flashId.c_str());
  }
}

const ApiConfig &apiConfigGet() { return gCfg; }

const char *apiDeviceToken() { return gCfg.deviceToken.c_str(); }

bool apiConfigSave(const ApiConfig &cfg) {
  if (!cfg.host.length() || !cfg.deviceId.length()) return false;
  if (!prefs.begin(NS, false)) return false;
  prefs.putString("host", cfg.host);
  prefs.putString("prefix", cfg.pathPrefix.length() ? cfg.pathPrefix : "/epaper");
  prefs.putString("device_id", cfg.deviceId);
  if (cfg.deviceToken.length()) prefs.putString("token", cfg.deviceToken);
  prefs.end();
  loadOverrides();
  return true;
}

bool apiConfigSaveToken(const String &token) {
  if (!token.length()) return false;
  if (!prefs.begin(NS, false)) return false;
  prefs.putString("token", token);
  prefs.end();
  loadOverrides();
  return true;
}

void apiConfigClearOverrides() {
  if (prefs.begin(NS, false)) {
    prefs.clear();
    prefs.end();
  }
  loadOverrides();
}

String apiDeviceUrl(const char *suffix) {
  const ApiConfig &c = gCfg;
  String url = CLOUD_API_SCHEME;
  url += "://";
  url += c.host;
  url += c.pathPrefix;
  url += "/api/v1/device/";
  url += c.deviceId;
  if (suffix && suffix[0]) url += suffix;
  return url;
}

String apiAbsoluteUrl(const char *pathOrUrl) {
  if (!pathOrUrl || !pathOrUrl[0]) return "";
  if (strncmp(pathOrUrl, "http://", 7) == 0 ||
      strncmp(pathOrUrl, "https://", 8) == 0) {
    return String(pathOrUrl);
  }
  const ApiConfig &c = gCfg;
  String url = CLOUD_API_SCHEME;
  url += "://";
  url += c.host;
  if (pathOrUrl[0] != '/') url += '/';
  url += pathOrUrl;
  return url;
}
