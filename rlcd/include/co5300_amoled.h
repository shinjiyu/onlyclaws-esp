#pragma once

#include "panel_display.h"

#ifdef BOARD_PANEL_AMOLED

#include <esp_heap_caps.h>

// Stub PanelDisplay for Waveshare ESP32-S3-Touch-AMOLED-1.75(C).
// Allocates a 1bpp PSRAM canvas so existing gfx.* / cloud paths compile and boot.
// CO5300 QSPI flush is not implemented yet — screen stays dark until the real driver.
class Co5300AmoledStub : public PanelDisplay {
 public:
  Co5300AmoledStub();
  bool begin() override;
  size_t frameBytes() const override { return bytes_; }
  bool showGxBitmap(const uint8_t *gx, size_t n) override;
  void drawPixel(int16_t x, int16_t y, uint16_t color) override;
  uint8_t *canvas() override { return fb_; }
  bool slowPanel() const override { return false; }
  const char *panelName() const override { return "CO5300-AMOLED-1.75-stub"; }

 protected:
  void flushPanel() override;

 private:
  uint8_t *fb_ = nullptr;
  size_t bytes_ = 0;
  size_t stride_ = 0;  // bytes per row, (W+7)/8
};

#endif
