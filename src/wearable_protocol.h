// Records and commands added for the wearable, next to DATA,1 and [NET],1.
// No Arduino dependency.
//
// ESP32 -> Pi (the Pi ignores every line that does not start with DATA or [NET],
// so these do not disturb older collectors):
//   BARO,1,<stream_id>,<seq>,<time_us>,<pressure_pa>,<temp_c>
//       BMP280 reading taken right after DATA sample <seq>, about 10 per second.
//   EVT,1,<stream_id>,<time_us>,<name>,<value>
//       name: button (click), sos (long press), alert_on, alert_cancel.
//   STAT,1,<stream_id>,<time_us>,<vbat_mv>,<percent>,<rssi_dbm>,<flags>
//       every 10 s. vbat_mv 0 and percent -1 mean "no battery reading".
//       flags: 1 = barometer ok, 2 = display found, 4 = alert active, 8 = battery low.
//   stream_id is empty until the gyro calibration has finished.
//
// Pi -> ESP32, one command per line:
//   CMD,1,ACT,<label>    activity currently recognised (walk, sit, stand, lie, ...)
//   CMD,1,ALERT,<0|1>    start / stop the fall alert
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

constexpr unsigned kStatFlagBaro = 1;
constexpr unsigned kStatFlagDisplay = 2;
constexpr unsigned kStatFlagAlert = 4;
constexpr unsigned kStatFlagBatteryLow = 8;

constexpr size_t kActivityLabelMax = 16;  // including the terminator
constexpr size_t kCommandLineMax = 64;

inline int formatBaroRecord(char *out, size_t size, const char *stream_id_hex, uint32_t seq,
                            uint64_t time_us, double pressure_pa, double temp_c) {
  return snprintf(out, size, "BARO,1,%s,%lu,%llu,%.2f,%.2f", stream_id_hex,
                  static_cast<unsigned long>(seq), static_cast<unsigned long long>(time_us),
                  pressure_pa, temp_c);
}

inline int formatEventRecord(char *out, size_t size, const char *stream_id_hex,
                             uint64_t time_us, const char *name, long value) {
  return snprintf(out, size, "EVT,1,%s,%llu,%s,%ld", stream_id_hex,
                  static_cast<unsigned long long>(time_us), name, value);
}

inline int formatStatusRecord(char *out, size_t size, const char *stream_id_hex,
                              uint64_t time_us, int vbat_mv, int percent, int rssi_dbm,
                              unsigned flags) {
  return snprintf(out, size, "STAT,1,%s,%llu,%d,%d,%d,%u", stream_id_hex,
                  static_cast<unsigned long long>(time_us), vbat_mv, percent, rssi_dbm, flags);
}

struct Command {
  enum class Type { None, Activity, Alert };
  Type type = Type::None;
  char label[kActivityLabelMax] = {};  // Activity
  bool on = false;                     // Alert
};

// Parses one command line (without the newline). Returns false for anything that is
// not a well-formed CMD,1 line; *out is then left as Type::None.
inline bool parseCommand(const char *line, Command *out) {
  *out = Command{};
  static const char kPrefix[] = "CMD,1,";
  const size_t prefix_len = sizeof(kPrefix) - 1;
  if (strncmp(line, kPrefix, prefix_len) != 0) return false;
  const char *rest = line + prefix_len;

  if (strncmp(rest, "ACT,", 4) == 0) {
    const char *label = rest + 4;
    const size_t len = strlen(label);
    if (len == 0 || len >= kActivityLabelMax) return false;
    for (size_t i = 0; i < len; ++i) {
      const char c = label[i];
      const bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
      if (!ok) return false;
    }
    memcpy(out->label, label, len + 1);
    out->type = Command::Type::Activity;
    return true;
  }
  if (strncmp(rest, "ALERT,", 6) == 0) {
    const char *value = rest + 6;
    if ((value[0] != '0' && value[0] != '1') || value[1] != '\0') return false;
    out->on = value[0] == '1';
    out->type = Command::Type::Alert;
    return true;
  }
  return false;
}

// Collects bytes into lines. Lines longer than the buffer are dropped whole.
class LineBuffer {
 public:
  // Returns true when a complete line is ready in line(); the next push starts a new one.
  bool push(char c) {
    if (ready_) {
      len_ = 0;
      ready_ = false;
    }
    if (c == '\r') return false;
    if (c == '\n') {
      const bool usable = !overflow_ && len_ > 0;
      overflow_ = false;
      if (!usable) {
        len_ = 0;
        return false;
      }
      buf_[len_] = '\0';
      ready_ = true;
      return true;
    }
    if (overflow_) return false;
    if (len_ >= kCommandLineMax - 1) {
      overflow_ = true;
      len_ = 0;
      return false;
    }
    buf_[len_++] = c;
    return false;
  }

  const char *line() const { return buf_; }

 private:
  char buf_[kCommandLineMax] = {};
  size_t len_ = 0;
  bool overflow_ = false;
  bool ready_ = false;
};
