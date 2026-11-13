#include "../src/battery.h"
#include <cstdio>

namespace {
int failures = 0;

void check(bool condition, const char *name) {
  std::printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) ++failures;
}
}

int main() {
  check(batteryPercent(4200) == 100, "4.20 V is 100%");
  check(batteryPercent(4350) == 100, "above 4.20 V clamps to 100%");
  check(batteryPercent(3300) == 0, "3.30 V is 0%");
  check(batteryPercent(3000) == 0, "below 3.30 V clamps to 0%");
  check(batteryPercent(3800) == 50, "3.80 V is 50%");
  check(batteryPercent(3850) == 57, "interpolates between table points");
  int previous = -1;
  bool monotonic = true;
  for (int mv = 3000; mv <= 4300; mv += 10) {
    const int percent = batteryPercent(mv);
    if (percent < previous) monotonic = false;
    previous = percent;
  }
  check(monotonic, "percentage never decreases as voltage rises");

  check(batteryLevel(100) == 4 && batteryLevel(75) == 4, "75..100% is 4 bars");
  check(batteryLevel(74) == 3 && batteryLevel(50) == 3, "50..74% is 3 bars");
  check(batteryLevel(49) == 2 && batteryLevel(25) == 2, "25..49% is 2 bars");
  check(batteryLevel(24) == 1 && batteryLevel(10) == 1, "10..24% is 1 bar");
  check(batteryLevel(9) == 0 && batteryLevel(0) == 0, "below 10% is 0 bars");

  check(!batteryVoltageValid(0) && !batteryVoltageValid(2499), "low readings are invalid");
  check(batteryVoltageValid(2500) && batteryVoltageValid(4500), "range ends are valid");
  check(!batteryVoltageValid(4501), "high readings are invalid");

  BatteryMonitor fresh;
  check(!fresh.valid() && fresh.percent() == -1 && fresh.level() == -1 && fresh.millivolts() == 0,
        "no reading yet: invalid, percent -1, level -1");
  check(!fresh.low(), "no reading yet: not low");

  BatteryMonitor monitor;
  monitor.addSample(4000);
  check(monitor.valid() && monitor.millivolts() == 4000, "first sample is taken as is");
  monitor.addSample(3200);
  check(monitor.millivolts() == 3900, "later samples are smoothed (alpha 1/8)");

  BatteryMonitor low;
  low.addSample(3540);  // 14%
  check(low.low(), "15% or less sets the low flag");
  for (int i = 0; i < 100; ++i) low.addSample(3580);  // 18%: inside the hysteresis band
  check(low.low(), "low flag holds inside the hysteresis band");
  for (int i = 0; i < 100; ++i) low.addSample(3700);
  check(!low.low(), "20% or more clears the low flag");

  BatteryMonitor gone;
  gone.addSample(3900);
  gone.addSample(0);
  gone.addSample(0);
  check(gone.valid() && gone.millivolts() == 3900, "one or two bad samples are ignored");
  gone.addSample(0);
  check(!gone.valid() && gone.percent() == -1, "three bad samples in a row forget the reading");
  gone.addSample(3700);
  check(gone.valid() && gone.millivolts() == 3700, "a good sample after that starts fresh");

  return failures == 0 ? 0 : 1;
}
