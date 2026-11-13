// Decides what the 128x64 OLED shows. Builds plain text; drawing is in display.cpp.
// No Arduino dependency. Text is ASCII (Vietnamese without diacritics) so any font works.
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "indicator.h"

constexpr size_t kDisplayTitleMax = 13;  // 12 characters of the 10 px wide font
constexpr size_t kDisplayLineMax = 22;   // 21 characters of the 6 px wide font

struct DisplayInput {
  SensorState sensor = SensorState::Starting;
  LinkState link = LinkState::UsbOnly;
  const char *activity = "";    // label from the Pi; "" when none or stale
  int stairs = 0;               // on-device stairs hint: 1 up, -1 down, 0 none
  bool alert_active = false;
  bool sos_notice = false;      // just sent an SOS event
  bool battery_valid = false;
  int battery_percent = -1;
  int battery_mv = 0;
  int battery_level = -1;       // 0..4, -1 unknown
  const char *ssid = "";
  int rssi_dbm = 0;
  const char *ip = "";
  unsigned port = 0;
};

struct DisplayView {
  char title[kDisplayTitleMax] = {};
  char lines[3][kDisplayLineMax] = {};
  int battery_level = -1;
  bool invert_title = false;  // alert banner
};

// Activity label -> short screen name. Unknown labels are shown upper-cased.
inline void activityDisplayName(const char *label, char *out, size_t size) {
  struct Name {
    const char *label;
    const char *text;
  };
  static const Name kNames[] = {
      {"walk", "DI BO"},           {"sit", "NGOI"},
      {"stand", "DUNG"},           {"lie", "NAM"},
      {"stairs_up", "LEN THANG"},  {"stairs_down", "XUONG THANG"},
      {"fall", "TE NGA"},
  };
  for (const Name &name : kNames) {
    if (strcmp(label, name.label) == 0) {
      snprintf(out, size, "%s", name.text);
      return;
    }
  }
  size_t i = 0;
  for (; label[i] != '\0' && i + 1 < size; ++i) {
    const char c = label[i];
    out[i] = (c >= 'a' && c <= 'z') ? static_cast<char>(c - 'a' + 'A') : (c == '_' ? ' ' : c);
  }
  out[i] = '\0';
}

inline void buildDisplayView(const DisplayInput &in, DisplayView *view) {
  *view = DisplayView{};
  view->battery_level = in.battery_valid ? in.battery_level : -1;

  if (in.alert_active) {
    snprintf(view->title, sizeof(view->title), "CANH BAO TE");
    view->invert_title = true;
  } else if (in.sos_notice) {
    snprintf(view->title, sizeof(view->title), "DA GUI SOS");
    view->invert_title = true;
  } else if (in.sensor == SensorState::Error) {
    snprintf(view->title, sizeof(view->title), "LOI CAM BIEN");
  } else if (in.sensor == SensorState::Calibrating) {
    snprintf(view->title, sizeof(view->title), "HIEU CHINH");
  } else if (in.sensor == SensorState::Starting) {
    snprintf(view->title, sizeof(view->title), "KHOI DONG");
  } else if (in.stairs != 0) {
    // The on-device hint wins over the Pi's label: the Pi model may not know stairs.
    activityDisplayName(in.stairs > 0 ? "stairs_up" : "stairs_down", view->title,
                        sizeof(view->title));
  } else if (in.activity[0] != '\0') {
    activityDisplayName(in.activity, view->title, sizeof(view->title));
  } else {
    snprintf(view->title, sizeof(view->title), "--");
  }

  if (in.battery_valid) {
    snprintf(view->lines[0], kDisplayLineMax, "Pin %d%% %d.%02dV", in.battery_percent,
             in.battery_mv / 1000, (in.battery_mv % 1000) / 10);
  } else {
    snprintf(view->lines[0], kDisplayLineMax, "Pin --");
  }

  switch (in.link) {
    case LinkState::UsbOnly:
      snprintf(view->lines[1], kDisplayLineMax, "USB");
      break;
    case LinkState::WifiDown:
      snprintf(view->lines[1], kDisplayLineMax, "WiFi: mat ket noi");
      break;
    case LinkState::WifiNoClient:
    case LinkState::ClientConnected:
      snprintf(view->lines[1], kDisplayLineMax, "%.11s %ddBm", in.ssid, in.rssi_dbm);
      break;
  }

  if (in.alert_active) {
    snprintf(view->lines[2], kDisplayLineMax, "Nhan nut de huy");
  } else if (in.sensor == SensorState::Calibrating) {
    snprintf(view->lines[2], kDisplayLineMax, "Giu yen 7 giay");
  } else if (in.link == LinkState::ClientConnected) {
    snprintf(view->lines[2], kDisplayLineMax, "Pi4: da ket noi");
  } else if (in.link == LinkState::WifiNoClient) {
    snprintf(view->lines[2], kDisplayLineMax, "%.15s:%u", in.ip, in.port);
  }
}
