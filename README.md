# IoT HAR — nhận diện hoạt động người bằng ESP32 + MPU6050

Đeo cảm biến quán tính MPU6050 ở eo; ESP32 lấy mẫu 50 Hz và gửi qua USB hoặc Wi-Fi tới
Raspberry Pi 4; Pi4 chạy mô hình **Random Forest** để nhận diện **đi bộ (walk), ngồi (sit),
đứng (stand), nằm (lie)** gần thời gian thực (một kết luận mỗi 1,28 s) và hiển thị trên trang web.

Firmware còn điều khiển phần cứng của bộ đeo: nút nhấn, hai LED, còi, đo pin, màn hình OLED và
cảm biến áp suất BMP280. Pi4 gửi hoạt động vừa nhận diện về để hiện trên màn hình, và ESP32 tự
bật cảnh báo khi nghi té. Các phần này là tùy chọn: chỉ có ESP32 + MPU6050 thì hệ thống vẫn chạy
như trước. Chi tiết: mục [Firmware bộ đeo](#firmware-bộ-đeo--nút-led-còi-pin-oled-bmp280).

```text
MPU6050 ─┐                 Wi-Fi TCP 8765
BMP280 ──┴─I2C─► ESP32 ── DATA 50 Hz, BARO, EVT, STAT ──► Raspberry Pi 4 ──► trình duyệt :8080
OLED ────I2C───►  │   ◄── CMD,1,ACT / CMD,1,ALERT ─────   (collector/, har/)
nút, LED, còi, pin┘
                 (src/)
```

> **Trạng thái:** phần firmware bộ đeo (nút, LED, còi, pin, OLED, BMP280, phát hiện nghi té) đã
> build và qua test trên máy tính, nhưng **chưa chạy trên mạch thật**. Luồng ESP32 + MPU6050 →
> Pi4 → trang web là phần đã chạy và đã đo.

| Thư mục | Chạy ở | Nội dung |
| --- | --- | --- |
| `src/`, `test/` | ESP32 | Firmware PlatformIO: đọc MPU6050 và BMP280, hiệu chỉnh gyro, phát qua USB/Wi-Fi, nút/LED/còi/pin/OLED, phát hiện nghi té; test C++ chạy trên máy tính |
| `src/hw_test/` | ESP32 | Chương trình thử từng phần cứng trên breadboard trước khi hàn |
| `collector/` | Pi4 | Thu một phiên có nhãn ra CSV + JSON, thống kê chất lượng truyền |
| `har/` | Laptop, Pi4 | Cắt cửa sổ, trích 70 đặc trưng, huấn luyện/đánh giá Random Forest, demo trực tiếp/phát lại |
| `data/har_own/` | — | Dữ liệu tự thu: 17 phiên train + 8 phiên test, 120 s/phiên |
| `har_runs/own_rf_01/` | — | Mô hình đã huấn luyện kèm báo cáo đánh giá và benchmark |

## Kết quả

| Thí nghiệm | Macro-F1 test | Ghi chú |
| --- | ---: | --- |
| Random Forest trên dữ liệu MPU6050 tự thu (`own_rf_01`) | **0.975** | Test là buổi thu khác ngày với train; 1 người |
| Random Forest trên UCI HAR (dữ liệu smartphone công khai) | 0.931 | Chia theo người |
| Mô hình UCI chấm trên dữ liệu MPU6050 | 0.106 | Gần bằng Dummy (0.100) → cần dữ liệu riêng |

Suy luận một cửa sổ trên Pi4: p95 khoảng 41 ms (ngưỡng 1,28 s). Chi tiết theo lớp và
confusion matrix: [`har_runs/own_rf_01/report.md`](har_runs/own_rf_01/report.md).

Giới hạn: dữ liệu của **một người**, cùng một cách đeo; chưa có lớp lên/xuống cầu thang. Phát
hiện nghi té trên ESP32 dùng ngưỡng khởi đầu, chưa được kiểm chứng trên dữ liệu té.

## Chạy thử nhanh không cần phần cứng

Dùng ESP32 giả phát lại một phiên đã thu, rồi mở `http://127.0.0.1:8080`
(Windows, Python 3.13; Linux thay đường dẫn `python` tương ứng):

```powershell
py -3.13 -m venv .venv-har
& ".\.venv-har\Scripts\python.exe" -m pip install -r requirements-har.txt
& ".\.venv-har\Scripts\python.exe" -m har fake-esp32 --csv data/har_own/test/20261014T042223Z-e1354d0d.csv --port 8765
# cửa sổ terminal khác:
& ".\.venv-har\Scripts\python.exe" -m har demo --run-dir har_runs/own_rf_01 --esp 127.0.0.1:8765 --data-dir data/har_own --host 127.0.0.1
```

## Khởi động với ESP32 thật

Cần: ESP32 + MPU6050 đã nối dây (VCC=3V3, GND=GND, SDA=GPIO21, SCL=GPIO22, AD0=GND),
Raspberry Pi 4 và ESP32 **cùng một mạng Wi-Fi 2.4 GHz**, điện thoại/laptop cùng mạng để xem web.
Nút, LED, còi, OLED, BMP280 và mạch đo pin là tùy chọn; chân nối ở mục
[Firmware bộ đeo](#firmware-bộ-đeo--nút-led-còi-pin-oled-bmp280).

### 1. Nạp firmware Wi-Fi (một lần, trên laptop)

1. Chép `src/wifi_secrets.example.h` thành `src/wifi_secrets.h`, điền tên và mật khẩu Wi-Fi.
2. Cắm ESP32 vào laptop, nạp bản Wi-Fi và mở Serial (thay `COM6` bằng cổng thực tế; nếu lệnh
   `pio` đã có trong PATH thì gõ `pio` thay cho đường dẫn đầy đủ):

   ```powershell
   $pio = "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe"
   & $pio run -e esp32dev_wifi -t upload --upload-port COM6
   & $pio device monitor -b 115200 --port COM6
   ```

3. Để cảm biến **nằm yên trên bàn**. Log đúng sẽ có lần lượt:

   ```text
   [READY] MPU6050 at 0x68; configuration verified.
   [CAL] DONE bias=(...) dps
   [WIFI] connected ssid=<tên mạng> ip=192.168.1.2      ← IP của ESP32, ghi lại
   ```

   Nếu có gắn OLED, địa chỉ IP cũng hiện trên màn hình khi Pi4 chưa kết nối. Dòng
   `[BARO] no BMP280 ...` và `[UI] no OLED ...` chỉ báo là không gắn hai phần đó.

   IP do router cấp nên có thể đổi; khi cần, xem lại log này hoặc danh sách thiết bị trên router
   (ESP32 có tên mạng `mpu6050-esp32`).

### 2. Cài đặt trên Pi4 (một lần)

Cần Python 3.11 trở lên (Raspberry Pi OS Bookworm đã có sẵn).

```bash
sudo apt update
sudo apt install git python3-venv
git clone https://github.com/huuvietnguyen72/iot-har ~/har-baseline
cd ~/har-baseline
python3 -m venv .venv-har
.venv-har/bin/pip install -r requirements-har.txt
```

Repo đã kèm mô hình `har_runs/own_rf_01` và dữ liệu `data/har_own` nên không cần huấn luyện lại.

Tạo file cấu hình từ mẫu, sửa `esp = ...` thành IP của ESP32, rồi thêm một token truy cập:

```bash
cp har/har_demo.example.toml har_demo.toml
nano har_demo.toml                                   # sửa dòng esp = "..."
echo "token = \"$(.venv-har/bin/python -m har new-token)\"" >> har_demo.toml
chmod 600 har_demo.toml
```

`har_demo.toml` chứa token nên không được đưa lên Git (đã có trong `.gitignore`). Trang web bắt
buộc có token khi mở cho cả mạng (`host = "0.0.0.0"`); chỉ khi `host = "127.0.0.1"` mới được bỏ.

**Tùy chọn — chạy demo như một dịch vụ tự khởi động cùng Pi4.** Script `deploy/install_pi.sh` chép
mã, mô hình và dữ liệu vào `/opt/har`, tạo `/etc/har/har_demo.toml` kèm token, rồi cài dịch vụ
systemd `har-demo`:

```bash
bash deploy/install_pi.sh
sudo nano /etc/har/har_demo.toml          # sửa esp = "..." rồi:
sudo systemctl restart har-demo
journalctl -u har-demo -f                 # xem log
```

Script và dịch vụ **chưa được chạy thử trên Pi4 thật**; nếu gặp lỗi, dùng cách chạy tay ở bước 3.

### 3. Mỗi lần sử dụng

1. **Hiệu chỉnh:** đặt cảm biến nằm yên trên bàn, cấp nguồn ESP32 (USB hoặc pin dự phòng 5 V)
   hoặc bấm nút EN. Giữ yên khoảng 7 giây. Nếu cảm biến bị cầm/đeo lúc này, hiệu chỉnh sẽ bị từ chối
   và tự thử lại sau 3 giây.
2. **Đeo cảm biến** đúng như lúc thu dữ liệu huấn luyện: hông phải ở thắt lưng, mặt chip MPU6050
   hướng ra ngoài, cổng USB của ESP32 chúc xuống. Đeo khác hướng thì mô hình dễ nhận sai.
3. Trên Pi4 (qua SSH), chọn **một** trong hai cách xem kết quả dưới đây. IP ESP32 lấy từ
   `har_demo.toml`; muốn đổi tạm thì thêm `--esp <IP>:8765` vào lệnh.

**Cách A — xem trên trang web**

```bash
cd ~/har-baseline
.venv-har/bin/python -m har demo --config har_demo.toml
```

Mở `http://<IP-Pi4>:8080/?token=<token>` trên điện thoại hoặc laptop (token nằm trong
`har_demo.toml`). Trình duyệt nhớ token, các lần sau chỉ cần `http://<IP-Pi4>:8080`. Không có token
thì trang trả lỗi 401. Trang mở sẵn chế độ **Trực tiếp**, hiển thị
hoạt động hiện tại (đi bộ/ngồi/đứng/nằm), độ tin cậy và tốc độ nhận mẫu; kết quả mới khoảng mỗi
1,28 giây. Nút **Phát lại** chạy lại các phiên đã thu trong `data/har_own` (ngắt kết nối ESP32);
bấm **Trực tiếp** để quay lại. Dừng bằng Ctrl+C trong SSH.

Kiểm tra nhanh từ chính Pi4: `curl -H "Authorization: Bearer <token>" http://127.0.0.1:8080/health`
trả mã 200 khi đang nhận dữ liệu hoặc đang phát lại, 503 khi chưa có dữ liệu hoặc dữ liệu bị trễ.

**Cách B — xem trên terminal**

```bash
cd ~/har-baseline
.venv-har/bin/python -m har live --config har_demo.toml
```

Mỗi kết luận in một dòng, ví dụ:

```text
Đã nhận dữ liệu từ ESP32
14:05:12  ĐI BỘ   93%   (thô: walk 0.95)   50.0 Hz  mất 0 mẫu
14:05:13  ĐI BỘ   95%   (thô: walk 0.97)   50.0 Hz  mất 0 mẫu
```

Cột phần trăm là xác suất trung bình 3 cửa sổ gần nhất; dưới 60% sẽ có thêm `(không chắc)`.
Dừng bằng Ctrl+C.

Cả hai lệnh cũng chạy được trên laptop (Windows: thay `.venv-har/bin/python` bằng
`.\.venv-har\Scripts\python.exe`) nếu laptop cùng mạng với ESP32. Không dùng file cấu hình thì
truyền thẳng tham số, ví dụ
`har live --run-dir har_runs/own_rf_01 --esp 192.168.1.2:8765`.

### Xử lý sự cố

| Thông báo | Nguyên nhân và cách xử lý |
| --- | --- |
| `Đang tìm ESP32 (…)… lần thử N` | Sai IP, ESP32 chưa vào mạng hoặc khác mạng với Pi4. Xem lại IP trong log Serial. |
| `ESP32 đang hiệu chỉnh — để yên trên bàn` | ESP32 vừa bật/reset. Tháo ra đặt yên trên bàn đến khi hết thông báo rồi đeo lại. |
| `ESP32 đang bận …` | ESP32 chỉ nhận một kết nối. Tắt `collector`, `demo` hoặc `live` khác đang chạy; ngay sau khi rớt Wi-Fi có thể phải chờ vài giây. |
| `Mất kết nối — đang thử lại` | 5 giây không nhận dữ liệu (mất Wi-Fi, hết pin). Chương trình tự kết nối lại. |
| `ESP32 vừa khởi động lại` | ESP32 reset và đã hiệu chỉnh lại; nếu nó reset khi đang đeo, xem dòng hiệu chỉnh ở trên. |
| `đặt token trong har_demo.toml …` | `har demo` từ chối mở cho cả mạng khi chưa có token. Thêm token như ở bước 2, hoặc đặt `host = "127.0.0.1"` nếu chỉ xem trên chính máy đó. |
| Trang báo `token required` (401) | Mở lại bằng `http://<IP-Pi4>:8080/?token=<token>`. |

Các phần dưới đây mô tả từng bước của dự án theo thứ tự thực hiện.

## Bước 1 — thu dữ liệu USB 50 Hz và hiệu chỉnh gyro

Firmware hiệu chỉnh gyro lúc khởi động rồi phát bản ghi `DATA` khoảng **50 Hz** qua USB 115200.
Gói Python `collector` (chạy trên Raspberry Pi 4, Debian 12, Python 3.11) lưu từng phiên ra
**CSV + JSON** kèm số liệu chất lượng truyền.

### Phần cứng và nạp firmware

- MPU6050: VCC=3V3, GND=GND, SDA=GPIO21, SCL=GPIO22, AD0=GND (địa chỉ 0x68).
- Các phần khác của bộ đeo (tùy chọn): xem bảng chân ở mục
  [Firmware bộ đeo](#firmware-bộ-đeo--nút-led-còi-pin-oled-bmp280).
- Build/Upload bằng PlatformIO. Đặt thư mục dự án ở **đường dẫn không dấu**: toolchain ESP32
  lỗi khi tạo file tạm trong đường dẫn có dấu tiếng Việt. Nếu không đổi được chỗ, thêm vào
  đầu `platformio.ini` một thư mục build không dấu, ví dụ:

  ```ini
  [platformio]
  build_dir = C:/pio-build/iot-har
  ```
- Giữ cảm biến cố định khi khởi động: hiệu chỉnh cần 2 giây ổn định + 500 mẫu (~5 giây).
  Nếu bị từ chối, chương trình tự thử lại sau 3 giây.

### Giao thức v1 (115200 baud, mỗi dòng một bản ghi)

```text
DATA,1,7a31b25c809fd416,12,8340000,-0.921,0.051,0.132,0.120,-0.080,0.050,29.40
```

`DATA,1,<stream_id>,<seq>,<device_time_us>,<ax_g>,<ay_g>,<az_g>,<gx_dps>,<gy_dps>,<gz_dps>,<temp_c>`

- `stream_id`: 16 ký tự hex, đổi mới sau mỗi lần hiệu chỉnh thành công; `seq` bắt đầu lại từ 0.
- `device_time_us`: microsecond đơn điệu của ESP32.
- `gx/gy/gz`: đã trừ bias gyro; gia tốc còn trọng lực, chưa hiệu chỉnh sai lệch.
- Các dòng `[SCAN]`, `[CAL]`, `[ID]`, `[READY]`, `[TEST]`, `[RETRY]`, `[ERROR]`, `[BARO]`,
  `[UI]`, `[FALL]` là thông báo, không phải bản ghi dữ liệu.
- Firmware bộ đeo gửi thêm các dòng `BARO`, `EVT`, `STAT` và nhận lệnh `CMD`; xem
  [Dòng mới trong giao thức](#dòng-mới-trong-giao-thức). Bộ thu bỏ qua các dòng này.

### Cài đặt bộ thu trên Pi4

`collector` chỉ cần thư viện chuẩn Python và pyserial. Nếu chưa clone repo vào
`~/har-baseline` (mục "Khởi động với ESP32 thật" → bước 2), làm như sau:

```bash
sudo apt update
sudo apt install git python3-serial
git clone https://github.com/huuvietnguyen72/iot-har ~/har-baseline
```

### Chạy một phiên thu (trên Pi4 qua SSH)

```bash
cd ~/har-baseline
python3 -m collector --port /dev/ttyUSB0 --duration 60 --label test
```

- `--port`: cổng thực tế (`python3 -m serial.tools.list_ports -v`); thoát miniterm (Ctrl+]) trước khi chạy.
- `--duration`: số giây ghi, tính từ mẫu hợp lệ đầu tiên (không tính thời gian hiệu chỉnh).
- `--label`: nhãn phiên, chỉ `[A-Za-z0-9_-]`; dùng `test` cho phiên kiểm tra trên bàn.
- `--output`: thư mục đích (mặc định `data`).
- Nhấn Ctrl+C để dừng sớm: phần dữ liệu đã nhận được giữ lại với trạng thái `interrupted`.

Nếu lỗi `Permission denied`, chạy `sudo usermod -aG dialout "$USER"`, đăng nhập SSH lại.

### Tệp kết quả

- `<session_id>.csv`: `session_id,label,stream_id,seq,device_time_us,host_elapsed_s,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c`.
- `<session_id>.json`: phiên bản giao thức, nhãn, trạng thái kết thúc, cổng/baud, thời lượng
  yêu cầu, stream_id, cấu hình cảm biến dự kiến và thống kê chất lượng: mẫu đã ghi, DATA lỗi,
  mẫu thiếu theo seq, trùng/đảo thứ tự, timestamp lỗi, dòng quá dài, khoảng cách mẫu lớn nhất,
  số khoảng cách > 40 ms, tốc độ mẫu thực tế từ timestamp thiết bị.
- Trạng thái kết thúc: `completed`, `interrupted`, `no_data`, `wait_timeout`, `stream_changed`,
  `serial_error`, hoặc `recording` nếu tiến trình bị tắt đột ngột.

Mã thoát CLI: 0 completed; 130 interrupted; 3 không nhận được dữ liệu; 4 stream đổi giữa chừng
(ESP32 reset/hiệu chỉnh lại — chạy phiên mới); 5 lỗi cổng serial; 6 lỗi vào/ra tệp; 2 lỗi tham số.

### Nghiệm thu trên thiết bị (60 giây)

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

Trên Pi4 (cùng mạng với ESP32):

```bash
cd ~/har-baseline
python3 -m collector --tcp ESP_IP:8765 --duration 60 --label test --output data
python3 -m collector --discover --duration 60 --label test --output data   # cần: sudo apt install python3-zeroconf
```

- ESP32 vẫn giữ nhịp lấy mẫu 50 Hz khi mạng chậm; mẫu bị bỏ được báo qua NET.
- Mất Wi-Fi hoặc ESP32 reset: phiên kết thúc `connection_lost`/`no_data`, dữ liệu đã ghi được giữ.
- Nguồn tạm thời: cấp ESP32 từ USB; khi đeo ở eo cần pin dự phòng 5V.
- Nghiệm thu thực tế: ở cả mạng nhà và hotspot iPhone, phiên 60 s đạt 50 Hz, không mất mẫu;
  ESP32 tự chuyển sang hotspot khi mạng nhà mất.

## Firmware bộ đeo — nút, LED, còi, pin, OLED, BMP280

Cả hai bản firmware (`esp32dev` qua USB và `esp32dev_wifi`) có thêm các phần dưới đây. Phần nào
không gắn thì firmware tự bỏ qua: chỉ có ESP32 + MPU6050 vẫn chạy như trước, dòng `DATA,1` và
`[NET],1` không đổi.

| Phần | Chân | Hoạt động |
|---|---|---|
| MPU6050, BMP280 | SDA 21, SCL 22 | BMP280 (0x76/0x77) được đọc ngay sau mỗi mẫu `DATA` thứ 5, tức 10 lần/giây |
| OLED 0,96" 128×64 | SDA 19, SCL 18 | Bus I2C riêng để việc vẽ không làm trễ mẫu 50 Hz. Địa chỉ 0x3C hoặc 0x3D |
| LED xanh, LED đỏ | 26, 27 | Xem bảng đèn bên dưới |
| Nút nhấn | 32 → GND | Nhấn: bật màn hình 10 giây, hủy cảnh báo. Giữ 2 giây: gửi SOS |
| Còi, motor rung | 25, 33 | Qua transistor S8050. Kêu khi có cảnh báo, bíp ngắn khi nhấn nút |
| Đo pin | 34 | Cầu chia 100 kΩ + 100 kΩ. Ngoài khoảng 2,5–4,5 V thì coi như không có pin |

Đèn báo:

| Đèn | Nghĩa |
|---|---|
| Xanh nháy nhanh | Đang hiệu chỉnh gyro, giữ yên thiết bị |
| Xanh nháy chậm | Có Wi-Fi, Pi4 chưa kết nối |
| Xanh chớp ngắn mỗi 2 giây | Đang gửi dữ liệu |
| Đỏ sáng liên tục | Lỗi cảm biến MPU6050 |
| Đỏ nháy chậm | Mất Wi-Fi |
| Đỏ chớp đôi mỗi 3 giây | Pin yếu (từ 15% trở xuống) |
| Đỏ nháy nhanh, còi kêu | Cảnh báo té. Còi tự im sau 60 giây, đèn nháy đến khi hủy |

Màn hình tắt khi không dùng và bật lại khi nhấn nút, khi có cảnh báo, hoặc khi cảm biến chưa
sẵn sàng. Dòng to là hoạt động Pi4 gửi về (hoặc trạng thái thiết bị); ba dòng nhỏ là pin, Wi-Fi
và trạng thái kết nối với Pi4. Chữ trên màn hình là tiếng Việt không dấu. Phần trăm pin chỉ là
ước lượng từ điện áp.

Tùy chọn khi build, thêm vào `build_flags` trong `platformio.ini`:

- `-D OLED_SH1106=1`: màn hình dùng chip SH1106 thay vì SSD1306. Nếu hình bị lệch 2 điểm ảnh
  sang một bên hoặc có sọc nhiễu ở mép, hãy thử cờ này.
- `-D BUZZER_PASSIVE=1`: còi thụ động, cần xung 2,7 kHz. Dùng khi trong `hw_test` chỉ phím `t`
  làm còi kêu.
- `-D FALL_DETECT=0`: tắt phát hiện nghi té trên thiết bị (xem mục dưới). Nên tắt khi thu dữ
  liệu té có dàn dựng, để còi không kêu giữa phiên thu.

### Phát hiện nghi té trên thiết bị

ESP32 tự bật cảnh báo, không cần Pi4, khi thấy đủ ba điều theo thứ tự (`src/fall_detector.h`):

1. Va đập: độ lớn gia tốc đạt 2,5 g trở lên.
2. Chờ 1 giây cho hết nảy, lăn.
3. Trong 2 giây tiếp theo, mọi mẫu đều gần 1 g (nằm yên) và trục Y lệch khỏi phương thẳng đứng
   hơn khoảng 60° (|ay| ≤ 0,5 g, tức là không còn đứng hay ngồi thẳng).

Khi đó thiết bị gửi `EVT,1,...,fall_suspect,<seq>` rồi bật còi và đèn đỏ. Người đeo nhấn nút để
hủy. Ngồi phịch xuống hay nhảy thì có va đập nhưng sau đó vẫn thẳng người nên bị bỏ qua; nằm
xuống nhẹ thì không có va đập. Thả người xuống giường vẫn có thể báo nhầm.

Các ngưỡng trên là giá trị khởi đầu theo thông lệ, **chưa được chỉnh trên dữ liệu té thật** và
chưa đo tỉ lệ báo nhầm, bỏ sót. Quy tắc dựa trên hướng đeo của dự án (trục Y chỉ xuống khi đứng).
Hãy coi mỗi lần báo là "nghi té" cho đến khi có dữ liệu kiểm chứng.

### Dòng mới trong giao thức

Bộ thu và trang demo hiện tại bỏ qua mọi dòng không bắt đầu bằng `DATA` hoặc `[NET]`, nên các
dòng mới không ảnh hưởng dữ liệu đang thu.

ESP32 gửi đi:

```text
BARO,1,<stream_id>,<seq>,<device_time_us>,<pressure_pa>,<temp_c>
EVT,1,<stream_id>,<device_time_us>,<name>,<value>
STAT,1,<stream_id>,<device_time_us>,<vbat_mv>,<percent>,<rssi_dbm>,<flags>
```

- `BARO`: `seq` là số thứ tự của mẫu `DATA` vừa đọc trước đó.
- `EVT`: `name` là `button` (nhấn nút, `value` là số lần), `sos` (giữ nút 2 giây),
  `fall_suspect` (thiết bị nghi té, `value` là `seq` của mẫu lúc đó), `alert_on` (đã bật cảnh
  báo), `alert_cancel` (người đeo nhấn nút hủy).
- `STAT`: mỗi 10 giây. `vbat_mv = 0` và `percent = -1` nghĩa là không đo được pin.
  `flags` là tổng của: 1 = BMP280 hoạt động, 2 = có OLED, 4 = đang cảnh báo, 8 = pin yếu.
- `stream_id` để trống cho đến khi hiệu chỉnh gyro xong.

Pi4 gửi về ESP32, mỗi lệnh một dòng (qua TCP 8765, hoặc gõ vào Serial Monitor để thử):

```text
CMD,1,ACT,<label>     hoạt động vừa nhận diện: walk, sit, stand, lie, ...
CMD,1,ALERT,<0|1>     bật / tắt cảnh báo té
```

Nhãn hoạt động chỉ gồm chữ thường, số và dấu gạch dưới, tối đa 15 ký tự. Nếu quá 5 giây không
có lệnh `ACT` mới, màn hình hiện `--`. `har live` và `har demo` (chế độ trực tiếp) gửi lệnh
`ACT` mỗi giây khi đang có kết quả nhận diện. Pi4 chưa gửi `ALERT` vì chưa có mô hình phát
hiện té; hiện cảnh báo do chính ESP32 bật (mục trên). Có thể gõ lệnh vào Serial Monitor để thử
còi và đèn.

Áp suất đi bằng dòng `BARO` riêng thay cho dòng `DATA2` từng dự tính: dòng `DATA,1` giữ nguyên
12 trường nên dữ liệu và mô hình cũ dùng tiếp được, và bộ thu cũ không báo lỗi định dạng.

## Bước 3A — Baseline nhận diện hoạt động (dữ liệu công khai)

Package `har/` dựng pipeline nhận diện `walk/sit/stand/lie` bằng dữ liệu UCI HAR
với mô hình **Random Forest** (chọn cấu hình bằng GroupKFold theo người), huấn luyện
trên laptop và thử suy luận trên Pi4. Kết quả: macro-F1 test 0.9306 trên UCI; benchmark
Pi4 p95 39.7 ms. Lệnh: [`har/README.md`](har/README.md).

## Bước 3B — Nhận diện trên dữ liệu MPU6050 tự thu (1 người)

Thu dữ liệu có nhãn và huấn luyện lại bằng `har train-own`. Dữ liệu đã thu nằm trong
`data/har_own/`, mô hình kết quả trong `har_runs/own_rf_01/`. Quy trình thu và lệnh:
[`har/README.md`](har/README.md).

## Demo — nhận diện walk/sit/stand/lie (trực tiếp và phát lại)

Pi4 đọc ESP32, chạy mô hình `har_runs/own_rf_01` và phục vụ trang web `http://<IP-Pi4>:8080`;
có chế độ phát lại CSV đã ghi khi không có cảm biến. Lệnh và lưu ý: `har/README.md`
(mục "Demo trực tiếp / phát lại").

## Kiểm tra phần mềm

Chạy từ thư mục gốc của repo.

Build firmware bằng PlatformIO (Windows; nếu `pio` đã có trong PATH thì gõ `pio` thay cho
đường dẫn đầy đủ). Bản Wi-Fi vẫn build được khi chưa có `src/wifi_secrets.h`, nhưng sẽ không vào được mạng:

```powershell
$pio = "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe"
& $pio run -e esp32dev
& $pio run -e esp32dev_wifi
```

Lần build đầu PlatformIO tự tải thư viện U8g2 (cần mạng).

Chương trình thử phần cứng trên breadboard (`src/hw_test/`, tách khỏi firmware chính): quét I2C,
đọc MPU6050 và BMP280, vẽ hình thử lên OLED, nháy LED, đọc nút, bật còi, đo áp pin. Nạp rồi mở
Serial Monitor, gõ `h` để xem lệnh:

```powershell
& $pio run -e hw_test -t upload
& $pio device monitor -e hw_test
```

Test C++ chạy trên máy tính (cần `g++`):

```bash
for t in calibration data_stream net_protocol bmp280 button battery indicator \
         wearable_protocol display_view fall_detector; do
  g++ -std=c++11 -Wall -Wextra -Werror test/${t}_test.cpp -o ${t}_test && ./${t}_test
done
```

Test Python (`collector` không cần pyserial; `har` cần các gói trong `requirements-har.txt`):

```text
python -m unittest discover -s collector/tests -t . -v
python -m unittest discover -s har/tests -t . -v
```

## Giấy phép

Mã nguồn phát hành theo giấy phép MIT — xem [`LICENSE`](LICENSE). Dữ liệu UCI HAR dùng trong
bước 3A thuộc giấy phép CC BY 4.0 (không kèm trong repo, tải bằng `har prepare`).
