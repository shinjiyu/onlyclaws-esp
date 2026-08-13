#include "character_ui.h"

#include <Fonts/FreeMonoBold9pt7b.h>
#include <math.h>
#include <string.h>

namespace {
constexpr int kCharCx = 110;
constexpr int kCharCy = 210;
constexpr int kBubbleX = 160;
constexpr int kBubbleY = 18;
constexpr int kBubbleW = 220;
constexpr int kBubbleH = 160;
constexpr int kBubblePad = 8;
constexpr uint32_t kFrameMs = 700;

uint32_t startMs = 0;
uint32_t lastFrameMs = 0;
uint32_t nextBlinkMs = 0;
uint32_t waveUntilMs = 0;
uint32_t reactUntilMs = 0;
uint32_t dialogUntilMs = 0;
bool eyesClosed = false;
bool dirty = true;
CharacterVoiceUi voiceUi = CHAR_VOICE_IDLE;

char dialogTitle[48] = {};
uint8_t *dialogGx = nullptr;
size_t dialogGxBytes = 0;
CharacterHud hud{};

bool gxPixelInk(const uint8_t *gx, int x, int y) {
  // GxEPD style MONO_HLSB: 1=white 0=black → ink when black
  if (x < 0 || y < 0 || x >= LCD_WIDTH || y >= LCD_HEIGHT) return false;
  const size_t i = ((size_t)y * LCD_WIDTH + (size_t)x) / 8;
  const uint8_t mask = (uint8_t)(0x80 >> (x & 7));
  return (gx[i] & mask) == 0;
}

void fillRoundRect(Adafruit_GFX &gfx, int x, int y, int w, int h, int r, uint16_t c) {
  gfx.fillRoundRect(x, y, w, h, r, c);
}

void drawBubbleChrome(Adafruit_GFX &gfx) {
  // white fill + black outline
  fillRoundRect(gfx, kBubbleX, kBubbleY, kBubbleW, kBubbleH, 12, 0);
  gfx.drawRoundRect(kBubbleX, kBubbleY, kBubbleW, kBubbleH, 12, 1);
  gfx.drawRoundRect(kBubbleX + 1, kBubbleY + 1, kBubbleW - 2, kBubbleH - 2, 11, 1);
  // pointer toward character
  const int tipX = kCharCx + 40;
  const int tipY = kCharCy - 70;
  gfx.fillTriangle(kBubbleX + 24, kBubbleY + kBubbleH - 2, kBubbleX + 48,
                   kBubbleY + kBubbleH - 2, tipX, tipY, 0);
  gfx.drawTriangle(kBubbleX + 24, kBubbleY + kBubbleH - 2, kBubbleX + 48,
                   kBubbleY + kBubbleH - 2, tipX, tipY, 1);
}

void blitGxIntoBubble(Adafruit_GFX &gfx, const uint8_t *gx) {
  const int titleH = dialogTitle[0] ? 18 : 0;
  const int dstX = kBubbleX + kBubblePad;
  const int dstY = kBubbleY + kBubblePad + titleH;
  const int dstW = kBubbleW - 2 * kBubblePad;
  const int dstH = kBubbleH - 2 * kBubblePad - titleH - 4;
  if (dstW <= 0 || dstH <= 0) return;

  // Coarse nearest-neighbor (step 2) — readable enough, much faster on MCU.
  for (int dy = 0; dy < dstH; dy += 2) {
    const int sy = dy * LCD_HEIGHT / dstH;
    for (int dx = 0; dx < dstW; dx += 2) {
      const int sx = dx * LCD_WIDTH / dstW;
      if (gxPixelInk(gx, sx, sy)) {
        gfx.fillRect(dstX + dx, dstY + dy, 2, 2, 1);
      }
    }
  }
}

void drawCharacter(Adafruit_GFX &gfx, uint32_t nowMs) {
  const float t = (nowMs - startMs) / 1000.0f;
  const float breath = sinf(t * 2.0f * 3.1415926f / 3.0f);
  const int bodyScale = (int)(breath * 3.0f);  // -3..3
  const int sway = (int)(sinf(t * 0.7f) * 4.0f);

  const bool waving = nowMs < waveUntilMs;
  const bool reacting = nowMs < reactUntilMs;
  const int nod = reacting ? (int)(sinf((reactUntilMs - nowMs) / 180.0f) * 6.0f) : 0;

  const int cx = kCharCx + sway;
  const int cy = kCharCy + nod;
  const int headR = 28;
  const int bodyW = 46;
  const int bodyH = 58 + bodyScale;

  // shadow
  gfx.fillEllipse(cx, cy + 78, 36, 8, 1);

  // legs
  gfx.drawLine(cx - 12, cy + 40, cx - 16, cy + 72, 1);
  gfx.drawLine(cx + 12, cy + 40, cx + 16, cy + 72, 1);
  gfx.fillCircle(cx - 16, cy + 74, 5, 1);
  gfx.fillCircle(cx + 16, cy + 74, 5, 1);

  // body
  gfx.fillRoundRect(cx - bodyW / 2, cy - 10, bodyW, bodyH, 14, 1);
  gfx.fillRoundRect(cx - bodyW / 2 + 3, cy - 7, bodyW - 6, bodyH - 6, 12, 0);
  gfx.drawRoundRect(cx - bodyW / 2 + 3, cy - 7, bodyW - 6, bodyH - 6, 12, 1);

  // arms
  if (waving) {
    const float phase = (waveUntilMs - nowMs) / 80.0f;
    const int wx = cx + 28 + (int)(sinf(phase) * 10.0f);
    const int wy = cy - 20 - (int)(fabsf(sinf(phase)) * 18.0f);
    gfx.drawLine(cx + 22, cy + 8, wx, wy, 1);
    gfx.fillCircle(wx, wy, 6, 1);
    gfx.drawLine(cx - 22, cy + 8, cx - 34, cy + 28, 1);
    gfx.fillCircle(cx - 34, cy + 30, 5, 1);
  } else {
    gfx.drawLine(cx - 22, cy + 8, cx - 34, cy + 30, 1);
    gfx.drawLine(cx + 22, cy + 8, cx + 34, cy + 30, 1);
    gfx.fillCircle(cx - 34, cy + 32, 5, 1);
    gfx.fillCircle(cx + 34, cy + 32, 5, 1);
  }

  // head
  const int hy = cy - 42 + nod / 2;
  gfx.fillCircle(cx, hy, headR, 1);
  gfx.fillCircle(cx, hy, headR - 3, 0);
  gfx.drawCircle(cx, hy, headR - 3, 1);

  // eyes
  if (eyesClosed) {
    gfx.drawLine(cx - 10, hy - 2, cx - 4, hy - 2, 1);
    gfx.drawLine(cx + 4, hy - 2, cx + 10, hy - 2, 1);
  } else {
    gfx.fillCircle(cx - 8, hy - 2, 3, 1);
    gfx.fillCircle(cx + 8, hy - 2, 3, 1);
  }

  // smile / recording mouth / surprise
  if (voiceUi == CHAR_VOICE_RECORDING) {
    gfx.fillCircle(cx, hy + 11, 7, 1);
    gfx.fillCircle(cx, hy + 11, 4, 0);
  } else if (reacting || voiceUi == CHAR_VOICE_DONE) {
    gfx.drawCircle(cx, hy + 10, 5, 1);
  } else if (voiceUi == CHAR_VOICE_FAIL) {
    gfx.drawLine(cx - 7, hy + 12, cx + 7, hy + 12, 1);
  } else {
    gfx.drawLine(cx - 8, hy + 10, cx, hy + 14, 1);
    gfx.drawLine(cx, hy + 14, cx + 8, hy + 10, 1);
  }

  // Recording sound rings
  if (voiceUi == CHAR_VOICE_RECORDING) {
    const int rings = 1 + ((nowMs / 350) % 3);
    for (int i = 1; i <= rings; ++i) {
      gfx.drawCircle(cx + 34, hy, 6 + i * 5, 1);
    }
  }
}

void drawVoiceBanner(Adafruit_GFX &gfx, uint32_t nowMs) {
  if (voiceUi == CHAR_VOICE_IDLE) return;

  const char *title = "";
  const char *sub = "";
  switch (voiceUi) {
    case CHAR_VOICE_RECORDING:
      title = "REC";
      sub = "Speak now 3s";
      break;
    case CHAR_VOICE_DONE:
      title = "END";
      sub = "Got it";
      break;
    case CHAR_VOICE_UPLOAD:
      title = "SEND";
      sub = "Uploading";
      break;
    case CHAR_VOICE_FAIL:
      title = "MISS";
      sub = "Try again";
      break;
    default:
      return;
  }

  // Full-width top banner
  gfx.fillRect(0, 0, LCD_WIDTH, 44, 1);
  gfx.fillRect(2, 2, LCD_WIDTH - 4, 40, 0);
  gfx.drawRect(2, 2, LCD_WIDTH - 4, 40, 1);

  gfx.setFont(&FreeMonoBold9pt7b);
  gfx.setTextColor(1);
  gfx.setCursor(14, 18);
  if (voiceUi == CHAR_VOICE_RECORDING) {
    // blinking REC dot
    if ((nowMs / 400) & 1) gfx.fillCircle(12, 14, 5, 1);
    else gfx.drawCircle(12, 14, 5, 1);
    gfx.setCursor(24, 18);
  }
  gfx.print(title);
  gfx.setCursor(14, 36);
  gfx.print(sub);

  // Bottom progress for recording (3s bar approximation by time since set — use blink blocks)
  if (voiceUi == CHAR_VOICE_RECORDING) {
    const int blocks = 1 + ((nowMs / 1000) % 3);
    for (int i = 0; i < 3; ++i) {
      const int x = LCD_WIDTH - 70 + i * 18;
      if (i < blocks) gfx.fillRect(x, 14, 14, 14, 1);
      else gfx.drawRect(x, 14, 14, 14, 1);
    }
  }
}

void drawHud(Adafruit_GFX &gfx) {
  gfx.setFont(&FreeMonoBold9pt7b);
  gfx.setTextColor(1);
  gfx.setCursor(8, 16);
  if (hud.ssid && hud.ssid[0]) {
    gfx.print(hud.ssid);
  } else {
    gfx.print("RLCD");
  }

  char line[48];
  if (!isnan(hud.tempC) && !isnan(hud.humidity)) {
    snprintf(line, sizeof(line), "%.1fC  %.0f%%", hud.tempC, hud.humidity);
    gfx.setCursor(8, 34);
    gfx.print(line);
  }

  if (hud.batteryPct >= 0) {
    snprintf(line, sizeof(line), "Bat %d%%", hud.batteryPct);
    gfx.setCursor(8, 52);
    gfx.print(line);
  } else if (!isnan(hud.batteryV)) {
    snprintf(line, sizeof(line), "Bat %.2fV", hud.batteryV);
    gfx.setCursor(8, 52);
    gfx.print(line);
  }

  gfx.setCursor(LCD_WIDTH - 70, LCD_HEIGHT - 10);
  gfx.printf("%ddBm", hud.rssi);
}

void drawDialog(Adafruit_GFX &gfx) {
  drawBubbleChrome(gfx);
  if (dialogTitle[0]) {
    gfx.setFont(&FreeMonoBold9pt7b);
    gfx.setTextColor(1);
    gfx.setCursor(kBubbleX + kBubblePad, kBubbleY + 16);
    // truncate title for width
    char t[40];
    strncpy(t, dialogTitle, sizeof(t) - 1);
    t[sizeof(t) - 1] = 0;
    if (strlen(t) > 18) {
      t[15] = '.';
      t[16] = '.';
      t[17] = '.';
      t[18] = 0;
    }
    gfx.print(t);
  }
  if (dialogGx && dialogGxBytes == (size_t)LCD_WIDTH * LCD_HEIGHT / 8) {
    blitGxIntoBubble(gfx, dialogGx);
  } else if (!dialogTitle[0]) {
    gfx.setFont(&FreeMonoBold9pt7b);
    gfx.setCursor(kBubbleX + 24, kBubbleY + 80);
    gfx.print("(empty)");
  }
}
}  // namespace

