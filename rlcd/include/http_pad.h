#pragma once

#include <Arduino.h>

// Local WiFi HTTP D-pad — works in ANY phone browser on the same LAN.
//   http://<esp-ip>/
void httpPadBegin(uint16_t port = 80);
void httpPadLoop();  // call from loop / dedicated task
