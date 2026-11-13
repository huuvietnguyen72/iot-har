#include "../src/wearable_protocol.h"
#include <cstdio>
#include <cstring>

namespace {
int failures = 0;

void check(bool condition, const char *name) {
  std::printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) ++failures;
}

void feed(LineBuffer &buffer, const char *text, char *last, size_t size, int *lines) {
  for (const char *p = text; *p != '\0'; ++p) {
    if (buffer.push(*p)) {
      std::snprintf(last, size, "%s", buffer.line());
      ++*lines;
    }
  }
}
}

int main() {
  char out[160];

  formatBaroRecord(out, sizeof(out), "0123456789abcdef", 42, 1234567ULL, 100812.4375, 28.41);
  check(std::strcmp(out, "BARO,1,0123456789abcdef,42,1234567,100812.44,28.41") == 0,
        "BARO record format");
  formatBaroRecord(out, sizeof(out), "0123456789abcdef", 4294967295UL, 18446744073709551615ULL,
                   110000.0, -40.0);
  check(std::strcmp(out,
                    "BARO,1,0123456789abcdef,4294967295,18446744073709551615,110000.00,-40.00") ==
            0,
        "BARO record keeps full-range seq and time");

  formatEventRecord(out, sizeof(out), "0123456789abcdef", 99ULL, "button", 3);
  check(std::strcmp(out, "EVT,1,0123456789abcdef,99,button,3") == 0, "EVT record format");
  formatEventRecord(out, sizeof(out), "", 99ULL, "sos", 1);
  check(std::strcmp(out, "EVT,1,,99,sos,1") == 0, "EVT record before calibration has empty id");

  formatStatusRecord(out, sizeof(out), "0123456789abcdef", 5000000ULL, 3987, 78, -61,
                     kStatFlagBaro | kStatFlagDisplay);
  check(std::strcmp(out, "STAT,1,0123456789abcdef,5000000,3987,78,-61,3") == 0,
        "STAT record format");
  formatStatusRecord(out, sizeof(out), "0123456789abcdef", 1ULL, 0, -1, 0, 0);
  check(std::strcmp(out, "STAT,1,0123456789abcdef,1,0,-1,0,0") == 0,
        "STAT record without a battery reading");
  check(std::strncmp(out, "DATA", 4) != 0 && std::strncmp(out, "[NET]", 5) != 0,
        "new records never look like DATA or [NET] lines");

  char small[10];
  const int needed = formatEventRecord(small, sizeof(small), "0123456789abcdef", 1ULL, "sos", 1);
  check(needed > static_cast<int>(sizeof(small)) && small[sizeof(small) - 1] == '\0',
        "formatting into a short buffer truncates safely");

  Command cmd;
  check(parseCommand("CMD,1,ACT,walk", &cmd) && cmd.type == Command::Type::Activity &&
            std::strcmp(cmd.label, "walk") == 0,
        "ACT command with a label");
  check(parseCommand("CMD,1,ACT,stairs_down", &cmd) && std::strcmp(cmd.label, "stairs_down") == 0,
        "ACT label may contain underscores");
  check(parseCommand("CMD,1,ACT,abcdefghijklmno", &cmd), "15-character label is accepted");
  check(!parseCommand("CMD,1,ACT,abcdefghijklmnop", &cmd) && cmd.type == Command::Type::None,
        "16-character label is rejected");
  check(!parseCommand("CMD,1,ACT,", &cmd), "empty label is rejected");
  check(!parseCommand("CMD,1,ACT,Walk", &cmd), "upper-case label is rejected");
  check(!parseCommand("CMD,1,ACT,walk,extra", &cmd), "label with a comma is rejected");
  check(!parseCommand("CMD,1,ACT,wa lk", &cmd), "label with a space is rejected");

  check(parseCommand("CMD,1,ALERT,1", &cmd) && cmd.type == Command::Type::Alert && cmd.on,
        "ALERT,1 turns the alert on");
  check(parseCommand("CMD,1,ALERT,0", &cmd) && cmd.type == Command::Type::Alert && !cmd.on,
        "ALERT,0 turns the alert off");
  check(!parseCommand("CMD,1,ALERT,2", &cmd), "ALERT value other than 0/1 is rejected");
  check(!parseCommand("CMD,1,ALERT,10", &cmd), "ALERT value with trailing text is rejected");
  check(!parseCommand("CMD,1,ALERT,", &cmd), "ALERT without a value is rejected");

  check(!parseCommand("CMD,2,ACT,walk", &cmd), "other protocol version is rejected");
  check(!parseCommand("CMD,1,REBOOT,1", &cmd), "unknown command is rejected");
  check(!parseCommand("DATA,1,x", &cmd), "non-command line is rejected");
  check(!parseCommand("", &cmd), "empty line is rejected");

  LineBuffer buffer;
  char last[kCommandLineMax] = {};
  int lines = 0;
  feed(buffer, "CMD,1,ACT,sit\n", last, sizeof(last), &lines);
  check(lines == 1 && std::strcmp(last, "CMD,1,ACT,sit") == 0, "one line in, one line out");
  feed(buffer, "CMD,1,ALERT,1\r\n", last, sizeof(last), &lines);
  check(lines == 2 && std::strcmp(last, "CMD,1,ALERT,1") == 0, "CRLF line endings are accepted");
  feed(buffer, "CMD,1,", last, sizeof(last), &lines);
  check(lines == 2, "partial line is not reported");
  feed(buffer, "ACT,lie\nCMD,1,ACT,walk\n", last, sizeof(last), &lines);
  check(lines == 4 && std::strcmp(last, "CMD,1,ACT,walk") == 0,
        "lines split across reads are joined; two lines in one read both arrive");
  feed(buffer, "\n\n", last, sizeof(last), &lines);
  check(lines == 4, "blank lines are skipped");

  char longLine[200];
  std::memset(longLine, 'x', sizeof(longLine));
  longLine[sizeof(longLine) - 2] = '\n';
  longLine[sizeof(longLine) - 1] = '\0';
  feed(buffer, longLine, last, sizeof(last), &lines);
  check(lines == 4, "over-long line is dropped whole");
  feed(buffer, "CMD,1,ALERT,0\n", last, sizeof(last), &lines);
  check(lines == 5 && std::strcmp(last, "CMD,1,ALERT,0") == 0,
        "the line after an over-long one is intact");

  char maxLine[kCommandLineMax + 1];
  std::memset(maxLine, 'y', kCommandLineMax - 1);
  maxLine[kCommandLineMax - 1] = '\n';
  maxLine[kCommandLineMax] = '\0';
  feed(buffer, maxLine, last, sizeof(last), &lines);
  check(lines == 6 && std::strlen(last) == kCommandLineMax - 1,
        "a line that exactly fills the buffer is kept");

  return failures == 0 ? 0 : 1;
}
