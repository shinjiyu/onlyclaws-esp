#include "st7305_rlcd.h"

#include <string.h>

#include "board_pins.h"

namespace {
constexpr uint32_t kSpiHz = 20000000;
}

St7305Rlcd::St7305Rlcd() : Adafruit_GFX(LCD_WIDTH, LCD_HEIGHT) {}

bool St7305Rlcd::begin(SPIClass *spi) {
  spi_ = spi ? spi : &SPI;
  bytes_ = (size_t)LCD_WIDTH * LCD_HEIGHT / 8;
  fb_ = (uint8_t *)heap_caps_malloc(bytes_, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!fb_) fb_ = (uint8_t *)malloc(bytes_);
  hw_ = (uint8_t *)heap_caps_malloc(bytes_, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!hw_) hw_ = (uint8_t *)malloc(bytes_);
  if (!fb_ || !hw_) {
    Serial.println("[lcd] buffer alloc failed");
    return false;
  }
  memset(fb_, 0x00, bytes_);

  pinMode(PIN_LCD_CS, OUTPUT);
  pinMode(PIN_LCD_DC, OUTPUT);
  pinMode(PIN_LCD_RST, OUTPUT);
  digitalWrite(PIN_LCD_CS, HIGH);
  digitalWrite(PIN_LCD_DC, LOW);
  digitalWrite(PIN_LCD_RST, HIGH);

  spi_->begin(PIN_LCD_SCLK, -1, PIN_LCD_MOSI, -1);
  hwReset();
  initRegs();
  return true;
}

void St7305Rlcd::hwReset() {
  digitalWrite(PIN_LCD_RST, HIGH);
  delay(50);
  digitalWrite(PIN_LCD_RST, LOW);
  delay(20);
  digitalWrite(PIN_LCD_RST, HIGH);
  delay(50);
}

void St7305Rlcd::writeCmd(uint8_t cmd) {
  digitalWrite(PIN_LCD_CS, LOW);
  digitalWrite(PIN_LCD_DC, LOW);
  spi_->beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  spi_->write(cmd);
  spi_->endTransaction();
  digitalWrite(PIN_LCD_CS, HIGH);
}

void St7305Rlcd::writeData(uint8_t data) {
  digitalWrite(PIN_LCD_CS, LOW);
  digitalWrite(PIN_LCD_DC, HIGH);
  spi_->beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  spi_->write(data);
  spi_->endTransaction();
  digitalWrite(PIN_LCD_CS, HIGH);
}

void St7305Rlcd::writeData(const uint8_t *data, size_t n) {
  digitalWrite(PIN_LCD_CS, LOW);
  digitalWrite(PIN_LCD_DC, HIGH);
  spi_->beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
  spi_->writeBytes(const_cast<uint8_t *>(data), n);
  spi_->endTransaction();
  digitalWrite(PIN_LCD_CS, HIGH);
}

