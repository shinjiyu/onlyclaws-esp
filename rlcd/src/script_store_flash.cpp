#include "script_store_flash.h"

#include <Arduino.h>
#include <esp_littlefs.h>
#include <esp_partition.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#include <string>

#include "cloud_config.h"
#include "script_engine.h"
#include "script_store.h"

namespace {

SemaphoreHandle_t gMu = nullptr;
bool gMounted = false;
bool gKeyOk = false;
bool gOffline = false;
uint8_t gPub[32];
ScriptStoreIo gIo{};

bool lock() {
  if (!gMu) gMu = xSemaphoreCreateMutex();
  return gMu && xSemaphoreTake(gMu, pdMS_TO_TICKS(2000)) == pdTRUE;
}

void unlock() {
  if (gMu) xSemaphoreGive(gMu);
}

std::string fullPath(const char *path) { return std::string("/littlefs/") + (path ? path : ""); }

bool ioExists(void *ctx, const char *path) {
  (void)ctx;
  struct stat st;
  return stat(fullPath(path).c_str(), &st) == 0;
}

bool ioRead(void *ctx, const char *path, std::string &out) {
  (void)ctx;
  FILE *f = fopen(fullPath(path).c_str(), "rb");
  if (!f) return false;
  if (fseek(f, 0, SEEK_END) != 0) {
    fclose(f);
    return false;
  }
  const long sz = ftell(f);
  if (sz < 0 || (size_t)sz > kScriptHeaderLen + kScriptMaxSource + kScriptSigLen + 64) {
    fclose(f);
    return false;
  }
  if (fseek(f, 0, SEEK_SET) != 0) {
    fclose(f);
    return false;
  }
  out.assign((size_t)sz, '\0');
  const size_t n = sz ? fread(&out[0], 1, (size_t)sz, f) : 0;
  const bool ok = n == (size_t)sz && ferror(f) == 0;
  fclose(f);
  if (!ok) out.clear();
  return ok;
}

bool ioWrite(void *ctx, const char *path, const uint8_t *data, size_t n) {
  (void)ctx;
  FILE *f = fopen(fullPath(path).c_str(), "wb");
  if (!f) return false;
  const size_t w = n ? fwrite(data, 1, n, f) : 0;
  const bool flushed = fflush(f) == 0;
  const bool ok = w == n && flushed && ferror(f) == 0;
  fclose(f);
  return ok;
}

bool ioRename(void *ctx, const char *from, const char *to) {
  (void)ctx;
  return rename(fullPath(from).c_str(), fullPath(to).c_str()) == 0;
}

bool ioRemove(void *ctx, const char *path) {
  (void)ctx;
  const std::string p = fullPath(path);
  struct stat st;
  if (stat(p.c_str(), &st) != 0) return true;
  return remove(p.c_str()) == 0;
}

int b64Val(char c) {
  if (c >= 'A' && c <= 'Z') return c - 'A';
  if (c >= 'a' && c <= 'z') return c - 'a' + 26;
  if (c >= '0' && c <= '9') return c - '0' + 52;
  if (c == '+') return 62;
  if (c == '/') return 63;
  return -1;
}

bool b64To64(const char *in, uint8_t out[64]) {
  if (!in) return false;
  size_t n = 0;
  int val = 0;
  int valb = -8;
  for (const char *p = in; *p; ++p) {
    if (*p == '=' || *p == '\n' || *p == '\r' || *p == ' ') continue;
    const int d = b64Val(*p);
    if (d < 0) return false;
    val = (val << 6) + d;
    valb += 6;
    if (valb >= 0) {
      if (n >= 64) return false;
      out[n++] = (uint8_t)((val >> valb) & 0xFF);
      valb -= 8;
    }
  }
  return n == 64;
}

// LittleFS must not sit on an app/OTA slot. App updates write app0/app1 only.
bool partitionOtaSafe(const esp_partition_t *part) {
  if (!part || part->type != ESP_PARTITION_TYPE_DATA) return false;
  esp_partition_iterator_t it =
      esp_partition_find(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_ANY, nullptr);
  while (it) {
    const esp_partition_t *app = esp_partition_get(it);
    const uint32_t a0 = part->address;
    const uint32_t a1 = part->address + part->size;
    const uint32_t b0 = app->address;
    const uint32_t b1 = app->address + app->size;
    if (a0 < b1 && b0 < a1) {
      esp_partition_iterator_release(it);
      return false;
    }
    it = esp_partition_next(it);
  }
  return true;
}

bool runImage(const ScriptImage &img) {
  return scriptEngineLoadLua(img.name.c_str(), img.source.c_str(), img.mode.c_str(), img.everyMs);
}

// Caller holds gMu. Tries older versions when the newest one will not run.
bool rollbackRun() {
  for (int i = 0; i < kScriptKeepVersions; ++i) {
    ScriptImage img;
    std::string err;
    const ScriptPick pick = scriptStorePick(gIo, gPub, img, err);
    if (pick != ScriptPick::Ready) {
      if (pick == ScriptPick::SafeMode) Serial.printf("[script] safe mode: %s\n", err.c_str());
      gOffline = false;
      return false;
    }
    if (runImage(img)) {
      gOffline = true;
      Serial.printf("[script] flash %s v%u\n", img.name.c_str(), (unsigned)img.version);
      return true;
    }
    Serial.printf("[script] rollback %s v%u: %s\n", img.name.c_str(), (unsigned)img.version,
                  scriptEngineLastError());
    std::string why;
    if (!scriptStoreMarkBad(gIo, img.name.c_str(), img.version, why)) {
      Serial.printf("[script] mark bad failed: %s\n", why.c_str());
      gOffline = false;
      return false;
    }
  }
  gOffline = false;
  Serial.println("[script] safe mode");
  return false;
}

}  // namespace

