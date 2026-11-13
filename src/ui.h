// Everything the wearer sees, hears and presses: button, two LEDs, buzzer, vibration
// motor, battery reading and the OLED. Runs in its own low-priority task, so none of
// it can delay the 50 Hz sensor loop.
#pragma once

#include "indicator.h"

// Configures the pins and starts the UI task. Call once from setup().
void uiBegin();

// Thread-safe; call from any task.
void uiSetSensorState(SensorState state);
void uiSetLinkState(LinkState state);
void uiSetActivity(const char *label);  // from CMD,1,ACT; goes stale after 5 s
void uiSetAlert(bool on);               // from CMD,1,ALERT
void uiSetBaroOk(bool ok);
void uiSetStairs(int direction);       // on-device stairs hint: 1 up, -1 down, 0 none

// Provided by the streaming code (main.cpp). Called from the UI task.
void publishEvent(const char *name, long value);
void publishStatus(int vbat_mv, int percent, int rssi_dbm, unsigned flags);
