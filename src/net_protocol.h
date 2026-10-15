#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static constexpr size_t kNetRecordMax = 160;
static constexpr size_t kNetQueueCapacity = 100;

struct NetCounters {
  uint32_t queue_dropped_total = 0;
  uint32_t unobserved_total = 0;
};

template <size_t Capacity, size_t RecordMax = kNetRecordMax>
class RecordQueueT {
 public:
  void push(const char *record, size_t len) {
    if (len >= RecordMax) len = RecordMax - 1;
    if (count_ == Capacity) {
      head_ = (head_ + 1) % Capacity;
      --count_;
      ++counters_.queue_dropped_total;
    }
    memcpy(slots_[tail_], record, len);
    slots_[tail_][len] = '\0';
    lengths_[tail_] = static_cast<uint8_t>(len);
    tail_ = (tail_ + 1) % Capacity;
    ++count_;
  }

  bool pop(char *out, size_t out_size) {
    if (count_ == 0 || out_size == 0) return false;
    size_t len = lengths_[head_];
    if (len > out_size - 1) len = out_size - 1;
    memcpy(out, slots_[head_], len);
    out[len] = '\0';
    head_ = (head_ + 1) % Capacity;
    --count_;
    return true;
  }

  size_t size() const { return count_; }

  void clear() {
    counters_.unobserved_total += static_cast<uint32_t>(count_);
    head_ = 0;
    tail_ = 0;
    count_ = 0;
  }

  const NetCounters &counters() const { return counters_; }

  void count_unobserved(size_t n) {
    counters_.unobserved_total += static_cast<uint32_t>(n);
  }

  void resetCounters() { counters_ = NetCounters{}; }

 private:
  char slots_[Capacity][RecordMax];
  uint8_t lengths_[Capacity];
  size_t head_ = 0;
  size_t tail_ = 0;
  size_t count_ = 0;
  NetCounters counters_;
};

using RecordQueue = RecordQueueT<kNetQueueCapacity>;

inline int formatNetLine(char *out, size_t size, const char *stream_id_hex,
                         const NetCounters &counters) {
  return snprintf(out, size, "[NET],1,%s,%lu,%lu", stream_id_hex,
                  static_cast<unsigned long>(counters.queue_dropped_total),
                  static_cast<unsigned long>(counters.unobserved_total));
}
