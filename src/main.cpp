#include <Arduino.h>
#include <Wire.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <stdint.h>
#include <string.h>
#include "data_stream.h"
#include "gyro_calibration.h"

#if WIFI_STREAMING
#include <WiFi.h>
#include <ESPmDNS.h>
#include "net_protocol.h"
#if __has_include("wifi_secrets.h")
#include "wifi_secrets.h"
#endif
#endif

namespace {
constexpr int kSdaPin = 21;
constexpr int kSclPin = 22;
constexpr uint32_t kSampleIntervalMs = 20;
constexpr uint32_t kRetryIntervalMs = 3000;
constexpr uint32_t kWarmupMs = 2000;
constexpr uint32_t kFreshSampleTimeoutMs = 1000;
constexpr uint32_t kCalibrationSamples = 500;
constexpr uint8_t kWhoAmI = 0x75;
constexpr uint8_t kDataStart = 0x3B;
constexpr uint8_t kPowerManagement = 0x6B;
constexpr uint8_t kInterruptStatus = 0x3A;

uint8_t sensorAddress = 0;
bool sensorReady = false;
bool busReady = false;
bool gyroCalibrated = false;
uint32_t lastAttemptMs = 0;
uint32_t lastCalibrationAttemptMs = 0;
uint32_t goodReads = 0;
uint32_t failedReads = 0;
GyroCalibration gyroCalibration;
EmitSchedule sampleSchedule(kSampleIntervalMs);
char streamIdHex[17] = {};
uint32_t sampleSeq = 0;

#if WIFI_STREAMING
constexpr uint16_t kTcpPort = 8765;
constexpr const char *kHostname = "mpu6050-esp32";
constexpr uint32_t kNetPeriodMs = 1000;
constexpr uint32_t kSendStallMs = 3000;
constexpr uint32_t kConnectTimeoutMs = 10000;
constexpr uint32_t kReconnectDelayMs = 3000;

#ifndef WIFI_HOME_SSID
#define WIFI_HOME_SSID ""
#define WIFI_HOME_PASS ""
#define WIFI_HOTSPOT_SSID ""
#define WIFI_HOTSPOT_PASS ""
#endif

struct WifiProfile {
  const char *ssid;
  const char *password;
};
const WifiProfile kProfiles[] = {
    {WIFI_HOME_SSID, WIFI_HOME_PASS},
    {WIFI_HOTSPOT_SSID, WIFI_HOTSPOT_PASS},
};

RecordQueue wifiQueue;
SemaphoreHandle_t queueMutex = nullptr;
#endif

enum class CalibrationResult { Success, Unstable, ReadError };

bool readRegisters(uint8_t address, uint8_t reg, uint8_t *data, size_t length) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  const uint8_t status = Wire.endTransmission(false);
  if (status != 0) {
    Serial.printf("[ERROR] I2C address=0x%02X register=0x%02X status=%u\n",
                  address, reg, status);
    return false;
  }

  const size_t received = Wire.requestFrom(address, length, true);
  if (received != length || Wire.available() < static_cast<int>(length)) {
    Serial.printf("[ERROR] Short read address=0x%02X register=0x%02X: %u/%u bytes\n",
                  address, reg, static_cast<unsigned>(received),
                  static_cast<unsigned>(length));
    while (Wire.available()) Wire.read();
    return false;
  }

  for (size_t i = 0; i < length; ++i) {
    data[i] = static_cast<uint8_t>(Wire.read());
  }
  return true;
}

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(sensorAddress);
  Wire.write(reg);
  Wire.write(value);
  const uint8_t status = Wire.endTransmission();
  if (status != 0) {
    Serial.printf("[ERROR] Write register=0x%02X status=%u\n", reg, status);
  }
  return status == 0;
}

bool writeAndVerify(uint8_t reg, uint8_t value) {
  uint8_t actual = 0;
  if (!writeRegister(reg, value) ||
      !readRegisters(sensorAddress, reg, &actual, 1)) return false;
  if (actual != value) {
    Serial.printf("[ERROR] Config register=0x%02X expected=0x%02X actual=0x%02X\n",
                  reg, value, actual);
    return false;
  }
  return true;
}

int16_t signedWord(const uint8_t *bytes) {
  const uint16_t word = (static_cast<uint16_t>(bytes[0]) << 8) | bytes[1];
  const int32_t value = word >= 0x8000 ? static_cast<int32_t>(word) - 65536 : word;
  return static_cast<int16_t>(value);
}

