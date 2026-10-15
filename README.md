# ESP32 + MPU6050: thu dữ liệu USB 50 Hz và hiệu chỉnh gyro

Firmware hiệu chỉnh gyro lúc khởi động rồi phát bản ghi `DATA` khoảng **50 Hz** qua USB 115200.
Gói Python `collector` (chạy trên Raspberry Pi 4, Debian 12, Python 3.11) lưu từng phiên ra
**CSV + JSON** kèm số liệu chất lượng truyền.

## Phần cứng và nạp firmware

- MPU6050: VCC=3V3, GND=GND, SDA=GPIO21, SCL=GPIO22, AD0=GND (địa chỉ 0x68).
- Build/Upload bằng PlatformIO. Trên Windows, `platformio.ini` đã đặt `build_dir` vào
  đường dẫn không dấu trong `%TEMP%` (toolchain ESP32 lỗi khi tạo file tạm trong đường
  dẫn có dấu tiếng Việt); build trực tiếp tại thư mục project, không cần sao chép.
- Giữ cảm biến cố định khi khởi động: hiệu chỉnh cần 2 giây ổn định + 500 mẫu (~5 giây).
  Nếu bị từ chối, chương trình tự thử lại sau 3 giây.

## Giao thức v1 (115200 baud, mỗi dòng một bản ghi)

```text
DATA,1,7a31b25c809fd416,12,8340000,-0.921,0.051,0.132,0.120,-0.080,0.050,29.40
```

`DATA,1,<stream_id>,<seq>,<device_time_us>,<ax_g>,<ay_g>,<az_g>,<gx_dps>,<gy_dps>,<gz_dps>,<temp_c>`

- `stream_id`: 16 ký tự hex, đổi mới sau mỗi lần hiệu chỉnh thành công; `seq` bắt đầu lại từ 0.
- `device_time_us`: microsecond đơn điệu của ESP32.
- `gx/gy/gz`: đã trừ bias gyro; gia tốc còn trọng lực, chưa hiệu chỉnh sai lệch.
- Các dòng `[SCAN]`, `[CAL]`, `[ID]`, `[READY]`, `[TEST]`, `[RETRY]`, `[ERROR]` là thông báo,
  không phải bản ghi dữ liệu.

## Cài đặt bộ thu trên Pi4

```bash
sudo apt update
sudo apt install python3-serial
```

Chép gói `collector` sang Pi4 (chạy trên laptop, PowerShell; thay `<IP>`):

```powershell
scp -r .\collector pi@<IP>:~/collector
```

## Chạy một phiên thu (trên Pi4 qua SSH)

```bash
cd ~
python3 -m collector --port /dev/ttyUSB0 --duration 60 --label test
```

- `--port`: cổng thực tế (`python3 -m serial.tools.list_ports -v`); thoát miniterm (Ctrl+]) trước khi chạy.
- `--duration`: số giây ghi, tính từ mẫu hợp lệ đầu tiên (không tính thời gian hiệu chỉnh).
- `--label`: nhãn phiên, chỉ `[A-Za-z0-9_-]`; dùng `test` cho phiên kiểm tra trên bàn.
- `--output`: thư mục đích (mặc định `data`).
- Nhấn Ctrl+C để dừng sớm: phần dữ liệu đã nhận được giữ lại với trạng thái `interrupted`.

Nếu lỗi `Permission denied`, chạy `sudo usermod -aG dialout "$USER"`, đăng nhập SSH lại.

## Tệp kết quả

- `<session_id>.csv`: `session_id,label,stream_id,seq,device_time_us,host_elapsed_s,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c`.
- `<session_id>.json`: phiên bản giao thức, nhãn, trạng thái kết thúc, cổng/baud, thời lượng
  yêu cầu, stream_id, cấu hình cảm biến dự kiến và thống kê chất lượng: mẫu đã ghi, DATA lỗi,
  mẫu thiếu theo seq, trùng/đảo thứ tự, timestamp lỗi, dòng quá dài, khoảng cách mẫu lớn nhất,
  số khoảng cách > 40 ms, tốc độ mẫu thực tế từ timestamp thiết bị.
- Trạng thái kết thúc: `completed`, `interrupted`, `no_data`, `wait_timeout`, `stream_changed`,
  `serial_error`, hoặc `recording` nếu tiến trình bị tắt đột ngột.

Mã thoát CLI: 0 completed; 130 interrupted; 3 không nhận được dữ liệu; 4 stream đổi giữa chừng
(ESP32 reset/hiệu chỉnh lại — chạy phiên mới); 5 lỗi cổng serial; 6 lỗi vào/ra tệp; 2 lỗi tham số.

## Kiểm tra phần mềm

Build firmware (PlatformIO, từ đường dẫn ASCII):

```text
pio run
```

Test host C++ (calibration + data stream):

```text
g++ -std=c++11 -Wall -Wextra -Werror test/calibration_test.cpp -o calibration-test
g++ -std=c++11 -Wall -Wextra -Werror test/data_stream_test.cpp -o data-stream-test
```

