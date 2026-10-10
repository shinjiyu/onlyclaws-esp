#include "ml_engine.h"

#include "oc_features.h"

#if OC_HAS_ML

#include <LittleFS.h>
#include <esp_heap_caps.h>
#include <mbedtls/base64.h>
#include <mbedtls/md.h>
#include <mbedtls/pk.h>
#include <math.h>
#include <string.h>
#include <sys/stat.h>

#include <new>

#include "api_config.h"
#include "cloud_config.h"
#include "cloud_http.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

namespace {

constexpr int kSlots = 6;
constexpr int kMaxOps = 48;
constexpr uint32_t kFetchMs = 60000;
using Resolver = tflite::MicroMutableOpResolver<kMaxOps>;

MlHooks gHooks;
Resolver *gResolver = nullptr;
bool gFsTried = false;
bool gFsOk = false;
uint32_t gClock = 0;

struct Slot {
  bool used = false;
  MlManifest m;
  uint8_t *blob = nullptr;
  uint8_t *arena = nullptr;
  void *interpMem = nullptr;
  tflite::MicroInterpreter *interp = nullptr;
  uint32_t lastUse = 0;
};
Slot gSlots[kSlots];

// Operator set v1. server/ml_opset.py mirrors this list and
// server/tests/test_ml_registry.py checks they match; append only, and bump
// kMlOpsetVersion when a release adds ops.
bool registerOpsetV1(Resolver &r) {
  bool ok = true;
  ok &= r.AddAdd() == kTfLiteOk;
  ok &= r.AddAveragePool2D() == kTfLiteOk;
  ok &= r.AddCast() == kTfLiteOk;
  ok &= r.AddConcatenation() == kTfLiteOk;
  ok &= r.AddConv2D() == kTfLiteOk;
  ok &= r.AddDepthwiseConv2D() == kTfLiteOk;
  ok &= r.AddDequantize() == kTfLiteOk;
  ok &= r.AddDiv() == kTfLiteOk;
  ok &= r.AddExpandDims() == kTfLiteOk;
  ok &= r.AddFullyConnected() == kTfLiteOk;
  ok &= r.AddHardSwish() == kTfLiteOk;
  ok &= r.AddLeakyRelu() == kTfLiteOk;
  ok &= r.AddLogistic() == kTfLiteOk;
  ok &= r.AddMaxPool2D() == kTfLiteOk;
  ok &= r.AddMaximum() == kTfLiteOk;
  ok &= r.AddMean() == kTfLiteOk;
  ok &= r.AddMinimum() == kTfLiteOk;
  ok &= r.AddMul() == kTfLiteOk;
  ok &= r.AddPack() == kTfLiteOk;
  ok &= r.AddPad() == kTfLiteOk;
  ok &= r.AddQuantize() == kTfLiteOk;
  ok &= r.AddRelu() == kTfLiteOk;
  ok &= r.AddRelu6() == kTfLiteOk;
  ok &= r.AddReshape() == kTfLiteOk;
  ok &= r.AddShape() == kTfLiteOk;
  ok &= r.AddSlice() == kTfLiteOk;
  ok &= r.AddSoftmax() == kTfLiteOk;
  ok &= r.AddSplit() == kTfLiteOk;
  ok &= r.AddSqueeze() == kTfLiteOk;
  ok &= r.AddStridedSlice() == kTfLiteOk;
  ok &= r.AddSub() == kTfLiteOk;
  ok &= r.AddTanh() == kTfLiteOk;
  ok &= r.AddTranspose() == kTfLiteOk;
  ok &= r.AddUnpack() == kTfLiteOk;
  ok &= r.AddWindow() == kTfLiteOk;
  ok &= r.AddFftAutoScale() == kTfLiteOk;
  ok &= r.AddRfft() == kTfLiteOk;
  ok &= r.AddEnergy() == kTfLiteOk;
  ok &= r.AddFilterBank() == kTfLiteOk;
  ok &= r.AddFilterBankSquareRoot() == kTfLiteOk;
  ok &= r.AddFilterBankSpectralSubtraction() == kTfLiteOk;
  ok &= r.AddPCAN() == kTfLiteOk;
  ok &= r.AddFilterBankLog() == kTfLiteOk;
  ok &= r.AddFramer() == kTfLiteOk;
  ok &= r.AddStacker() == kTfLiteOk;
  return ok;
}

bool fail(std::string &err, const char *why) {
  err = why;
  return false;
}

bool ensureResolver() {
  if (gResolver) return true;
  void *mem = heap_caps_malloc(sizeof(Resolver), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!mem) return false;
  gResolver = new (mem) Resolver();
  if (!registerOpsetV1(*gResolver)) Serial.println("[ml] op registration incomplete");
  return true;
}

constexpr const char *kFsBase = "/lfs";

// stat() instead of LittleFS.exists(): the Arduino VFS logs an error for every
// missing path it probes.
bool fsHas(const String &path) {
  struct stat st;
  return stat((String(kFsBase) + path).c_str(), &st) == 0;
}

bool fsReady() {
  if (!gFsTried) {
    gFsTried = true;
    gFsOk = LittleFS.begin(true, kFsBase, 4, "spiffs");
    if (gFsOk && !fsHas("/ml")) LittleFS.mkdir("/ml");
    Serial.printf("[ml] model store %s (%u KB free)\n", gFsOk ? "ready" : "unavailable",
                  gFsOk ? (unsigned)((LittleFS.totalBytes() - LittleFS.usedBytes()) / 1024) : 0);
  }
  return gFsOk;
}

String envPath(const char *name) { return String("/ml/") + name + ".json"; }
String blobPath(const char *name) { return String("/ml/") + name + ".tfl"; }

bool writeAtomic(const String &path, const uint8_t *data, size_t n) {
  const String tmp = path + ".tmp";
  File f = LittleFS.open(tmp, "w");
  if (!f) return false;
  const size_t wrote = f.write(data, n);
  f.close();
  if (wrote != n) {
    LittleFS.remove(tmp);
    return false;
  }
  if (fsHas(path)) LittleFS.remove(path);
  return LittleFS.rename(tmp, path);
}

std::string sha256Hex(const uint8_t *data, size_t n) {
  uint8_t h[32];
  mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), data, n, h);
  static const char *hex = "0123456789abcdef";
  std::string out(64, '0');
  for (int i = 0; i < 32; ++i) {
    out[i * 2] = hex[h[i] >> 4];
    out[i * 2 + 1] = hex[h[i] & 15];
  }
  return out;
}

