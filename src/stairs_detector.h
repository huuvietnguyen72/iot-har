// On-device stairs detection from the barometer plus the accelerometer. No Arduino dependency.
//
// Air pressure falls about 12 Pa per metre of height. Climbing stairs raises the wearer
// about 0.15-0.35 m/s, i.e. a steady pressure change of roughly 2-4 Pa/s, while walking on
// the flat leaves pressure unchanged. The detector reports "up" or "down" when, for
// kConfirmMs in a row:
//   - the wearer is moving: the standard deviation of |a| over the last 2 s is at least
//     kMovingStdG (rules out standing in a lift),
//   - the pressure trend over the last kWindowMs (least-squares slope) is between
//     kMinSlopePaPerS and kMaxSlopePaPerS in size,
//   - the first and second half of the window both change in the same direction by at
//     least kHalfFraction of the threshold (rules out a single jump from a door or a fan).
// It returns to "none" after kReleaseMs without those conditions.
//
// The thresholds are estimates from physics, not tuned on recorded stairs. Treat the
// output as a hint until it has been checked on data.
#pragma once

#include <math.h>
#include <stddef.h>
#include <stdint.h>

enum class StairsState { None, Up, Down };

constexpr uint32_t kStairsWindowMs = 5000;
constexpr uint32_t kStairsMinSpanMs = 4500;     // window must be (almost) full
constexpr uint32_t kStairsMaxGapMs = 1000;      // longer pressure gap: start over
constexpr float kStairsMinSlopePaPerS = 1.2f;   // about 0.1 m/s vertical
constexpr float kStairsMaxSlopePaPerS = 10.0f;  // faster than this is not stairs
constexpr float kStairsHalfFraction = 0.5f;
constexpr float kStairsMovingStdG = 0.06f;
constexpr uint32_t kStairsConfirmMs = 2000;
constexpr uint32_t kStairsReleaseMs = 2000;

constexpr size_t kStairsPressureSlots = 64;     // > 5 s at 10 Hz
constexpr size_t kStairsMotionSamples = 100;    // 2 s at 50 Hz

class StairsDetector {
 public:
  void reset() {
    pressure_count_ = 0;
    pressure_head_ = 0;
    motion_count_ = 0;
    motion_head_ = 0;
    motion_sum_ = 0.0;
    motion_sum_sq_ = 0.0;
    state_ = StairsState::None;
    candidate_ = StairsState::None;
    releasing_ = false;
    has_last_pressure_ = false;
    slope_ = 0.0f;
  }

  // Every accelerometer sample (g), 50 Hz.
  void addAccel(float ax, float ay, float az) {
    const double magnitude = sqrt(static_cast<double>(ax) * ax + static_cast<double>(ay) * ay +
                                  static_cast<double>(az) * az);
    if (motion_count_ == kStairsMotionSamples) {
      const double old = motion_[motion_head_];
      motion_sum_ -= old;
      motion_sum_sq_ -= old * old;
    } else {
      ++motion_count_;
    }
    motion_[motion_head_] = magnitude;
    motion_sum_ += magnitude;
    motion_sum_sq_ += magnitude * magnitude;
    motion_head_ = (motion_head_ + 1) % kStairsMotionSamples;
  }

  // Every pressure reading (Pa), about 10 Hz. Returns the state after this reading.
  StairsState addPressure(float pressure_pa, uint32_t now_ms) {
    if (has_last_pressure_ && now_ms - last_pressure_ms_ > kStairsMaxGapMs) {
      pressure_count_ = 0;  // stale window: a gap in the readings
      pressure_head_ = 0;
    }
    has_last_pressure_ = true;
    last_pressure_ms_ = now_ms;
    times_[pressure_head_] = now_ms;
    pressures_[pressure_head_] = pressure_pa;
    pressure_head_ = (pressure_head_ + 1) % kStairsPressureSlots;
    if (pressure_count_ < kStairsPressureSlots) ++pressure_count_;

    const StairsState seen = evaluate(now_ms);
    if (seen != StairsState::None && seen == candidate_) {
      if (seen != state_ && now_ms - candidate_since_ms_ >= kStairsConfirmMs) state_ = seen;
    } else if (seen != candidate_) {
      candidate_ = seen;
      candidate_since_ms_ = now_ms;
    }
    if (state_ != StairsState::None && seen != state_) {
      if (!releasing_) {
        releasing_ = true;
        release_since_ms_ = now_ms;
      } else if (now_ms - release_since_ms_ >= kStairsReleaseMs) {
        state_ = StairsState::None;
        releasing_ = false;
      }
    } else {
      releasing_ = false;
    }
    return state_;
  }

