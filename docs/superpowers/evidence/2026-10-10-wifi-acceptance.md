# Bằng chứng nghiệm thu bước 2 — Wi-Fi 50 Hz

Cập nhật: 2026-10-10. Tiêu chí: `../specs/2026-10-10-mpu6050-wifi-acceptance.md`.

## Phần mềm (đã chạy)

| Kiểm tra | Lệnh | Kết quả |
| --- | --- | --- |
| Build USB | `platformio run -e esp32dev` | SUCCESS |
| Build Wi-Fi | `platformio run -e esp32dev_wifi` | SUCCESS |
| C++ net protocol | `g++ ... test/net_protocol_test.cpp` + chạy | 0 failure(s), exit 0 |
| C++ data stream | `g++ ... test/data_stream_test.cpp` + chạy | 0 failure(s), exit 0 |
| C++ calibration | `g++ ... test/calibration_test.cpp` + chạy | 0 failure(s), exit 0 |
| Python | `python -m unittest discover -s collector/tests -t .` | Ran 84 tests — OK |

## Trạng thái AC

| AC | Nội dung | Trạng thái |
| --- | --- | --- |
| AC-01 | Build + regression + hợp đồng phần mềm | ĐẠT (bao gồm USB smoke 60 giây) |
| AC-02 | Wi-Fi nhà + hotspot iPhone | ĐẠT cả hai (3 phiên mạng nhà + 3 phiên hotspot iPhone) |
| AC-03 | Đổi mạng không nạp lại firmware | ĐẠT: nhà→hotspot→nhà, không nạp lại (ESP32 IP đổi .20→.2) |
| AC-04 | Pin dự phòng 10 phút | **ĐẠT cả hai mạng** (nhà + hotspot), 30.002 mẫu/phiên |
| AC-05 | Đeo ở eo, đi bộ 5 phút | **ĐẠT cả hai mạng**, dải ±4 g/±500 °/s, không clipping |
| AC-06 | Phản ứng chuyển động trên Wi-Fi | ĐẠT: xoay đỉnh 444.86 dps, về 0.925 dps khi yên (50.0 Hz) |
| AC-07 | Lỗi/ngắt/phục hồi (Wi-Fi) | ĐẠT: Ctrl+C, reset, client thứ hai, mất Wi-Fi |
| AC-08 | Nghẽn không chặn lấy mẫu | ĐẠT: client nghẽn bị đóng (drain 4400 B); phiên sau sạch |

## Kết quả thiết bị thật — mạng nhà `<SSID nhà>` (2026-10-11)

ESP32 nạp `esp32dev_wifi`, nguồn USB laptop, IP `192.168.1.20`; Pi4 `192.168.1.19`.

| Phiên | Lệnh | Kết quả |
| --- | --- | --- |
| Sạch 1 | `--tcp 192.168.1.20:8765 --duration 60` | completed, 3002 mẫu, 50.0 Hz, 0 lỗi, `gaps_over_40ms=0`, `max_gap_us=20078` |
| Sạch 2 | (lặp) | completed, 3002 mẫu, 50.0 Hz, 0 lỗi |
| Sạch 3 | (lặp) | completed, 3002 mẫu, 50.0 Hz, 0 lỗi |
| Ctrl+C | `timeout -s INT 15` | interrupted, 736 mẫu giữ nguyên |
| Reset ESP32 giữa phiên | pulse RTS sau 18 giây | no_data, 750 mẫu giữ nguyên |
| Client thứ hai | hai collector đồng thời | B `connection_lost` 0 mẫu; A `completed` 2002 mẫu/50.0 Hz/0 lỗi |

## Kết quả thiết bị thật — hotspot iPhone `<SSID hotspot>` (2026-10-11)

ESP32 IPv4 `172.20.10.2`, Pi4 `172.20.10.3`, laptop `172.20.10.5` (cùng hotspot).
ESP32 tự chuyển từ `<SSID nhà>` (thất bại) sang `<SSID hotspot>` sau khi tắt mạng nhà.

| Phiên | Lệnh | Kết quả |
| --- | --- | --- |
| Sạch 1 | `--tcp 172.20.10.2:8765 --duration 60` | completed, 3002 mẫu, 50.0 Hz, 0 lỗi, `max_gap_us=20063`, `gaps_over_40ms=0` |
| Sạch 2 | (lặp) | completed, 3002 mẫu, 50.0 Hz, 0 lỗi |
| Sạch 3 | (lặp) | completed, 3001 mẫu, 50.0 Hz, 0 lỗi |

Telemetry phiên Sạch 1: đầu=cuối (`queue_dropped_total=0`, `unobserved_total=0`), `telemetry_errors=0`.

## AC-03 — quay lại mạng nhà (2026-10-11)

Bật lại mạng nhà, Pi4 và laptop về `<SSID nhà>`. ESP32 (sau khi bấm EN) tự ưu tiên
mạng nhà và nhận IP mới `192.168.1.2` (trước đó `192.168.1.20`), **không nạp lại firmware**.

| Phiên | Lệnh | Kết quả |
| --- | --- | --- |
| Nhà sau khi về | `--tcp 192.168.1.2:8765 --duration 60` | completed, 3002 mẫu, 50.0 Hz, 0 lỗi |

Lưu ý vận hành: địa chỉ IP ESP32 có thể đổi giữa các lần kết nối (DHCP); nên dùng
`--discover` hoặc đọc IP từ log thay vì ghi cứng. Lần kết nối TCP đầu sau khi ESP32
vừa vào mạng có thể báo `No route to host` tạm thời — đợi ping thông rồi chạy.

