#include "claude_proto.h"

#include <ArduinoJson.h>
#include <string.h>

namespace {

constexpr size_t kMaxEntryBytes = 64;
constexpr size_t kMaxHintBytes = 160;
constexpr size_t kMaxTextBytes = 200;

// Cut at a byte limit without splitting a UTF-8 sequence.
std::string clip(const char *s, size_t maxBytes) {
  if (!s) return std::string();
  size_t n = strlen(s);
  if (n <= maxBytes) return std::string(s, n);
  n = maxBytes;
  while (n > 0 && ((uint8_t)s[n] & 0xC0) == 0x80) --n;
  return std::string(s, n);
}

const JsonDocument &lineFilter() {
  // Sized for 64-bit host tests too (bigger slots); a truncated filter would
  // silently drop "content".
  static StaticJsonDocument<1024> f;
  static bool built = false;
  if (!built) {
    built = true;
    for (const char *k : {"cmd", "name", "evt", "role", "time", "total", "running", "waiting",
                          "msg", "entries", "tokens", "tokens_today", "prompt"}) {
      f[k] = true;
    }
    f["content"][0]["type"] = true;
    f["content"][0]["text"] = true;
  }
  return f;
}

void appendJson(const JsonDocument &doc, std::string &out) {
  const size_t n = measureJson(doc);
  std::string s(n, '\0');
  serializeJson(doc, &s[0], n + 1);
  out += s;
  out += '\n';
}

void ack(const char *cmd, bool ok, const char *error, std::string &out) {
  StaticJsonDocument<256> doc;
  doc["ack"] = cmd;
  doc["ok"] = ok;
  doc["n"] = 0;
  if (error) doc["error"] = error;
  appendJson(doc, out);
}

}  // namespace

void ClaudeProto::feed(const char *data, size_t n, uint32_t nowMs, const ClaudeStatus &st,
                       std::string &out) {
  for (size_t i = 0; i < n; ++i) {
    const char c = data[i];
    if (c == '\n') {
      if (!overflow_ && !buf_.empty()) handleLine(&buf_[0], buf_.size(), nowMs, st, out);
      buf_.clear();
      overflow_ = false;
      continue;
    }
    if (c == '\r' || overflow_) continue;
    if (buf_.size() >= kMaxLine) {
      overflow_ = true;
      buf_.clear();
      continue;
    }
    buf_.push_back(c);
  }
}

void ClaudeProto::handleLine(char *line, size_t n, uint32_t nowMs, const ClaudeStatus &st,
                             std::string &out) {
  DynamicJsonDocument doc(3072);
  // char* input → zero-copy; strings point into `line`.
  if (deserializeJson(doc, line, n, DeserializationOption::Filter(lineFilter()))) return;
  JsonObject o = doc.as<JsonObject>();
  if (o.isNull()) return;

  if (o.containsKey("cmd")) {
    const char *cmd = o["cmd"] | "";
    if (!strcmp(cmd, "status")) {
      DynamicJsonDocument r(512);
      r["ack"] = "status";
      r["ok"] = true;
      JsonObject data = r.createNestedObject("data");
      data["name"] = st_.name.empty() ? st.name : st_.name.c_str();
      data["sec"] = st.sec;
      if (st.batKnown) {
        JsonObject bat = data.createNestedObject("bat");
        bat["pct"] = st.batPct;
        if (st.batMv > 0) bat["mV"] = st.batMv;
        bat["usb"] = st.usb;
      }
      JsonObject sys = data.createNestedObject("sys");
      sys["up"] = st.upS;
      sys["heap"] = st.heap;
      appendJson(r, out);
    } else if (!strcmp(cmd, "name")) {
      st_.name = clip(o["name"] | "", 32);
      ack(cmd, true, nullptr, out);
    } else if (!strcmp(cmd, "owner")) {
      st_.owner = clip(o["name"] | "", 32);
      ack(cmd, true, nullptr, out);
    } else if (!strcmp(cmd, "unpair")) {
      unpair_ = true;
      ack(cmd, true, nullptr, out);
    } else if (!strcmp(cmd, "char_begin") || !strcmp(cmd, "file") || !strcmp(cmd, "chunk") ||
               !strcmp(cmd, "file_end") || !strcmp(cmd, "char_end")) {
      ack(cmd, false, "folder push not supported", out);
    } else {
      ack(cmd, false, "unsupported", out);
    }
    return;
  }

  if (o.containsKey("time")) {
    JsonArray t = o["time"].as<JsonArray>();
    if (!t.isNull() && t.size() >= 1) {
      st_.epoch = t[0].as<int64_t>();
      st_.tzOffset = t.size() >= 2 ? t[1].as<int32_t>() : 0;
      st_.hasTime = true;
      time_ = true;
    }
    return;
  }

  if (o.containsKey("evt")) {
    if (!strcmp(o["evt"] | "", "turn") && !strcmp(o["role"] | "", "assistant")) {
      for (JsonObject block : o["content"].as<JsonArray>()) {
        if (!strcmp(block["type"] | "", "text")) {
          st_.lastText = clip(block["text"] | "", kMaxTextBytes);
          break;
        }
      }
    }
    return;
  }

  if (!o.containsKey("total") && !o.containsKey("prompt") && !o.containsKey("msg")) return;

  st_.seen = true;
  st_.lastMs = nowMs;
  st_.total = o["total"] | 0;
  st_.running = o["running"] | 0;
  st_.waiting = o["waiting"] | 0;
  st_.tokens = o["tokens"] | 0L;
  st_.tokensToday = o["tokens_today"] | 0L;
  st_.msg = clip(o["msg"] | "", kMaxEntryBytes);
  st_.entries.clear();
  for (const char *e : o["entries"].as<JsonArray>()) {
    if (st_.entries.size() >= kMaxEntries) break;
    st_.entries.push_back(clip(e, kMaxEntryBytes));
  }
  JsonObject p = o["prompt"].as<JsonObject>();
  if (p.isNull()) {
    st_.hasPrompt = false;
    st_.prompt = ClaudePrompt{};
    decided_.clear();
  } else {
    st_.hasPrompt = true;
    st_.prompt.id = p["id"] | "";
    st_.prompt.tool = clip(p["tool"] | "", 32);
    st_.prompt.hint = clip(p["hint"] | "", kMaxHintBytes);
  }
}

std::string ClaudeProto::permissionLine(const std::string &id, bool allow) {
  if (id.empty()) return std::string();
  DynamicJsonDocument doc(256 + id.size());
  doc["cmd"] = "permission";
  doc["id"] = id.c_str();
  doc["decision"] = allow ? "once" : "deny";
  std::string out;
  appendJson(doc, out);
  return out;
}

bool ClaudeProto::connected(uint32_t nowMs) const {
  return st_.seen && (uint32_t)(nowMs - st_.lastMs) < kStaleMs;
}

bool ClaudeProto::promptPending() const {
  return st_.hasPrompt && !st_.prompt.id.empty() && st_.prompt.id != decided_;
}

bool ClaudeProto::takeUnpair() {
  const bool v = unpair_;
  unpair_ = false;
  return v;
}

bool ClaudeProto::takeTime() {
  const bool v = time_;
  time_ = false;
  return v;
}