bool verifyManifest(const std::string &manifest, const char *sigB64, std::string &err) {
  const char *pem = OC_ML_PUBKEY_PEM;
  if (!pem[0]) {
#ifdef OC_ML_ALLOW_UNSIGNED
    return true;
#else
    return fail(err, "no ml public key in firmware");
#endif
  }
  uint8_t der[160];
  size_t derLen = 0;
  if (!sigB64 || mbedtls_base64_decode(der, sizeof(der), &derLen, (const uint8_t *)sigB64,
                                       strlen(sigB64)) != 0) {
    return fail(err, "bad signature encoding");
  }
  uint8_t hash[32];
  mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), (const uint8_t *)manifest.data(),
             manifest.size(), hash);
  mbedtls_pk_context pk;
  mbedtls_pk_init(&pk);
  int rc = mbedtls_pk_parse_public_key(&pk, (const uint8_t *)pem, strlen(pem) + 1);
  if (rc == 0) rc = mbedtls_pk_verify(&pk, MBEDTLS_MD_SHA256, hash, sizeof(hash), der, derLen);
  mbedtls_pk_free(&pk);
  return rc == 0 || fail(err, "manifest signature mismatch");
}

// Envelope {"manifest": "<json>", "sig": "<base64 DER>"}: from the control
// plane when reachable, else the cached copy. Verified either way.
bool fetchEnvelope(const char *name, std::string &manifest, std::string &raw,
                   std::string &err) {
  String body;
  const bool online = cloudHttpJson("GET", apiDeviceUrl((String("/models/") + name).c_str()), "",
                                    body, 15000);
  if (online) {
    raw.assign(body.c_str(), body.length());
  } else if (fsReady() && fsHas(envPath(name))) {
    File f = LittleFS.open(envPath(name), "r");
    raw.assign(f.readString().c_str());
    f.close();
  } else {
    return fail(err, "model not found (offline and not cached)");
  }
  DynamicJsonDocument doc(raw.size() + 1024);
  if (deserializeJson(doc, raw)) return fail(err, "bad model envelope");
  const char *m = doc["manifest"] | "";
  manifest = m;
  return verifyManifest(manifest, doc["sig"] | (const char *)nullptr, err);
}

