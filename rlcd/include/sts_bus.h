#pragma once

#include <Arduino.h>
#include <HardwareSerial.h>

// Minimal Feetech SMS/STS bus (enough for RoArm WritePosEx / ReadPos).
// Protocol matches Waveshare RoArm-M2 SCServo SMS_STS usage.

namespace sts {

constexpr uint8_t INST_WRITE = 0x03;
constexpr uint8_t INST_READ = 0x02;
constexpr uint8_t ADDR_ACC = 41;           // SMS_STS_ACC
constexpr uint8_t ADDR_GOAL_POSITION_L = 42;
constexpr uint8_t ADDR_PRESENT_POSITION_L = 56;

bool begin(HardwareSerial &serial, int rxPin, int txPin, uint32_t baud = 1000000);
void end();

// Position: 0..4095 typical; negative values encode direction bit like SMS_STS.
bool writePosEx(uint8_t id, int16_t position, uint16_t speed, uint8_t acc);
bool readPos(uint8_t id, int16_t &positionOut);
bool enableTorque(uint8_t id, bool on);
bool ping(uint8_t id);
int lastError();  // debug: last genRead failure code

}  // namespace sts
