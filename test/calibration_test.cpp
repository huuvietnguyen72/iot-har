#include "../src/gyro_calibration.h"
#include <cmath>
#include <cstdio>

namespace {
int failures = 0;

void check(bool condition, const char *name) {
  std::printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) ++failures;
}

bool near(double actual, double expected) {
  return std::fabs(actual - expected) < 0.00001;
}

void fillStationary(GyroCalibration &calibration, unsigned count = 500) {
  // Hand-checked fixture: 0.93 g mainly on X, with gyro bias on all axes.
  // Alternating +/-13 raw units cancels exactly for an even sample count.
  for (unsigned i = 0; i < count; ++i) {
    const int16_t noise = (i % 2 == 0) ? 13 : -13;
    const int16_t accel[3] = {-7618, 409, 1090};
    const int16_t gyro[3] = {static_cast<int16_t>(2000 + noise),
                            static_cast<int16_t>(600 + noise),
                            static_cast<int16_t>(50 + noise)};
    calibration.add(accel, gyro);
  }
}
}

int main() {
  GyroCalibration stationary;
  fillStationary(stationary);
  check(stationary.acceptable(500),
        "stationary biased gyro is accepted with tilted 0.93 g acceleration");
  check(near(stationary.correctedDps(2000, 0), 0.0) &&
        near(stationary.correctedDps(600, 1), 0.0) &&
        near(stationary.correctedDps(50, 2), 0.0),
        "subtract independently measured bias on all three axes");
  check(near(stationary.correctedDps(2655, 0), 10.0) &&
        near(stationary.correctedDps(1345, 0), -10.0),
        "real positive and negative rotation is preserved after correction");

  GyroCalibration incomplete;
  fillStationary(incomplete, 499);
  check(!incomplete.acceptable(500), "incomplete calibration is rejected");

  GyroCalibration rotating;
  for (unsigned i = 0; i < 500; ++i) {
    const int16_t accel[3] = {0, 0, 8192};
    const int16_t gyro[3] = {static_cast<int16_t>(2000 + (i % 2 ? 400 : -400)), 600, 50};
    rotating.add(accel, gyro);
  }
  check(!rotating.acceptable(500), "varying rotation during calibration is rejected");

  GyroCalibration tilted;
  for (unsigned i = 0; i < 500; ++i) {
    // A 30-degree tilt keeps mean gravity about 0.966 g, so only the
    // acceleration-variation checks can reject this otherwise stable gyro.
    const int16_t accel[3] = {static_cast<int16_t>(i < 250 ? 0 : 4096), 0,
                             static_cast<int16_t>(i < 250 ? 8192 : 7094)};
    const int16_t gyro[3] = {2000, 600, 50};
    tilted.add(accel, gyro);
  }
  check(!tilted.acceptable(500), "changing gravity direction during calibration is rejected");

  GyroCalibration spike;
  for (unsigned i = 0; i < 500; ++i) {
    const int16_t accel[3] = {0, 0, 8192};
    const int16_t gyro[3] = {static_cast<int16_t>(i == 250 ? 4000 : 2000), 600, 50};
    spike.add(accel, gyro);
  }
  check(!spike.acceptable(500), "brief movement cannot be hidden by averaging");

  GyroCalibration noGravity;
  for (unsigned i = 0; i < 500; ++i) {
    const int16_t accel[3] = {0, 0, 0};
    const int16_t gyro[3] = {2000, 600, 50};
    noGravity.add(accel, gyro);
  }
  check(!noGravity.acceptable(500), "implausible stationary acceleration is rejected");

  std::printf("%d failure(s)\n", failures);
  return failures == 0 ? 0 : 1;
}