void characterBegin() {
  startMs = millis();
  lastFrameMs = 0;
  nextBlinkMs = startMs + 2000;
  waveUntilMs = 0;
  reactUntilMs = 0;
  dialogUntilMs = 0;
  eyesClosed = false;
  voiceUi = CHAR_VOICE_IDLE;
  dirty = true;
  dialogTitle[0] = 0;
  if (dialogGx) {
    free(dialogGx);
    dialogGx = nullptr;
  }
  dialogGxBytes = 0;
}

void characterTick(uint32_t nowMs) {
  if (nowMs >= nextBlinkMs) {
    eyesClosed = !eyesClosed;
    nextBlinkMs = nowMs + (eyesClosed ? 160 : (2000 + (nowMs % 2500)));
    dirty = true;
  }
  if (dialogUntilMs && nowMs >= dialogUntilMs) {
    characterClearDialog();
  }
  // Restore smile when surprise window ends.
  static bool wasReacting = false;
  const bool reacting = reactUntilMs && nowMs < reactUntilMs;
  if (wasReacting && !reacting) {
    reactUntilMs = 0;
    dirty = true;
  }
  wasReacting = reacting;

  if ((nowMs - lastFrameMs) >= kFrameMs) {
    dirty = true;
  }
}

void characterWave() {
  waveUntilMs = millis() + 1600;
  dirty = true;
}