  StairsState state() const { return state_; }
  float slopePaPerS() const { return slope_; }  // last full-window slope, for logging
  bool moving() const {
    if (motion_count_ < kStairsMotionSamples) return false;
    const double mean = motion_sum_ / motion_count_;
    const double variance = motion_sum_sq_ / motion_count_ - mean * mean;
    return variance > 0 && sqrt(variance) >= kStairsMovingStdG;
  }

 private:
  // Least-squares slope (Pa/s) of the readings in [from_ms, to_ms]; false if under 3 points.
  bool slope(uint32_t from_ms, uint32_t to_ms, uint32_t origin_ms, float *out) const {
    double n = 0, st = 0, sp = 0, stt = 0, stp = 0;
    for (size_t i = 0; i < pressure_count_; ++i) {
      const size_t slot = (pressure_head_ + kStairsPressureSlots - 1 - i) % kStairsPressureSlots;
      const uint32_t age = origin_ms - times_[slot];
      if (age > origin_ms - from_ms || age < origin_ms - to_ms) continue;
      const double t = -static_cast<double>(age) / 1000.0;
      const double p = pressures_[slot];
      n += 1;
      st += t;
      sp += p;
      stt += t * t;
      stp += t * p;
    }
    const double denominator = n * stt - st * st;
    if (n < 3 || denominator <= 0) return false;
    *out = static_cast<float>((n * stp - st * sp) / denominator);
    return true;
  }

  StairsState evaluate(uint32_t now_ms) {
    if (pressure_count_ < 3) return StairsState::None;
    const size_t oldest = (pressure_head_ + kStairsPressureSlots - pressure_count_) %
                          kStairsPressureSlots;
    uint32_t span = now_ms - times_[oldest];
    if (span > kStairsWindowMs) span = kStairsWindowMs;
    if (span < kStairsMinSpanMs) return StairsState::None;

    const uint32_t start = now_ms - span;
    const uint32_t middle = now_ms - span / 2;
    float whole = 0, first = 0, second = 0;
    if (!slope(start, now_ms, now_ms, &whole) || !slope(start, middle, now_ms, &first) ||
        !slope(middle, now_ms, now_ms, &second)) {
      return StairsState::None;
    }
    slope_ = whole;
    if (!moving()) return StairsState::None;
    const float size = fabsf(whole);
    if (size < kStairsMinSlopePaPerS || size > kStairsMaxSlopePaPerS) return StairsState::None;
    const float half_min = kStairsMinSlopePaPerS * kStairsHalfFraction;
    const bool rising = whole > 0;
    const bool halves_agree = rising ? (first >= half_min && second >= half_min)
                                     : (first <= -half_min && second <= -half_min);
    if (!halves_agree) return StairsState::None;
    // Pressure falls going up.
    return rising ? StairsState::Down : StairsState::Up;
  }

  uint32_t times_[kStairsPressureSlots] = {};
  float pressures_[kStairsPressureSlots] = {};
  size_t pressure_count_ = 0;
  size_t pressure_head_ = 0;
  bool has_last_pressure_ = false;
  uint32_t last_pressure_ms_ = 0;

  double motion_[kStairsMotionSamples] = {};
  size_t motion_count_ = 0;
  size_t motion_head_ = 0;
  double motion_sum_ = 0.0;
  double motion_sum_sq_ = 0.0;

  StairsState state_ = StairsState::None;
  StairsState candidate_ = StairsState::None;
  uint32_t candidate_since_ms_ = 0;
  bool releasing_ = false;
  uint32_t release_since_ms_ = 0;
  float slope_ = 0.0f;
};
