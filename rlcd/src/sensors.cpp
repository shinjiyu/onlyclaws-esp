#include "sensors.h"

#include <Wire.h>
#include <math.h>

#include "board_pins.h"

namespace {
constexpr uint8_t kShtc3Addr = 0x70;
bool ready = false;

bool shtcWriteCmd(uint16_t cmd) {
  Wire.beginTransmission(kShtc3Addr);
  Wire.write((uint8_t)(cmd >> 8));
  Wire.write((uint8_t)(cmd & 0xFF));
  return Wire.endTransmission() == 0;
}

bool shtcRead(uint8_t *buf, size_t n) {
  const size_t got = Wire.requestFrom((int)kShtc3Addr, (int)n);
  if (got != n) return false;
  for (size_t i = 0; i < n; ++i) buf[i] = Wire.read();
  return true;
}

int batteryPctFromV(float v) {
  // Coarse Li-ion curve for 18650 single cell.
  if (v <= 3.30f) return 0;
  if (v >= 4.15f) return 100;
  if (v < 3.60f) return (int)((v - 3.30f) / 0.30f * 20.0f);
  if (v < 3.90f) return 20 + (int)((v - 3.60f) / 0.30f * 50.0f);
  return 70 + (int)((v - 3.90f) / 0.25f * 30.0f);
}
}  // namespace

bool sensorsBegin() {
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(100000);
  delay(5);
  // Wake SHTC3
  shtcWriteCmd(0x3517);
  delay(2);
  if (PIN_BAT_ADC >= 0) {
    pinMode(PIN_BAT_ADC, INPUT);
    analogReadResolution(12);
  }
  ready = true;
  return true;
}

bool sensorsRead(SensorReading &out) {
  out = SensorReading{};
  if (!ready) sensorsBegin();

  // SHTC3: wake + normal measure (clock stretching disabled: 0x7866)
  shtcWriteCmd(0x3517);
  delay(2);
  if (shtcWriteCmd(0x7866)) {
    delay(15);
    uint8_t raw[6] = {};
    if (shtcRead(raw, 6)) {
      const uint16_t tRaw = ((uint16_t)raw[0] << 8) | raw[1];
      const uint16_t hRaw = ((uint16_t)raw[3] << 8) | raw[4];
      out.tempC = -45.0f + 175.0f * ((float)tRaw / 65535.0f);
      out.humidity = 100.0f * ((float)hRaw / 65535.0f);
      if (out.humidity < 0) out.humidity = 0;
      if (out.humidity > 100) out.humidity = 100;
      out.okTemp = true;
    }
  }

  // Battery: 3x divider (RLCD). Skip when pin not wired (ePaper map).
  if (PIN_BAT_ADC < 0) {
    out.batteryV = NAN;
    out.batteryPct = -1;
    return out.okTemp || out.okBattery;
  }
  uint32_t sum = 0;
  const int n = 8;
  for (int i = 0; i < n; ++i) {
    sum += analogReadMilliVolts(PIN_BAT_ADC);
    delay(2);
  }
  const float pinV = (sum / (float)n) / 1000.0f;
  out.batteryV = pinV * 3.0f;
  // USB-only boards often read near 0 or nonsense; treat plausible pack range.
  if (out.batteryV >= 2.8f && out.batteryV <= 4.4f) {
    out.okBattery = true;
    out.batteryPct = batteryPctFromV(out.batteryV);
  } else {
    out.batteryV = NAN;
    out.batteryPct = -1;
  }

  return out.okTemp || out.okBattery;
}
