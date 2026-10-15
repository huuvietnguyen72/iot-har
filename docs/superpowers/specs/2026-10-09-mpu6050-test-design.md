# ESP32 / MPU6050 hardware test

Approved in chat: ESP32 DevKit, Arduino, direct Wire register access.

## Configuration

- Keep environment `esp32dev` and existing Espressif platform.
- SDA GPIO21, SCL GPIO22, I2C 100 kHz, timeout 50 ms.
- Serial 115200 baud; print samples every 200 ms.
- VCC 3V3, GND common, AD0 GND (0x68); also support 0x69.
- Use only Arduino/Wire, without external sensor dependencies.

## Firmware

Scan the I2C bus, then validate WHO_AM_I (register 0x75, expected 0x68)
at either candidate address. Reset and wake the sensor; enable all axes,
configure +/-2 g and +/-250 deg/s, DLPF setting 3, sample divider 9.
Read back the configuration before streaming.

Read 14 bytes in one transaction from 0x3B. Decode signed big-endian
acceleration, temperature and gyroscope values. Convert acceleration using
16384 LSB/g, gyroscope using 131 LSB/(deg/s), temperature using raw/340+36.53.
Print raw values, converted values, acceleration magnitude, and read counters.
Reject all-zero/all-0xFF frames; warn about identical frames persisting for
five seconds. Successful reads establish communication, not proof of motion.
Report I2C errors and retry initialization every three seconds after a failure.

## Verification

Build with PlatformIO. If a connected ESP32 is available, upload and capture
Serial output. Check identity/configuration and sustained successful reads.
For physical confirmation, the user must hold the board still, tilt it and
rotate it. At rest, acceleration magnitude should be about 1 g and gyro near
zero with uncalibrated bias; tilt changes acceleration axes and rotation
changes gyro readings. Disconnecting the sensor must produce errors.

README documents wiring, commands, expected output and troubleshooting.
