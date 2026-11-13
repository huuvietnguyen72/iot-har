// On-device fall suspicion from the accelerometer alone. No Arduino dependency.
//
// Rule: a hard impact, then the wearer is lying and still.
//   1. Impact: |a| reaches kImpactG.
//   2. Settle: ignore the next kSettleMs (bouncing, rolling).
//   3. Observe kObserveMs: every sample must be still (|a| close to 1 g) and the
//      device's Y axis, which points down when the wearer is upright, must be far
//      from vertical (|ay| below kLyingMaxAyG, i.e. tilted more than about 60 degrees).
// Sitting down hard or jumping gives an impact but ends upright, so it is dropped.
// Lying down gently has no impact. Dropping onto a bed can still trigger it; the wearer
// cancels with the button.
//
// The thresholds are starting values taken from common practice, not tuned on recorded
// falls. Treat a detection as "suspected fall" until it has been validated on data.
#pragma once

#include <math.h>
#include <stdint.h>

constexpr float kImpactG = 2.5f;
constexpr uint32_t kSettleMs = 1000;
constexpr uint32_t kObserveMs = 2000;
constexpr float kStillMinG = 0.75f;
constexpr float kStillMaxG = 1.25f;
constexpr float kLyingMaxAyG = 0.5f;

class FallDetector {
 public:
  void reset() { state_ = State::Idle; }

  // Feed every accelerometer sample (g). Returns true once per suspected fall.
  bool update(float ax, float ay, float az, uint32_t now_ms) {
    const float magnitude = sqrtf(ax * ax + ay * ay + az * az);
    switch (state_) {
      case State::Idle:
        if (magnitude >= kImpactG) {
          state_ = State::Settling;
          since_ms_ = now_ms;
        }
        return false;
      case State::Settling:
        if (magnitude >= kImpactG) {
          since_ms_ = now_ms;  // still tumbling: restart the settle time
        } else if (now_ms - since_ms_ >= kSettleMs) {
          state_ = State::Observing;
          since_ms_ = now_ms;
        }
        return false;
      case State::Observing: {
        if (magnitude >= kImpactG) {
          state_ = State::Settling;
          since_ms_ = now_ms;
          return false;
        }
        const bool still = magnitude >= kStillMinG && magnitude <= kStillMaxG;
        const bool lying = fabsf(ay) <= kLyingMaxAyG;
        if (!still || !lying) {
          state_ = State::Idle;  // moving or upright: the wearer is fine
          return false;
        }
        if (now_ms - since_ms_ >= kObserveMs) {
          state_ = State::Idle;
          return true;
        }
        return false;
      }
    }
    return false;
  }

  bool watching() const { return state_ != State::Idle; }

 private:
  enum class State { Idle, Settling, Observing };
  State state_ = State::Idle;
  uint32_t since_ms_ = 0;
};
