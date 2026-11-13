// What the LEDs, buzzer and vibration motor should do for a given device state.
// Pure functions of the state and the clock, so the patterns are testable on a PC.
#pragma once

#include <stdint.h>

enum class SensorState { Starting, Calibrating, Streaming, Error };
enum class LinkState { UsbOnly, WifiDown, WifiNoClient, ClientConnected };

constexpr uint32_t kAlertSoundMs = 60000;  // buzzer gives up after this; the red LED keeps blinking

// Fall alert requested by the Pi (CMD,1,ALERT,1). Stays active until cancelled.
class Alert {
 public:
  // Returns true when this call started a new alert.
  bool start(uint32_t now_ms) {
    if (active_) return false;
    active_ = true;
    started_ms_ = now_ms;
    return true;
  }
  // Returns true when an alert was active.
  bool clear() {
    const bool was = active_;
    active_ = false;
    return was;
  }
  bool active() const { return active_; }
  bool sounding(uint32_t now_ms) const { return active_ && now_ms - started_ms_ < kAlertSoundMs; }

 private:
  bool active_ = false;
  uint32_t started_ms_ = 0;
};

struct IndicatorInput {
  SensorState sensor = SensorState::Starting;
  LinkState link = LinkState::UsbOnly;
  bool battery_low = false;
  bool alert_active = false;
  bool alert_sounding = false;
};

struct IndicatorOutput {
  bool green = false;
  bool red = false;
  bool buzzer = false;
  bool motor = false;
};

// Green: fast blink = calibrating, slow blink = Wi-Fi up but the Pi is not connected,
//        short flash every 2 s = streaming to the Pi (or over USB).
// Red:   solid = sensor error, slow blink = Wi-Fi down, double flash every 3 s = battery low.
// Alert: red blinks fast, buzzer and motor pulse; overrides everything else.
inline IndicatorOutput computeIndicator(const IndicatorInput &in, uint32_t now_ms) {
  IndicatorOutput out;
  if (in.alert_active) {
    out.red = now_ms % 250 < 125;
    out.buzzer = in.alert_sounding && now_ms % 500 < 250;
    out.motor = out.buzzer;
    return out;
  }

  const bool delivering =
      in.link == LinkState::UsbOnly || in.link == LinkState::ClientConnected;
  switch (in.sensor) {
    case SensorState::Calibrating:
      out.green = now_ms % 250 < 125;
      break;
    case SensorState::Streaming:
      if (delivering) {
        out.green = now_ms % 2000 < 100;
      } else if (in.link == LinkState::WifiNoClient) {
        out.green = now_ms % 1000 < 500;
      }
      break;
    case SensorState::Starting:
    case SensorState::Error:
      break;
  }

  if (in.sensor == SensorState::Error) {
    out.red = true;
  } else if (in.link == LinkState::WifiDown) {
    out.red = now_ms % 1000 < 500;
  } else if (in.battery_low) {
    const uint32_t phase = now_ms % 3000;
    out.red = phase < 100 || (phase >= 200 && phase < 300);
  }
  return out;
}