bool readFreshFrame(uint8_t *frame) {
  const uint32_t started = millis();
  while (millis() - started < kFreshSampleTimeoutMs) {
    uint8_t status = 0;
    if (!readRegisters(sensorAddress, kInterruptStatus, &status, 1)) return false;
    if ((status & 0x01) != 0) {
      if (!readRegisters(sensorAddress, kDataStart, frame, 14)) return false;
      bool allZero = true;
      bool allFF = true;
      for (size_t i = 0; i < 14; ++i) {
        allZero = allZero && frame[i] == 0;
        allFF = allFF && frame[i] == 0xFF;
      }
      if (allZero || allFF) {
        Serial.println("[ERROR] Invalid frame: all bytes are 0x00 or 0xFF.");
        return false;
      }
      return true;
    }
    delay(1);
  }
  Serial.println("[ERROR] No fresh MPU6050 sample within 1 s.");
  return false;
}

bool initializeSensor() {
  gyroCalibrated = false;
  Serial.println("\n[SCAN] Looking for I2C devices...");
  unsigned deviceCount = 0;
  bool candidates[2] = {};
  for (uint8_t address = 1; address < 127; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      ++deviceCount;
      Serial.printf("[SCAN] Device at 0x%02X\n", address);
      if (address == 0x68 || address == 0x69) candidates[address - 0x68] = true;
    }
  }
  Serial.printf("[SCAN] %u device(s)\n", deviceCount);

  sensorAddress = 0;
  for (uint8_t i = 0; i < 2; ++i) {
    if (!candidates[i]) continue;
    const uint8_t address = 0x68 + i;
    uint8_t identity = 0;
    if (!readRegisters(address, kWhoAmI, &identity, 1)) continue;
    Serial.printf("[ID] address=0x%02X WHO_AM_I=0x%02X (expected 0x68)\n",
                  address, identity);
    // WHO_AM_I remains 0x68 even when AD0 selects I2C address 0x69.
    if (identity == 0x68) {
      sensorAddress = address;
      break;
    }
    Serial.println("[ERROR] Device identity does not match MPU6050.");
  }
  if (sensorAddress == 0) {
    Serial.println("[ERROR] MPU6050 not detected. Check 3V3/GND/SDA21/SCL22/AD0.");
    return false;
  }

  if (!writeRegister(kPowerManagement, 0x80)) return false;
  delay(100);
  if (!writeAndVerify(kPowerManagement, 0x01)) return false; // X gyro PLL.
  delay(100);
  if (!writeAndVerify(0x6C, 0x00) || // Enable all axes.
      !writeAndVerify(0x1A, 0x03) || // DLPF: accel 44 Hz, gyro 42 Hz.
      !writeAndVerify(0x19, 0x09) || // Internal sample rate: 100 Hz.
      !writeAndVerify(0x1B, 0x08) || // +/-500 deg/s, 65.5 LSB/(deg/s).
      !writeAndVerify(0x1C, 0x08) || // +/-4 g, 8192 LSB/g.
      !writeAndVerify(0x37, 0x00) || // Clear interrupts only by reading INT_STATUS.
      !writeAndVerify(0x38, 0x01)) { // Enable DATA_RDY; no INT wire required.
    return false;
  }
  delay(100);
  Serial.printf("[READY] MPU6050 at 0x%02X; configuration verified.\n", sensorAddress);
  Serial.println("[TEST] Hold still: |a| near 1 g. Tilt/rotate: axes must change.");
  return true;
}

CalibrationResult calibrateGyro() {
  Serial.println("\n[CAL] Keep MPU6050 STILL on a fixed surface for about 7 seconds.");
  Serial.println("[CAL] Warming up for 2 seconds...");
  delay(kWarmupMs);

  uint8_t status = 0;
  if (!readRegisters(sensorAddress, kInterruptStatus, &status, 1)) {
    return CalibrationResult::ReadError;
  }

  GyroCalibration candidate;
  Serial.println("[CAL] Collecting 500 fresh samples...");
  for (uint32_t i = 0; i < kCalibrationSamples; ++i) {
    uint8_t frame[14];
    if (!readFreshFrame(frame)) return CalibrationResult::ReadError;
    const int16_t accel[3] = {signedWord(frame), signedWord(frame + 2),
                              signedWord(frame + 4)};
    const int16_t gyro[3] = {signedWord(frame + 8), signedWord(frame + 10),
                             signedWord(frame + 12)};
    candidate.add(accel, gyro);
    if ((i + 1) % 100 == 0) {
      Serial.printf("[CAL] %lu/%lu samples\n", static_cast<unsigned long>(i + 1),
                    static_cast<unsigned long>(kCalibrationSamples));
    }
  }

  Serial.printf("[CAL] gyro_std=(%.3f,%.3f,%.3f) dps accel_std=(%.4f,%.4f,%.4f) g\n",
                candidate.gyroStdDevDps(0), candidate.gyroStdDevDps(1),
                candidate.gyroStdDevDps(2), candidate.accelStdDevG(0),
                candidate.accelStdDevG(1), candidate.accelStdDevG(2));
  if (!candidate.acceptable(kCalibrationSamples)) {
    Serial.println("[CAL] REJECTED: motion, vibration, or implausible readings.");
    Serial.println("[CAL] Keep sensor still; calibration will retry in 3 seconds.");
    return CalibrationResult::Unstable;
  }

  gyroCalibration = candidate;
  gyroCalibrated = true;
  const uint64_t streamIdValue =
      (static_cast<uint64_t>(esp_random()) << 32) | static_cast<uint64_t>(esp_random());
  formatStreamId(streamIdHex, sizeof(streamIdHex), streamIdValue);
  sampleSeq = 0;
  sampleSchedule.start(millis());
#if WIFI_STREAMING
  if (queueMutex != nullptr) {
    xSemaphoreTake(queueMutex, portMAX_DELAY);
    wifiQueue.clear();
    wifiQueue.resetCounters();
    xSemaphoreGive(queueMutex);
  }
#endif
  Serial.printf("[CAL] DONE bias=(%.3f,%.3f,%.3f) dps\n",
                gyroCalibration.biasDps(0), gyroCalibration.biasDps(1),
                gyroCalibration.biasDps(2));
  Serial.printf("[CAL] stream_id=%s; now streaming DATA records at 50 Hz.\n", streamIdHex);
  return CalibrationResult::Success;
}

