#include "../src/fall_detector.h"
#include <cstdio>

namespace {
int failures = 0;

void check(bool condition, const char *name) {
  std::printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) ++failures;
}

struct Sim {
  FallDetector detector;
  uint32_t now = 0;
  int detections = 0;

  // Feeds a constant acceleration at 50 Hz for duration_ms.
  void hold(float ax, float ay, float az, uint32_t duration_ms) {
    for (uint32_t t = 0; t < duration_ms; t += 20) {
      if (detector.update(ax, ay, az, now)) ++detections;
      now += 20;
    }
  }
  void upright(uint32_t ms) { hold(0.02f, -0.98f, 0.04f, ms); }
  void lying(uint32_t ms) { hold(0.05f, 0.10f, 0.99f, ms); }
  void impact() { hold(1.5f, -2.5f, 1.0f, 40); }  // |a| about 3.1 g
};
}

int main() {
  {
    Sim s;
    s.upright(5000);
    check(s.detections == 0 && !s.detector.watching(), "standing still: nothing");
  }
  {
    Sim s;
    s.upright(2000);
    s.impact();
    check(s.detector.watching(), "impact starts the watch");
    s.lying(2900);
    check(s.detections == 0, "no detection before settle + observe time has passed");
    s.lying(400);
    check(s.detections == 1, "impact, then lying still: one suspected fall");
    s.lying(10000);
    check(s.detections == 1, "staying down does not report again");
  }
  {
    Sim s;
    s.upright(2000);
    s.impact();
    s.upright(5000);
    check(s.detections == 0 && !s.detector.watching(),
          "impact, then upright (sat down hard, jumped): dropped");
  }
  {
    Sim s;
    s.upright(2000);
    s.lying(10000);
    check(s.detections == 0, "lying down without an impact: nothing");
  }
  {
    Sim s;
    s.upright(2000);
    s.impact();
    s.lying(1200);
    s.hold(0.3f, 0.2f, 1.6f, 200);  // moving: getting up
    s.lying(5000);
    check(s.detections == 0, "movement during the observation window cancels the watch");
  }
  {
    Sim s;
    s.upright(2000);
    s.impact();
    s.lying(600);
    s.impact();  // second bump while tumbling restarts the settle time
    s.lying(2900);
    check(s.detections == 0, "a second impact restarts the timing");
    s.lying(400);
    check(s.detections == 1, "and the fall is still reported afterwards");
  }
  {
    Sim s;
    s.upright(1000);
    s.hold(0.0f, -2.4f, 0.0f, 100);  // just under the threshold
    s.lying(5000);
    check(s.detections == 0, "a bump below the impact threshold is ignored");
  }
  {
    Sim s;
    s.upright(1000);
    s.impact();
    s.hold(0.60f, -0.75f, 0.25f, 5000);  // leaning about 40 degrees, still mostly upright
    check(s.detections == 0, "leaning but not lying is not a fall");
  }
  {
    Sim s;
    s.now = 0xFFFFF000u;  // millis() wraps during the sequence
    s.upright(1000);
    s.impact();
    s.lying(3400);
    check(s.detections == 1, "timing survives millis() wrap-around");
  }
  {
    Sim s;
    s.upright(1000);
    s.impact();
    s.detector.reset();
    s.lying(5000);
    check(s.detections == 0 && !s.detector.watching(), "reset() abandons a watch in progress");
  }
  {
    Sim s;
    s.impact();
    s.lying(3400);
    s.upright(3000);
    s.impact();
    s.lying(3400);
    check(s.detections == 2, "a later, separate fall is reported again");
  }

  return failures == 0 ? 0 : 1;
}
