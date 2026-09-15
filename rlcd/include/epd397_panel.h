#pragma once

#include "panel_display.h"

#ifdef BOARD_PANEL_EPAPER

#include <GxEPD2_BW.h>
#include <SPI.h>

// Waveshare ESP32-S3-ePaper-3.97 — GDEM0397T81 800x480.
class Epd397Panel : public PanelDisplay {
 public:
  using Driver = GxEPD2_397_GDEM0397T81;
  // Small page buffer — we draw via writeImage from our own SPIRAM canvas.
  static constexpr int16_t kPageH = 40;

  Epd397Panel();
  bool begin() override;
  void drawPixel(int16_t x, int16_t y, uint16_t color) override;
  void fillScreen(uint16_t color) override;
  void flush() override;
  bool showGxBitmap(const uint8_t *gx, size_t n) override;
  size_t frameBytes() const override { return bytes_; }
  bool slowPanel() const override { return true; }
  const char *panelName() const override { return "GxEPD2-397"; }

 private:
  GxEPD2_BW<Driver, kPageH> epd_;
  uint8_t *fb_ = nullptr;  // 1=ink
  size_t bytes_ = 0;
  uint8_t flushCount_ = 0;
};

#endif
