#include "../src/button.h"
#include <cstdio>

namespace {
int failures = 0;

void check(bool condition, const char *name) {
  std::printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) ++failures;
}

// Feeds the same raw level every millisecond; returns the number of events seen.
int run(Button &button, bool level, uint32_t from_ms, uint32_t to_ms, ButtonEvent *events,
        int max_events) {
  int count = 0;
  for (uint32_t t = from_ms; t < to_ms; ++t) {
    const ButtonEvent event = button.update(level, t);
    if (event != ButtonEvent::None && count < max_events) events[count++] = event;
  }
  return count;
}
}

int main() {
  ButtonEvent events[8];

  Button click(30, 2000);
  check(run(click, false, 0, 100, events, 8) == 0, "idle button reports nothing");
  int n = run(click, true, 100, 300, events, 8);
  check(n == 1 && events[0] == ButtonEvent::Down, "press reports Down once");
  check(click.pressed(), "pressed() is true while held");
  n = run(click, false, 300, 500, events, 8);
  check(n == 1 && events[0] == ButtonEvent::Click, "short release reports Click");
  check(!click.pressed(), "pressed() is false after release");

  Button bounce(30, 2000);
  n = 0;
  for (uint32_t t = 0; t < 25; ++t) {  // chatter shorter than the debounce time
    if (bounce.update(t % 2 == 0, t) != ButtonEvent::None) ++n;
  }
  check(n == 0, "contact bounce is ignored");
  n = run(bounce, true, 25, 80, events, 8);
  check(n == 1 && events[0] == ButtonEvent::Down, "stable level after bounce reports Down");

  Button glitch(30, 2000);
  n = run(glitch, true, 0, 20, events, 8);
  n += run(glitch, false, 20, 200, events, 8);
  check(n == 0, "pulse shorter than debounce is ignored");

  Button hold(30, 2000);
  n = run(hold, true, 0, 2500, events, 8);
  check(n == 2 && events[0] == ButtonEvent::Down && events[1] == ButtonEvent::LongPress,
        "holding reports Down then LongPress once");
  n = run(hold, false, 2500, 2700, events, 8);
  check(n == 0, "release after a long press reports no Click");
  n = run(hold, true, 2700, 2800, events, 8);
  n += run(hold, false, 2800, 2900, events + n, 8 - n);
  check(n == 2 && events[0] == ButtonEvent::Down && events[1] == ButtonEvent::Click,
        "button works again after a long press");

  Button wrap(30, 2000);
  const uint32_t near_wrap = 0xFFFFFFF0u;
  n = 0;
  for (uint32_t i = 0; i < 100; ++i) {
    if (wrap.update(true, near_wrap + i) == ButtonEvent::Down) ++n;
  }
  check(n == 1, "debounce survives millis() wrap-around");

  return failures == 0 ? 0 : 1;
}