void attemptCalibration() {
  const CalibrationResult result = calibrateGyro();
  lastCalibrationAttemptMs = millis();
  if (result == CalibrationResult::ReadError) {
    ++failedReads;
    sensorReady = false;
    gyroCalibrated = false;
    lastAttemptMs = millis();
    Serial.println("[ERROR] Calibration read failed; reinitializing in 3 seconds.");
  }
}

void publishRecord(const char *line) {
#if WIFI_STREAMING
  xSemaphoreTake(queueMutex, portMAX_DELAY);
  wifiQueue.push(line, strlen(line));
  xSemaphoreGive(queueMutex);
#else
  Serial.println(line);
#endif
}

bool emitSample() {
  uint8_t frame[14];
  if (!readFreshFrame(frame)) return false;
  const uint64_t timeUs = static_cast<uint64_t>(esp_timer_get_time());
  const int16_t axRaw = signedWord(frame);
  const int16_t ayRaw = signedWord(frame + 2);
  const int16_t azRaw = signedWord(frame + 4);
  const int16_t temperatureRaw = signedWord(frame + 6);
  const int16_t gxRaw = signedWord(frame + 8);
  const int16_t gyRaw = signedWord(frame + 10);
  const int16_t gzRaw = signedWord(frame + 12);

  StreamSample sample;
  sample.seq = sampleSeq;
  sample.time_us = timeUs;
  sample.ax = axRaw / 8192.0f;
  sample.ay = ayRaw / 8192.0f;
  sample.az = azRaw / 8192.0f;
  sample.gx = static_cast<float>(gyroCalibration.correctedDps(gxRaw, 0));
  sample.gy = static_cast<float>(gyroCalibration.correctedDps(gyRaw, 1));
  sample.gz = static_cast<float>(gyroCalibration.correctedDps(gzRaw, 2));
  sample.temp_c = temperatureRaw / 340.0f + 36.53f;

  char line[160];
  formatDataRecord(line, sizeof(line), streamIdHex, sample);
  publishRecord(line);
  ++sampleSeq;
  ++goodReads;
  return true;
}

#if WIFI_STREAMING
void connectWifi() {
  for (size_t i = 0; i < sizeof(kProfiles) / sizeof(kProfiles[0]); ++i) {
    if (kProfiles[i].ssid[0] == '\0') continue;
    Serial.printf("[WIFI] trying %s...\n", kProfiles[i].ssid);
    WiFi.begin(kProfiles[i].ssid, kProfiles[i].password);
    const uint32_t started = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - started < kConnectTimeoutMs) {
      delay(100);
    }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("[WIFI] connected ssid=%s ip=%s\n", kProfiles[i].ssid,
                    WiFi.localIP().toString().c_str());
      return;
    }
    WiFi.disconnect(true);
  }
  Serial.println("[WIFI] no configured network connected");
}

void sendBytes(WiFiClient &client, const char *data, size_t len) {
  size_t offset = 0;
  uint32_t lastProgress = millis();
  while (offset < len) {
    if (!client || !client.connected()) return;
    const size_t written =
        client.write(reinterpret_cast<const uint8_t *>(data) + offset, len - offset);
    if (written > 0) {
      offset += written;
      lastProgress = millis();
      continue;
    }
    if (millis() - lastProgress >= kSendStallMs) {
      client.stop();
      return;
    }
    delay(1);
  }
}

