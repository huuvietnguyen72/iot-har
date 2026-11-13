#include "ui.h"

#include <Arduino.h>
#include <string.h>

#include "battery.h"
#include "button.h"
#include "display.h"
#include "display_view.h"
#include "pins.h"
#include "wearable_protocol.h"

#if WIFI_STREAMING
#include <WiFi.h>
#endif

#ifndef BUZZER_PASSIVE
#define BUZZER_PASSIVE 0  // 1 = passive buzzer that needs a tone instead of DC
#endif

namespace {
constexpr uint32_t kTickMs = 5;
constexpr uint32_t kBatteryPeriodMs = 1000;
constexpr int kBatterySamples = 8;
constexpr int kBatteryDivider = 2;  // 100 kOhm + 100 kOhm
constexpr uint32_t kStatusPeriodMs = 10000;
constexpr uint32_t kDisplayPeriodMs = 250;
constexpr uint32_t kDisplayProbePeriodMs = 30000;
constexpr uint32_t kWakeMs = 10000;       // screen stays on this long after a press
constexpr uint32_t kBootWakeMs = 20000;
constexpr uint32_t kSosNoticeMs = 5000;
constexpr uint32_t kActivityFreshMs = 5000;
constexpr uint32_t kClickBeepMs = 60;
constexpr uint32_t kSosBeepMs = 800;
constexpr uint32_t kNetInfoPeriodMs = 1000;
constexpr unsigned kPassiveToneHz = 2700;
constexpr unsigned kTcpPort = 8765;

// State written by other tasks.
portMUX_TYPE stateMux = portMUX_INITIALIZER_UNLOCKED;
SensorState sensorState = SensorState::Starting;
#if WIFI_STREAMING
LinkState linkState = LinkState::WifiDown;
#else
LinkState linkState = LinkState::UsbOnly;
#endif
char activityLabel[kActivityLabelMax] = {};
uint32_t activitySetMs = 0;
bool activitySet = false;
bool alertOnRequested = false;
bool alertOffRequested = false;
bool baroOk = false;
int stairsDirection = 0;

struct Snapshot {
  SensorState sensor;
  LinkState link;
  char activity[kActivityLabelMax];
  bool alertOn;
  bool alertOff;
  bool baro;
  int stairs;
};

Snapshot takeSnapshot(uint32_t now) {
  Snapshot s;
  portENTER_CRITICAL(&stateMux);
  s.sensor = sensorState;
  s.link = linkState;
  const bool fresh = activitySet && now - activitySetMs < kActivityFreshMs;
  if (fresh) {
    memcpy(s.activity, activityLabel, sizeof(s.activity));
  } else {
    s.activity[0] = '\0';
  }
  s.alertOn = alertOnRequested;
  s.alertOff = alertOffRequested;
  alertOnRequested = false;
  alertOffRequested = false;
  s.baro = baroOk;
  s.stairs = stairsDirection;
  portEXIT_CRITICAL(&stateMux);
  return s;
}

// "now is before deadline", safe across millis() wrap-around.
bool before(uint32_t now, uint32_t deadline) { return static_cast<int32_t>(now - deadline) < 0; }

void setBuzzer(bool on) {
  static bool current = false;
  if (on == current) return;
  current = on;
#if BUZZER_PASSIVE
  if (on) {
    tone(pins::kBuzzer, kPassiveToneHz);
  } else {
    noTone(pins::kBuzzer);
  }
#else
  digitalWrite(pins::kBuzzer, on ? HIGH : LOW);
#endif
}

int readBatteryMillivolts() {
  uint32_t sum = 0;
  for (int i = 0; i < kBatterySamples; ++i) sum += analogReadMilliVolts(pins::kBattery);
  return static_cast<int>(sum / kBatterySamples) * kBatteryDivider;
}

bool sameView(const DisplayView &a, const DisplayView &b) {
  return a.battery_level == b.battery_level && a.invert_title == b.invert_title &&
         strcmp(a.title, b.title) == 0 && strcmp(a.lines[0], b.lines[0]) == 0 &&
         strcmp(a.lines[1], b.lines[1]) == 0 && strcmp(a.lines[2], b.lines[2]) == 0;
}

void uiTask(void *) {
  Button button;
  BatteryMonitor battery;
  Alert alert;

  bool displayOk = displayBegin();
  if (displayOk) {
    Serial.printf("[UI] OLED found at 0x%02X\n", displayAddress());
  } else {
    Serial.println("[UI] no OLED on SDA=19 SCL=18; continuing without a display");
  }

  const uint32_t start = millis();
  uint32_t wakeUntil = start + kBootWakeMs;
  uint32_t beepUntil = start;
  uint32_t sosNoticeUntil = start;
  uint32_t lastBatteryMs = start - kBatteryPeriodMs;
  uint32_t lastStatusMs = start;
  uint32_t lastDisplayMs = start - kDisplayPeriodMs;
  uint32_t lastProbeMs = start;
  uint32_t lastNetInfoMs = start - kNetInfoPeriodMs;
  uint32_t clicks = 0;
  bool pressCancelledAlert = false;
  bool screenOn = displayOk;
  bool forceDraw = true;
  DisplayView shown;
  char ssid[33] = "";
  char ip[16] = "";
  int rssi = 0;

  for (;;) {
    const uint32_t now = millis();
    const Snapshot state = takeSnapshot(now);

    if (state.alertOff) alert.clear();
    if (state.alertOn && alert.start(now)) publishEvent("alert_on", 1);

    switch (button.update(digitalRead(pins::kButton) == LOW, now)) {
      case ButtonEvent::Down:
        wakeUntil = now + kWakeMs;
        beepUntil = now + kClickBeepMs;
        pressCancelledAlert = alert.clear();
        if (pressCancelledAlert) publishEvent("alert_cancel", 1);
        break;
      case ButtonEvent::Click:
        if (!pressCancelledAlert) publishEvent("button", static_cast<long>(++clicks));
        break;
      case ButtonEvent::LongPress:
        // A hold that began by cancelling an alert is not a call for help.
        if (!pressCancelledAlert) {
          publishEvent("sos", 1);
          sosNoticeUntil = now + kSosNoticeMs;
          beepUntil = now + kSosBeepMs;
          wakeUntil = now + kWakeMs;
        }
        break;
      case ButtonEvent::None:
        break;
    }

    if (now - lastBatteryMs >= kBatteryPeriodMs) {
      lastBatteryMs = now;
      battery.addSample(readBatteryMillivolts());
    }

#if WIFI_STREAMING
    if (now - lastNetInfoMs >= kNetInfoPeriodMs) {
      lastNetInfoMs = now;
      if (state.link == LinkState::WifiDown) {
        ssid[0] = '\0';
        ip[0] = '\0';
        rssi = 0;
      } else {
        snprintf(ssid, sizeof(ssid), "%s", WiFi.SSID().c_str());
        snprintf(ip, sizeof(ip), "%s", WiFi.localIP().toString().c_str());
        rssi = WiFi.RSSI();
      }
    }
#else
    (void)lastNetInfoMs;
#endif

    IndicatorInput indicator;
    indicator.sensor = state.sensor;
    indicator.link = state.link;
    indicator.battery_low = battery.low();
    indicator.alert_active = alert.active();
    indicator.alert_sounding = alert.sounding(now);
    const IndicatorOutput out = computeIndicator(indicator, now);
    digitalWrite(pins::kLedGreen, out.green ? HIGH : LOW);
    digitalWrite(pins::kLedRed, out.red ? HIGH : LOW);
    digitalWrite(pins::kMotor, out.motor ? HIGH : LOW);
    setBuzzer(out.buzzer || before(now, beepUntil));

    if (now - lastStatusMs >= kStatusPeriodMs) {
      lastStatusMs = now;
      const unsigned flags = (state.baro ? kStatFlagBaro : 0) |
                             (displayOk ? kStatFlagDisplay : 0) |
                             (alert.active() ? kStatFlagAlert : 0) |
                             (battery.low() ? kStatFlagBatteryLow : 0);
      publishStatus(battery.millivolts(), battery.percent(), rssi, flags);
    }

    if (!displayOk) {
      if (now - lastProbeMs >= kDisplayProbePeriodMs) {
        lastProbeMs = now;
        displayOk = displayBegin();
        if (displayOk) {
          Serial.printf("[UI] OLED found at 0x%02X\n", displayAddress());
          screenOn = true;
          forceDraw = true;
          wakeUntil = now + kWakeMs;
        }
      }
    } else {
      const bool wantOn = alert.active() || before(now, wakeUntil) ||
                          before(now, sosNoticeUntil) ||
                          state.sensor != SensorState::Streaming;
      if (wantOn != screenOn) {
        screenOn = wantOn;
        displaySetPower(screenOn);
        forceDraw = screenOn;
      }
      if (screenOn && now - lastDisplayMs >= kDisplayPeriodMs) {
        lastDisplayMs = now;
        DisplayInput in;
        in.sensor = state.sensor;
        in.link = state.link;
        in.activity = state.activity;
        in.stairs = state.stairs;
        in.alert_active = alert.active();
        in.sos_notice = before(now, sosNoticeUntil);
        in.battery_valid = battery.valid();
        in.battery_percent = battery.percent();
        in.battery_mv = battery.millivolts();
        in.battery_level = battery.level();
        in.ssid = ssid;
        in.rssi_dbm = rssi;
        in.ip = ip;
        in.port = kTcpPort;
        DisplayView view;
        buildDisplayView(in, &view);
        if (forceDraw || !sameView(view, shown)) {
          displayDraw(view);  // about 30 ms on the OLED's own bus
          shown = view;
          forceDraw = false;
        }
      }
    }

    vTaskDelay(pdMS_TO_TICKS(kTickMs));
  }
}
}  // namespace