Test Python (không cần pyserial; chạy từ thư mục `esp32-test`):

```text
python3 -m unittest discover -s collector/tests -t . -v
```

## Nghiệm thu trên thiết bị (60 giây)

1. Nạp firmware; cắm ESP32 vào Pi4; chạy collector; giữ cảm biến cố định tới hết `[CAL] DONE`.
2. Mục tiêu: tốc độ 49–51 Hz từ timestamp thiết bị (khoảng 2.940–3.060 mẫu/60 giây);
   phiên sạch có 0 DATA lỗi, 0 mẫu thiếu/trùng/đảo thứ tự và 0 khoảng cách > 40 ms.
3. Xoay/lắc cảm biến sau khi ghi: giá trị gyro phải thay đổi rồi trở về gần 0 khi dừng.
4. Kiểm tra số dòng CSV khớp `samples_written` trong JSON.
5. Thử dừng giữa chừng bằng Ctrl+C, rút USB và reset ESP32: khi reset ESP32, phiên thường kết
   thúc với trạng thái `no_data` (mã thoát 3) vì quá trình hiệu chỉnh lại lâu hơn ngưỡng gap
   3 giây, dữ liệu đã ghi vẫn nguyên vẹn; `stream_changed` (mã thoát 4) là trường hợp quan sát
   được stream_id mới mà ngưỡng gap chưa kịp kích hoạt.

## Bước 2 — truyền Wi-Fi 50 Hz

Firmware có hai biến thể build: `esp32dev` (USB, mặc định) và `esp32dev_wifi` (Wi-Fi).
Bản Wi-Fi lấy mẫu vào hàng đợi 100 mẫu và phát qua TCP cổng 8765; một client tại một
thời điểm. Dòng `[NET],1,<stream_id>,<queue_dropped_total>,<unobserved_total>` là telemetry,
không phải DATA.

### Cấu hình mạng

Chép `src/wifi_secrets.example.h` thành `src/wifi_secrets.h` (đã gitignore) và điền:
- `WIFI_HOME_SSID` / `WIFI_HOME_PASS`: mạng nhà 2.4 GHz (ưu tiên).
- `WIFI_HOTSPOT_SSID` / `WIFI_HOTSPOT_PASS`: hotspot iPhone, đã bật Maximize Compatibility.

Không đưa mật khẩu vào source/log. ESP32 thử mạng nhà trước, rồi hotspot, mỗi lần tối đa 10 giây.

### Nạp và chạy

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -e esp32dev_wifi -t upload --upload-port COM6
```

Trên Pi4 (cùng mạng với ESP32), từ thư mục chứa package `collector`:

```bash
python3 -m collector --tcp ESP_IP:8765 --duration 60 --label test --output data
python3 -m collector --discover --duration 60 --label test --output data   # cần: pip install zeroconf
```

- ESP32 vẫn giữ nhịp lấy mẫu 50 Hz khi mạng chậm; mẫu bị bỏ được báo qua NET.
- Mất Wi-Fi hoặc ESP32 reset: phiên kết thúc `connection_lost`/`no_data`, dữ liệu đã ghi được giữ.
- Nguồn tạm thời: cấp ESP32 từ USB; khi đeo ở eo cần pin dự phòng 5V.
- Tiêu chí nghiệm thu chi tiết: `docs/superpowers/specs/2026-10-10-mpu6050-wifi-acceptance.md`.

## Bước 3A — Baseline nhận diện hoạt động (dữ liệu công khai)

Package `har/` dựng pipeline nhận diện `walk/sit/stand/lie` bằng dữ liệu UCI HAR
với mô hình **Random Forest** (chọn cấu hình bằng GroupKFold theo người), huấn luyện
trên laptop và thử suy luận trên Pi4. Xem `har/README.md`. Đặc tả:
`docs/superpowers/specs/2026-10-12-har-public-baseline-design.md`. Kết quả hiện tại
(macro-F1 test 0.9306 trên UCI; benchmark Pi4 p95 39.7 ms):
`docs/superpowers/evidence/2026-10-12-har-public-baseline.md`.

## Bước 3B — Nhận diện trên dữ liệu MPU6050 của bạn (1 người)

Thu dữ liệu có nhãn và huấn luyện lại bằng `har train-own`. Quy trình thu (hiệu chỉnh trên
bàn, hướng đeo, xen kẽ hoạt động, buổi test riêng) và tiêu chí nghiệm thu:
`docs/superpowers/specs/2026-10-13-har-own-data-design.md`. Lệnh: `har/README.md`.

## Demo — nhận diện walk/sit/stand/lie (trực tiếp và phát lại)

Pi4 đọc ESP32, chạy mô hình `har_runs/own_rf_01` và phục vụ trang web `http://<IP-Pi4>:8080`;
có chế độ phát lại CSV đã ghi khi không có cảm biến. Lệnh và lưu ý: `har/README.md`
(mục "Demo trực tiếp / phát lại").
