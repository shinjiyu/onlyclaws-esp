#pragma once

#include <Adafruit_GFX.h>
#include <Arduino.h>

// Panel-agnostic 1bpp drawing surface used by the Lua runtime.
// Color convention: 1 = ink (dark), 0 = background.
class PanelDisplay : public Adafruit_GFX {
 public:
  PanelDisplay(int16_t w, int16_t h) : Adafruit_GFX(w, h) {}
  ~PanelDisplay() override = default;

  virtual bool begin() = 0;
  virtual void flush() = 0;
  virtual size_t frameBytes() const = 0;
  virtual bool showGxBitmap(const uint8_t *gx, size_t n) = 0;

  // e-ink / slow panels: demos should lengthen loop ticks.
  virtual bool slowPanel() const { return false; }
  virtual const char *panelName() const { return "panel"; }
};
