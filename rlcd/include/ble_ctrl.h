#pragma once

#include <Arduino.h>

// BLE peripheral, advertised as Claude-OC-XXXX.
//
// D-pad (Web Bluetooth / nRF Connect), not advertised, found in GATT:
//   Service  a1b20001-c3d4-4e5f-8091-23456789abcd
//   Char DIR a1b20002-...  write/write-without-response  payload: "U"|"D"|"L"|"R"
//   Char RST a1b20003-...  write  any byte => restart flag
//
// Nordic UART (advertised), raw byte transport for Claude Hardware Buddy:
//   Service 6e400001-b5a3-f393-e0a9-e50e24dcca9e
//   RX      6e400002-...  central writes
//   TX      6e400003-...  device notifies
// UART data is only delivered on an encrypted, authenticated link; the device
// requests LE Secure pairing (DisplayOnly passkey) when the central subscribes.

void bleCtrlBegin(const char *advName = nullptr);
bool bleCtrlConnected();
const char *bleCtrlName();  // "" before bleCtrlBegin
// Sticky last direction ('U','D','L','R') or 0 if never set.
char bleCtrlDir();
bool bleCtrlTakeRestart();  // true once if phone asked to restart

// Called from the BLE host task. Keep handlers short and non-blocking.
using BleUartRxFn = void (*)(const uint8_t *data, size_t n);
// passkey != 0: show it; passkey == 0: pairing finished or link dropped.
using BlePairingFn = void (*)(uint32_t passkey);
void bleCtrlSetUartRx(BleUartRxFn fn);
void bleCtrlSetPairing(BlePairingFn fn);
// Notify on TX, chunked to the peer MTU. False if no UART peer.
bool bleCtrlUartSend(const char *data, size_t n);
bool bleCtrlUartSecure();
void bleCtrlForgetBonds();
