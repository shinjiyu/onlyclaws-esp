#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#include <string>
#include <vector>

#include "ml_manifest.h"

// On-device inference plugin (OC_PLUGIN_ML). TFLite Micro with the fixed
// operator set kMlOpsetVersion; models are data fetched from the control plane
// (signed manifest + .tflite), cached on the LittleFS "spiffs" partition and
// run from PSRAM. Main-loop only. Stubs return "ml not built" without the plugin.

struct MlHooks {
  // 16 kHz mono mic; returns samples read (0 = none ready yet).
  size_t (*micRead)(int16_t *out, size_t maxSamples) = nullptr;
};

void mlBegin(const MlHooks &hooks);

// Fetch (or reuse cache) and build an interpreter. Audio models also load
// their frontend.
bool mlLoad(const char *name, std::string &err);
void mlUnload(const char *name);

struct MlResult {
  std::vector<float> scores;
  int top = -1;
  uint32_t ms = 0;  // inference time, recording excluded
};

// Audio models: record one clip, run frontend per frame, classify.
bool mlListen(const char *name, MlResult &out, std::string &err);
// Any model: float input (quantized as the tensor needs), float output.
bool mlRun(const char *name, const float *in, size_t n, MlResult &out, std::string &err);

struct MlInfo {
  const MlManifest *manifest = nullptr;
  size_t arenaUsed = 0;
  size_t inputElems = 0;
  size_t outputElems = 0;
};
bool mlInfo(const char *name, MlInfo &out);

// meta.ml for /status: {opset, models:[...]}
void mlFillStatus(JsonObject meta);