void sendNet(WiFiClient &client) {
  char net[kNetRecordMax];
  NetCounters counters;
  xSemaphoreTake(queueMutex, portMAX_DELAY);
  counters = wifiQueue.counters();
  xSemaphoreGive(queueMutex);
  formatNetLine(net, sizeof(net), streamIdHex, counters);
  sendBytes(client, net, strlen(net));
  sendBytes(client, "\n", 1);
}

void networkTask(void *) {
  connectWifi();
  WiFiServer server(kTcpPort);
  server.begin();
  MDNS.begin(kHostname);
  MDNS.addService("mpu6050", "tcp", kTcpPort);
  WiFiClient client;
  char record[kNetRecordMax];
  char line[kNetRecordMax + 2];
  uint32_t lastNetMs = 0;
  for (;;) {
    if (WiFi.status() != WL_CONNECTED) {
      if (client) client.stop();
      delay(kReconnectDelayMs);
      connectWifi();
      continue;
    }
    WiFiClient incoming = server.available();
    if (incoming) {
      if (client && client.connected()) {
        Serial.println("[NET] second client rejected");
        incoming.stop();
      } else {
        if (client) client.stop();
        client = incoming;
        xSemaphoreTake(queueMutex, portMAX_DELAY);
        wifiQueue.clear();
        wifiQueue.resetCounters();
        xSemaphoreGive(queueMutex);
        Serial.printf("[NET] client connected from %s\n",
                      client.remoteIP().toString().c_str());
        sendNet(client);
        lastNetMs = millis();
      }
    }
    if (!client || !client.connected()) {
      if (client) client.stop();
      xSemaphoreTake(queueMutex, portMAX_DELAY);
      size_t drained = 0;
      while (wifiQueue.pop(record, sizeof(record))) {
        wifiQueue.count_unobserved(1);
        if (++drained >= 50) break;
      }
      xSemaphoreGive(queueMutex);
      delay(10);
      continue;
    }
    int sent = 0;
    while (sent < 50) {
      xSemaphoreTake(queueMutex, portMAX_DELAY);
      const bool have = wifiQueue.pop(record, sizeof(record));
      xSemaphoreGive(queueMutex);
      if (!have) break;
      size_t len = strlen(record);
      if (len > sizeof(line) - 2) len = sizeof(line) - 2;
      memcpy(line, record, len);
      line[len] = '\n';
      line[len + 1] = '\0';
      sendBytes(client, line, len + 1);
      if (!client || !client.connected()) break;
      ++sent;
    }
    if (client && client.connected() && millis() - lastNetMs >= kNetPeriodMs) {
      sendNet(client);
      lastNetMs = millis();
    }
    delay(1);
  }
}
#endif
} // namespace

void setup() {
  Serial.begin(115200);
  delay(1000);
#if WIFI_STREAMING
  Serial.println("\n=== ESP32 MPU6050 Wi-Fi streaming ===");
#else
  Serial.println("\n=== ESP32 MPU6050 USB streaming ===");
#endif
  Serial.println("Wiring: VCC=3V3 GND=GND SDA=21 SCL=22 AD0=GND");
#if WIFI_STREAMING
  queueMutex = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(networkTask, "net", 8192, nullptr, 1, nullptr, 0);
#endif
  busReady = Wire.begin(kSdaPin, kSclPin, 100000);
  Wire.setTimeOut(50);
  if (!busReady) {
    Serial.println("[ERROR] Cannot initialize ESP32 I2C bus.");
  } else {
    sensorReady = initializeSensor();
    if (sensorReady) attemptCalibration();
  }
  lastAttemptMs = millis();
}

void loop() {
  const uint32_t now = millis();
  if (!sensorReady) {
    if (now - lastAttemptMs >= kRetryIntervalMs) {
      if (!busReady) {
        busReady = Wire.begin(kSdaPin, kSclPin, 100000);
        Wire.setTimeOut(50);
      }
      sensorReady = busReady && initializeSensor();
      lastAttemptMs = millis();
      if (sensorReady) {
        attemptCalibration();
      } else {
        Serial.println("[RETRY] Initialization failed; retrying in 3 s.");
      }
    }
    delay(10);
    return;
  }
  if (!gyroCalibrated) {
    if (now - lastCalibrationAttemptMs >= kRetryIntervalMs) attemptCalibration();
    delay(10);
    return;
  }
  if (sampleSchedule.due(now)) {
    if (emitSample()) {
      sampleSchedule.onEmit(now);
    } else {
      ++failedReads;
      sensorReady = false;
      gyroCalibrated = false;
      lastAttemptMs = millis();
      Serial.printf("[ERROR] Sample rejected. successful=%lu errors=%lu; retrying in 3 s.\n",
                    static_cast<unsigned long>(goodReads),
                    static_cast<unsigned long>(failedReads));
    }
  }
  delay(1);
}