uint8_t *readCachedBlob(const MlManifest &m) {
  if (!fsReady() || !fsHas(blobPath(m.name.c_str()))) return nullptr;
  File f = LittleFS.open(blobPath(m.name.c_str()), "r");
  if (!f || f.size() != m.bytes) return nullptr;
  uint8_t *buf =
      (uint8_t *)heap_caps_aligned_alloc(16, m.bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  const bool ok = buf && f.read(buf, m.bytes) == m.bytes && sha256Hex(buf, m.bytes) == m.sha256;
  f.close();
  if (!ok) {
    free(buf);
    return nullptr;
  }
  return buf;
}

uint8_t *fetchBlob(const MlManifest &m, const std::string &envelope, std::string &err) {
  if (uint8_t *cached = readCachedBlob(m)) return cached;
  uint8_t *data = nullptr;
  size_t n = 0;
  const String url = apiDeviceUrl((String("/models/") + m.name.c_str() + "/blob").c_str());
  if (!cloudHttpGetBlob(url, m.bytes, &data, &n, kFetchMs)) {
    fail(err, "model download failed");
    return nullptr;
  }
  if (n != m.bytes || sha256Hex(data, n) != m.sha256) {
    free(data);
    fail(err, "model sha256 mismatch");
    return nullptr;
  }
  if (fsReady()) {
    const bool ok = writeAtomic(blobPath(m.name.c_str()), data, n) &&
                    writeAtomic(envPath(m.name.c_str()), (const uint8_t *)envelope.data(),
                                envelope.size());
    if (!ok) Serial.println("[ml] cache write failed (store full?)");
  }
  return data;
}

void freeSlot(Slot &s) {
  if (s.interp) s.interp->~MicroInterpreter();
  free(s.interpMem);
  free(s.arena);
  free(s.blob);
  s = Slot{};
}

Slot *findSlot(const char *name) {
  for (Slot &s : gSlots) {
    if (s.used && s.m.name == name) {
      s.lastUse = ++gClock;
      return &s;
    }
  }
  return nullptr;
}

Slot *freeOrOldestSlot(const char *keep) {
  Slot *pick = nullptr;
  for (Slot &s : gSlots) {
    if (!s.used) return &s;
    if (keep && s.m.name == keep) continue;
    if (!pick || s.lastUse < pick->lastUse) pick = &s;
  }
  if (pick) {
    Serial.printf("[ml] evict %s\n", pick->m.name.c_str());
    freeSlot(*pick);
  }
  return pick;
}

size_t elems(const TfLiteTensor *t) {
  if (!t || !t->dims) return 0;
  size_t n = 1;
  for (int i = 0; i < t->dims->size; ++i) n *= (size_t)t->dims->data[i];
  return n;
}

bool buildSlot(Slot &s, const MlManifest &m, uint8_t *blob, std::string &err) {
  s.m = m;
  s.blob = blob;
  const size_t arenaBytes = (size_t)m.arenaKb * 1024;
  s.arena =
      (uint8_t *)heap_caps_aligned_alloc(16, arenaBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  s.interpMem =
      heap_caps_malloc(sizeof(tflite::MicroInterpreter), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!s.arena || !s.interpMem) {
    freeSlot(s);
    return fail(err, "out of PSRAM");
  }
  const tflite::Model *model = tflite::GetModel(blob);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    freeSlot(s);
    return fail(err, "tflite schema version mismatch");
  }
  s.interp = new (s.interpMem) tflite::MicroInterpreter(model, *gResolver, s.arena, arenaBytes);
  if (s.interp->AllocateTensors() != kTfLiteOk) {
    freeSlot(s);
    return fail(err, "AllocateTensors failed (op outside opset or arena_kb too small)");
  }
  s.used = true;
  s.lastUse = ++gClock;
  Serial.printf("[ml] %s v%d ready: %s, arena %u/%u B\n", m.name.c_str(), m.version,
                m.kind.c_str(), (unsigned)s.interp->arena_used_bytes(), (unsigned)arenaBytes);
  return true;
}

bool checkAudioPair(const Slot &cls, const Slot &fe, std::string &err) {
  const MlAudioSpec &a = cls.m.audio;
  const TfLiteTensor *fin = fe.interp->input(0);
  const TfLiteTensor *fout = fe.interp->output(0);
  const TfLiteTensor *cin = cls.interp->input(0);
  if (fin->type != kTfLiteInt16 || elems(fin) != (size_t)a.windowSamples()) {
    return fail(err, "frontend input must be int16[window samples]");
  }
  if (elems(fout) != (size_t)a.features) return fail(err, "frontend output != features");
  if (cin->type != fout->type || elems(cin) != (size_t)a.frames * (size_t)a.features) {
    return fail(err, "classifier input != frames x features of frontend type");
  }
  return true;
}

bool loadImpl(const char *name, const char *wantKind, const char *keep, std::string &err) {
  if (!mlNameOk(name)) return fail(err, "bad model name");
  if (!ensureResolver()) return fail(err, "out of PSRAM");
  std::string manifest, envelope;
  if (!fetchEnvelope(name, manifest, envelope, err)) return false;
  MlManifest m;
  if (!mlParseManifest(manifest.data(), manifest.size(), m, err)) return false;
  if (m.name != name) return fail(err, "manifest name mismatch");
  if (wantKind && m.kind != wantKind) return fail(err, "frontend has wrong kind");

  if (m.kind == "audio") {
    if (!gHooks.micRead) return fail(err, "no microphone on this board");
    if (!loadImpl(m.audio.frontend.c_str(), "frontend", name, err)) return false;
  }

  Slot *cur = findSlot(name);
  if (!cur || cur->m.sha256 != m.sha256) {
    uint8_t *blob = fetchBlob(m, envelope, err);
    if (!blob) return false;
    if (cur) freeSlot(*cur);
    Slot *s = cur ? cur : freeOrOldestSlot(m.kind == "audio" ? m.audio.frontend.c_str() : keep);
    if (!s) {
      free(blob);
      return fail(err, "no model slot");
    }
    if (!buildSlot(*s, m, blob, err)) return false;
    cur = s;
  }
  if (m.kind == "audio") {
    Slot *fe = findSlot(m.audio.frontend.c_str());
    if (!fe || !checkAudioPair(*cur, *fe, err)) {
      if (err.empty()) err = "frontend not loaded";
      freeSlot(*cur);
      return false;
    }
  }
  return true;
}

Slot *readySlot(const char *name, std::string &err) {
  if (Slot *s = findSlot(name)) return s;
  if (!loadImpl(name, nullptr, nullptr, err)) return nullptr;
  return findSlot(name);
}

float dequant(const TfLiteTensor *t, size_t i) {
  switch (t->type) {
    case kTfLiteFloat32: return t->data.f[i];
    case kTfLiteInt8: return (t->data.int8[i] - t->params.zero_point) * t->params.scale;
    case kTfLiteUInt8: return (t->data.uint8[i] - t->params.zero_point) * t->params.scale;
    case kTfLiteInt16: return (t->data.i16[i] - t->params.zero_point) * t->params.scale;
    default: return NAN;
  }
}

template <typename T>
T quantTo(float x, const TfLiteTensor *t, long lo, long hi) {
  const float scale = t->params.scale != 0.0f ? t->params.scale : 1.0f;
  long q = lroundf(x / scale) + t->params.zero_point;
  if (q < lo) q = lo;
  if (q > hi) q = hi;
  return (T)q;
}

bool quantIn(TfLiteTensor *t, size_t i, float x) {
  switch (t->type) {
    case kTfLiteFloat32: t->data.f[i] = x; return true;
    case kTfLiteInt8: t->data.int8[i] = quantTo<int8_t>(x, t, -128, 127); return true;
    case kTfLiteUInt8: t->data.uint8[i] = quantTo<uint8_t>(x, t, 0, 255); return true;
    case kTfLiteInt16: t->data.i16[i] = quantTo<int16_t>(x, t, -32768, 32767); return true;
    default: return false;
  }
}

void collect(const TfLiteTensor *out, MlResult &r) {
  const size_t n = elems(out);
  r.scores.resize(n);
  for (size_t i = 0; i < n; ++i) r.scores[i] = dequant(out, i);
  r.top = mlArgMax(r.scores);
}

}  // namespace

