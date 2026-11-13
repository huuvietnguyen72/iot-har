#include "../src/stairs_detector.h"
#include <cmath>
#include <cstdio>

namespace {
int failures = 0;

void check(bool condition, const char *name) {
  std::printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) ++failures;
}

// Simulates the firmware: accelerometer at 50 Hz, a pressure reading after every 5th sample.
struct Sim {
  StairsDetector detector;
  uint32_t now = 0;
  uint32_t seq = 0;
  double pressure = 100000.0;
  uint32_t noise_state = 12345;
  int ups = 0, downs = 0;  // number of transitions into each state
  StairsState last = StairsState::None;
  uint32_t first_up_ms = 0, first_down_ms = 0;

  // Deterministic noise, uniform in [-amplitude, amplitude].
  double noise(double amplitude) {
    noise_state = noise_state * 1103515245u + 12345u;
    return ((noise_state >> 8) % 20001 / 10000.0 - 1.0) * amplitude;
  }

  // slope_pa_s: pressure change per second; walking: gait-like |a| swing, else still.
  void run(uint32_t ms, double slope_pa_s, bool walking, double noise_pa = 1.5,
           bool baro = true) {
    for (uint32_t t = 0; t < ms; t += 20) {
      const double phase = 2 * 3.14159265358979 * 1.8 * now / 1000.0;  // 1.8 steps per second
      const float swing = walking ? static_cast<float>(0.25 * std::sin(phase)) : 0.0f;
      detector.addAccel(0.02f, -1.0f - swing, 0.03f);
      pressure += slope_pa_s * 0.02;
      if (baro && seq % 5 == 0) {
        const StairsState s =
            detector.addPressure(static_cast<float>(pressure + noise(noise_pa)), now);
        if (s != last) {
          if (s == StairsState::Up && ups++ == 0) first_up_ms = now;
          if (s == StairsState::Down && downs++ == 0) first_down_ms = now;
          last = s;
        }
      }
      ++seq;
      now += 20;
    }
  }
};
}

int main() {
  {
    Sim s;
    s.run(30000, 0.0, true);
    check(s.ups == 0 && s.downs == 0, "walking on the flat: nothing");
  }
  {
    Sim s;
    s.run(5000, 0.0, true);
    const uint32_t start = s.now;
    s.run(15000, -3.0, true);  // climbing about 0.25 m/s
    check(s.ups == 1 && s.downs == 0, "climbing stairs: reported as up once");
    check(s.first_up_ms - start <= 8000, "up is reported within 8 s of starting to climb");
    check(s.detector.slopePaPerS() < -2.0f, "the measured slope is close to the true -3 Pa/s");
    s.run(10000, 0.0, true);
    check(s.last == StairsState::None, "walking on the landing ends the stairs state");
    check(s.ups == 1, "and up is not reported again");
  }
  {
    Sim s;
    s.run(5000, 0.0, true);
    s.run(15000, 3.0, true);
    check(s.downs == 1 && s.ups == 0, "going down stairs: reported as down");
  }
  {
    Sim s;
    s.run(5000, 0.0, false);
    s.run(15000, -3.0, false);
    s.run(15000, -12.0, false);
    check(s.ups == 0 && s.downs == 0, "standing in a lift (pressure changes, no steps): nothing");
  }
  {
    Sim s;
    s.run(5000, 0.0, true);
    s.run(15000, -0.6, true);
    check(s.ups == 0, "a slow drift below the threshold: nothing");
  }
  {
    Sim s;
    s.run(5000, 0.0, true);
    s.run(15000, -15.0, true);
    check(s.ups == 0, "a change too fast for stairs: nothing");
  }
  {
    Sim s;
    s.run(8000, 0.0, true);
    s.pressure -= 8.0;  // a door slams or a fan starts: one jump
    s.run(12000, 0.0, true);
    check(s.ups == 0 && s.downs == 0, "a single pressure jump while walking: nothing");
  }
  {
    Sim s;
    s.run(5000, 0.0, true);
    s.run(1500, -3.0, true);
    s.run(10000, 0.0, true);
    check(s.ups == 0, "a 1.5 s ramp is shorter than the confirmation time: nothing");
  }
  {
    Sim s;
    s.run(5000, 0.0, true);
    s.run(3000, -3.0, true, 1.5, true);
    s.run(3000, -3.0, true, 1.5, false);  // barometer silent for 3 s
    const int before = s.ups;
    s.run(2000, -3.0, true);
    check(before == 0 && s.ups == 0, "a gap in pressure readings restarts the window");
    s.run(10000, -3.0, true);
    check(s.ups == 1, "detection resumes once the window is full again");
  }
  {
    Sim s;
    s.run(5000, 0.0, true);
    s.run(15000, -3.0, true);
    s.detector.reset();
    check(s.detector.state() == StairsState::None, "reset() clears the state");
  }
  {
    Sim s;
    s.now = 0xFFFFC000u;  // millis() wraps during the climb
    s.run(5000, 0.0, true);
    s.run(15000, -3.0, true);
    check(s.ups == 1, "timing survives millis() wrap-around");
  }
  {
    Sim s;
    s.run(5000, 0.0, true);
    s.run(15000, -3.0, true, 3.0);
    check(s.ups == 1, "still detected with twice the expected sensor noise");
  }

  return failures == 0 ? 0 : 1;
}
