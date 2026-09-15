#pragma once

#include <Arduino.h>

// Shared phone D-pad state (LAN HTTP and/or BLE writers).

void padCtrlSetDir(char d);
char padCtrlDir();              // sticky 'U'|'D'|'L'|'R' (default 'R')
void padCtrlRequestRestart();
bool padCtrlTakeRestart();      // one-shot
void padCtrlSetLink(bool on);   // any control channel connected/active
bool padCtrlLinked();
