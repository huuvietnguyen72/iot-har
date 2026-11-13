// Breadboard hardware check for the wearable: I2C scan, MPU6050, BMP280, OLED, LEDs,
// button, buzzer, optional vibration motor and battery voltage. Separate from
// the streaming firmware; build it with the hw_test environment:
//   pio run -e hw_test -t upload
//   pio device monitor -e hw_test
#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <stdint.h>
#include "../bmp280.h"
#include "../display.h"
#include "../pins.h"

namespace {
constexpr int kSdaPin = pins::kSda;
constexpr int kSclPin = pins::kScl;
constexpr int kLedGreenPin = pins::kLedGreen;
constexpr int kLedRedPin = pins::kLedRed;
constexpr int kButtonPin = pins::kButton;
constexpr int kBuzzerPin = pins::kBuzzer;
constexpr int kMotorPin = pins::kMotor;
constexpr int kBatteryPin = pins::kBattery;  // ADC1, readable while Wi-Fi is on
constexpr float kBatteryDivider = 2.0f;    // 100 kOhm + 100 kOhm
constexpr float kBatteryAbsentV = 0.5f;
constexpr uint32_t kDebounceMs = 30;
constexpr uint32_t kReportMs = 1000;
constexpr uint32_t kPressurePeriodMs = 100;
constexpr uint32_t kPulseMs = 300;
constexpr uint32_t kClickMs = 80;
constexpr unsigned kPassiveToneHz = 2700;

constexpr uint8_t kMpuWhoAmI = 0x75;
constexpr uint8_t kMpuPowerManagement = 0x6B;
constexpr uint8_t kMpuAccelConfig = 0x1C;
constexpr uint8_t kMpuAccelStart = 0x3B;
constexpr uint8_t kMpuAccel4g = 0x08;
constexpr float kAccelLsbPerG = 8192.0f;   // +/-4 g, same as the streaming firmware

constexpr uint8_t kBmpChipIdRegister = 0xD0;
constexpr uint8_t kBmpCalibrationStart = 0x88;
constexpr uint8_t kBmpCtrlMeas = 0xF4;
constexpr uint8_t kBmpConfig = 0xF5;
constexpr uint8_t kBmpDataStart = 0xF7;
constexpr uint8_t kBmpConfigFilter16 = 0x10;          // standby 0.5 ms, IIR x16
constexpr uint8_t kBmpCtrlNormalT2P16 = 0x57;         // temp x2, pressure x16, normal

// Same thresholds as the standing mount check in the retraining plan (Task 1.3).
constexpr float kMountSideMaxG = 0.15f;
constexpr float kMountUpMinG = -1.05f;
constexpr float kMountUpMaxG = -0.90f;

constexpr size_t kPressureWindow = 50;     // 5 s at 10 Hz

uint8_t mpuAddress = 0;
uint8_t bmpAddress = 0;
Bmp280Calibration bmpCalibration;
uint32_t i2cErrors = 0;

float pressureWindow[kPressureWindow];
size_t pressureCount = 0;
size_t pressureNext = 0;
float lastTemperatureC = NAN;

bool buttonReading = false;
bool buttonPressed = false;
uint32_t buttonChangedMs = 0;
uint32_t buttonPresses = 0;

int pulsePin = -1;
uint32_t pulseEndMs = 0;
uint32_t lastPressureMs = 0;
uint32_t lastReportMs = 0;
unsigned oledPattern = 0;

bool readRegisters(uint8_t address, uint8_t reg, uint8_t *data, size_t length) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0 ||
      Wire.requestFrom(address, static_cast<uint8_t>(length), static_cast<uint8_t>(true)) !=
          length) {
    while (Wire.available()) Wire.read();
    ++i2cErrors;
    return false;
  }
  for (size_t i = 0; i < length; ++i) data[i] = static_cast<uint8_t>(Wire.read());
  return true;
}

bool writeRegister(uint8_t address, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(value);
  if (Wire.endTransmission() != 0) {
    ++i2cErrors;
    return false;
  }
  return true;
}

const char *deviceLabel(uint8_t address) {
  switch (address) {
    case 0x38: return "AHT20 (humidity, not used)";
    case 0x68:
    case 0x69: return "MPU6050?";
    case 0x76:
    case 0x77: return "BMP280/BME280?";
    default: return "unknown";
  }
}

void scanI2c() {
  mpuAddress = 0;
  bmpAddress = 0;
  Serial.println("[I2C] scanning 0x01..0x7E");
  int found = 0;
  for (uint8_t address = 1; address < 0x7F; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() != 0) continue;
    ++found;
    Serial.printf("[I2C] 0x%02X %s\n", address, deviceLabel(address));
    uint8_t id = 0;
    if ((address == 0x68 || address == 0x69) &&
        readRegisters(address, kMpuWhoAmI, &id, 1)) {
      Serial.printf("[ID] 0x%02X WHO_AM_I=0x%02X (expected 0x68)\n", address, id);
      if (id == 0x68) mpuAddress = address;
    }
    if ((address == 0x76 || address == 0x77) &&
        readRegisters(address, kBmpChipIdRegister, &id, 1)) {
      const char *kind = id == kBmp280ChipId   ? "BMP280"
                         : id == kBme280ChipId ? "BME280 (pressure part is the same)"
                         : id == 0x55          ? "BMP180 (not supported here)"
                                               : "unexpected";
      Serial.printf("[ID] 0x%02X chip_id=0x%02X %s\n", address, id, kind);
      if (id == kBmp280ChipId || id == kBme280ChipId) bmpAddress = address;
    }
  }
  Serial.printf("[I2C] %d device(s) found\n", found);
}

