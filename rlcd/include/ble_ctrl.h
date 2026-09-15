#pragma once

#include <Arduino.h>

// BLE peripheral for phone D-pad (Web Bluetooth / nRF Connect).
// Service  a1b20001-c3d4-4e5f-8091-23456789abcd
// Char DIR a1b20002-...  write/write-without-response  payload: "U"|"D"|"L"|"R"
// Char RST a1b20003-...  write  any byte => restart flag

void bleCtrlBegin(const char *advName);
bool bleCtrlConnected();
// Sticky last direction ('U','D','L','R') or 0 if never set.
char bleCtrlDir();
bool bleCtrlTakeRestart();  // true once if phone asked to restart
