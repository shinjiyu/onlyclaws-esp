#include "st7789_panel.h"

#include <string.h>

#include "board_pins.h"

#ifdef BOARD_PANEL_ST7789

namespace {
constexpr uint32_t kSpiHz = 40000000;
constexpr uint16_t kInk = 0x0000;    // black
constexpr uint16_t kPaper = 0xFFFF;  // white
}

St7789Panel::St7789Panel() : PanelDisplay(LCD_WIDTH, LCD_HEIGHT) {}

bool St7789Panel::begin() {
  bytes_ = (size_t)LCD_WIDTH * (size_t)LCD_HEIGHT / 8;
  fb_ = (uint8_t *)malloc(bytes_);
  if (!fb_) {
    Serial.println("[st7789] buffer alloc failed");
    return false;
  }
  memset(fb_, 0x00, bytes_);

  if (PIN_LCD_BL >= 0) {
    pinMode(PIN_LCD_BL, OUTPUT);
    digitalWrite(PIN_LCD_BL, HIGH);
  }
  if (PIN_LCD_CS >= 0) {
    pinMode(PIN_LCD_CS, OUTPUT);
    digitalWrite(PIN_LCD_CS, HIGH);
  }
  pinMode(PIN_LCD_DC, OUTPUT);
  digitalWrite(PIN_LCD_DC, LOW);
  if (PIN_LCD_RST >= 0) {
    pinMode(PIN_LCD_RST, OUTPUT);
    digitalWrite(PIN_LCD_RST, HIGH);
  }

  spi_ = &SPI;
  spi_->begin(PIN_LCD_SCLK, -1, PIN_LCD_MOSI, -1);
  hwReset();
  initRegs();
  Serial.printf("[st7789] %dx%d ready heap=%u\n", LCD_WIDTH, LCD_HEIGHT,
                (unsigned)ESP.getFreeHeap());
  flush();
  return true;
}

void St7789Panel::hwReset() {
  if (PIN_LCD_RST < 0) {
    // Soft reset only (Passport RST tied high).
    writeCmd(0x01);
    delay(120);
    return;
  }
  digitalWrite(PIN_LCD_RST, HIGH);
  delay(20);
  digitalWrite(PIN_LCD_RST, LOW);
  delay(20);
  digitalWrite(PIN_LCD_RST, HIGH);
  delay(120);
}

void St7789Panel::writeCmd(uint8_t cmd) {
  digitalWrite(PIN_LCD_DC, LOW);
  if (PIN_LCD_CS >= 0) digitalWrite(PIN_LCD_CS, LOW);
  spi_->beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  spi_->transfer(cmd);
  spi_->endTransaction();
  if (PIN_LCD_CS >= 0) digitalWrite(PIN_LCD_CS, HIGH);
}

void St7789Panel::writeData(uint8_t data) {
  digitalWrite(PIN_LCD_DC, HIGH);
  if (PIN_LCD_CS >= 0) digitalWrite(PIN_LCD_CS, LOW);
  spi_->beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  spi_->transfer(data);
  spi_->endTransaction();
  if (PIN_LCD_CS >= 0) digitalWrite(PIN_LCD_CS, HIGH);
}

void St7789Panel::writeData(const uint8_t *data, size_t n) {
  if (!data || !n) return;
  digitalWrite(PIN_LCD_DC, HIGH);
  if (PIN_LCD_CS >= 0) digitalWrite(PIN_LCD_CS, LOW);
  spi_->beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  spi_->writeBytes(data, n);
  spi_->endTransaction();
  if (PIN_LCD_CS >= 0) digitalWrite(PIN_LCD_CS, HIGH);
}

