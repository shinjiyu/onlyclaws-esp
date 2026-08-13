#pragma once

#include <Arduino.h>

// SoftAP + captive-portal webpage for WiFi provisioning.
// Blocks until credentials are saved (or timeoutMs==0 forever).
bool wifiApProvision(uint32_t timeoutMs = 0);