void St7305Rlcd::initRegs() {
  writeCmd(0xD6);
  writeData(0x17);
  writeData(0x02);
  writeCmd(0xD1);
  writeData(0x01);
  writeCmd(0xC0);
  writeData(0x11);
  writeData(0x04);
  writeCmd(0xC1);
  {
    const uint8_t d[] = {0x41, 0x41, 0x41, 0x41};
    writeData(d, sizeof(d));
  }
  writeCmd(0xC2);
  {
    const uint8_t d[] = {0x19, 0x19, 0x19, 0x19};
    writeData(d, sizeof(d));
  }
  writeCmd(0xC4);
  {
    const uint8_t d[] = {0x41, 0x41, 0x41, 0x41};
    writeData(d, sizeof(d));
  }
  writeCmd(0xC5);
  {
    const uint8_t d[] = {0x19, 0x19, 0x19, 0x19};
    writeData(d, sizeof(d));
  }
  writeCmd(0xD8);
  writeData(0xA6);
  writeData(0xE9);
  writeCmd(0xB2);
  writeData(0x05);
  writeCmd(0xB3);
  {
    const uint8_t d[] = {0xE5, 0xF6, 0x05, 0x46, 0x77, 0x77, 0x77, 0x77, 0x76, 0x45};
    writeData(d, sizeof(d));
  }
  writeCmd(0xB4);
  {
    const uint8_t d[] = {0x05, 0x46, 0x77, 0x77, 0x77, 0x77, 0x76, 0x45};
    writeData(d, sizeof(d));
  }
  writeCmd(0x62);
  {
    const uint8_t d[] = {0x32, 0x03, 0x1F};
    writeData(d, sizeof(d));
  }
  writeCmd(0xB7);
  writeData(0x13);
  writeCmd(0xB0);
  writeData(0x64);
  writeCmd(0x11);
  delay(200);
  writeCmd(0xC9);
  writeData(0x00);
  writeCmd(0x36);
  writeData(0x48);
  writeCmd(0x3A);
  writeData(0x11);
  writeCmd(0xB9);
  writeData(0x20);
  writeCmd(0xB8);
  writeData(0x29);
  writeCmd(0x20);
  writeCmd(0x2A);
  {
    const uint8_t d[] = {0x12, 0x2A};
    writeData(d, sizeof(d));
  }
  writeCmd(0x2B);
  {
    const uint8_t d[] = {0x00, 0xC7};
    writeData(d, sizeof(d));
  }
  writeCmd(0x35);
  writeData(0x00);
  writeCmd(0xD0);
  writeData(0xFF);
  writeCmd(0x38);
  writeCmd(0x29);
}

void St7305Rlcd::drawPixel(int16_t x, int16_t y, uint16_t color) {
  if (!fb_ || x < 0 || y < 0 || x >= LCD_WIDTH || y >= LCD_HEIGHT) return;
  const size_t i = ((size_t)y * LCD_WIDTH + (size_t)x) / 8;
  const uint8_t mask = (uint8_t)(0x80 >> (x & 7));
  if (color) {
    fb_[i] |= mask;
  } else {
    fb_[i] &= (uint8_t)~mask;
  }
}

void St7305Rlcd::fillScreen(uint16_t color) {
  if (!fb_) return;
  memset(fb_, color ? 0xFF : 0x00, bytes_);
}

void St7305Rlcd::invertDisplay(bool i) { writeCmd(i ? 0x21 : 0x20); }

bool St7305Rlcd::showGxBitmap(const uint8_t *gx, size_t n) {
  if (!fb_ || !gx || n != bytes_) return false;
  // Gx: 1=white,0=black  →  our canvas: 1=ink,0=background
  for (size_t i = 0; i < bytes_; ++i) fb_[i] = (uint8_t)~gx[i];
  display();
  return true;
}

void St7305Rlcd::display() {
  if (!fb_ || !hw_) return;
  memset(hw_, 0, bytes_);

  for (int y = 0; y < LCD_HEIGHT; ++y) {
    for (int x = 0; x < LCD_WIDTH; ++x) {
      const size_t i = ((size_t)y * LCD_WIDTH + (size_t)x) / 8;
      const uint8_t mask = (uint8_t)(0x80 >> (x & 7));
      if (!(fb_[i] & mask)) continue;

      const int inv_y = LCD_HEIGHT - 1 - y;
      const int byte_x = x / 2;
      const int block_y = inv_y / 4;
      const int index = byte_x * 75 + block_y;
      const int local_x = x % 2;
      const int local_y = inv_y % 4;
      const int bit = 7 - (local_y * 2 + local_x);
      hw_[index] |= (uint8_t)(1 << bit);
    }
  }

  writeCmd(0x2A);
  writeData(0x12);
  writeData(0x2A);
  writeCmd(0x2B);
  writeData(0x00);
  writeData(0xC7);
  writeCmd(0x2C);
  writeData(hw_, bytes_);
}