void uiBegin() {
  pinMode(pins::kLedGreen, OUTPUT);
  pinMode(pins::kLedRed, OUTPUT);
  pinMode(pins::kBuzzer, OUTPUT);
  pinMode(pins::kMotor, OUTPUT);
  digitalWrite(pins::kLedGreen, LOW);
  digitalWrite(pins::kLedRed, LOW);
  digitalWrite(pins::kBuzzer, LOW);
  digitalWrite(pins::kMotor, LOW);
  pinMode(pins::kButton, INPUT_PULLUP);
  analogSetPinAttenuation(pins::kBattery, ADC_11db);
  xTaskCreatePinnedToCore(uiTask, "ui", 6144, nullptr, 1, nullptr, 0);
}

void uiSetSensorState(SensorState state) {
  portENTER_CRITICAL(&stateMux);
  sensorState = state;
  portEXIT_CRITICAL(&stateMux);
}

void uiSetLinkState(LinkState state) {
  portENTER_CRITICAL(&stateMux);
  linkState = state;
  portEXIT_CRITICAL(&stateMux);
}

void uiSetActivity(const char *label) {
  const uint32_t now = millis();
  portENTER_CRITICAL(&stateMux);
  strncpy(activityLabel, label, sizeof(activityLabel) - 1);
  activityLabel[sizeof(activityLabel) - 1] = '\0';
  activitySetMs = now;
  activitySet = true;
  portEXIT_CRITICAL(&stateMux);
}

void uiSetAlert(bool on) {
  portENTER_CRITICAL(&stateMux);
  if (on) {
    alertOnRequested = true;
  } else {
    alertOffRequested = true;
    alertOnRequested = false;
  }
  portEXIT_CRITICAL(&stateMux);
}

void uiSetStairs(int direction) {
  portENTER_CRITICAL(&stateMux);
  stairsDirection = direction > 0 ? 1 : direction < 0 ? -1 : 0;
  portEXIT_CRITICAL(&stateMux);
}

void uiSetBaroOk(bool ok) {
  portENTER_CRITICAL(&stateMux);
  baroOk = ok;
  portEXIT_CRITICAL(&stateMux);
}
