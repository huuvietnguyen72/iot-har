// 0.96" 128x64 I2C OLED on the second I2C bus (pins::kOledSda / kOledScl).
// SSD1306 by default; build with -D OLED_SH1106=1 for an SH1106 panel.
#pragma once

#include <stdint.h>

#include "display_view.h"

// Looks for the panel at 0x3C / 0x3D and initialises it. Safe to call again later.
bool displayBegin();
bool displayPresent();
uint8_t displayAddress();  // 0 when no panel answered

void displayDraw(const DisplayView &view);
void displaySetPower(bool on);

// Patterns for hw_test: 0 = frame and text, 1 = all pixels on, 2 = checkerboard.
void displayTestPattern(unsigned step);
