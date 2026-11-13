#include "display.h"

#include <Arduino.h>
#include <U8g2lib.h>
#include <Wire.h>

#include "pins.h"

#ifndef OLED_SH1106
#define OLED_SH1106 0
#endif

namespace {
constexpr uint32_t kOledBusHz = 400000;
constexpr int kTitleHeight = 20;
constexpr int kLineBaseline[3] = {32, 46, 60};
constexpr int kBatteryX = 104;
constexpr int kBatteryY = 23;

#if OLED_SH1106
U8G2_SH1106_128X64_NONAME_F_2ND_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
#else
U8G2_SSD1306_128X64_NONAME_F_2ND_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
#endif

uint8_t address = 0;

bool answers(uint8_t candidate) {
  Wire1.beginTransmission(candidate);
  return Wire1.endTransmission() == 0;
}

void drawBattery(int level) {
  if (level < 0) return;
  oled.drawFrame(kBatteryX, kBatteryY, 20, 10);
  oled.drawBox(kBatteryX + 20, kBatteryY + 3, 2, 4);
  for (int i = 0; i < level && i < 4; ++i) {
    oled.drawBox(kBatteryX + 2 + i * 4, kBatteryY + 2, 3, 6);
  }
}
}  // namespace

bool displayBegin() {
  // Start the bus here with our pins; U8g2 then reuses it as it is.
  Wire1.begin(pins::kOledSda, pins::kOledScl, kOledBusHz);
  Wire1.setTimeOut(50);
  address = answers(0x3C) ? 0x3C : answers(0x3D) ? 0x3D : 0;
  if (address == 0) return false;
  oled.setI2CAddress(static_cast<uint8_t>(address << 1));
  oled.setBusClock(kOledBusHz);
  oled.begin();
  oled.setFontMode(1);
  oled.clearBuffer();
  oled.sendBuffer();
  return true;
}

bool displayPresent() { return address != 0; }

uint8_t displayAddress() { return address; }

void displaySetPower(bool on) {
  if (address == 0) return;
  oled.setPowerSave(on ? 0 : 1);
}

void displayDraw(const DisplayView &view) {
  if (address == 0) return;
  oled.clearBuffer();

  oled.setFont(u8g2_font_10x20_tr);
  const int titleWidth = oled.getStrWidth(view.title);
  const int titleX = titleWidth < 128 ? (128 - titleWidth) / 2 : 0;
  if (view.invert_title) {
    oled.setDrawColor(1);
    oled.drawBox(0, 0, 128, kTitleHeight);
    oled.setDrawColor(0);
    oled.drawStr(titleX, 16, view.title);
    oled.setDrawColor(1);
  } else {
    oled.drawStr(titleX, 16, view.title);
    oled.drawHLine(0, kTitleHeight - 1, 128);
  }

  oled.setFont(u8g2_font_6x12_tr);
  for (int i = 0; i < 3; ++i) oled.drawStr(0, kLineBaseline[i], view.lines[i]);
  drawBattery(view.battery_level);
  oled.sendBuffer();
}

void displayTestPattern(unsigned step) {
  if (address == 0) return;
  oled.clearBuffer();
  switch (step % 3) {
    case 0:
      oled.drawFrame(0, 0, 128, 64);
      oled.setFont(u8g2_font_10x20_tr);
      oled.drawStr(24, 26, "OLED OK");
      oled.setFont(u8g2_font_6x12_tr);
      oled.drawStr(8, 44, "Vien phai kin 4 canh");
      oled.drawStr(8, 58, OLED_SH1106 ? "SH1106 128x64" : "SSD1306 128x64");
      break;
    case 1:
      oled.drawBox(0, 0, 128, 64);
      break;
    default:
      for (int y = 0; y < 64; y += 8) {
        for (int x = (y / 8) % 2 * 8; x < 128; x += 16) oled.drawBox(x, y, 8, 8);
      }
      break;
  }
  oled.sendBuffer();
}
