#include "audio_es8311.h"

#include <Wire.h>
#include <driver/i2s.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <math.h>

#include "board_pins.h"

namespace {
bool ready = false;
bool micReady = false;
uint32_t sampleRate = 16000;
SemaphoreHandle_t i2sMu = nullptr;
// PCM tone amplitude (int16 full-scale=32767). Keep mid; DAC reg handles overall loudness.
constexpr float kToneAmp = 14000.0f;

struct Coeff {
  uint8_t pre_div, pre_mult, adc_div, dac_div, fs_mode, lrck_h, lrck_l, bclk_div,
      adc_osr, dac_osr;
};
constexpr Coeff kCoeff16k256 = {1, 1, 1, 1, 0, 0, 0xff, 4, 0x10, 0x20};

bool i2cWrite(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

uint8_t i2cRead(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0xFF;
  if (Wire.requestFrom((int)addr, 1) != 1) return 0xFF;
  return Wire.read();
}

bool esWrite(uint8_t reg, uint8_t val) { return i2cWrite(ES8311_I2C_ADDR, reg, val); }
uint8_t esRead(uint8_t reg) { return i2cRead(ES8311_I2C_ADDR, reg); }
bool micWrite(uint8_t reg, uint8_t val) { return i2cWrite(ES7210_I2C_ADDR, reg, val); }
uint8_t micRead(uint8_t reg) { return i2cRead(ES7210_I2C_ADDR, reg); }

void dumpRegs(const char *tag) {
  Serial.printf(
      "[audio] %s es8311=0x%02X es7210=0x%02X%02X pa=%d mic=%d\n", tag,
      esRead(0xFD), micRead(0x3D), micRead(0x3E), digitalRead(PIN_AUDIO_PA),
      (int)micReady);
}

bool es8311InitRegs() {
  esWrite(0x00, 0x1F);
  delay(20);
  esWrite(0x00, 0x00);
  delay(10);
  esWrite(0x01, 0x3F);
  const Coeff &c = kCoeff16k256;
  esWrite(0x02, (uint8_t)(((c.pre_div - 1) << 5) | (c.pre_mult << 3)));
  esWrite(0x03, (uint8_t)((c.fs_mode << 6) | c.adc_osr));
  esWrite(0x04, c.dac_osr);
  esWrite(0x05, (uint8_t)(((c.adc_div - 1) << 4) | (c.dac_div - 1)));
  esWrite(0x06, (uint8_t)(c.bclk_div < 19 ? (c.bclk_div - 1) : c.bclk_div));
  esWrite(0x07, c.lrck_h);
  esWrite(0x08, c.lrck_l);
  uint8_t reg00 = esRead(0x00);
  esWrite(0x00, (uint8_t)(reg00 & 0xBF));
  esWrite(0x09, 0x0C);
  esWrite(0x0A, 0x0C);
  esWrite(0x14, 0x1A);
  esWrite(0x16, 0x24);
  esWrite(0x17, 0xC8);
  esWrite(0x0D, 0x01);
  esWrite(0x0E, 0x02);
  esWrite(0x12, 0x00);
  esWrite(0x13, 0x10);
  esWrite(0x1C, 0x6A);
  esWrite(0x37, 0x08);
  esWrite(0x31, 0x00);
  // ES8311 DAC volume: 0x00≈-95.5dB … 0xBF=0dB (0.5dB/step). Mid ~0x9A ≈ -18dB.
  esWrite(0x32, 0x9A);
  esWrite(0x00, 0x80);
  delay(50);
  return esRead(0xFD) == 0x83;
}

bool es7210InitRegs() {
  // Espressif es7210_config_codec sequence (16 kHz, MCLK=256*fs, I2S 16-bit, no TDM).
  micWrite(0x00, 0xFF);
  delay(10);
  micWrite(0x00, 0x32);
  delay(10);
  micWrite(0x09, 0x30);
  micWrite(0x0A, 0x30);
  micWrite(0x23, 0x2A);
  micWrite(0x22, 0x0A);
  micWrite(0x21, 0x2A);
  micWrite(0x20, 0x0A);

  // REG11: I2S + 16-bit; REG12: non-TDM
  micWrite(0x11, 0x60);
  micWrite(0x12, 0x00);

  micWrite(0x40, 0xC3);  // analog power / VMID
  micWrite(0x41, 0x70);  // MIC1/2 bias 2.87V
  micWrite(0x42, 0x70);  // MIC3/4 bias

  // PGA gain 37.5dB (enum 14) | 0x10
  micWrite(0x43, 0x1E);
  micWrite(0x44, 0x1E);
  micWrite(0x45, 0x1E);
  micWrite(0x46, 0x1E);

  micWrite(0x47, 0x08);
  micWrite(0x48, 0x08);
  micWrite(0x49, 0x08);
  micWrite(0x4A, 0x08);

  // 16kHz @ MCLK 4.096MHz (coeff table entry)
  micWrite(0x07, 0x20);  // OSR
  micWrite(0x02, 0x01 | (1 << 6) | (1 << 7));  // adc_div=1, doubler, dll
  micWrite(0x04, 0x01);  // lrck_h
  micWrite(0x05, 0x00);  // lrck_l

  micWrite(0x06, 0x04);  // power down DLL
  micWrite(0x4B, 0x0F);  // MIC12 bias+ADC+PGA on
  micWrite(0x4C, 0x0F);  // MIC34 on

  // ADC digital volume ~ +18 dB (0xBF = 0dB)
  micWrite(0x1B, 0xE3);
  micWrite(0x1C, 0xE3);
  micWrite(0x1D, 0xE3);
  micWrite(0x1E, 0xE3);

  micWrite(0x00, 0x71);
  delay(10);
  micWrite(0x00, 0x41);
  delay(50);

  const uint8_t id1 = micRead(0x3D);
  const uint8_t id2 = micRead(0x3E);
  Serial.printf("[audio] ES7210 id=0x%02X%02X state=0x%02X gain1=0x%02X\n", id1, id2,
                micRead(0x00), micRead(0x43));
  return id1 == 0x72 && id2 == 0x10;
}

bool i2sInit() {
  i2s_config_t cfg = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_RX),
      .sample_rate = (int)sampleRate,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
      .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = 8,
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
  int16_t silence[64] = {};
  size_t n = 0;
  i2s_write(I2S_NUM_0, silence, sizeof(silence), &n, pdMS_TO_TICKS(50));
  return true;
}

bool writeStereoFramesUnlocked(const int16_t *mono, size_t frames) {
  constexpr size_t kChunk = 256;
  int16_t stereo[kChunk * 2];
  size_t done = 0;
  while (done < frames) {
    const size_t n = (frames - done < kChunk) ? (frames - done) : kChunk;
    for (size_t i = 0; i < n; ++i) {
      stereo[i * 2] = mono[done + i];
      stereo[i * 2 + 1] = mono[done + i];
    }
    size_t off = 0;
    const size_t bytes = n * 2 * sizeof(int16_t);
    const uint8_t *p = reinterpret_cast<const uint8_t *>(stereo);
    while (off < bytes) {
      size_t got = 0;
      if (i2s_write(I2S_NUM_0, p + off, bytes - off, &got, pdMS_TO_TICKS(1000)) !=
          ESP_OK) {
        return false;
      }
      if (got == 0) return false;
      off += got;
    }
    done += n;
  }
  return true;
}

bool playToneUnlocked(uint16_t freqHz, uint16_t ms, float amp) {
  const size_t n = (size_t)sampleRate * ms / 1000;
  int16_t *buf = (int16_t *)malloc(n * sizeof(int16_t));
  if (!buf) return false;
  const float w = 2.0f * 3.1415926f * (float)freqHz / (float)sampleRate;
  for (size_t i = 0; i < n; ++i) {
    float env = 1.0f;
    if (i < 30) env = (float)i / 30.0f;
    if (i + 30 > n) env = (float)(n - i) / 30.0f;
    buf[i] = (int16_t)(sinf(w * i) * amp * env);
  }
  const bool ok = writeStereoFramesUnlocked(buf, n);
  free(buf);
  return ok;
}
}  // namespace

