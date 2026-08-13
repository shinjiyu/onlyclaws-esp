#include "audio_es8311.h"

#include <Wire.h>
#include <driver/i2s.h>
#include <math.h>

#include "board_pins.h"

namespace {
bool ready = false;
uint32_t sampleRate = 16000;

bool esWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(ES8311_I2C_ADDR);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

uint8_t esRead(uint8_t reg) {
  Wire.beginTransmission(ES8311_I2C_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0xFF;
  if (Wire.requestFrom((int)ES8311_I2C_ADDR, 1) != 1) return 0xFF;
  return Wire.read();
}

bool es8311InitRegs() {
  // Soft reset
  esWrite(0x00, 0x80);
  delay(10);
  esWrite(0x00, 0x00);
  delay(10);

  // Clock / format — master clock from MCLK, 16-bit I2S slave-ish config
  // Sequence adapted from common ES8311 Arduino demos for Waveshare boards.
  esWrite(0x01, 0x30);
  esWrite(0x02, 0x10);
  esWrite(0x03, 0x10);
  esWrite(0x16, 0x24);
  esWrite(0x04, 0x20);
  esWrite(0x05, 0x00);
  esWrite(0x06, (sampleRate >= 24000) ? 0x0F : 0x03);
  esWrite(0x07, 0x00);
  esWrite(0x08, 0xFF);
  esWrite(0x09, 0x0F);
  esWrite(0x0A, 0x00);
  esWrite(0x0B, 0x00);
  esWrite(0x0C, 0x00);
  esWrite(0x10, 0x1F);
  esWrite(0x11, 0x7F);
  esWrite(0x00, 0x80);
  delay(5);
  esWrite(0x00, 0x00);
  esWrite(0x0D, 0x01);
  esWrite(0x01, 0x3F);
  esWrite(0x14, 0x1A);
  esWrite(0x12, 0x00);
  esWrite(0x13, 0x10);
  esWrite(0x0E, 0x02);
  esWrite(0x0F, 0x44);
  esWrite(0x15, 0x40);
  esWrite(0x1B, 0x0A);
  esWrite(0x1C, 0x6A);
  esWrite(0x37, 0x08);
  esWrite(0x44, (uint8_t)0x00);
  esWrite(0x17, 0xC0);  // DAC power up
  esWrite(0x32, 0xFF);  // DAC volume (max for audible smoke test)

  const uint8_t id = esRead(0xFD);
  Serial.printf("[audio] ES8311 id=0x%02X\n", id);
  return true;
}

bool i2sInit() {
  i2s_config_t cfg = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_RX),
      .sample_rate = (int)sampleRate,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = 6,
      .dma_buf_len = 256,
      .use_apll = true,
      .tx_desc_auto_clear = true,
      .fixed_mclk = (int)(sampleRate * 256),
  };

  i2s_pin_config_t pins = {
      .mck_io_num = PIN_I2S_MCLK,
      .bck_io_num = PIN_I2S_BCLK,
      .ws_io_num = PIN_I2S_WS,
      .data_out_num = PIN_I2S_DOUT,
      .data_in_num = PIN_I2S_DIN,
  };

  if (i2s_driver_install(I2S_NUM_0, &cfg, 0, nullptr) != ESP_OK) {
    Serial.println("[audio] i2s install failed");
    return false;
  }
  if (i2s_set_pin(I2S_NUM_0, &pins) != ESP_OK) {
    Serial.println("[audio] i2s pins failed");
    i2s_driver_uninstall(I2S_NUM_0);
    return false;
  }
  i2s_zero_dma_buffer(I2S_NUM_0);
  return true;
}
}  // namespace

void audioSetPa(bool on) {
  pinMode(PIN_AUDIO_PA, OUTPUT);
  digitalWrite(PIN_AUDIO_PA, on ? HIGH : LOW);
}

bool audioBegin(uint32_t sr) {
  if (ready) return true;
  sampleRate = sr ? sr : 16000;

  Wire.begin(PIN_AUDIO_I2C_SDA, PIN_AUDIO_I2C_SCL);
  Wire.setClock(100000);
  delay(20);

  audioSetPa(false);
  if (!es8311InitRegs()) {
    Serial.println("[audio] codec init failed");
    return false;
  }
  if (!i2sInit()) return false;

  audioSetPa(true);
  ready = true;
  Serial.printf("[audio] ready @ %u Hz\n", (unsigned)sampleRate);
  return true;
}

void audioEnd() {
  if (!ready) return;
  audioSetPa(false);
  i2s_driver_uninstall(I2S_NUM_0);
  ready = false;
}

bool audioIsReady() { return ready; }

uint32_t audioSampleRate() { return sampleRate; }

bool audioPlayPcm(const int16_t *samples, size_t count) {
  if (!ready || !samples || !count) return false;
  size_t written = 0;
  const uint8_t *p = reinterpret_cast<const uint8_t *>(samples);
  size_t bytes = count * sizeof(int16_t);
  while (written < bytes) {
    size_t n = 0;
    if (i2s_write(I2S_NUM_0, p + written, bytes - written, &n, pdMS_TO_TICKS(1000)) !=
        ESP_OK) {
      return false;
    }
    written += n;
  }
  return true;
}

bool audioPlayBeep(uint16_t freqHz, uint16_t ms) {
  if (!ready) return false;
  audioSetPa(true);
  const size_t n = (size_t)sampleRate * ms / 1000;
  int16_t *buf = (int16_t *)malloc(n * sizeof(int16_t));
  if (!buf) return false;
  const float w = 2.0f * 3.1415926f * (float)freqHz / (float)sampleRate;
  for (size_t i = 0; i < n; ++i) {
    float env = 1.0f;
    if (i < 40) env = (float)i / 40.0f;
    if (i + 40 > n) env = (float)(n - i) / 40.0f;
    buf[i] = (int16_t)(sinf(w * i) * 20000.0f * env);
  }
  const bool ok = audioPlayPcm(buf, n);
  free(buf);
  return ok;
}

bool audioPlayDemo() {
  if (!ready) return false;
  // C5 D5 E5 G5 E5 C5 — short ascending motif
  static const uint16_t notes[] = {523, 587, 659, 784, 659, 523};
  static const uint16_t durs[] = {180, 180, 180, 280, 180, 360};
  Serial.println("[audio] play demo start");
  audioSetPa(true);
  bool ok = true;
  for (size_t i = 0; i < sizeof(notes) / sizeof(notes[0]); ++i) {
    if (!audioPlayBeep(notes[i], durs[i])) {
      ok = false;
      break;
    }
    delay(35);
  }
  Serial.printf("[audio] play demo %s\n", ok ? "ok" : "fail");
  return ok;
}

size_t audioRecordPcm(int16_t *out, size_t count) {
  if (!ready || !out || !count) return 0;
  size_t got = 0;
  uint8_t *p = reinterpret_cast<uint8_t *>(out);
  size_t bytes = count * sizeof(int16_t);
  while (got < bytes) {
    size_t n = 0;
    if (i2s_read(I2S_NUM_0, p + got, bytes - got, &n, pdMS_TO_TICKS(1000)) != ESP_OK) {
      break;
    }
    if (n == 0) break;
    got += n;
  }
  return got / sizeof(int16_t);
}
