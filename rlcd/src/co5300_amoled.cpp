#include "co5300_amoled.h"

#include <string.h>

#include "board_pins.h"

#ifdef BOARD_PANEL_AMOLED

Co5300AmoledStub::Co5300AmoledStub() : PanelDisplay(LCD_WIDTH, LCD_HEIGHT) {}

bool Co5300AmoledStub::begin() {
  stride_ = (size_t)(LCD_WIDTH + 7) / 8;
  bytes_ = stride_ * (size_t)LCD_HEIGHT;
  fb_ = (uint8_t *)heap_caps_malloc(bytes_, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!fb_) fb_ = (uint8_t *)malloc(bytes_);
  if (!fb_) {
    Serial.println("[amoled] buffer alloc failed");
    return false;
  }
  memset(fb_, 0x00, bytes_);
  // Hold panel reset high; real QSPI init comes with the CO5300 driver.
  if (PIN_LCD_RST >= 0) {
    pinMode(PIN_LCD_RST, OUTPUT);
    digitalWrite(PIN_LCD_RST, HIGH);
  }
  Serial.printf("[amoled] stub %dx%d stride=%u bytes=%u (no QSPI yet)\n", LCD_WIDTH,
                LCD_HEIGHT, (unsigned)stride_, (unsigned)bytes_);
  return true;
}

void Co5300AmoledStub::drawPixel(int16_t x, int16_t y, uint16_t color) {
  if (!fb_ || x < 0 || y < 0 || x >= LCD_WIDTH || y >= LCD_HEIGHT) return;
  // Circular active area — corners of the square canvas are off-glass.
  const int32_t cx = LCD_WIDTH / 2;
  const int32_t cy = LCD_HEIGHT / 2;
  const int32_t dx = (int32_t)x - cx;
  const int32_t dy = (int32_t)y - cy;
  if (dx * dx + dy * dy > (int32_t)AMOLED_SAFE_R * (int32_t)AMOLED_SAFE_R) return;

  uint8_t *row = fb_ + (size_t)y * stride_;
  const uint8_t bit = (uint8_t)(0x80 >> (x & 7));
  if (color) row[x >> 3] |= bit;
  else row[x >> 3] &= (uint8_t)~bit;
}

bool Co5300AmoledStub::showGxBitmap(const uint8_t *gx, size_t n) {
  if (!gx || n < bytes_ || !fb_) return false;
  memcpy(fb_, gx, bytes_);
  flush();
  return true;
}

void Co5300AmoledStub::flushPanel() {
  // Hardware path not wired. Canvas is ready for the future QSPI blit.
}

#endif