void scriptStoreBegin() {
  gIo.exists = ioExists;
  gIo.read = ioRead;
  gIo.write = ioWrite;
  gIo.rename = ioRename;
  gIo.remove = ioRemove;
  gIo.ctx = nullptr;
  gKeyOk = scriptHexTo32(OC_SCRIPT_PUBKEY_HEX, gPub);
  if (!gKeyOk) Serial.println("[script] public key missing; signed scripts refused");

  const esp_partition_t *part = esp_partition_find_first(
      ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "littlefs");
  if (!part) {
    Serial.println("[script] littlefs partition missing (flash partitions csv)");
    return;
  }
  if (!partitionOtaSafe(part)) {
    Serial.println("[script] littlefs overlaps an app slot; not mounting");
    return;
  }
  Serial.printf("[script] littlefs @0x%x size %u (data, not an OTA slot)\n",
                (unsigned)part->address, (unsigned)part->size);

  if (!esp_littlefs_mounted("littlefs")) {
    esp_vfs_littlefs_conf_t conf = {};
    conf.base_path = "/littlefs";
    conf.partition_label = "littlefs";
    conf.partition = nullptr;
    conf.format_if_mount_failed = true;
    conf.read_only = false;
    conf.dont_mount = false;
    conf.grow_on_mount = true;
    const esp_err_t err = esp_vfs_littlefs_register(&conf);
    if (err != ESP_OK) {
      Serial.printf("[script] littlefs mount failed: %d\n", (int)err);
      return;
    }
  }
  mkdir("/littlefs/s", 0755);
  gMounted = true;
}

void scriptStoreBoot() {
  if (!gMounted || !gKeyOk || !lock()) return;
  rollbackRun();
  unlock();
}

bool scriptStoreAcceptAndRun(const char *scriptId, const char *source, const char *mode,
                             uint32_t everyMs, uint32_t version, const char *sha256Hex,
                             const char *sigB64) {
  if (!gMounted || !gKeyOk) {
    scriptEngineFail("script store unavailable");
    return false;
  }
  if (!lock()) {
    scriptEngineFail("script store busy");
    return false;
  }
  ScriptImage in;
  in.name = scriptId ? scriptId : "";
  in.version = version;
  in.mode = mode ? mode : "";
  in.everyMs = everyMs;
  in.source = source ? source : "";
  std::string prefix;
  std::string err;
  uint8_t expect[32];
  uint8_t dig[32];
  uint8_t sig[64];
  if (!scriptEnvelopePrefix(in, prefix, err) || !scriptHexTo32(sha256Hex, expect)) {
    unlock();
    scriptEngineFail(err.empty() ? "bad script envelope" : err.c_str());
    return false;
  }
  scriptSha256((const uint8_t *)in.source.data(), in.source.size(), dig);
  if (memcmp(expect, dig, 32) != 0 || !b64To64(sigB64, sig)) {
    unlock();
    scriptEngineFail("bad script signature");
    return false;
  }
  std::string blob = prefix;
  blob.append((const char *)sig, 64);
  if (!scriptStoreAccept(gIo, (const uint8_t *)blob.data(), blob.size(), gPub, err)) {
    unlock();
    Serial.printf("[script] reject: %s\n", err.c_str());
    scriptEngineFail(err.c_str());
    return false;
  }
  if (!runImage(in)) {
    std::string why;
    scriptStoreMarkBad(gIo, in.name.c_str(), in.version, why);
    Serial.printf("[script] new script failed: %s\n", scriptEngineLastError());
    rollbackRun();
    unlock();
    return false;
  }
  gOffline = true;
  unlock();
  return true;
}

void scriptStoreOnStop() {
  if (!gMounted || !lock()) {
    gOffline = false;
    return;
  }
  std::string err;
  if (!scriptStoreSetRun(gIo, false, err)) Serial.printf("[script] stop persist: %s\n", err.c_str());
  gOffline = false;
  unlock();
}

bool scriptStoreInfo(ScriptPersistInfo *out) {
  if (!out) return false;
  memset(out, 0, sizeof(*out));
  out->mounted = gMounted;
  if (!gMounted || !lock()) return true;
  ScriptStoreView view;
  if (scriptStoreView(gIo, view)) {
    out->run = view.run;
    out->safeMode = view.safeMode;
    out->version = view.version;
    strncpy(out->name, view.name.c_str(), sizeof(out->name) - 1);
  }
  unlock();
  return true;
}

bool scriptStoreRunsOffline() { return gOffline; }
