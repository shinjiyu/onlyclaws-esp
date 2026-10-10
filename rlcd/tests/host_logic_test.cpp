// Host-side checks for the pure firmware logic: Claude Buddy protocol and the
// battery badge helpers. Built and run by test_host_logic.py.

#include <stdio.h>
#include <string.h>

#include <string>

#include "claude_proto.h"
#include "oc_battery.h"

static int gFailures = 0;

#define CHECK(cond)                                                \
  do {                                                             \
    if (!(cond)) {                                                 \
      fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
      ++gFailures;                                                 \
    }                                                              \
  } while (0)

static bool contains(const std::string &s, const char *needle) {
  return s.find(needle) != std::string::npos;
}

static void feedStr(ClaudeProto &p, const char *s, uint32_t nowMs, const ClaudeStatus &st,
                    std::string &out) {
  p.feed(s, strlen(s), nowMs, st, out);
}

static ClaudeStatus status() {
  ClaudeStatus st;
  st.name = "Claude-OC-ABCD";
  st.sec = true;
  st.batKnown = true;
  st.batPct = 87;
  st.batMv = 4012;
  st.usb = false;
  st.upS = 42;
  st.heap = 123456;
  return st;
}

static void testHeartbeatAndPrompt() {
  ClaudeProto p;
  std::string out;
  const char *hb =
      "{\"total\":3,\"running\":1,\"waiting\":1,\"msg\":\"approve: Bash\","
      "\"entries\":[\"10:42 git push\",\"10:41 yarn test\"],\"tokens\":184502,"
      "\"tokens_today\":31200,\"prompt\":{\"id\":\"req_abc123\",\"tool\":\"Bash\","
      "\"hint\":\"rm -rf /tmp/foo\"}}\n";
  // Split mid-line: the transport delivers arbitrary chunks.
  p.feed(hb, 20, 1000, status(), out);
  CHECK(!p.state().seen);
  p.feed(hb + 20, strlen(hb) - 20, 1000, status(), out);
  CHECK(out.empty());
  const ClaudeState &s = p.state();
  CHECK(s.seen);
  CHECK(s.total == 3 && s.running == 1 && s.waiting == 1);
  CHECK(s.tokens == 184502 && s.tokensToday == 31200);
  CHECK(s.entries.size() == 2 && s.entries[0] == "10:42 git push");
  CHECK(p.promptPending());
  CHECK(s.prompt.id == "req_abc123" && s.prompt.tool == "Bash");
  CHECK(p.connected(1000 + 29000));
  CHECK(!p.connected(1000 + 31000));

  const std::string allow = ClaudeProto::permissionLine("req_abc123", true);
  CHECK(allow == "{\"cmd\":\"permission\",\"id\":\"req_abc123\",\"decision\":\"once\"}\n");
  CHECK(contains(ClaudeProto::permissionLine("x", false), "\"decision\":\"deny\""));
  CHECK(ClaudeProto::permissionLine("", true).empty());

  p.markDecided("req_abc123");
  CHECK(!p.promptPending());
  // Same prompt repeated in the next heartbeat stays decided.
  p.feed(hb, strlen(hb), 11000, status(), out);
  CHECK(!p.promptPending());
  // Prompt leaves, then a new one arrives.
  feedStr(p, "{\"total\":3,\"running\":1,\"waiting\":0}\n", 21000, status(), out);
  CHECK(!p.state().hasPrompt);
  feedStr(p, "{\"total\":3,\"waiting\":1,\"prompt\":{\"id\":\"req_2\",\"tool\":\"Edit\"}}\n",
          22000, status(), out);
  CHECK(p.promptPending() && p.state().prompt.id == "req_2");
}

