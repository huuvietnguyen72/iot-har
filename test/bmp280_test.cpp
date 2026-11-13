#include "../src/bmp280.h"
#include <cstdio>
#include <cstdlib>

namespace {
int failures = 0;

void check(bool condition, const char *name) {
  std::printf("%s: %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) ++failures;
}

void putU16(uint8_t *bytes, int value) {
  bytes[0] = static_cast<uint8_t>(value & 0xFF);
  bytes[1] = static_cast<uint8_t>((value >> 8) & 0xFF);
}

// Calibration example from the Bosch BMP280 datasheet compensation table.
Bmp280Calibration datasheetCalibration() {
  const int words[12] = {27504, 26435, -1000, 36477, -10685, 3024,
                         2855,  140,   -7,    15500, -14600, 6000};
  uint8_t raw[kBmp280CalibrationBytes];
  for (unsigned i = 0; i < 12; ++i) putU16(raw + 2 * i, words[i]);
  return parseBmp280Calibration(raw);
}
}  // namespace

int main() {
  const Bmp280Calibration c = datasheetCalibration();
  check(c.t1 == 27504 && c.t2 == 26435 && c.t3 == -1000,
        "temperature coefficients parse as unsigned/signed little endian");
  check(c.p1 == 36477 && c.p2 == -10685 && c.p9 == 6000 && c.p6 == -7,
        "pressure coefficients parse as unsigned/signed little endian");

  const uint8_t data[kBmp280DataBytes] = {0x65, 0x5A, 0xC0, 0x7E, 0xED, 0x00};
  check(bmp280RawPressure(data) == 415148, "20-bit raw pressure is assembled from 0xF7..0xF9");
  check(bmp280RawTemperature(data) == 519888,
        "20-bit raw temperature is assembled from 0xFA..0xFC");

  const int32_t tFine = bmp280TFine(c, 519888);
  check(std::abs(tFine - 128422) <= 2, "t_fine matches the datasheet example");
  check(bmp280CentiCelsius(tFine) == 2508, "temperature is 25.08 degC as in the datasheet");

  const double pascal = bmp280PressureQ24_8(c, 415148, tFine) / 256.0;
  check(pascal > 100652.0 && pascal < 100655.0, "pressure is about 100653 Pa as in the datasheet");

  Bmp280Calibration broken = c;
  broken.p1 = 0;
  check(bmp280PressureQ24_8(broken, 415148, tFine) == 0, "zero dig_P1 returns 0 instead of dividing");

  std::printf("%d failure(s)\n", failures);
  return failures == 0 ? 0 : 1;
}
