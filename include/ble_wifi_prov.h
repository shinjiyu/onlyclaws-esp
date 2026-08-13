#pragma once

#include <Arduino.h>

// Blocks until credentials are received (or timeoutMs==0 forever).
// On success, saves to NVS and returns true.
bool bleWifiProvision(uint32_t timeoutMs = 0);

// Non-blocking helpers if needed later.
void bleWifiProvStop();
bool bleWifiProvGotCreds();
