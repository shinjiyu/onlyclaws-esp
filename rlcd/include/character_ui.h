#pragma once

#include <Arduino.h>
#include <Adafruit_GFX.h>

#include "board_pins.h"

struct CharacterHud {
  float tempC = NAN;
  float humidity = NAN;
  float batteryV = NAN;
  int batteryPct = -1;
  int rssi = 0;
  const char *ssid = "";
};

enum CharacterVoiceUi : uint8_t {
  CHAR_VOICE_IDLE = 0,
  CHAR_VOICE_RECORDING,  // 正在录音
  CHAR_VOICE_DONE,       // 录音结束
  CHAR_VOICE_UPLOAD,     // 上传中
  CHAR_VOICE_FAIL,       // 失败/没听清
};

void characterBegin();
void characterTick(uint32_t nowMs);
void characterWave();
void characterReact();
void characterClearReact();
void characterSetVoiceUi(CharacterVoiceUi mode);
CharacterVoiceUi characterVoiceUi();
void characterSetDialog(const char *title, const uint8_t *gxBitmap, size_t gxBytes,
                        uint32_t holdMs = 60000);
void characterClearDialog();
bool characterHasDialog();
void characterSetHud(const CharacterHud &hud);
void characterRender(Adafruit_GFX &gfx);
bool characterNeedsRedraw(uint32_t nowMs);
