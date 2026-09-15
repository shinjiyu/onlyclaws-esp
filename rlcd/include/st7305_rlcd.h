#pragma once

#include "panel_display.h"

#include <SPI.h>

// ST7305 reflective LCD — Waveshare ESP32-S3-RLCD-4.2 (400x300).
class St7305Rlcd : public PanelDisplay {
 public:
  St7305Rlcd();
  bool begin() override;
  bool begin(SPIClass *spi);
  void drawPixel(int16_t x, int16_t y, uint16_t color) override;
  void fillScreen(uint16_t color) override;
  void flush() override { display(); }
  void display();  // legacy alias
  void invertDisplay(bool i);
  bool showGxBitmap(const uint8_t *gx, size_t n) override;
  size_t frameBytes() const override { return bytes_; }
  const char *panelName() const override { return "ST7305-RLCD-4.2"; }

 private:
  SPIClass *spi_ = nullptr;
  uint8_t *fb_ = nullptr;
  uint8_t *hw_ = nullptr;
  size_t bytes_ = 0;

  void hwReset();
  void writeCmd(uint8_t cmd);
  void writeData(uint8_t data);
  void writeData(const uint8_t *data, size_t n);
  void initRegs();
};
