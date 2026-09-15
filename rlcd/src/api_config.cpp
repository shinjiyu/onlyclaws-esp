#include "api_config.h"

#include <Preferences.h>

#include "cloud_config.h"
#include "device_secrets.h"

namespace {
Preferences prefs;
ApiConfig gCfg;
constexpr const char *NS = "cloud";

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
  // Non-empty flash secrets refresh NVS (token update without wiping Wi‑Fi NVS).
  const String flashId = String(EPD_DEVICE_ID);
  const String flashTok = String(EPD_DEVICE_TOKEN);
  if (flashTok.length() && flashId.length()) {
    if (gCfg.deviceId != flashId || gCfg.deviceToken != flashTok) {
      gCfg.deviceId = flashId;
      gCfg.deviceToken = flashTok;
      apiConfigSave(gCfg);
      Serial.printf("[cloud] refreshed NVS creds for device=%s\n", flashId.c_str());
    }
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
