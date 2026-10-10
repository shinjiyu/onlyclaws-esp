#pragma once

#include <Arduino.h>

#include "claude_proto.h"
#include "oc_battery.h"

class PanelDisplay;

// Claude desktop Hardware Buddy plugin (OC_HAS_BLE builds). Knows the JSON
// protocol and the prompt card; the BLE transport is wired in by main.cpp.
// Stubs (no-ops, nullptr state) when BLE is compiled out.

struct ClaudeBuddyHooks {
  PanelDisplay *display = nullptr;
  bool (*send)(const char *data, size_t n) = nullptr;
  bool (*secure)() = nullptr;
  void (*forgetBonds)() = nullptr;
  bool (*beep)(uint16_t hz, uint16_t ms) = nullptr;
  const char *deviceName = "";
};

void claudeBuddyBegin(const ClaudeBuddyHooks &hooks);

// BLE host task side: raw UART bytes, and pairing passkey (0 = finished).
void claudeBuddyFeed(const uint8_t *data, size_t n);
void claudeBuddyPasskey(uint32_t passkey);

// Main loop side.
void claudeBuddyPoll(const OcBattery &battery);
// A card (passkey or permission prompt) owns the panel: pause Lua, skip HUD.
bool claudeBuddyOwnsScreen();
// KEY = allow, BOOT = deny. True if a card consumed the press.
bool claudeBuddyButton(bool allow);
// Framework prompt card on/off (Lua claude.takeover). On by default.
void claudeBuddySetTakeover(bool on);
bool claudeBuddyConnected();
// One HUD line, "" if Claude never connected.
void claudeBuddySummary(char *out, size_t n);

// Lua surface.
const ClaudeState *claudeBuddyState();
bool claudeBuddyPromptPending();
bool claudeBuddyDecide(const char *id, bool allow);