static void testCommands() {
  ClaudeProto p;
  std::string out;
  const char *cmds = "{\"cmd\":\"status\"}\r\n{\"cmd\":\"name\",\"name\":\"Clawd\"}\n"
                     "{\"cmd\":\"owner\",\"name\":\"Felix\"}\n{\"cmd\":\"char_begin\"}\n"
                     "{\"cmd\":\"bogus\"}\n";
  p.feed(cmds, strlen(cmds), 0, status(), out);
  CHECK(contains(out, "\"ack\":\"status\""));
  CHECK(contains(out, "\"name\":\"Claude-OC-ABCD\""));
  CHECK(contains(out, "\"sec\":true"));
  CHECK(contains(out, "\"pct\":87"));
  CHECK(contains(out, "\"heap\":123456"));
  CHECK(contains(out, "{\"ack\":\"name\",\"ok\":true,\"n\":0}"));
  CHECK(contains(out, "{\"ack\":\"owner\",\"ok\":true,\"n\":0}"));
  CHECK(contains(out, "\"ack\":\"char_begin\",\"ok\":false"));
  CHECK(contains(out, "\"ack\":\"bogus\",\"ok\":false"));
  CHECK(p.state().name == "Clawd" && p.state().owner == "Felix");

  out.clear();
  feedStr(p, "{\"cmd\":\"status\"}\n", 0, status(), out);
  CHECK(contains(out, "\"name\":\"Clawd\""));

  out.clear();
  CHECK(!p.takeUnpair());
  feedStr(p, "{\"cmd\":\"unpair\"}\n", 0, status(), out);
  CHECK(contains(out, "\"ack\":\"unpair\",\"ok\":true"));
  CHECK(p.takeUnpair());
  CHECK(!p.takeUnpair());

  ClaudeStatus noBat = status();
  noBat.batKnown = false;
  out.clear();
  feedStr(p, "{\"cmd\":\"status\"}\n", 0, noBat, out);
  CHECK(!contains(out, "\"bat\""));
}

static void testTimeTurnAndJunk() {
  ClaudeProto p;
  std::string out;
  feedStr(p, "{\"time\":[1775731234,-25200]}\n", 0, status(), out);
  CHECK(p.takeTime());
  CHECK(!p.takeTime());
  CHECK(p.state().epoch == 1775731234 && p.state().tzOffset == -25200);

  const char *turn =
      "{\"evt\":\"turn\",\"role\":\"assistant\",\"content\":[{\"type\":\"tool_use\"},"
      "{\"type\":\"text\",\"text\":\"Done.\"}]}\n";
  p.feed(turn, strlen(turn), 0, status(), out);
  CHECK(p.state().lastText == "Done.");
  CHECK(!p.state().seen);

  // Garbage and an oversize line are dropped; the next line still parses.
  feedStr(p, "not json\n", 0, status(), out);
  std::string huge(ClaudeProto::kMaxLine + 10, 'x');
  huge += "\n{\"total\":1}\n";
  p.feed(huge.data(), huge.size(), 5, status(), out);
  CHECK(out.empty());
  CHECK(p.state().seen && p.state().total == 1);

  // UTF-8 is clipped on a character boundary (32-byte tool limit).
  std::string tool;
  for (int i = 0; i < 20; ++i) tool += "\xE5\xB7\xA5";  // 3-byte CJK
  const std::string hb = "{\"prompt\":{\"id\":\"u\",\"tool\":\"" + tool + "\"}}\n";
  p.feed(hb.data(), hb.size(), 6, status(), out);
  CHECK(p.state().prompt.tool.size() == 30);
}

static void testBattery() {
  CHECK(ocBatteryPctFromMv(3200) == 0);
  CHECK(ocBatteryPctFromMv(3300) == 0);
  CHECK(ocBatteryPctFromMv(3600) == 20);
  CHECK(ocBatteryPctFromMv(3900) == 70);
  CHECK(ocBatteryPctFromMv(4150) == 100);
  CHECK(ocBatteryPctFromMv(4300) == 100);
  int prev = -1;
  for (int mv = 3000; mv <= 4400; mv += 10) {
    const int pct = ocBatteryPctFromMv(mv);
    CHECK(pct >= prev);
    prev = pct;
  }

  char label[8];
  OcBattery b;
  ocBatteryLabel(b, label, sizeof(label));
  CHECK(label[0] == 0);
  b.sensed = true;
  ocBatteryLabel(b, label, sizeof(label));
  CHECK(!strcmp(label, "USB"));
  b.present = true;
  b.pct = 87;
  ocBatteryLabel(b, label, sizeof(label));
  CHECK(!strcmp(label, "87%"));
  b.charging = true;
  ocBatteryLabel(b, label, sizeof(label));
  CHECK(!strcmp(label, "87%+"));
  b.pct = 140;
  ocBatteryLabel(b, label, sizeof(label));
  CHECK(!strcmp(label, "100%+"));

  OcBattery a = b;
  a.mv = 4000;
  CHECK(ocBatterySame(a, b));
  a.pct = 86;
  CHECK(!ocBatterySame(a, b));
}

int main() {
  testHeartbeatAndPrompt();
  testCommands();
  testTimeTurnAndJunk();
  testBattery();
  if (gFailures) {
    fprintf(stderr, "%d failure(s)\n", gFailures);
    return 1;
  }
  printf("ok\n");
  return 0;
}
