#include "claude_buddy.h"

#include "oc_features.h"

#if OC_HAS_BLE

#include <Fonts/FreeMonoBold12pt7b.h>
#include <Fonts/FreeMonoBold18pt7b.h>
#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/stream_buffer.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

#include <string>
#include <vector>

#include "panel_display.h"

namespace {

constexpr size_t kInboxBytes = 8192;
constexpr uint32_t kPasskeyCardMs = 60000;
constexpr int16_t kCharW = 14;  // FreeMonoBold12pt advance
constexpr int16_t kLineH = 26;

ClaudeBuddyHooks gHooks;
ClaudeProto gProto;
StreamBufferHandle_t gInbox = nullptr;
StaticStreamBuffer_t gInboxCtl;

volatile uint32_t gPasskey = 0;
volatile bool gPasskeyNew = false;
volatile bool gPairDone = false;

enum class Card : uint8_t { None, Passkey, Prompt };
Card gCard = Card::None;
uint32_t gCardSinceMs = 0;
std::string gCardId;
uint8_t *gSaved = nullptr;
bool gSavedValid = false;
bool gTakeover = true;
OcBattery gBattery{};

// Panel fonts are ASCII only: one '?' per multi-byte UTF-8 character.
std::string ascii(const std::string &s) {
  std::string o;
  o.reserve(s.size());
  for (const char ch : s) {
    const uint8_t c = (uint8_t)ch;
    if (c < 0x80) o.push_back(c >= 0x20 ? (char)c : ' ');
    else if ((c & 0xC0) == 0xC0) o.push_back('?');
  }
  return o;
}

std::vector<std::string> wrap(const std::string &s, size_t cols, size_t maxLines) {
  std::vector<std::string> lines;
  size_t i = 0;
  while (i < s.size() && lines.size() < maxLines) {
    size_t n = s.size() - i;
    if (n > cols) {
      n = cols;
      const size_t sp = s.rfind(' ', i + cols);
      if (sp != std::string::npos && sp > i && sp - i > cols - 8) n = sp - i;
    }
    lines.push_back(s.substr(i, n));
    i += n;
    while (i < s.size() && s[i] == ' ') ++i;
  }
  if (i < s.size() && !lines.empty()) {
    std::string &last = lines.back();
    if (last.size() > cols - 3) last.resize(cols - 3);
    last += "...";
  }
  return lines;
}

void saveCanvas() {
  PanelDisplay *d = gHooks.display;
  uint8_t *cv = d ? d->canvas() : nullptr;
  gSavedValid = false;
  if (!cv) return;
  if (!gSaved) {
    gSaved = (uint8_t *)heap_caps_malloc(d->frameBytes(), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  }
  if (!gSaved) return;
  memcpy(gSaved, cv, d->frameBytes());
  gSavedValid = true;
}

void restoreCanvas() {
  PanelDisplay *d = gHooks.display;
  if (!d) return;
  uint8_t *cv = d->canvas();
  if (gSavedValid && cv) memcpy(cv, gSaved, d->frameBytes());
  else d->fillScreen(0);
  gSavedValid = false;
  d->flush();
}

void openCard(Card c) {
  if (gCard == Card::None) saveCanvas();
  gCard = c;
  gCardSinceMs = millis();
}

void closeCard() {
  gCard = Card::None;
  gCardId.clear();
  restoreCanvas();
}

void cardFrame(PanelDisplay &d, const char *title) {
  d.fillScreen(0);
  d.drawRect(4, 4, d.width() - 8, d.height() - 8, 1);
  d.drawRect(6, 6, d.width() - 12, d.height() - 12, 1);
  d.setTextSize(1);
  d.setTextColor(1);
  d.setFont(&FreeMonoBold18pt7b);
  d.setCursor(18, 44);
  d.print(title);
  d.setFont(&FreeMonoBold12pt7b);
}

void drawPasskeyCard(uint32_t pk) {
  PanelDisplay *d = gHooks.display;
  if (!d) return;
  cardFrame(*d, "Pair Claude");
  d->setCursor(18, 90);
  d->print("Enter this code on");
  d->setCursor(18, 116);
  d->print("your computer:");
  char code[8];
  snprintf(code, sizeof(code), "%03u %03u", (unsigned)(pk / 1000), (unsigned)(pk % 1000));
  d->setFont(&FreeMonoBold18pt7b);
  d->setTextSize(2);
  const int16_t w = (int16_t)(strlen(code) * 21 * 2);
  d->setCursor((d->width() - w) / 2, 200);
  d->print(code);
  d->setTextSize(1);
  d->setFont(&FreeMonoBold12pt7b);
  d->setCursor(18, d->height() - 20);
  d->print(gHooks.deviceName);
  d->flush();
}

void drawPromptCard() {
  PanelDisplay *d = gHooks.display;
  if (!d) return;
  const ClaudeState &s = gProto.state();
  cardFrame(*d, "Claude asks");
  const size_t cols = (size_t)((d->width() - 36) / kCharW);
  std::string tool = "Tool: " + ascii(s.prompt.tool);
  if (s.waiting > 1) tool += " (" + std::to_string(s.waiting) + " waiting)";
  if (tool.size() > cols) tool.resize(cols);
  d->setCursor(18, 82);
  d->print(tool.c_str());

  const int16_t footerTop = d->height() - 42;
  int16_t y = 120;
  const size_t maxLines = (size_t)((footerTop - 8 - y) / kLineH + 1);
  for (const std::string &line : wrap(ascii(s.prompt.hint), cols, maxLines)) {
    d->setCursor(18, y);
    d->print(line.c_str());
    y += kLineH;
  }

  d->fillRect(6, footerTop, d->width() - 12, 36, 1);
  d->setTextColor(0);
  d->setCursor(18, footerTop + 25);
  d->print("KEY allow    BOOT deny");
  d->setTextColor(1);
  d->flush();
}

ClaudeStatus statusNow() {
  ClaudeStatus st;
  st.name = gHooks.deviceName;
  st.sec = gHooks.secure && gHooks.secure();
  st.batKnown = gBattery.sensed && gBattery.present && gBattery.pct >= 0;
  st.batPct = gBattery.pct;
  st.batMv = gBattery.mv;
  st.usb = gBattery.usb || (gBattery.sensed && !gBattery.present);
  st.upS = millis() / 1000;
  st.heap = ESP.getFreeHeap();
  return st;
}

void syncClock() {
  const ClaudeState &s = gProto.state();
  if (s.epoch < 1700000000 || time(nullptr) >= 1700000000) return;
  timeval tv{(time_t)s.epoch, 0};
  settimeofday(&tv, nullptr);
  Serial.println("[claude] clock set from desktop");
}

bool decide(const std::string &id, bool allow) {
  if (id.empty() || !gProto.promptPending() || gProto.state().prompt.id != id) return false;
  const std::string line = ClaudeProto::permissionLine(id, allow);
  if (!gHooks.send || !gHooks.send(line.data(), line.size())) return false;
  gProto.markDecided(id);
  Serial.printf("[claude] %s %s\n", allow ? "allow" : "deny", id.c_str());
  if (gHooks.beep) gHooks.beep(allow ? 1320 : 440, 70);
  if (gCard == Card::Prompt && gCardId == id) closeCard();
  return true;
}

void updateCards() {
  if (gPasskeyNew) {
    gPasskeyNew = false;
    gPairDone = false;
    openCard(Card::Passkey);
    drawPasskeyCard(gPasskey);
  }
  if (gCard == Card::Passkey) {
    if (!gPairDone && millis() - gCardSinceMs < kPasskeyCardMs) return;
    closeCard();
  }
  gPairDone = false;

  // A silent desktop can no longer receive a decision; give the screen back.
  const bool want = gTakeover && gHooks.display && gProto.promptPending() &&
                    gProto.connected(millis());
  if (want) {
    const std::string &id = gProto.state().prompt.id;
    if (gCard == Card::Prompt && gCardId == id) return;
    openCard(Card::Prompt);
    gCardId = id;
    drawPromptCard();
    if (gHooks.beep) gHooks.beep(990, 60);
  } else if (gCard == Card::Prompt) {
    closeCard();
  }
}

}  // namespace

void claudeBuddyBegin(const ClaudeBuddyHooks &hooks) {
  gHooks = hooks;
  if (gInbox) return;
  uint8_t *mem =
      (uint8_t *)heap_caps_malloc(kInboxBytes + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!mem) {
    Serial.println("[claude] inbox alloc failed");
    return;
  }
  gInbox = xStreamBufferCreateStatic(kInboxBytes, 1, mem, &gInboxCtl);
}

void claudeBuddyFeed(const uint8_t *data, size_t n) {
  if (gInbox && data && n) xStreamBufferSend(gInbox, data, n, 0);
}

void claudeBuddyPasskey(uint32_t passkey) {
  if (passkey) {
    gPasskey = passkey;
    gPasskeyNew = true;
  } else {
    gPairDone = true;
  }
}

void claudeBuddyPoll(const OcBattery &battery) {
  gBattery = battery;
  if (gInbox) {
    const ClaudeStatus st = statusNow();
    std::string out;
    uint8_t buf[512];
    size_t got;
    while ((got = xStreamBufferReceive(gInbox, buf, sizeof(buf), 0)) > 0) {
      gProto.feed((const char *)buf, got, millis(), st, out);
    }
    if (!out.empty() && gHooks.send) gHooks.send(out.data(), out.size());
  }
  if (gProto.takeUnpair() && gHooks.forgetBonds) gHooks.forgetBonds();
  if (gProto.takeTime()) syncClock();
  updateCards();
}

bool claudeBuddyOwnsScreen() { return gCard != Card::None; }

bool claudeBuddyButton(bool allow) {
  if (gCard == Card::Passkey) return true;
  if (gCard != Card::Prompt) return false;
  const std::string id = gCardId;
  if (!decide(id, allow) && gHooks.beep) gHooks.beep(220, 150);
  return true;
}

void claudeBuddySetTakeover(bool on) {
  gTakeover = on;
  if (!on && gCard == Card::Prompt) closeCard();
}

bool claudeBuddyConnected() { return gProto.connected(millis()); }

void claudeBuddySummary(char *out, size_t n) {
  if (!out || !n) return;
  const ClaudeState &s = gProto.state();
  if (!s.seen) {
    out[0] = 0;
  } else if (!claudeBuddyConnected()) {
    snprintf(out, n, "Claude offline");
  } else {
    snprintf(out, n, "Claude %d run %d wait", s.running, s.waiting);
  }
}

const ClaudeState *claudeBuddyState() { return &gProto.state(); }

bool claudeBuddyPromptPending() { return gProto.promptPending(); }

bool claudeBuddyDecide(const char *id, bool allow) {
  return id && decide(std::string(id), allow);
}

#else  // !OC_HAS_BLE

void claudeBuddyBegin(const ClaudeBuddyHooks &hooks) { (void)hooks; }
void claudeBuddyFeed(const uint8_t *data, size_t n) {
  (void)data;
  (void)n;
}
void claudeBuddyPasskey(uint32_t passkey) { (void)passkey; }
void claudeBuddyPoll(const OcBattery &battery) { (void)battery; }
bool claudeBuddyOwnsScreen() { return false; }
bool claudeBuddyButton(bool allow) {
  (void)allow;
  return false;
}
void claudeBuddySetTakeover(bool on) { (void)on; }
bool claudeBuddyConnected() { return false; }
void claudeBuddySummary(char *out, size_t n) {
  if (out && n) out[0] = 0;
}
const ClaudeState *claudeBuddyState() { return nullptr; }
bool claudeBuddyPromptPending() { return false; }
bool claudeBuddyDecide(const char *id, bool allow) {
  (void)id;
  (void)allow;
  return false;
}

#endif
