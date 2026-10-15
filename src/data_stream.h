#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

struct StreamSample {
  uint32_t seq = 0;
  uint64_t time_us = 0;
  float ax = 0.0f;
  float ay = 0.0f;
  float az = 0.0f;
  float gx = 0.0f;
  float gy = 0.0f;
  float gz = 0.0f;
  float temp_c = 0.0f;
};

inline void formatStreamId(char *out, size_t size, uint64_t value) {
  snprintf(out, size, "%016llx", static_cast<unsigned long long>(value));
}

inline int formatDataRecord(char *out, size_t size, const char *stream_id_hex,
                            const StreamSample &sample) {
  return snprintf(out, size,
                  "DATA,1,%s,%lu,%llu,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.2f",
                  stream_id_hex, static_cast<unsigned long>(sample.seq),
                  static_cast<unsigned long long>(sample.time_us),
                  static_cast<double>(sample.ax), static_cast<double>(sample.ay),
                  static_cast<double>(sample.az), static_cast<double>(sample.gx),
                  static_cast<double>(sample.gy), static_cast<double>(sample.gz),
                  static_cast<double>(sample.temp_c));
}

class EmitSchedule {
 public:
  explicit EmitSchedule(uint32_t interval_ms) : interval_ms_(interval_ms) {}

  void start(uint32_t now_ms) {
    started_ = true;
    last_ms_ = now_ms - interval_ms_;
  }

  bool due(uint32_t now_ms) const {
    return started_ && (now_ms - last_ms_) >= interval_ms_;
  }

  void onEmit(uint32_t now_ms) { last_ms_ = now_ms; }

 private:
  uint32_t interval_ms_;
  uint32_t last_ms_ = 0;
  bool started_ = false;
};
