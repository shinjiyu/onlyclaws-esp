#pragma once

#include <Arduino.h>

// Local wake phrase: say clearly 「嘿小爪」 (3 beats).
bool wakeWordBegin();
void wakeWordPause();
void wakeWordResume();
bool wakeWordConsumeTrigger();  // true once per detection
bool wakeWordIsListening();
const char *wakeWordPhrase();
bool wakeWordLockI2S(uint32_t ms = 1000);
void wakeWordUnlockI2S();