bool initMpu() {
  return mpuAddress != 0 && writeRegister(mpuAddress, kMpuPowerManagement, 0x00) &&
         writeRegister(mpuAddress, kMpuAccelConfig, kMpuAccel4g);
}

bool initBmp() {
  if (bmpAddress == 0) return false;
  uint8_t raw[kBmp280CalibrationBytes];
  if (!readRegisters(bmpAddress, kBmpCalibrationStart, raw, sizeof(raw))) return false;
  bmpCalibration = parseBmp280Calibration(raw);
  // Write config while the sensor is still asleep; it may be ignored in normal mode.
  return writeRegister(bmpAddress, kBmpConfig, kBmpConfigFilter16) &&
         writeRegister(bmpAddress, kBmpCtrlMeas, kBmpCtrlNormalT2P16);
}

void samplePressure() {
  uint8_t data[kBmp280DataBytes];
  if (!readRegisters(bmpAddress, kBmpDataStart, data, sizeof(data))) return;
  const int32_t tFine = bmp280TFine(bmpCalibration, bmp280RawTemperature(data));
  const uint32_t q24 = bmp280PressureQ24_8(bmpCalibration, bmp280RawPressure(data), tFine);
  if (q24 == 0) return;
  lastTemperatureC = bmp280CentiCelsius(tFine) / 100.0f;
  pressureWindow[pressureNext] = q24 / 256.0f;
  pressureNext = (pressureNext + 1) % kPressureWindow;
  if (pressureCount < kPressureWindow) ++pressureCount;
}

bool readAccel(float g[3]) {
  uint8_t data[6];
  if (mpuAddress == 0 || !readRegisters(mpuAddress, kMpuAccelStart, data, sizeof(data))) {
    return false;
  }
  for (int axis = 0; axis < 3; ++axis) {
    const int16_t raw = static_cast<int16_t>((data[2 * axis] << 8) | data[2 * axis + 1]);
    g[axis] = raw / kAccelLsbPerG;
  }
  return true;
}

void startPulse(int pin, uint32_t ms) {
  if (pulsePin >= 0) digitalWrite(pulsePin, LOW);
  pinMode(pin, OUTPUT);  // tone() may have taken the buzzer pin
  digitalWrite(pin, HIGH);
  pulsePin = pin;
  pulseEndMs = millis() + ms;
}

void updatePulse(uint32_t now) {
  if (pulsePin >= 0 && static_cast<int32_t>(now - pulseEndMs) >= 0) {
    digitalWrite(pulsePin, LOW);
    pulsePin = -1;
  }
}

void updateButton(uint32_t now) {
  const bool reading = digitalRead(kButtonPin) == LOW;  // pull-up: pressed reads LOW
  if (reading != buttonReading) {
    buttonReading = reading;
    buttonChangedMs = now;
  }
  if (now - buttonChangedMs >= kDebounceMs && buttonPressed != buttonReading) {
    buttonPressed = buttonReading;
    if (buttonPressed) {
      ++buttonPresses;
      Serial.printf("[BTN] press %lu\n", static_cast<unsigned long>(buttonPresses));
      startPulse(kBuzzerPin, kClickMs);
    }
  }
}

float batteryVolts() {
  return analogReadMilliVolts(kBatteryPin) * kBatteryDivider / 1000.0f;
}

void report() {
  char battery[16] = "--";
  const float volts = batteryVolts();
  if (volts >= kBatteryAbsentV) snprintf(battery, sizeof(battery), "%.2fV", volts);

  char pressure[48] = "p=--";
  if (pressureCount > 0) {
    double sum = 0;
    for (size_t i = 0; i < pressureCount; ++i) sum += pressureWindow[i];
    const double mean = sum / pressureCount;
    double squares = 0;
    for (size_t i = 0; i < pressureCount; ++i) {
      squares += (pressureWindow[i] - mean) * (pressureWindow[i] - mean);
    }
    snprintf(pressure, sizeof(pressure), "p=%.1fPa sd=%.2fPa T=%.1fC", mean,
             sqrt(squares / pressureCount), lastTemperatureC);
  }

  char accel[64] = "acc=--";
  float g[3];
  if (readAccel(g)) {
    const bool mountOk = fabsf(g[0]) <= kMountSideMaxG && fabsf(g[2]) <= kMountSideMaxG &&
                         g[1] >= kMountUpMinG && g[1] <= kMountUpMaxG;
    snprintf(accel, sizeof(accel), "acc=(%.2f,%.2f,%.2f)g mount=%s", g[0], g[1], g[2],
             mountOk ? "OK" : "adjust");
  }

  Serial.printf("[STAT] btn=%lu vbat=%s %s %s i2c_err=%lu\n",
                static_cast<unsigned long>(buttonPresses), battery, pressure, accel,
                static_cast<unsigned long>(i2cErrors));
}

