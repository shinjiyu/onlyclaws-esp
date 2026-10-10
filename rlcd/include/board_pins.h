#pragma once

// Pin map follows the PlatformIO env.
//   BOARD_PANEL_EPAPER  Waveshare ESP32-S3-ePaper-3.97
//   BOARD_PANEL_RLCD    Waveshare ESP32-S3-RLCD-4.2
//   BOARD_ROARM         Waveshare RoArm-M2 driver (classic ESP32, STS servo bus)
//   neither             ESP32-S3 bare module (BOOT on GPIO0 only)

#ifdef BOARD_ROARM

// Servo TTL UART (Waveshare RoArm-M2_config.h defaults).
constexpr int PIN_SERVO_RX = 18;
constexpr int PIN_SERVO_TX = 19;

constexpr int PIN_BOOT_BTN = 0;
constexpr int PIN_KEY_BTN = 0;
constexpr int PIN_BAT_ADC = -1;
// Stock OLED sits on I2C 32/33; left alone so sensorsBegin() skips the bus.
constexpr int PIN_I2C_SDA = -1;
constexpr int PIN_I2C_SCL = -1;

constexpr int LCD_WIDTH = 0;
constexpr int LCD_HEIGHT = 0;

#elif defined(BOARD_PANEL_EPAPER)

// E-paper SPI
constexpr int PIN_EPD_BUSY = 3;
constexpr int PIN_EPD_DC = 9;
constexpr int PIN_EPD_CS = 10;
constexpr int PIN_EPD_SCLK = 11;
constexpr int PIN_EPD_MOSI = 12;
constexpr int PIN_EPD_RST = 46;

constexpr int PIN_BOOT_BTN = 0;
constexpr int PIN_KEY_BTN = 0;  // no dedicated KEY; BOOT doubles as input.key
constexpr int PIN_VBAT_PWR = 1;
constexpr int PIN_BAT_ADC = -1;  // no ADC wired in this pin map

constexpr int PIN_I2C_SDA = 41;
constexpr int PIN_I2C_SCL = 42;

constexpr int PIN_I2S_MCLK = 13;
constexpr int PIN_I2S_BCLK = 14;
constexpr int PIN_I2S_DIN = 21;
constexpr int PIN_I2S_WS = 47;
constexpr int PIN_I2S_DOUT = 48;
constexpr int PIN_AUDIO_PA = 39;
constexpr int PIN_AUDIO_I2C_SDA = 41;
constexpr int PIN_AUDIO_I2C_SCL = 42;
constexpr uint8_t ES8311_I2C_ADDR = 0x18;
constexpr uint8_t ES7210_I2C_ADDR = 0x40;

constexpr int LCD_WIDTH = 800;
constexpr int LCD_HEIGHT = 480;

#elif defined(BOARD_PANEL_RLCD)

constexpr int PIN_LCD_DC = 5;
constexpr int PIN_LCD_CS = 40;
constexpr int PIN_LCD_RST = 41;
constexpr int PIN_LCD_SCLK = 11;
constexpr int PIN_LCD_MOSI = 12;

constexpr int PIN_I2C_SDA = 13;
constexpr int PIN_I2C_SCL = 14;

constexpr int PIN_BOOT_BTN = 0;
constexpr int PIN_KEY_BTN = 18;
constexpr int PIN_BAT_ADC = 4;

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

#else  // ESP32-S3 bare module

constexpr int PIN_BOOT_BTN = 0;
constexpr int PIN_KEY_BTN = 0;  // BOOT doubles as the long-press input
constexpr int PIN_BAT_ADC = -1;
constexpr int PIN_I2C_SDA = -1;
constexpr int PIN_I2C_SCL = -1;

constexpr int LCD_WIDTH = 0;
constexpr int LCD_HEIGHT = 0;

#endif
