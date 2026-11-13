#pragma once

#include <stdint.h>

// BMP280 calibration parsing and integer compensation, following the Bosch
// BMP280 datasheet (section 3.11.3). No Arduino dependencies, so the math is
// tested on the host by test/bmp280_test.cpp.

constexpr uint8_t kBmp280ChipId = 0x58;
constexpr uint8_t kBme280ChipId = 0x60;
constexpr unsigned kBmp280CalibrationBytes = 24;  // registers 0x88..0x9F
constexpr unsigned kBmp280DataBytes = 6;          // registers 0xF7..0xFC

struct Bmp280Calibration {
  uint16_t t1 = 0;
  int16_t t2 = 0, t3 = 0;
  uint16_t p1 = 0;
  int16_t p2 = 0, p3 = 0, p4 = 0, p5 = 0, p6 = 0, p7 = 0, p8 = 0, p9 = 0;
};

inline uint16_t bmp280U16(const uint8_t *bytes) {
  return static_cast<uint16_t>(bytes[0] | (bytes[1] << 8));
}

inline int16_t bmp280S16(const uint8_t *bytes) {
  return static_cast<int16_t>(bmp280U16(bytes));
}

// raw holds the 24 little-endian bytes read from register 0x88.
inline Bmp280Calibration parseBmp280Calibration(const uint8_t *raw) {
  Bmp280Calibration c;
  c.t1 = bmp280U16(raw);
  c.t2 = bmp280S16(raw + 2);
  c.t3 = bmp280S16(raw + 4);
  c.p1 = bmp280U16(raw + 6);
  c.p2 = bmp280S16(raw + 8);
  c.p3 = bmp280S16(raw + 10);
  c.p4 = bmp280S16(raw + 12);
  c.p5 = bmp280S16(raw + 14);
  c.p6 = bmp280S16(raw + 16);
  c.p7 = bmp280S16(raw + 18);
  c.p8 = bmp280S16(raw + 20);
  c.p9 = bmp280S16(raw + 22);
  return c;
}

// data holds the 6 bytes read from register 0xF7: pressure then temperature,
// each a 20-bit value (MSB, LSB, XLSB[7:4]).
inline int32_t bmp280RawPressure(const uint8_t *data) {
  return (static_cast<int32_t>(data[0]) << 12) | (static_cast<int32_t>(data[1]) << 4) |
         (data[2] >> 4);
}

inline int32_t bmp280RawTemperature(const uint8_t *data) {
  return bmp280RawPressure(data + 3);
}

// Fine temperature shared by the temperature and pressure formulas.
inline int32_t bmp280TFine(const Bmp280Calibration &c, int32_t adcT) {
  const int32_t t1 = c.t1;
  const int32_t var1 = (((adcT >> 3) - t1 * 2) * c.t2) >> 11;
  const int32_t delta = (adcT >> 4) - t1;
  const int32_t var2 = (((delta * delta) >> 12) * c.t3) >> 14;
  return var1 + var2;
}

// Temperature in hundredths of a degree Celsius.
inline int32_t bmp280CentiCelsius(int32_t tFine) {
  return (tFine * 5 + 128) >> 8;
}

// Pressure in Pa as unsigned Q24.8 (divide by 256). Returns 0 when the
// calibration is invalid. Left shifts of possibly negative values are written
// as multiplications to stay well defined.
inline uint32_t bmp280PressureQ24_8(const Bmp280Calibration &c, int32_t adcP, int32_t tFine) {
  int64_t var1 = static_cast<int64_t>(tFine) - 128000;
  int64_t var2 = var1 * var1 * c.p6;
  var2 += var1 * c.p5 * 131072;                       // << 17
  var2 += static_cast<int64_t>(c.p4) * 34359738368LL;  // << 35
  var1 = ((var1 * var1 * c.p3) >> 8) + var1 * c.p2 * 4096;  // << 12
  var1 = ((140737488355328LL + var1) * c.p1) >> 33;    // 1 << 47
  if (var1 == 0) return 0;
  int64_t p = 1048576 - adcP;
  p = ((p * 2147483648LL - var2) * 3125) / var1;       // << 31
  var1 = (static_cast<int64_t>(c.p9) * (p >> 13) * (p >> 13)) >> 25;
  var2 = (static_cast<int64_t>(c.p8) * p) >> 19;
  p = ((p + var1 + var2) >> 8) + static_cast<int64_t>(c.p7) * 16;  // << 4
  return static_cast<uint32_t>(p);
}
