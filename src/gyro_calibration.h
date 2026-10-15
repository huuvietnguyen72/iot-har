#pragma once

#include <stddef.h>
#include <stdint.h>
#include <math.h>

class GyroCalibration {
 public:
  void add(const int16_t accel[3], const int16_t gyro[3]) {
    ++count_;
    for (size_t axis = 0; axis < 3; ++axis) {
      accel_[axis].add(accel[axis] / 8192.0, count_);
      gyro_[axis].add(gyro[axis] / 65.5, count_);
    }
  }

  bool acceptable(uint32_t requiredCount) const {
    if (count_ < requiredCount || count_ < 2) return false;
    const double gravity = sqrt(accel_[0].mean * accel_[0].mean +
                                accel_[1].mean * accel_[1].mean +
                                accel_[2].mean * accel_[2].mean);
    // Allow uncalibrated accel scale/bias; do not force gravity onto Z.
    if (gravity < 0.75 || gravity > 1.25) return false;
    for (size_t axis = 0; axis < 3; ++axis) {
      // Variation about the mean detects movement without rejecting the
      // large constant zero offset that this calibration needs to measure.
      if (gyro_[axis].stdDev(count_) > 1.0 || gyro_[axis].span() > 6.0 ||
          accel_[axis].stdDev(count_) > 0.03 || accel_[axis].span() > 0.15 ||
          fabs(gyro_[axis].mean) > 490.0) return false;
    }
    return true;
  }

  double biasDps(size_t axis) const { return gyro_[axis].mean; }
  double gyroStdDevDps(size_t axis) const { return gyro_[axis].stdDev(count_); }
  double accelStdDevG(size_t axis) const { return accel_[axis].stdDev(count_); }
  double correctedDps(int16_t raw, size_t axis) const {
    return raw / 65.5 - biasDps(axis);
  }

 private:
  struct AxisStats {
    double mean = 0.0;
    double m2 = 0.0;
    double minimum = 0.0;
    double maximum = 0.0;

    void add(double value, uint32_t count) {
      const double delta = value - mean;
      mean += delta / count;
      m2 += delta * (value - mean);
      if (count == 1 || value < minimum) minimum = value;
      if (count == 1 || value > maximum) maximum = value;
    }

    double stdDev(uint32_t count) const {
      if (count < 2) return 0.0;
      const double variance = m2 / (count - 1);
      return sqrt(variance > 0.0 ? variance : 0.0);
    }

    double span() const { return maximum - minimum; }
  };

  uint32_t count_ = 0;
  AxisStats accel_[3];
  AxisStats gyro_[3];
};
