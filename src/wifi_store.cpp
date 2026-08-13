#include "wifi_store.h"

#include <Preferences.h>

namespace {
Preferences prefs;
constexpr const char *NS = "wifi";
}  // namespace

bool wifiStoreLoad(WifiCreds &out) {
  if (!prefs.begin(NS, true)) return false;
  out.ssid = prefs.getString("ssid", "");
  out.pass = prefs.getString("pass", "");
  prefs.end();
  return out.ssid.length() > 0;
}

bool wifiStoreSave(const String &ssid, const String &pass) {
  if (!ssid.length()) return false;
  if (!prefs.begin(NS, false)) return false;
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.end();
  return true;
}

void wifiStoreClear() {
  if (!prefs.begin(NS, false)) return;
  prefs.clear();
  prefs.end();
}

bool wifiStoreHasCreds() {
  WifiCreds c;
  return wifiStoreLoad(c);
}
