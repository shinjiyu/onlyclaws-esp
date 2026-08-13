#pragma once

#include <Arduino.h>

struct WifiCreds {
  String ssid;
  String pass;
};

bool wifiStoreLoad(WifiCreds &out);
bool wifiStoreSave(const String &ssid, const String &pass);
void wifiStoreClear();
bool wifiStoreHasCreds();
