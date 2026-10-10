#pragma once

#include "panel_display.h"

// No physical panel — satisfies PanelDisplay for arm / headless products.
class HeadlessPanel : public PanelDisplay {
 public:
  HeadlessPanel() : PanelDisplay(8, 8) {}
  bool begin() override { return true; }
  void flush() override {}
  void drawPixel(int16_t, int16_t, uint16_t) override {}
  size_t frameBytes() const override { return 8; }
  bool showGxBitmap(const uint8_t *, size_t) override { return false; }
  bool slowPanel() const override { return true; }
  const char *panelName() const override { return "headless"; }
};
