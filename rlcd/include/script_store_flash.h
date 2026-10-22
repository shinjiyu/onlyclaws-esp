#pragma once

#include <stdbool.h>
#include <stdint.h>

// LittleFS `littlefs` partition adapter around script_store.h.
// The partition is data, not an OTA app slot. This code never erases it
// except for the filesystem driver's format-if-mount-fails on first use.

struct ScriptPersistInfo {
  bool mounted;
  bool run;
  bool safeMode;
  uint32_t version;
  char name[33];
};

void scriptStoreBegin();
// Load the last good script into the Lua engine. Rolls back when a version
// fails to execute. Safe mode leaves the engine idle.
void scriptStoreBoot();
// Verify the signed envelope, store it, and run it. On a Lua load failure,
// mark that version bad and try the previous one.
bool scriptStoreAcceptAndRun(const char *scriptId, const char *source, const char *mode,
                             uint32_t everyMs, uint32_t version, const char *sha256Hex,
                             const char *sigB64);
void scriptStoreOnStop();
bool scriptStoreInfo(ScriptPersistInfo *out);
// True while a script restored or accepted from flash is the one running.
bool scriptStoreRunsOffline();
