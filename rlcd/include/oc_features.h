#pragma once

// Compile-time plugins. The ESP32-S3 core (Wi-Fi, identity, cloud, Lua)
// always builds. Define these on the PlatformIO env that needs the hardware.
//
//   OC_PLUGIN_PANEL   ST7305 or GxEPD2, selected by BOARD_PANEL_*
//   OC_PLUGIN_AUDIO   ES8311 playback
//   OC_PLUGIN_BLE     NimBLE D-pad (RLCD only; ePaper leaves it off for heap)

#if defined(OC_PLUGIN_PANEL)
#define OC_HAS_PANEL 1
#else
#define OC_HAS_PANEL 0
#endif

#if defined(OC_PLUGIN_AUDIO)
#define OC_HAS_AUDIO 1
#else
#define OC_HAS_AUDIO 0
#endif

#if defined(OC_PLUGIN_BLE)
#define OC_HAS_BLE 1
#else
#define OC_HAS_BLE 0
#endif
