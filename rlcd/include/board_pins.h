#pragma once

// Waveshare ESP32-S3-RLCD-4.2

// ST7305 reflective LCD (SPI)
constexpr int PIN_LCD_DC = 5;
constexpr int PIN_LCD_CS = 40;
constexpr int PIN_LCD_RST = 41;
constexpr int PIN_LCD_SCLK = 11;
constexpr int PIN_LCD_MOSI = 12;

// Shared I2C (SHTC3 / ES8311 / ES7210 / RTC)
constexpr int PIN_I2C_SDA = 13;
constexpr int PIN_I2C_SCL = 14;

// Buttons
constexpr int PIN_BOOT_BTN = 0;
constexpr int PIN_KEY_BTN = 18;

// Battery ADC (3x divider)
constexpr int PIN_BAT_ADC = 4;

// Audio (skeleton reserved)
constexpr int PIN_I2S_MCLK = 16;
constexpr int PIN_I2S_BCLK = 9;
constexpr int PIN_I2S_WS = 45;
constexpr int PIN_I2S_DOUT = 8;
constexpr int PIN_I2S_DIN = 10;
constexpr int PIN_AUDIO_PA = 46;
constexpr int PIN_AUDIO_I2C_SDA = PIN_I2C_SDA;
constexpr int PIN_AUDIO_I2C_SCL = PIN_I2C_SCL;
constexpr uint8_t ES8311_I2C_ADDR = 0x18;
constexpr uint8_t ES7210_I2C_ADDR = 0x40;

constexpr int LCD_WIDTH = 400;
constexpr int LCD_HEIGHT = 300;