bool audioLockI2S(uint32_t ms) {
  if (!i2sMu) return true;
  return xSemaphoreTake(i2sMu, pdMS_TO_TICKS(ms)) == pdTRUE;
}

void audioUnlockI2S() {
  if (i2sMu) xSemaphoreGive(i2sMu);
}

void audioSetPa(bool on) {
  pinMode(PIN_AUDIO_PA, OUTPUT);
  digitalWrite(PIN_AUDIO_PA, on ? HIGH : LOW);
}

bool audioBegin(uint32_t sr) {
  if (ready) return true;
  sampleRate = sr ? sr : 16000;
  micReady = false;
  if (!i2sMu) i2sMu = xSemaphoreCreateMutex();

  audioSetPa(true);
  delay(5);
  Wire.begin(PIN_AUDIO_I2C_SDA, PIN_AUDIO_I2C_SCL);
  Wire.setClock(100000);
  delay(20);

  if (!i2sInit()) return false;
  delay(20);
  if (!es8311InitRegs()) Serial.println("[audio] ES8311 init warn");
  micReady = es7210InitRegs();
  if (!micReady) Serial.println("[audio] ES7210 init failed");

  audioSetPa(true);
  ready = true;
  dumpRegs("init");
  Serial.printf("[audio] ready @ %u Hz duplex mic=%d\n", (unsigned)sampleRate,
                (int)micReady);
  return true;
}

void audioEnd() {
  if (!ready) return;
  audioSetPa(false);
  i2s_driver_uninstall(I2S_NUM_0);
  ready = false;
  micReady = false;
}

bool audioIsReady() { return ready; }
bool audioMicReady() { return ready && micReady; }
uint32_t audioSampleRate() { return sampleRate; }

bool audioPlayPcm(const int16_t *samples, size_t count) {
  if (!ready || !samples || !count) return false;
  if (!audioLockI2S(1500)) return false;
  audioSetPa(true);
  const bool ok = writeStereoFramesUnlocked(samples, count);
  audioUnlockI2S();
  return ok;
}

