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

  // Sprite blit, Gx MONO_HLSB (1=white, 0=black, MSB left). Width must be a
  // multiple of 8. Does not flush; pixels outside the panel are clipped.
  bool blitGx(int16_t x, int16_t y, int16_t w, int16_t h, const uint8_t *gx, size_t n) {
    if (!gx || w < 8 || h < 1 || (w & 7) != 0) return false;
    const size_t stride = (size_t)w / 8;
    const size_t need = stride * (size_t)h;
    if (n < need) return false;
    for (int16_t row = 0; row < h; ++row) {
      const uint8_t *src = gx + (size_t)row * stride;
      for (int16_t col = 0; col < w; ++col) {
        const uint8_t bit = (uint8_t)(0x80 >> (col & 7));
        const bool white = (src[col >> 3] & bit) != 0;
        drawPixel((int16_t)(x + col), (int16_t)(y + row), white ? 0 : 1);
      }
    }
    return true;
  }

  // e-ink / slow panels: demos should lengthen loop ticks.
  virtual bool slowPanel() const { return false; }
  virtual const char *panelName() const { return "panel"; }
};