void mlBegin(const MlHooks &hooks) { gHooks = hooks; }

bool mlLoad(const char *name, std::string &err) {
  return loadImpl(name, nullptr, nullptr, err);
}

void mlUnload(const char *name) {
  if (Slot *s = findSlot(name)) freeSlot(*s);
}

bool mlListen(const char *name, MlResult &out, std::string &err) {
  out = MlResult{};
  Slot *s = readySlot(name, err);
  if (!s) return false;
  if (s->m.kind != "audio") return fail(err, "not an audio model");
  const MlAudioSpec a = s->m.audio;
  Slot *fe = readySlot(a.frontend.c_str(), err);
  if (!fe) return false;
  s = findSlot(name);
  if (!s) return fail(err, "model evicted while loading frontend");
  if (!gHooks.micRead) return fail(err, "no microphone on this board");

  const size_t total = (size_t)a.totalSamples();
  int16_t *pcm = (int16_t *)heap_caps_malloc(total * sizeof(int16_t),
                                             MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!pcm) return fail(err, "out of PSRAM");
  // Drop audio the I2S DMA buffered before this call.
  for (uint32_t t0 = millis(); millis() - t0 < 60;) gHooks.micRead(pcm, 256);
  size_t got = 0;
  const uint32_t deadline = millis() + (uint32_t)(total * 1000 / kMlMicRate) + 2000;
  while (got < total) {
    const size_t want = total - got < 256 ? total - got : 256;
    const size_t n = gHooks.micRead(pcm + got, want);
    if (!n) {
      if ((int32_t)(millis() - deadline) > 0) {
        free(pcm);
        return fail(err, "microphone timeout");
      }
      delay(1);
      continue;
    }
    got += n;
  }

  const uint32_t t0 = millis();
  TfLiteTensor *fin = fe->interp->input(0);
  const TfLiteTensor *fout = fe->interp->output(0);
  TfLiteTensor *cin = s->interp->input(0);
  const size_t rowBytes = fout->bytes;
  const int win = a.windowSamples();
  const int stride = a.strideSamples();
  bool ok = true;
  for (int f = 0; f < a.frames && ok; ++f) {
    memcpy(fin->data.i16, pcm + (size_t)f * stride, (size_t)win * sizeof(int16_t));
    ok = fe->interp->Invoke() == kTfLiteOk;
    if (ok) memcpy(cin->data.raw + (size_t)f * rowBytes, fout->data.raw, rowBytes);
  }
  free(pcm);
  if (!ok) return fail(err, "frontend invoke failed");
  if (s->interp->Invoke() != kTfLiteOk) return fail(err, "invoke failed");
  collect(s->interp->output(0), out);
  out.ms = millis() - t0;
  return true;
}