void characterReact() {
  reactUntilMs = millis() + 900;
  dirty = true;
}

void characterClearReact() {
  reactUntilMs = 0;
  dirty = true;
}

void characterSetVoiceUi(CharacterVoiceUi mode) {
  voiceUi = mode;
  if (mode == CHAR_VOICE_RECORDING) {
    reactUntilMs = 0;
  }
  dirty = true;
}

CharacterVoiceUi characterVoiceUi() { return voiceUi; }

void characterSetDialog(const char *title, const uint8_t *gxBitmap, size_t gxBytes,
                        uint32_t holdMs) {
  if (title) {
    strncpy(dialogTitle, title, sizeof(dialogTitle) - 1);
    dialogTitle[sizeof(dialogTitle) - 1] = 0;
  } else {
    dialogTitle[0] = 0;
  }

  const size_t need = (size_t)LCD_WIDTH * LCD_HEIGHT / 8;
  if (gxBitmap && gxBytes == need) {
    if (!dialogGx) {
      dialogGx = (uint8_t *)heap_caps_malloc(need, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
      if (!dialogGx) dialogGx = (uint8_t *)malloc(need);
    }
    if (dialogGx) {
      memcpy(dialogGx, gxBitmap, need);
      dialogGxBytes = need;
    }
  } else {
    dialogGxBytes = 0;
  }

  dialogUntilMs = millis() + holdMs;
  // Brief nod only — do not leave face stuck in O-mouth.
  characterReact();
  dirty = true;
}

void characterClearDialog() {
  dialogTitle[0] = 0;
  dialogGxBytes = 0;
  dialogUntilMs = 0;
  dirty = true;
}

bool characterHasDialog() { return dialogUntilMs != 0 && millis() < dialogUntilMs; }

void characterSetHud(const CharacterHud &h) {
  hud = h;
  dirty = true;
}

bool characterNeedsRedraw(uint32_t nowMs) {
  (void)nowMs;
  return dirty;
}

void characterRender(Adafruit_GFX &gfx) {
  gfx.fillScreen(0);
  // soft floor line
  gfx.drawFastHLine(20, LCD_HEIGHT - 28, LCD_WIDTH - 40, 1);
  const uint32_t now = millis();
  drawCharacter(gfx, now);
  if (voiceUi == CHAR_VOICE_IDLE &&
      (characterHasDialog() || dialogGxBytes || dialogTitle[0])) {
    drawDialog(gfx);
  }
  drawVoiceBanner(gfx, now);
  if (voiceUi == CHAR_VOICE_IDLE) {
    drawHud(gfx);
  }
  lastFrameMs = now;
  dirty = false;
}
