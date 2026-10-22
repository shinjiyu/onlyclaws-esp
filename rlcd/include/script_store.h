#pragma once

#include <stddef.h>
#include <stdint.h>

#include <string>

// Signed Lua envelope stored on the LittleFS `littlefs` partition.
// Pure C++ (no Arduino, no ESP-IDF) so host tests can drive power-loss,
// bad signatures, and rollback. Wire format and partition notes:
// doc/structurizr/SCRIPT-PERSIST.md.
//
//   0  4   magic "LCLW"
//   4  1   format version (1)
//   5  32  script id, NUL-padded
//  37  1   mode: 1 = once, 2 = loop
//  38  1   flags (0)
//  39  4   every_ms, little-endian
//  43  4   content length, little-endian
//  47  4   monotonic version, little-endian
//  51  32  SHA-256 of the Lua bytes
//  83  N   Lua source
//  83+N 64 Ed25519 signature over the bytes before it

constexpr uint8_t kScriptFmtVersion = 1;
constexpr size_t kScriptNameLen = 32;
constexpr size_t kScriptHeaderLen = 83;
constexpr size_t kScriptSigLen = 64;
constexpr size_t kScriptMaxSource = 24000;
constexpr int kScriptKeepVersions = 3;

struct ScriptImage {
  std::string name;
  uint32_t version = 0;
  std::string mode;
  uint32_t everyMs = 1000;
  std::string source;
};

// POSIX-shaped filesystem. `write` replaces nothing by itself; the store
// does the .tmp write, read-back, and rename. Paths are store-relative
// ("s/index.json"), not absolute.
struct ScriptStoreIo {
  bool (*exists)(void *ctx, const char *path);
  bool (*read)(void *ctx, const char *path, std::string &out);
  bool (*write)(void *ctx, const char *path, const uint8_t *data, size_t n);
  bool (*rename)(void *ctx, const char *from, const char *to);
  bool (*remove)(void *ctx, const char *path);
  void *ctx;
};

enum class ScriptPick : int {
  Ready = 0,     // `out` is a verified image and the index says run
  Stopped = 1,   // a script is stored but a stop cleared the run flag
  Empty = 2,     // nothing stored
  SafeMode = 3,  // every retained version failed verification
  IoError = 4,   // read/write failed; caller should retry, not mark bad
};

void scriptSha256(const uint8_t *data, size_t n, uint8_t out[32]);
bool scriptHexTo32(const char *hex, uint8_t out[32]);
void scriptSha256Hex(const uint8_t *data, size_t n, char out[65]);

// Header + source. Fills the SHA-256 from `in.source`.
bool scriptEnvelopePrefix(const ScriptImage &in, std::string &prefix, std::string &err);

// Verify signature and hash. Does not touch the filesystem.
bool scriptEnvelopeOpen(const uint8_t *blob, size_t n, const uint8_t pubkey[32], ScriptImage &out,
                        std::string &err);

// Verify, then write `<name>.<version>` via .tmp + read-back + rename, then
// publish the index the same way. Keeps the last kScriptKeepVersions of the
// active script. Rejects a bad signature before any final file is created.
bool scriptStoreAccept(ScriptStoreIo &io, const uint8_t *blob, size_t n, const uint8_t pubkey[32],
                       std::string &err);

// Newest valid version of the active script, or why there isn't one.
// A blob that fails verification is marked invalid and the next is tried.
ScriptPick scriptStorePick(ScriptStoreIo &io, const uint8_t pubkey[32], ScriptImage &out,
                           std::string &err);

// Lua accepted the blob but executing it failed. Drop that version and keep
// the older ones for the next pick.
bool scriptStoreMarkBad(ScriptStoreIo &io, const char *name, uint32_t version, std::string &err);

// Remote stop. Files stay; boot will not run them until the next accept.
bool scriptStoreSetRun(ScriptStoreIo &io, bool run, std::string &err);

struct ScriptStoreView {
  bool run = false;
  bool safeMode = false;
  uint32_t version = 0;
  std::string name;
};

bool scriptStoreView(ScriptStoreIo &io, ScriptStoreView &out);
