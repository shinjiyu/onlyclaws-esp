#pragma once

// Waveshare ESP32-S3-ePaper-3.97 (matches xiaozhi / official pin map)

// E-paper
constexpr int PIN_EPD_BUSY = 3;
constexpr int PIN_EPD_DC = 9;
constexpr int PIN_EPD_CS = 10;
constexpr int PIN_EPD_SCLK = 11;
constexpr int PIN_EPD_MOSI = 12;
constexpr int PIN_EPD_RST = 46;

// Buttons / power
constexpr int PIN_BOOT_BTN = 0;
constexpr int PIN_VBAT_PWR = 1;

// ES8311 audio
constexpr int PIN_I2S_MCLK = 13;
constexpr int PIN_I2S_BCLK = 14;
constexpr int PIN_I2S_DIN = 21;   // codec -> MCU (mic)
constexpr int PIN_I2S_WS = 47;
constexpr int PIN_I2S_DOUT = 48;  // MCU -> codec (spk)
constexpr int PIN_AUDIO_PA = 39;
constexpr int PIN_AUDIO_I2C_SDA = 41;
constexpr int PIN_AUDIO_I2C_SCL = 42;
constexpr uint8_t ES8311_I2C_ADDR = 0x18;
