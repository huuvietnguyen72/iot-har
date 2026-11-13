// GPIO map of the wearable, shared by the streaming firmware and hw_test.
#pragma once

namespace pins {
constexpr int kSda = 21;       // sensor bus: MPU6050 + BMP280
constexpr int kScl = 22;
constexpr int kOledSda = 19;   // second I2C bus, OLED only, so drawing never delays sampling
constexpr int kOledScl = 18;
constexpr int kLedGreen = 26;
constexpr int kLedRed = 27;
constexpr int kButton = 32;    // to GND, internal pull-up
constexpr int kBuzzer = 25;    // through S8050
constexpr int kMotor = 33;     // optional vibration motor through S8050
constexpr int kBattery = 34;   // ADC1 (works with Wi-Fi on), 100k/100k divider
}  // namespace pins