bool mlRun(const char *name, const float *in, size_t n, MlResult &out, std::string &err) {
  out = MlResult{};
  Slot *s = readySlot(name, err);
  if (!s) return false;
  TfLiteTensor *t = s->interp->input(0);
  if (elems(t) != n) return fail(err, "input length does not match the model");
  for (size_t i = 0; i < n; ++i) {
    if (!quantIn(t, i, in[i])) return fail(err, "unsupported input type");
  }
  const uint32_t t0 = millis();
  if (s->interp->Invoke() != kTfLiteOk) return fail(err, "invoke failed");
  collect(s->interp->output(0), out);
  out.ms = millis() - t0;
  return true;
}

bool mlInfo(const char *name, MlInfo &out) {
  out = MlInfo{};
  Slot *s = findSlot(name);
  if (!s) return false;
  out.manifest = &s->m;
  out.arenaUsed = s->interp->arena_used_bytes();
  out.inputElems = elems(s->interp->input(0));
  out.outputElems = elems(s->interp->output(0));
  return true;
}

void mlFillStatus(JsonObject meta) {
  JsonObject ml = meta.createNestedObject("ml");
  ml["opset"] = kMlOpsetVersion;
  JsonArray models = ml.createNestedArray("models");
  for (const Slot &s : gSlots) {
    if (s.used) models.add(String(s.m.name.c_str()) + "@" + s.m.version);
  }
}

#else  // !OC_HAS_ML

void mlBegin(const MlHooks &hooks) { (void)hooks; }
bool mlLoad(const char *name, std::string &err) {
  (void)name;
  err = "ml not built";
  return false;
}
void mlUnload(const char *name) { (void)name; }
bool mlListen(const char *name, MlResult &out, std::string &err) {
  (void)name;
  out = MlResult{};
  err = "ml not built";
  return false;
}
bool mlRun(const char *name, const float *in, size_t n, MlResult &out, std::string &err) {
  (void)name;
  (void)in;
  (void)n;
  out = MlResult{};
  err = "ml not built";
  return false;
}
bool mlInfo(const char *name, MlInfo &out) {
  (void)name;
  out = MlInfo{};
  return false;
}
void mlFillStatus(JsonObject meta) { (void)meta; }

#endif