// The OLED sits alone on the second I2C bus, so it is not part of scanI2c().
bool checkOled() {
  const bool found = displayBegin();
  if (found) {
    Serial.printf("[OLED] found at 0x%02X on SDA=%d SCL=%d\n", displayAddress(),
                  pins::kOledSda, pins::kOledScl);
    oledPattern = 0;
    displayTestPattern(oledPattern);
  } else {
    Serial.printf("[OLED] nothing at 0x3C/0x3D on SDA=%d SCL=%d\n", pins::kOledSda,
                  pins::kOledScl);
  }
  return found;
}

void printHelp() {
  Serial.println("[HELP] b=buzzer DC 300ms  t=buzzer tone 2.7kHz 300ms  m=motor 300ms");
  Serial.println("[HELP] o=next OLED test pattern (text, all on, checkerboard)");
  Serial.println("[HELP] s=rescan I2C  h=help. A loud 'b' means an active buzzer;");
  Serial.println("[HELP] if only 't' sounds, the buzzer is passive and needs tone().");
  Serial.println("[HELP] mount=OK only when worn and standing still (Y arrow down).");
}

void handleSerial() {
  while (Serial.available()) {
    switch (Serial.read()) {
      case 'b':
        Serial.println("[OUT] buzzer DC");
        startPulse(kBuzzerPin, kPulseMs);
        break;
      case 't':
        Serial.println("[OUT] buzzer tone");
        tone(kBuzzerPin, kPassiveToneHz, kPulseMs);
        break;
      case 'm':
        Serial.println("[OUT] motor");
        startPulse(kMotorPin, kPulseMs);
        break;
      case 's':
        scanI2c();
        Serial.printf("[INIT] MPU6050 %s, BMP280 %s\n", initMpu() ? "ok" : "missing",
                      initBmp() ? "ok" : "missing");
        checkOled();
        break;
      case 'o':
        if (displayPresent()) {
          oledPattern = (oledPattern + 1) % 3;
          Serial.printf("[OLED] pattern %u\n", oledPattern);
          displayTestPattern(oledPattern);
        } else {
          Serial.println("[OLED] not found; press s to look again");
        }
        break;
      case 'h':
        printHelp();
        break;
      default:
        break;
    }
  }
}
}  // namespace

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== Wearable hardware check ===");
  Serial.println("I2C SDA=21 SCL=22 | LED green=26 red=27 | button=32 | buzzer=25 | "
                 "motor=33 | battery=34 | OLED SDA=19 SCL=18");

  pinMode(kLedGreenPin, OUTPUT);
  pinMode(kLedRedPin, OUTPUT);
  pinMode(kBuzzerPin, OUTPUT);
  pinMode(kMotorPin, OUTPUT);
  pinMode(kButtonPin, INPUT_PULLUP);
  analogSetPinAttenuation(kBatteryPin, ADC_11db);

  Serial.println("[LED] green on");
  digitalWrite(kLedGreenPin, HIGH);
  delay(500);
  digitalWrite(kLedGreenPin, LOW);
  Serial.println("[LED] red on");
  digitalWrite(kLedRedPin, HIGH);
  delay(500);
  digitalWrite(kLedRedPin, LOW);

  Wire.begin(kSdaPin, kSclPin, 100000);
  Wire.setTimeOut(50);
  scanI2c();
  const bool mpuOk = initMpu();
  const bool bmpOk = initBmp();
  Serial.printf("[CHECK] MPU6050 %s\n", mpuOk ? "PASS" : "FAIL: check VCC/GND/SDA/SCL/AD0");
  Serial.printf("[CHECK] BMP280 %s\n", bmpOk ? "PASS" : "FAIL: check wiring and chip id");
  Serial.printf("[CHECK] OLED %s\n",
                checkOled() ? "PASS: the screen must show OLED OK inside a full frame"
                            : "FAIL: check VCC(3V3)/GND/SCL18/SDA19");

  Serial.println("[OUT] startup beep");
  startPulse(kBuzzerPin, kClickMs);
  printHelp();
}

void loop() {
  const uint32_t now = millis();
  handleSerial();
  updateButton(now);
  updatePulse(now);
  if (bmpAddress != 0 && now - lastPressureMs >= kPressurePeriodMs) {
    lastPressureMs = now;
    samplePressure();
  }
  if (now - lastReportMs >= kReportMs) {
    lastReportMs = now;
    report();
  }
  digitalWrite(kLedGreenPin, (now / 500) % 2 ? HIGH : LOW);  // heartbeat
  digitalWrite(kLedRedPin, buttonPressed ? HIGH : LOW);
  delay(1);
}
