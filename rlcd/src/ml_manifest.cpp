#include "ml_manifest.h"

#include <ArduinoJson.h>
#include <string.h>

bool mlNameOk(const char *name) {
  if (!name || !name[0]) return false;
  const size_t n = strlen(name);
  if (n > 32) return false;
  for (size_t i = 0; i < n; ++i) {
    const char c = name[i];
    const bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
    if (!ok) return false;
  }
  return true;
}

namespace {

bool hex64(const char *s) {
  if (!s || strlen(s) != 64) return false;
  for (int i = 0; i < 64; ++i) {
    const char c = s[i];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return true;
}

bool fail(std::string &err, const char *why) {
  err = why;
  return false;
}

}  // namespace

bool mlParseManifest(const char *json, size_t n, MlManifest &out, std::string &err) {
  out = MlManifest{};
  DynamicJsonDocument doc(4096);
  if (!json || deserializeJson(doc, json, n)) return fail(err, "manifest not json");
  JsonObject o = doc.as<JsonObject>();
  if (o.isNull()) return fail(err, "manifest not an object");

  const char *name = o["name"] | "";
  if (!mlNameOk(name)) return fail(err, "bad name");
  out.name = name;
  out.version = o["version"] | 0;
  out.opset = o["opset"] | 0;
  if (out.opset < 1) return fail(err, "bad opset");
  if (out.opset > kMlOpsetVersion) return fail(err, "opset newer than firmware");
  out.kind = o["kind"] | "";
  if (out.kind != "audio" && out.kind != "tensor" && out.kind != "frontend") {
    return fail(err, "bad kind");
  }
  const char *sha = o["sha256"] | "";
  if (!hex64(sha)) return fail(err, "bad sha256");
  out.sha256 = sha;
  const long bytes = o["bytes"] | 0L;
  if (bytes <= 0 || (size_t)bytes > kMlMaxModelBytes) return fail(err, "bad bytes");
  out.bytes = (size_t)bytes;
  out.arenaKb = o["arena_kb"] | 0;
  if (out.arenaKb < 1 || out.arenaKb > kMlMaxArenaKb) return fail(err, "bad arena_kb");

  for (const char *l : o["labels"].as<JsonArray>()) {
    if (out.labels.size() >= 64) break;
    out.labels.push_back(l ? std::string(l, strnlen(l, 32)) : std::string());
  }

  if (out.kind == "audio") {
    JsonObject a = o["audio"].as<JsonObject>();
    if (a.isNull()) return fail(err, "audio spec missing");
    MlAudioSpec &s = out.audio;
    s.rate = a["rate"] | 0;
    s.windowMs = a["window_ms"] | 0;
    s.strideMs = a["stride_ms"] | 0;
    s.frames = a["frames"] | 0;
    s.features = a["features"] | 0;
    s.frontend = a["frontend"] | "";
    if (s.rate != kMlMicRate) return fail(err, "audio rate must be 16000");
    if (s.windowMs < 1 || s.windowMs > 1000) return fail(err, "bad window_ms");
    if (s.strideMs < 1 || s.strideMs > 1000) return fail(err, "bad stride_ms");
    if (s.frames < 1 || s.frames > 500) return fail(err, "bad frames");
    if (s.features < 1 || s.features > 512) return fail(err, "bad features");
    if (s.totalSamples() > 10 * kMlMicRate) return fail(err, "clip longer than 10 s");
    if (!mlNameOk(s.frontend.c_str()) || s.frontend == out.name) {
      return fail(err, "bad frontend");
    }
  }
  return true;
}

int mlArgMax(const std::vector<float> &scores) {
  int best = -1;
  for (size_t i = 0; i < scores.size(); ++i) {
    if (best < 0 || scores[i] > scores[(size_t)best]) best = (int)i;
  }
  return best;
}
