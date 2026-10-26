#pragma once

#include "panel_display.h"

#ifdef BOARD_PANEL_ST7789

#include <SPI.h>

// ST7789P3 240×320 — FoloToy AI Passport (ESP32-C3).
// Logical canvas stays 1bpp (Lua gfx.*); flush expands to RGB565 on the wire.
class St7789Panel : public PanelDisplay {
 public:
  St7789Panel();
  bool begin() override;
  void drawPixel(int16_t x, int16_t y, uint16_t color) override;
  void fillScreen(uint16_t color) override;
  bool showGxBitmap(const uint8_t *gx, size_t n) override;
  size_t frameBytes() const override { return bytes_; }
  uint8_t *canvas() override { return fb_; }
  bool slowPanel() const override { return false; }
  const char *panelName() const override { return "ST7789-Folo-Passport"; }

 protected:
  void flushPanel() override;

 private:
  SPIClass *spi_ = nullptr;
  uint8_t *fb_ = nullptr;
  size_t bytes_ = 0;

  void hwReset();
  void writeCmd(uint8_t cmd);
  void writeData(uint8_t data);
  void writeData(const uint8_t *data, size_t n);
  void initRegs();
  void setAddrWindow(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1);
};

#endif
