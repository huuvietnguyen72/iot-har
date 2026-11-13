// Single-cell Li-ion battery estimate from the divided ADC voltage. No Arduino dependency.
//
// The percentage is an estimate: cell voltage is not linear in charge and sags while
// Wi-Fi transmits. Show it as a level (0..4 bars) rather than trusting the exact number.
#pragma once

#include <stddef.h>
#include <stdint.h>

constexpr int kBatteryMinValidMv = 2500;  // below this the cell is absent or the switch is off
constexpr int kBatteryMaxValidMv = 4500;
constexpr int kBatteryLowPercent = 15;
constexpr int kBatteryLowClearPercent = 20;

inline bool batteryVoltageValid(int millivolts) {
  return millivolts >= kBatteryMinValidMv && millivolts <= kBatteryMaxValidMv;
}

// 0..100 from the cell voltage, by linear interpolation over a discharge table.
inline int batteryPercent(int millivolts) {
  struct Point {
    int mv;
    int percent;
  };
  static const Point kCurve[] = {
      {3300, 0},  {3400, 5},  {3500, 10}, {3600, 20}, {3700, 35},
      {3800, 50}, {3900, 65}, {4000, 80}, {4100, 90}, {4200, 100},
  };
  const size_t count = sizeof(kCurve) / sizeof(kCurve[0]);
  if (millivolts <= kCurve[0].mv) return 0;
  if (millivolts >= kCurve[count - 1].mv) return 100;
  for (size_t i = 1; i < count; ++i) {
    if (millivolts <= kCurve[i].mv) {
      const Point &a = kCurve[i - 1];
      const Point &b = kCurve[i];
      return a.percent + (millivolts - a.mv) * (b.percent - a.percent) / (b.mv - a.mv);
    }
  }
  return 100;
}

// 0..4 bars.
inline int batteryLevel(int percent) {
  if (percent >= 75) return 4;
  if (percent >= 50) return 3;
  if (percent >= 25) return 2;
  if (percent >= 10) return 1;
  return 0;
}

// Smooths ADC samples and applies hysteresis to the low-battery flag.
class BatteryMonitor {
 public:
  void addSample(int millivolts) {
    if (!batteryVoltageValid(millivolts)) {
      // A few bad samples in a row mean the cell is gone (switch off, USB power only).
      if (invalid_run_ < kInvalidRunToForget) ++invalid_run_;
      if (invalid_run_ >= kInvalidRunToForget) {
        valid_ = false;
        low_ = false;
      }
      return;
    }
    invalid_run_ = 0;
    if (!valid_) {
      filtered_mv_x8_ = millivolts * 8;
      valid_ = true;
    } else {
      filtered_mv_x8_ += millivolts - filtered_mv_x8_ / 8;  // EMA, alpha = 1/8
    }
    const int percent = batteryPercent(millivolts_unchecked());
    if (percent <= kBatteryLowPercent) low_ = true;
    if (percent >= kBatteryLowClearPercent) low_ = false;
  }

  bool valid() const { return valid_; }
  int millivolts() const { return valid_ ? millivolts_unchecked() : 0; }
  int percent() const { return valid_ ? batteryPercent(millivolts_unchecked()) : -1; }
  int level() const { return valid_ ? batteryLevel(percent()) : -1; }
  bool low() const { return valid_ && low_; }

 private:
  static constexpr int kInvalidRunToForget = 3;
  int millivolts_unchecked() const { return filtered_mv_x8_ / 8; }

  int filtered_mv_x8_ = 0;
  int invalid_run_ = 0;
  bool valid_ = false;
  bool low_ = false;
};
