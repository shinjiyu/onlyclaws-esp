#include "sensors.h"

#include <Wire.h>
#include <math.h>

#include "board_pins.h"

namespace {
constexpr uint8_t kShtc3Addr = 0x70;
// TG28 is a renamed AXP2101 (ePaper 3.97 PMU on the shared I2C bus).
constexpr uint8_t kAxpAddr = 0x34;
constexpr uint8_t kAxpChipId = 0x4A;
bool ready = false;
bool axpReady = false;

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

bool axpRead(uint8_t reg, uint8_t *val) {
  Wire.beginTransmission(kAxpAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)kAxpAddr, 1) != 1) return false;
  *val = Wire.read();
  return true;
}

bool axpSetBit(uint8_t reg, uint8_t bit) {
  uint8_t v = 0;
  if (!axpRead(reg, &v)) return false;
  if (v & (1u << bit)) return true;
  Wire.beginTransmission(kAxpAddr);
  Wire.write(reg);
  Wire.write((uint8_t)(v | (1u << bit)));
  return Wire.endTransmission() == 0;
}

// Read-mostly: only turns on the VBAT ADC channel and the fuel gauge.
void axpProbe() {
  uint8_t id = 0;
  axpReady = axpRead(0x03, &id) && id == kAxpChipId;
  if (!axpReady) return;
  axpSetBit(0x30, 0);  // ADC channel enable: VBAT
  axpSetBit(0x18, 3);  // fuel gauge enable
  Serial.println("[sensors] TG28/AXP2101 fuel gauge");
}

bool axpBattery(OcBattery &b) {
  uint8_t s1 = 0, s2 = 0;
  if (!axpRead(0x00, &s1) || !axpRead(0x01, &s2)) return false;
  b.sensed = true;
  b.usb = (s1 & 0x20) != 0;
  b.present = (s1 & 0x08) != 0;
  if (!b.present) return true;
  uint8_t hi = 0, lo = 0, pct = 0;
  if (axpRead(0x34, &hi) && axpRead(0x35, &lo)) b.mv = ((hi & 0x3F) << 8) | lo;
  if (axpRead(0xA4, &pct) && pct <= 100) {
    b.pct = pct;
  } else if (b.mv > 0) {
    b.pct = ocBatteryPctFromMv(b.mv);
  }
  b.charging = ((s2 >> 5) & 0x03) == 0x01;
  return true;
}

bool adcBattery(OcBattery &b) {
  b.sensed = true;
  uint32_t sum = 0;
  const int n = 8;
  for (int i = 0; i < n; ++i) {
    sum += analogReadMilliVolts(PIN_BAT_ADC);
    delay(2);
  }
  // 1/3 divider on the RLCD. USB-only boards read near 0 or nonsense.
  const int mv = (int)(sum / n) * 3;
  if (mv >= 2800 && mv <= 4400) {
    b.present = true;
    b.mv = mv;
    b.pct = ocBatteryPctFromMv(mv);
  }
  return true;
}
}  // namespace

bool sensorsBegin() {
  if (PIN_BAT_ADC >= 0) {
    pinMode(PIN_BAT_ADC, INPUT);
    analogReadResolution(12);
    analogSetPinAttenuation(PIN_BAT_ADC, ADC_11db);
  }
  if (PIN_I2C_SDA < 0 || PIN_I2C_SCL < 0) {
    ready = false;
    return false;
  }
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(100000);
  delay(5);
  // Wake SHTC3
  shtcWriteCmd(0x3517);
  delay(2);
  if (PIN_BAT_ADC < 0) axpProbe();
  ready = true;
  return true;
}

bool sensorsBattery(OcBattery &out) {
  out = OcBattery{};
  if (PIN_BAT_ADC >= 0) return adcBattery(out);
  if (PIN_I2C_SDA < 0 || PIN_I2C_SCL < 0) return false;
  if (!ready) sensorsBegin();
  return axpReady && axpBattery(out);
}

bool sensorsRead(SensorReading &out) {
  out = SensorReading{};
  if (PIN_I2C_SDA < 0 || PIN_I2C_SCL < 0) return false;
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

  OcBattery b;
  if (sensorsBattery(b) && b.present && b.mv > 0) {
    out.okBattery = true;
    out.batteryV = b.mv / 1000.0f;
    out.batteryPct = b.pct;
    out.charging = b.charging;
  }
  return out.okTemp || out.okBattery;
}
