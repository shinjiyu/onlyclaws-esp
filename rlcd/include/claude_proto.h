#pragma once

#include <stddef.h>
#include <stdint.h>

#include <string>
#include <vector>

// Claude desktop Hardware Buddy wire protocol (newline-delimited JSON over a
// byte stream). Transport- and UI-free so host tests can drive it.
// Spec: https://github.com/anthropics/claude-desktop-buddy/blob/main/REFERENCE.md

struct ClaudePrompt {
  std::string id;
  std::string tool;
  std::string hint;
};

// Device facts for the {"cmd":"status"} ack, supplied by the caller.
struct ClaudeStatus {
  const char *name = "";
  bool sec = false;
  bool batKnown = false;
  int batPct = -1;
  int batMv = -1;
  bool usb = false;
  uint32_t upS = 0;
  uint32_t heap = 0;
};

struct ClaudeState {
  bool seen = false;    // at least one heartbeat
  uint32_t lastMs = 0;  // caller clock at the last heartbeat
  int total = 0;
  int running = 0;
  int waiting = 0;
  long tokens = 0;
  long tokensToday = 0;
  std::string msg;
  std::vector<std::string> entries;  // newest first
  bool hasPrompt = false;
  ClaudePrompt prompt;
  std::string owner;
  std::string name;
  std::string lastText;  // first text block of the last assistant turn
  bool hasTime = false;
  int64_t epoch = 0;
  int32_t tzOffset = 0;
};

class ClaudeProto {
 public:
  static constexpr size_t kMaxLine = 6144;
  static constexpr size_t kMaxEntries = 4;
  static constexpr uint32_t kStaleMs = 30000;

  // Raw bytes in; every complete line is handled and its reply (if any) is
  // appended to `out`, newline-terminated.
  void feed(const char *data, size_t n, uint32_t nowMs, const ClaudeStatus &st, std::string &out);

  // {"cmd":"permission",...}\n, or "" for an empty id.
  static std::string permissionLine(const std::string &id, bool allow);

  const ClaudeState &state() const { return st_; }
  bool connected(uint32_t nowMs) const;
  // A prompt is pending until it is decided here or leaves the heartbeat.
  bool promptPending() const;
  void markDecided(const std::string &id) { decided_ = id; }

  // One-shot events for the caller.
  bool takeUnpair();
  bool takeTime();

 private:
  void handleLine(char *line, size_t n, uint32_t nowMs, const ClaudeStatus &st, std::string &out);

  ClaudeState st_;
  std::string buf_;
  bool overflow_ = false;
  std::string decided_;
  bool unpair_ = false;
  bool time_ = false;
};
