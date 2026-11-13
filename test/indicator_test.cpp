#include "../src/indicator.h"
#include <cstdio>

namespace {
int failures = 0;

void check(bool condition, const char *name) {
  std::printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) ++failures;
}

struct Duty {
  int green = 0, red = 0, buzzer = 0, motor = 0;
};

// Milliseconds each output is on during [0, span_ms).
Duty duty(const IndicatorInput &in, uint32_t span_ms) {
  Duty d;
  for (uint32_t t = 0; t < span_ms; ++t) {
    const IndicatorOutput out = computeIndicator(in, t);
    d.green += out.green;
    d.red += out.red;
    d.buzzer += out.buzzer;
    d.motor += out.motor;
  }
  return d;
}
}

int main() {
  IndicatorInput in;

  in.sensor = SensorState::Streaming;
  in.link = LinkState::ClientConnected;
  Duty d = duty(in, 6000);
  check(d.green == 300 && d.red == 0, "streaming to the Pi: short green flash every 2 s");
  check(d.buzzer == 0 && d.motor == 0, "streaming: buzzer and motor stay off");

  in.link = LinkState::UsbOnly;
  d = duty(in, 6000);
  check(d.green == 300 && d.red == 0, "USB streaming looks the same as streaming to the Pi");

  in.link = LinkState::WifiNoClient;
  d = duty(in, 6000);
  check(d.green == 3000 && d.red == 0, "Wi-Fi up, no client: green blinks slowly");

  in.link = LinkState::WifiDown;
  d = duty(in, 6000);
  check(d.green == 0 && d.red == 3000, "Wi-Fi down: red blinks slowly, green off");

  in = IndicatorInput{};
  in.sensor = SensorState::Calibrating;
  in.link = LinkState::WifiNoClient;
  d = duty(in, 1000);
  check(d.green == 500 && d.red == 0, "calibrating: green blinks fast");
  check(computeIndicator(in, 0).green && !computeIndicator(in, 125).green &&
            computeIndicator(in, 250).green,
        "calibrating blink period is 250 ms");

  in = IndicatorInput{};
  in.sensor = SensorState::Error;
  in.link = LinkState::ClientConnected;
  d = duty(in, 3000);
  check(d.red == 3000 && d.green == 0, "sensor error: red solid, green off");

  in = IndicatorInput{};
  in.sensor = SensorState::Streaming;
  in.link = LinkState::ClientConnected;
  in.battery_low = true;
  d = duty(in, 6000);
  check(d.red == 400 && d.green == 300, "battery low: red double flash, green keeps its flash");

  in.link = LinkState::WifiDown;
  d = duty(in, 6000);
  check(d.red == 3000, "Wi-Fi down takes priority over the battery flash");

  in = IndicatorInput{};
  in.sensor = SensorState::Streaming;
  in.link = LinkState::ClientConnected;
  in.alert_active = true;
  in.alert_sounding = true;
  d = duty(in, 1000);
  check(d.red == 500 && d.green == 0, "alert: red blinks fast, green off");
  check(d.buzzer == 500 && d.motor == 500, "alert: buzzer and motor pulse");
  in.alert_sounding = false;
  d = duty(in, 1000);
  check(d.red == 500 && d.buzzer == 0 && d.motor == 0, "alert after timeout: light only");

  in = IndicatorInput{};
  in.sensor = SensorState::Error;
  in.alert_active = true;
  in.alert_sounding = true;
  check(duty(in, 1000).buzzer == 500, "alert overrides the sensor-error display");

  Alert alert;
  check(!alert.active() && !alert.sounding(0), "alert starts inactive");
  check(!alert.clear(), "clearing an inactive alert reports false");
  check(alert.start(1000), "start reports a new alert");
  check(!alert.start(5000), "start while active is ignored");
  check(alert.active() && alert.sounding(1000) && alert.sounding(60999),
        "alert sounds for the first 60 s");
  check(alert.active() && !alert.sounding(61000), "alert stays active but silent after 60 s");
  check(alert.clear() && !alert.active(), "clear ends the alert");
  check(alert.start(70000) && alert.sounding(70001), "a new alert sounds again");

  Alert wrap;
  wrap.start(0xFFFFFF00u);
  check(wrap.sounding(0x00000100u), "alert timing survives millis() wrap-around");

  return failures == 0 ? 0 : 1;
}
