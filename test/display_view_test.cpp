#include "../src/display_view.h"
#include <cstdio>
#include <cstring>

namespace {
int failures = 0;

void check(bool condition, const char *name) {
  std::printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) ++failures;
}

bool eq(const char *a, const char *b) { return std::strcmp(a, b) == 0; }

DisplayInput streaming() {
  DisplayInput in;
  in.sensor = SensorState::Streaming;
  in.link = LinkState::ClientConnected;
  in.activity = "walk";
  in.battery_valid = true;
  in.battery_percent = 78;
  in.battery_mv = 3987;
  in.battery_level = 4;
  in.ssid = "NhaMinh";
  in.rssi_dbm = -61;
  in.ip = "192.168.1.23";
  in.port = 8765;
  return in;
}
}

int main() {
  char name[kDisplayTitleMax];
  activityDisplayName("walk", name, sizeof(name));
  check(eq(name, "DI BO"), "walk -> DI BO");
  activityDisplayName("sit", name, sizeof(name));
  check(eq(name, "NGOI"), "sit -> NGOI");
  activityDisplayName("stand", name, sizeof(name));
  check(eq(name, "DUNG"), "stand -> DUNG");
  activityDisplayName("lie", name, sizeof(name));
  check(eq(name, "NAM"), "lie -> NAM");
  activityDisplayName("stairs_down", name, sizeof(name));
  check(eq(name, "XUONG THANG"), "stairs_down -> XUONG THANG");
  activityDisplayName("run_fast", name, sizeof(name));
  check(eq(name, "RUN FAST"), "unknown label is upper-cased, underscore becomes space");
  activityDisplayName("abcdefghijklmno", name, sizeof(name));
  check(std::strlen(name) == kDisplayTitleMax - 1, "long unknown label is cut to the title width");

  DisplayView view;
  DisplayInput in = streaming();
  buildDisplayView(in, &view);
  check(eq(view.title, "DI BO") && !view.invert_title, "streaming: title is the activity");
  check(eq(view.lines[0], "Pin 78% 3.98V"), "battery line with percent and volts");
  check(eq(view.lines[1], "NhaMinh -61dBm"), "Wi-Fi line with SSID and RSSI");
  check(eq(view.lines[2], "Pi4: da ket noi"), "third line says the Pi is connected");
  check(view.battery_level == 4, "battery bars are passed through");

  in.battery_mv = 4005;
  buildDisplayView(in, &view);
  check(eq(view.lines[0], "Pin 78% 4.00V"), "volts keep the leading zero of the decimals");

  in = streaming();
  in.activity = "";
  buildDisplayView(in, &view);
  check(eq(view.title, "--"), "no activity yet: placeholder title");

  in = streaming();
  in.battery_valid = false;
  buildDisplayView(in, &view);
  check(eq(view.lines[0], "Pin --") && view.battery_level == -1, "no battery reading");

  in = streaming();
  in.link = LinkState::WifiNoClient;
  buildDisplayView(in, &view);
  check(eq(view.lines[2], "192.168.1.23:8765"), "waiting for the Pi: show where to connect");

  in.link = LinkState::WifiDown;
  buildDisplayView(in, &view);
  check(eq(view.lines[1], "WiFi: mat ket noi") && eq(view.lines[2], ""),
        "Wi-Fi down: say so, no address");

  in.link = LinkState::UsbOnly;
  buildDisplayView(in, &view);
  check(eq(view.lines[1], "USB"), "USB build: link line says USB");

  in = streaming();
  in.sensor = SensorState::Calibrating;
  buildDisplayView(in, &view);
  check(eq(view.title, "HIEU CHINH") && eq(view.lines[2], "Giu yen 7 giay"),
        "calibrating: title and hold-still hint");

  in.sensor = SensorState::Error;
  buildDisplayView(in, &view);
  check(eq(view.title, "LOI CAM BIEN"), "sensor error title");

  in.sensor = SensorState::Starting;
  buildDisplayView(in, &view);
  check(eq(view.title, "KHOI DONG"), "starting title");

  in = streaming();
  in.alert_active = true;
  in.sos_notice = true;
  buildDisplayView(in, &view);
  check(eq(view.title, "CANH BAO TE") && view.invert_title && eq(view.lines[2], "Nhan nut de huy"),
        "alert: banner and cancel hint, above everything else");

  in = streaming();
  in.sos_notice = true;
  buildDisplayView(in, &view);
  check(eq(view.title, "DA GUI SOS") && view.invert_title, "SOS notice banner");

  in = streaming();
  in.ssid = "MotTenWifiRatLaDaiDaiDai";
  in.rssi_dbm = -100;
  in.ip = "255.255.255.255";
  in.port = 65535;
  in.battery_percent = 100;
  in.battery_mv = 4200;
  in.link = LinkState::WifiNoClient;
  buildDisplayView(in, &view);
  bool fits = true;
  for (const char *line : view.lines) fits = fits && std::strlen(line) <= kDisplayLineMax - 1;
  check(fits, "worst-case lines fit the 21-character width");
  check(eq(view.lines[1], "MotTenWifiR -100dBm"), "long SSID is cut, RSSI stays visible");
  check(eq(view.lines[2], "255.255.255.255:65535"), "longest address fits exactly");

  return failures == 0 ? 0 : 1;
}
