#pragma once

#include <Adafruit_GFX.h>
#include <Arduino.h>
#include <SPI.h>

// Minimal ST7305 driver for Waveshare ESP32-S3-RLCD-4.2 (400x300 mono).
class St7305Rlcd : public Adafruit_GFX {
 public:
  St7305Rlcd();
  bool begin(SPIClass *spi = &SPI);
  void drawPixel(int16_t x, int16_t y, uint16_t color) override;
  void fillScreen(uint16_t color) override;
  void display();
  void invertDisplay(bool i);
  // Load GxEPD2-style bitmap (1=white) into canvas (1=ink) and refresh.
  bool showGxBitmap(const uint8_t *gx, size_t n);
  size_t frameBytes() const { return bytes_; }

 private:
  SPIClass *spi_ = nullptr;
  uint8_t *fb_ = nullptr;  // MONO_HLSB canvas
  uint8_t *hw_ = nullptr;  // panel native packed buffer
  size_t bytes_ = 0;

  void hwReset();
  void writeCmd(uint8_t cmd);
  void writeData(uint8_t data);
  void writeData(const uint8_t *data, size_t n);
  void initRegs();
};