## AC-07 — mất Wi-Fi giữa phiên (2026-10-11)

Ngắt nguồn router ~10 giây trong lúc collector chạy nền trên Pi4 (ESP32 `192.168.1.2`).

| Phép thử | Kết quả |
| --- | --- |
| Mất Wi-Fi giữa phiên | `status=no_data`, giữ 2129 mẫu, `device_span_s=42.56`, 0 lỗi; mẫu ngừng ở ~43.5s, `no_data` sau ~3s |

AC-01 (USB smoke 60 giây) và AC-06 (chuyển động trên Wi-Fi) và AC-07 (Ctrl+C, reset,
client thứ hai, mất Wi-Fi) đã đạt trên thiết bị thật.

## AC-08 — nghẽn mạng (2026-10-11)

Client nghẽn: `SO_RCVBUF=2048`, kết nối rồi không đọc 12 giây.

| Phép thử | Kết quả |
| --- | --- |
| Client nghẽn | Server chủ động đóng; client chỉ drain được 4400 byte rồi EOF (bộ đệm hữu hạn, không tăng vô hạn) |
| Phiên thường sau đó | completed, 501 mẫu/10s, 50.1 Hz, 0 lỗi — sampling phục hồi ngay |

Bằng chứng bộ đệm/partial-write ở mức đơn vị nằm trong `test/net_protocol_test.cpp` (C++)
và các test Python TCP.

## Kết luận

Đã nghiệm thu trên thiết bị thật: AC-01, AC-02, AC-03, AC-06, AC-07, AC-08.
Còn lại **AC-04 và AC-05 = BLOCKED** (chưa có pin dự phòng cho ESP32 khi đeo ở eo).

Telemetry phiên Sạch 1: `firmware_counters_first == last` (cùng stream, `queue_dropped_total=0`,
`unobserved_total=0`), `telemetry_errors=0`; CSV 3002 hàng khớp `samples_written`.
JSON lưu tại `data/20261011T1031*.json` và `...T103433Z`, `...T103500Z` (bản sao từ Pi4).

## Báo cáo tổng hợp

AC-04/AC-05 đạt **cả hai mạng** (nhà + hotspot iPhone). Tất cả AC-01..AC-08 đã đạt.

## AC-04 / AC-05 — hotspot iPhone (2026-10-13)

Cả ba cùng hotspot `<SSID hotspot>`: ESP32 `172.20.10.2`, Pi4 `172.20.10.3`, laptop `172.20.10.5`.
Đã tắt Wi-Fi nhà để ESP32 chọn hotspot.

| Phiên | Nội dung | Kết quả |
| --- | --- | --- |
| AC-04 hotspot | 10 phút trên bàn | completed, 30.002 mẫu, span 600.02 s, 50.0 Hz, metadata 4/500, một stream, 0 lỗi |
| AC-05 hotspot | 5 phút đeo, ±4 g/±500 | completed, 15.002 mẫu, một stream, 0 lỗi, không clipping (`|a|`max 2.01 g, `|g|`max 198 °/s); 30 s đầu `|g|`=1.64, 30 s cuối `|g|`=1.62 dps |

## AC-04 / AC-05 — nguồn pin, đeo ở eo (mạng nhà, 2026-10-13)

ESP32 nạp `esp32dev_wifi`, cấp nguồn **pin dự phòng USB 5 V/3 A** (đã bỏ điện trở nối tiếp
gây sụt áp), `<SSID nhà>`, IP `192.168.1.2`.

| Phiên | Nội dung | Kết quả |
| --- | --- | --- |
| AC-04 | 10 phút trên bàn | completed, 30.002 mẫu, 50.0 Hz, một stream, 0 lỗi, `gaps_over_40ms=0` |
| AC-05 (1) | 5 phút đeo, dải **±2 g/±250** | completed, 15.002 mẫu, nhưng **chạm thang đo**: `ay=−2.000 g`, `gz≈±250 dps` |
| AC-05 (2) | 5 phút đeo, dải **±4 g/±500** | completed, 15.003 mẫu, một stream, 0 lỗi, **không clipping** (`|a|`max 1.93 g, `|g|`max 196 °/s); 30 s cuối yên `|g|`=3.56 dps |

### Thay đổi firmware: dải ±4 g / ±500 °/s (2026-10-13)

Do đi bộ chạm thang đo ±2 g/±250 °/s, đổi sang **±4 g** (`0x1C=0x08`, 8192 LSB/g) và
**±500 °/s** (`0x1B=0x08`, 65.5 LSB/(°/s)). Cập nhật `src/main.cpp`,
`src/gyro_calibration.h` (hệ số quy đổi), `collector/session.py` (`sensor_config`) và
`test/calibration_test.cpp`. Build 2 env SUCCESS; C++ tests 0 failure; collector 84 OK.

Ghi chú: một lần thử AC-04 đầu tiên kết thúc `no_data` ở giây ~44 do **rớt Wi‑Fi tạm**
(không phải reset; cùng `stream_id` tiếp tục). Lần chạy sau đạt 10 phút.

Lưu ý vận hành: đôi khi cần chờ ESP32 lên mạng (`No route to host` thoáng qua); nên
chờ `ping` thông trước khi mở collector. mDNS `mpu6050-esp32.local` có lúc trả cache cũ —
kiểm tra bằng quét TCP cổng 8765.

