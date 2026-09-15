#include "epd397_panel.h"

#ifdef BOARD_PANEL_EPAPER

#include <string.h>
#include <esp_heap_caps.h>

#include "board_pins.h"

Epd397Panel::Epd397Panel()
    : PanelDisplay(LCD_WIDTH, LCD_HEIGHT),
      epd_(Driver(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY)) {}

bool Epd397Panel::begin() {
  bytes_ = (size_t)LCD_WIDTH * LCD_HEIGHT / 8;
  fb_ = (uint8_t *)heap_caps_malloc(bytes_, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!fb_) fb_ = (uint8_t *)malloc(bytes_);
  if (!fb_) {
    Serial.println("[epd] buffer alloc failed");
    return false;
  }
  memset(fb_, 0x00, bytes_);

  SPI.begin(PIN_EPD_SCLK, -1, PIN_EPD_MOSI, PIN_EPD_CS);
  epd_.init(115200);
  epd_.epd2.selectFastFullUpdate(true);
  epd_.setRotation(0);
  Serial.printf("[epd] %s %dx%d ready heap=%u psram=%u\n", panelName(), LCD_WIDTH,
                LCD_HEIGHT, ESP.getFreeHeap(), ESP.getFreePsram());
  return true;
}

void Epd397Panel::drawPixel(int16_t x, int16_t y, uint16_t color) {
  if (!fb_ || x < 0 || y < 0 || x >= LCD_WIDTH || y >= LCD_HEIGHT) return;
  const size_t i = ((size_t)y * LCD_WIDTH + (size_t)x) / 8;
  const uint8_t mask = (uint8_t)(0x80 >> (x & 7));
  if (color) {
    fb_[i] |= mask;
  } else {
    fb_[i] &= (uint8_t)~mask;
  }
}

void Epd397Panel::fillScreen(uint16_t color) {
  if (!fb_) return;
  memset(fb_, color ? 0xFF : 0x00, bytes_);
}

bool Epd397Panel::showGxBitmap(const uint8_t *gx, size_t n) {
  if (!fb_ || !gx || n != bytes_) return false;
  // Gx: 1=white → canvas 1=ink
  for (size_t i = 0; i < bytes_; ++i) fb_[i] = (uint8_t)~gx[i];
  flush();
  return true;
}

void Epd397Panel::flush() {
  if (!fb_) return;

  // Mostly partial refresh for demos; full refresh every 6 frames to clear ghosting.
  const bool full = (flushCount_ % 6) == 0;
  flushCount_++;

  // Canvas is 1=ink; GxEPD2 writeImage expects 1=white → invert in-driver.
  epd_.setFullWindow();
  epd_.writeImage(fb_, 0, 0, LCD_WIDTH, LCD_HEIGHT, true /*invert*/);
  epd_.refresh(!full);  // true = partial update mode
  if (full) {
    Serial.printf("[epd] full refresh heap=%u\n", ESP.getFreeHeap());
  }
}

#endif