bool audioPlayBeep(uint16_t freqHz, uint16_t ms) {
  if (!ready) return false;
  if (!audioLockI2S(1500)) return false;
  audioSetPa(true);
  const bool ok = playToneUnlocked(freqHz, ms, kToneAmp);
  audioUnlockI2S();
  return ok;
}

bool audioPlayDemo() {
  if (!ready) return false;
  static const uint16_t notes[] = {523, 587, 659, 784, 659, 523};
  static const uint16_t durs[] = {180, 180, 180, 280, 180, 360};
  if (!audioLockI2S(3000)) return false;
  audioSetPa(true);
  bool ok = true;
  for (size_t i = 0; i < sizeof(notes) / sizeof(notes[0]); ++i) {
    if (!playToneUnlocked(notes[i], durs[i], kToneAmp)) {
      ok = false;
      break;
    }
    delay(30);
  }
  audioUnlockI2S();
  return ok;
}

bool audioSpeakCue(AudioCue cue) {
  if (!ready) return false;
  if (!audioLockI2S(2000)) return false;
  audioSetPa(true);
  bool ok = false;
  switch (cue) {
    case AUDIO_CUE_RECORD_START:
      ok = playToneUnlocked(880, 90, kToneAmp) &&
           playToneUnlocked(1175, 110, kToneAmp);
      break;
    case AUDIO_CUE_RECORD_END:
      ok = playToneUnlocked(1175, 80, kToneAmp) &&
           playToneUnlocked(880, 100, kToneAmp);
      break;
    case AUDIO_CUE_OK:
      ok = playToneUnlocked(784, 100, kToneAmp) &&
           playToneUnlocked(988, 140, kToneAmp);
      break;
    case AUDIO_CUE_FAIL:
      ok = playToneUnlocked(400, 180, kToneAmp) &&
           playToneUnlocked(320, 200, kToneAmp);
      break;
    case AUDIO_CUE_UPLOAD_OK:
      ok = playToneUnlocked(660, 80, kToneAmp) &&
           playToneUnlocked(880, 80, kToneAmp) &&
           playToneUnlocked(1320, 130, kToneAmp);
      break;
    default:
      ok = playToneUnlocked(700, 90, kToneAmp);
      break;
  }
  audioUnlockI2S();
  return ok;
}

size_t audioRecordPcm(int16_t *out, size_t count) {
  if (!ready || !micReady || !out || !count) return 0;
  if (!audioLockI2S(3000)) return 0;

  int16_t warm[256];
  const uint32_t warmUntil = millis() + 120;
  while (millis() < warmUntil) {
    size_t n = 0;
    // Keep TX alive so RX clocks on full-duplex I2S.
    int16_t z[64] = {};
    size_t wn = 0;
    i2s_write(I2S_NUM_0, z, sizeof(z), &wn, pdMS_TO_TICKS(20));
    i2s_read(I2S_NUM_0, warm, sizeof(warm), &n, pdMS_TO_TICKS(50));
  }

  size_t gotMono = 0;
  while (gotMono < count) {
    int16_t z[128] = {};
    size_t wn = 0;
    i2s_write(I2S_NUM_0, z, sizeof(z), &wn, pdMS_TO_TICKS(20));

    int16_t stereo[256];
    size_t bytes = 0;
    if (i2s_read(I2S_NUM_0, stereo, sizeof(stereo), &bytes, pdMS_TO_TICKS(500)) !=
        ESP_OK) {
      break;
    }
    const size_t frames = bytes / (sizeof(int16_t) * 2);
    if (!frames) break;
    for (size_t i = 0; i < frames && gotMono < count; ++i) {
      const int16_t l = stereo[i * 2];
      const int16_t r = stereo[i * 2 + 1];
      out[gotMono++] = (abs(l) >= abs(r)) ? l : r;
    }
  }
  audioUnlockI2S();
  return gotMono;
}

size_t audioMicReadMono(int16_t *out, size_t maxFrames) {
  if (!ready || !micReady || !out || !maxFrames) return 0;
  int16_t z[128] = {};
  size_t wn = 0;
  i2s_write(I2S_NUM_0, z, sizeof(z), &wn, pdMS_TO_TICKS(20));

  int16_t stereo[512];
  const size_t want = (maxFrames > 256 ? 256 : maxFrames) * 2 * sizeof(int16_t);
  size_t bytes = 0;
  if (i2s_read(I2S_NUM_0, stereo, want, &bytes, pdMS_TO_TICKS(40)) != ESP_OK) {
    return 0;
  }
  const size_t frames = bytes / (sizeof(int16_t) * 2);
  const size_t n = frames < maxFrames ? frames : maxFrames;
  for (size_t i = 0; i < n; ++i) {
    const int16_t l = stereo[i * 2];
    const int16_t r = stereo[i * 2 + 1];
    out[i] = (abs(l) >= abs(r)) ? l : r;
  }
  return n;
}
