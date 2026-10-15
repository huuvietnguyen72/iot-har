#include "../src/data_stream.h"
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
  char id[17];
  formatStreamId(id, sizeof(id), 0x7a31b25c809fd416ULL);
  check(std::strcmp(id, "7a31b25c809fd416") == 0, "formatStreamId prints 16 lowercase hex digits");
  formatStreamId(id, sizeof(id), 0);
  check(std::strcmp(id, "0000000000000000") == 0, "formatStreamId pads to 16 digits");

  StreamSample sample;
  sample.seq = 12;
  sample.time_us = 8340000ULL;
  sample.ax = 0.5f;
  sample.ay = -0.25f;
  sample.az = 1.0f;
  sample.gx = 0.125f;
  sample.gy = -0.125f;
  sample.gz = 0.0f;
  sample.temp_c = 29.5f;

  char record[160];
  const int length = formatDataRecord(record, sizeof(record), "7a31b25c809fd416", sample);
  check(std::strcmp(record,
                    "DATA,1,7a31b25c809fd416,12,8340000,0.500,-0.250,1.000,"
                    "0.125,-0.125,0.000,29.50") == 0,
        "formatDataRecord emits protocol v1 record");
  check(length == static_cast<int>(std::strlen(record)),
        "formatDataRecord returns the record length");

  char tiny[10];
  formatDataRecord(tiny, sizeof(tiny), "7a31b25c809fd416", sample);
  check(std::strcmp(tiny, "DATA,1,7a") == 0, "formatDataRecord truncates safely");

  EmitSchedule schedule(20);
  check(!schedule.due(100), "schedule is not due before start");
  schedule.start(1000);
  check(schedule.due(1000), "schedule is due immediately after start");
  schedule.onEmit(1000);
  check(!schedule.due(1019), "schedule is not due one millisecond early");
  check(schedule.due(1020), "schedule is due at the interval");
  schedule.onEmit(1020);
  check(schedule.due(1100), "schedule is due when the loop is late");
  schedule.onEmit(1100);
  check(!schedule.due(1101), "no catch-up burst after a late emit");
  check(schedule.due(1120), "cadence continues from the late emit");

  EmitSchedule wrap(20);
  wrap.start(10);
  check(!wrap.due(0x00000005u), "schedule wraps without false due");
  check(wrap.due(0x0000000Au), "schedule wraps at the interval");

  std::printf("%d failure(s)\n", failures);
  return failures == 0 ? 0 : 1;
}
