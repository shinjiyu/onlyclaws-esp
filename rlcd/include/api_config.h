#pragma once

#include <Arduino.h>

struct ApiConfig {
  String host;          // e.g. onlyclaws.world
  String pathPrefix;    // e.g. /epaper
  String deviceId;      // e.g. a4cb8fdf8440
};

void apiConfigBegin();
const ApiConfig &apiConfigGet();
bool apiConfigSave(const ApiConfig &cfg);
void apiConfigClearOverrides();

// https://host/epaper/api/v1/device/{id}{suffix}
String apiDeviceUrl(const char *suffix);
// https://host + absolute path (or pass-through if already http)
String apiAbsoluteUrl(const char *pathOrUrl);
