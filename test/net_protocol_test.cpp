#include "../src/net_protocol.h"
#include <cstdio>
#include <cstring>

namespace {
int failures = 0;

void check(bool condition, const char *name) {
  std::printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) ++failures;
}
}

int main() {
  RecordQueueT<4> q;

  check(q.size() == 0, "new queue is empty");
  char out[200];
  check(!q.pop(out, sizeof(out)), "pop on empty queue returns false");
  check(q.counters().queue_dropped_total == 0, "fresh queue has no drops");
  check(q.counters().unobserved_total == 0, "fresh queue has no unobserved");

  q.push("first", 5);
  q.push("second", 6);
  check(q.size() == 2, "size tracks pushes");
  check(q.pop(out, sizeof(out)) && std::strcmp(out, "first") == 0, "pop returns FIFO first");
  check(q.pop(out, sizeof(out)) && std::strcmp(out, "second") == 0, "pop returns FIFO second");
  check(q.size() == 0, "size returns to zero");

  q.push("a", 1);
  q.push("b", 1);
  q.push("c", 1);
  q.push("d", 1);
  check(q.size() == 4, "queue reaches capacity");
  q.push("e", 1);
  check(q.size() == 4, "push at capacity keeps capacity");
  check(q.counters().queue_dropped_total == 1, "overflow drops one oldest sample");
  check(q.pop(out, sizeof(out)) && std::strcmp(out, "b") == 0, "oldest sample is the one dropped");
  check(q.pop(out, sizeof(out)) && std::strcmp(out, "c") == 0, "order preserved after drop");
  check(q.pop(out, sizeof(out)) && std::strcmp(out, "d") == 0, "order preserved after drop 2");
  check(q.pop(out, sizeof(out)) && std::strcmp(out, "e") == 0, "newest sample retained");

  q.push("keep1", 5);
  q.push("keep2", 5);
  q.clear();
  check(q.size() == 0, "clear empties the queue");
  check(q.counters().unobserved_total == 2, "clear counts pending samples as unobserved");
  check(q.counters().queue_dropped_total == 1, "clear does not change dropped counter");

  q.count_unobserved(3);
  check(q.counters().unobserved_total == 5, "count_unobserved accumulates");

  RecordQueueT<2> small;
  small.push("12345", 5);
  char tiny[4];
  check(small.pop(tiny, sizeof(tiny)) && std::strcmp(tiny, "123") == 0, "pop truncates to output size");

  RecordQueueT<2, 8> trunc;
  trunc.push("0123456789", 10);
  char buf[16];
  check(trunc.pop(buf, sizeof(buf)) && std::strcmp(buf, "0123456") == 0, "push truncates to record max");

  NetCounters counters;
  counters.queue_dropped_total = 7;
  counters.unobserved_total = 12;
  char net[64];
  const int len = formatNetLine(net, sizeof(net), "7a31b25c809fd416", counters);
  check(std::strcmp(net, "[NET],1,7a31b25c809fd416,7,12") == 0, "formatNetLine emits protocol v1 net line");
  check(len == static_cast<int>(std::strlen(net)), "formatNetLine returns the line length");

  char net_tiny[8];
  formatNetLine(net_tiny, sizeof(net_tiny), "7a31b25c809fd416", counters);
  check(std::strcmp(net_tiny, "[NET],1") == 0, "formatNetLine truncates safely");

  std::printf("%d failure(s)\n", failures);
  return failures == 0 ? 0 : 1;
}