void St7789Panel::initRegs() {
  writeCmd(0x11);  // sleep out
  delay(120);
  writeCmd(0x36);
  writeData(0x00);  // RGB, portrait
  writeCmd(0x3A);
  writeData(0x55);  // 16-bit
  writeCmd(0xB2);
  {
    const uint8_t d[] = {0x0C, 0x0C, 0x00, 0x33, 0x33};
    writeData(d, sizeof(d));
  }
  writeCmd(0xB7);
  writeData(0x35);
  writeCmd(0xBB);
  writeData(0x19);
  writeCmd(0xC0);
  writeData(0x2C);
  writeCmd(0xC2);
  writeData(0x01);
  writeCmd(0xC3);
  writeData(0x12);
  writeCmd(0xC4);
  writeData(0x20);
  writeCmd(0xC6);
  writeData(0x0F);
  writeCmd(0xD0);
  {
    const uint8_t d[] = {0xA4, 0xA1};
    writeData(d, sizeof(d));
  }
  writeCmd(0xE0);
  {
    const uint8_t d[] = {0xD0, 0x04, 0x0D, 0x11, 0x13, 0x2B, 0x3F, 0x54,
                         0x4C, 0x18, 0x0D, 0x0B, 0x1F, 0x23};
    writeData(d, sizeof(d));
  }
  writeCmd(0xE1);
  {
    const uint8_t d[] = {0xD0, 0x04, 0x0C, 0x11, 0x13, 0x2C, 0x3F, 0x44,
                         0x51, 0x2F, 0x1F, 0x1F, 0x20, 0x23};
    writeData(d, sizeof(d));
  }
  writeCmd(0x21);  // INVON — Passport panel needs invert
  writeCmd(0x29);  // display on
  delay(20);
}

void St7789Panel::setAddrWindow(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1) {
  writeCmd(0x2A);
  uint8_t xa[] = {(uint8_t)(x0 >> 8), (uint8_t)x0, (uint8_t)(x1 >> 8), (uint8_t)x1};
  writeData(xa, sizeof(xa));
  writeCmd(0x2B);
  uint8_t ya[] = {(uint8_t)(y0 >> 8), (uint8_t)y0, (uint8_t)(y1 >> 8), (uint8_t)y1};
  writeData(ya, sizeof(ya));
  writeCmd(0x2C);
}

void St7789Panel::drawPixel(int16_t x, int16_t y, uint16_t color) {
  if (!fb_ || x < 0 || y < 0 || x >= LCD_WIDTH || y >= LCD_HEIGHT) return;
  const size_t i = ((size_t)y * LCD_WIDTH + (size_t)x) / 8;
  const uint8_t mask = (uint8_t)(0x80 >> (x & 7));
  if (color) fb_[i] |= mask;
  else fb_[i] &= (uint8_t)~mask;
}

void St7789Panel::fillScreen(uint16_t color) {
  if (!fb_) return;
  memset(fb_, color ? 0xFF : 0x00, bytes_);
}

bool St7789Panel::showGxBitmap(const uint8_t *gx, size_t n) {
  if (!fb_ || !gx || n != bytes_) return false;
  for (size_t i = 0; i < bytes_; ++i) fb_[i] = (uint8_t)~gx[i];
  flush();
  return true;
}

void St7789Panel::flushPanel() {
  if (!fb_ || !spi_) return;
  setAddrWindow(0, 0, (uint16_t)(LCD_WIDTH - 1), (uint16_t)(LCD_HEIGHT - 1));
  // One scanline of RGB565.
  uint8_t line[LCD_WIDTH * 2];
  digitalWrite(PIN_LCD_DC, HIGH);
  if (PIN_LCD_CS >= 0) digitalWrite(PIN_LCD_CS, LOW);
  spi_->beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  for (int y = 0; y < LCD_HEIGHT; ++y) {
    const uint8_t *row = fb_ + ((size_t)y * LCD_WIDTH) / 8;
    for (int x = 0; x < LCD_WIDTH; ++x) {
      const uint8_t mask = (uint8_t)(0x80 >> (x & 7));
      const bool ink = (row[x >> 3] & mask) != 0;
      const uint16_t c = ink ? kInk : kPaper;
      line[x * 2] = (uint8_t)(c >> 8);
      line[x * 2 + 1] = (uint8_t)c;
    }
    spi_->writeBytes(line, sizeof(line));
  }
  spi_->endTransaction();
  if (PIN_LCD_CS >= 0) digitalWrite(PIN_LCD_CS, HIGH);
}

#endif
