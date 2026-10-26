#pragma once

// Pin map follows the PlatformIO env.
//   BOARD_PANEL_EPAPER  Waveshare ESP32-S3-ePaper-3.97
//   BOARD_PANEL_RLCD    Waveshare ESP32-S3-RLCD-4.2
//   BOARD_PANEL_AMOLED  Waveshare ESP32-S3-Touch-AMOLED-1.75 / 1.75C
//   BOARD_PANEL_ST7789  FoloToy AI Passport (ESP32-C3, 240x320)
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

#elif defined(BOARD_PANEL_AMOLED)

// Waveshare ESP32-S3-Touch-AMOLED-1.75(C) — see HARDWARE_REFERENCE (waveshareteam).
// Display QSPI (CO5300); flush not implemented in stub driver yet.
constexpr int PIN_LCD_DATA0 = 4;
constexpr int PIN_LCD_DATA1 = 5;
constexpr int PIN_LCD_DATA2 = 6;
constexpr int PIN_LCD_DATA3 = 7;
constexpr int PIN_LCD_CS = 12;
constexpr int PIN_LCD_TE = 13;
constexpr int PIN_LCD_PCLK = 38;
constexpr int PIN_LCD_RST = 39;
constexpr int PIN_TP_RST = 40;
constexpr int PIN_TP_INT = 11;

constexpr int PIN_I2C_SDA = 15;
constexpr int PIN_I2C_SCL = 14;

constexpr int PIN_BOOT_BTN = 0;
constexpr int PIN_KEY_BTN = 0;  // PWR is on AXP/TCA; BOOT doubles as input.key for now
constexpr int PIN_BAT_ADC = -1;  // AXP2101 @ 0x34 on shared I2C

constexpr int PIN_I2S_MCLK = 42;
constexpr int PIN_I2S_BCLK = 9;
constexpr int PIN_I2S_WS = 45;
constexpr int PIN_I2S_DOUT = 8;
constexpr int PIN_I2S_DIN = 10;
constexpr int PIN_AUDIO_PA = 46;
constexpr int PIN_AUDIO_I2C_SDA = PIN_I2C_SDA;
constexpr int PIN_AUDIO_I2C_SCL = PIN_I2C_SCL;
constexpr uint8_t ES8311_I2C_ADDR = 0x18;
constexpr uint8_t ES7210_I2C_ADDR = 0x40;

constexpr int LCD_WIDTH = 466;
constexpr int LCD_HEIGHT = 466;
constexpr int AMOLED_SAFE_R = 233;

#elif defined(BOARD_PANEL_ST7789)

// FoloToy AI Passport — bsp_pins.h (FoloToy/ai-passport).
constexpr int PIN_LCD_MOSI = 9;
constexpr int PIN_LCD_SCLK = 8;
constexpr int PIN_LCD_CS = 1;
constexpr int PIN_LCD_DC = 20;
constexpr int PIN_LCD_RST = -1;  // tied high; SWRESET
constexpr int PIN_LCD_BL = 21;

constexpr int PIN_I2C_SDA = 10;
constexpr int PIN_I2C_SCL = 7;

constexpr int PIN_BOOT_BTN = 0;
constexpr int PIN_KEY_BTN = 0;  // ADC ladder on GPIO0 (UP/DOWN/OK) — later
constexpr int PIN_BAT_ADC = -1;  // CW2017 @ 0x63 on I2C

constexpr int PIN_I2S_MCLK = 6;
constexpr int PIN_I2S_BCLK = 5;
constexpr int PIN_I2S_WS = 3;
constexpr int PIN_I2S_DOUT = 2;
constexpr int PIN_I2S_DIN = 4;
constexpr int PIN_AUDIO_PA = -1;  // always-on amp
constexpr int PIN_AUDIO_I2C_SDA = PIN_I2C_SDA;
constexpr int PIN_AUDIO_I2C_SCL = PIN_I2C_SCL;
constexpr uint8_t ES8311_I2C_ADDR = 0x18;
constexpr uint8_t ES7210_I2C_ADDR = 0x40;  // absent on Passport; soft-fail

constexpr int LCD_WIDTH = 240;
constexpr int LCD_HEIGHT = 320;

#else  // ESP32-S3 bare module

constexpr int PIN_BOOT_BTN = 0;
constexpr int PIN_KEY_BTN = 0;  // BOOT doubles as the long-press input
constexpr int PIN_BAT_ADC = -1;
constexpr int PIN_I2C_SDA = -1;
constexpr int PIN_I2C_SCL = -1;

constexpr int LCD_WIDTH = 0;
constexpr int LCD_HEIGHT = 0;

#endif
