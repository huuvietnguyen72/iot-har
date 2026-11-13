# IoT HAR — nhận diện hoạt động người bằng ESP32 + MPU6050

Một bộ đeo ở eo gồm ESP32 và cảm biến quán tính MPU6050 lấy mẫu 50 Hz, gửi qua Wi-Fi (hoặc USB)
tới Raspberry Pi 4. Pi4 chạy mô hình **Random Forest** nhận diện **đi bộ (walk), ngồi (sit), đứng
(stand), nằm (lie)**, cứ khoảng 1,28 giây ra một kết luận, và hiển thị trên trang web. Khi gắn thêm
cảm biến áp suất BMP280, hệ thống nhận ra thêm **lên cầu thang** và **xuống cầu thang**
([mục 8](#8-nhận-diện-lên--xuống-cầu-thang)).

Bộ đeo có thể gắn thêm nút nhấn, hai LED, còi, mạch đo pin, màn hình OLED và BMP280. Pi4 gửi hoạt
động vừa nhận diện về để hiện trên màn hình; ESP32 tự bật cảnh báo khi nghi té. Các phần thêm này
là tùy chọn: chỉ có ESP32 + MPU6050 thì hệ thống vẫn chạy.

```text
MPU6050 ─┐                  Wi-Fi TCP 8765
BMP280 ──┴─I2C─► ESP32 ── DATA 50 Hz, BARO, EVT, STAT ──► Raspberry Pi 4 ──► trình duyệt :8080
OLED ────I2C───►  │    ◄── CMD,1,ACT / CMD,1,ALERT ─────   (collector/, har/)
nút, LED, còi, pin┘
                 (src/)
```

> **Trạng thái:** luồng ESP32 + MPU6050 → Pi4 → trang web đã chạy và đã đo. Phần bộ đeo (nút,
> LED, còi, pin, OLED, BMP280, phát hiện nghi té, nhận diện cầu thang) và script cài dịch vụ trên
> Pi4 đã build và qua test trên máy tính, nhưng **chưa chạy trên phần cứng thật**. Mô hình mẫu
> chưa có lớp cầu thang vì chưa thu dữ liệu cầu thang.

## Repo có gì

| Thư mục | Chạy ở | Nội dung |
| --- | --- | --- |
| `src/`, `test/` | ESP32 | Firmware PlatformIO và test C++ chạy trên máy tính |
| `src/hw_test/` | ESP32 | Chương trình thử từng linh kiện trên breadboard trước khi hàn |
| `collector/` | Pi4 | Thu một phiên có nhãn ra CSV + JSON, kèm thống kê chất lượng truyền |
| `har/` | Laptop, Pi4 | Trích đặc trưng, huấn luyện, đánh giá, demo trực tiếp và phát lại ([`har/README.md`](har/README.md)) |
| `deploy/` | Pi4 | Script cài demo thành dịch vụ systemd |
| `data/har_own/` | — | **Dữ liệu mẫu**: 25 phiên 120 s (walk/sit/stand/lie) |
| `har_runs/own_rf_01/` | — | **Mô hình mẫu** huấn luyện từ dữ liệu mẫu (`model.joblib`, `metadata.json`) |

Dữ liệu mẫu và mô hình mẫu có sẵn để bạn chạy thử ngay mà không cần thu dữ liệu. Chúng được thu
từ **một người**, với **một cách đeo** (mục 2). Người khác đeo, hoặc đeo khác hướng, thì mô hình
dễ nhận sai; khi đó hãy thu dữ liệu của mình (mục 6) và huấn luyện lại (mục 7). Số liệu đánh giá
của mô hình mẫu nằm ở [`KET_QUA.md`](KET_QUA.md).

**Các bước:**

1. [Chạy thử không cần phần cứng](#1-chạy-thử-không-cần-phần-cứng)
2. [Chuẩn bị phần cứng](#2-chuẩn-bị-phần-cứng)
3. [Nạp firmware cho ESP32](#3-nạp-firmware-cho-esp32)
4. [Cài đặt trên Raspberry Pi 4](#4-cài-đặt-trên-raspberry-pi-4)
5. [Sử dụng hằng ngày](#5-sử-dụng-hằng-ngày)
6. [Thu dữ liệu của bạn](#6-thu-dữ-liệu-của-bạn)
7. [Huấn luyện mô hình của bạn](#7-huấn-luyện-mô-hình-của-bạn)
8. [Nhận diện lên / xuống cầu thang](#8-nhận-diện-lên--xuống-cầu-thang)
9. [Tham khảo: firmware bộ đeo](#9-tham-khảo-firmware-bộ-đeo)
10. [Tham khảo: giao thức](#10-tham-khảo-giao-thức)
11. [Kiểm tra phần mềm](#11-kiểm-tra-phần-mềm)

Ngoài ra: [Xử lý sự cố](#xử-lý-sự-cố).

## 1. Chạy thử không cần phần cứng

Dùng một ESP32 giả phát lại một phiên trong dữ liệu mẫu, rồi xem nhận diện trên trang web. Cần
Python 3.11 trở lên. Ví dụ trên Windows:

```powershell
py -3.13 -m venv .venv-har
& ".\.venv-har\Scripts\python.exe" -m pip install -r requirements-har.txt
& ".\.venv-har\Scripts\python.exe" -m har fake-esp32 --csv data/har_own/test/20261014T042223Z-e1354d0d.csv --port 8765
# mở cửa sổ terminal thứ hai:
& ".\.venv-har\Scripts\python.exe" -m har demo --run-dir har_runs/own_rf_01 --esp 127.0.0.1:8765 --data-dir data/har_own --host 127.0.0.1
```

Mở `http://127.0.0.1:8080`. Trên Linux hay macOS, thay `.\.venv-har\Scripts\python.exe` bằng
`.venv-har/bin/python`. Có thể thay file CSV bằng bất kỳ file `.csv` nào trong `data/har_own/`.

## 2. Chuẩn bị phần cứng

**Bắt buộc:** ESP32 DevKit, MPU6050 (module GY-521), Raspberry Pi 4.

| MPU6050 | ESP32 |
| --- | --- |
| VCC | 3V3 |
| GND | GND |
| SDA | GPIO21 |
| SCL | GPIO22 |
| AD0 | GND (địa chỉ 0x68) |

**Tùy chọn** (chân nối ở [mục 9](#9-tham-khảo-firmware-bộ-đeo)): BMP280, OLED 0,96", nút nhấn,
2 LED, còi, motor rung, mạch đo pin.

**Cách đeo** (giống lúc thu dữ liệu mẫu): hông phải ở thắt lưng, mặt chip MPU6050 hướng ra ngoài,
mũi tên trục Y trên board chỉ xuống đất. Khi đứng yên, `ay` khoảng −1 g, còn `ax` và `az` gần 0.
Nếu bạn đeo khác thì phải thu dữ liệu và huấn luyện lại theo cách đeo đó.

ESP32, Pi4 và máy dùng để xem web phải ở **cùng một mạng Wi-Fi 2.4 GHz** (ESP32 không có 5 GHz).

## 3. Nạp firmware cho ESP32

Cần [PlatformIO](https://platformio.org/) (cài qua tiện ích của VS Code hoặc `pip install platformio`).
Lần build đầu PlatformIO tự tải toolchain và thư viện U8g2 nên cần mạng.

> Đặt thư mục dự án ở **đường dẫn không có dấu tiếng Việt**: toolchain ESP32 lỗi khi đường dẫn
> có dấu. Nếu không đổi được, thêm vào đầu `platformio.ini`:
>
> ```ini
> [platformio]
> build_dir = C:/pio-build/iot-har
> ```

1. Chép `src/wifi_secrets.example.h` thành `src/wifi_secrets.h` (file này không được đưa lên Git)
   và điền tên, mật khẩu Wi-Fi. ESP32 thử mạng `WIFI_HOME` trước, rồi `WIFI_HOTSPOT`, mỗi mạng tối
   đa 10 giây. Nếu dùng hotspot iPhone, bật *Maximize Compatibility*.
2. Cắm ESP32 vào máy tính và nạp. Thay `COM6` bằng cổng thật (Linux: `/dev/ttyUSB0`); nếu lệnh
   `pio` đã có trong PATH thì gõ `pio` thay cho đường dẫn đầy đủ:

   ```powershell
   $pio = "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe"
   & $pio run -e esp32dev_wifi -t upload --upload-port COM6
   & $pio device monitor -b 115200 --port COM6
   ```

3. Để cảm biến **nằm yên trên bàn** khoảng 7 giây. Log đúng có lần lượt:

   ```text
   [READY] MPU6050 at 0x68; configuration verified.
   [CAL] DONE bias=(...) dps
   [WIFI] connected ssid=<tên mạng> ip=192.168.1.50      ← IP của ESP32, ghi lại
   ```

   IP do router cấp nên có thể đổi; xem lại log này, danh sách thiết bị trên router (tên
   `mpu6050-esp32`), hoặc màn hình OLED nếu có gắn. Dòng `[BARO] no BMP280 ...` và
   `[UI] no OLED ...` chỉ báo là chưa gắn hai phần đó.

Các bản build trong `platformio.ini`:

| Môi trường | Dùng khi |
| --- | --- |
| `esp32dev_wifi` | Dùng thật: gửi dữ liệu qua Wi-Fi, TCP cổng 8765 |
| `esp32dev` | Gửi dữ liệu qua USB (cáp nối thẳng vào Pi4) |
| `hw_test` | Thử từng linh kiện trên breadboard: quét I2C, MPU6050, BMP280, OLED, LED, nút, còi, pin. Mở Serial Monitor, gõ `h` để xem lệnh |

## 4. Cài đặt trên Raspberry Pi 4

Cần Python 3.11 trở lên (Raspberry Pi OS Bookworm đã có sẵn).

```bash
sudo apt update
sudo apt install git python3-venv
git clone https://github.com/huuvietnguyen72/iot-har ~/har-baseline
cd ~/har-baseline
python3 -m venv .venv-har
.venv-har/bin/pip install -r requirements-har.txt
```

Tạo file cấu hình từ mẫu, sửa `esp = ...` thành IP của ESP32, rồi thêm token truy cập:

```bash
cp har/har_demo.example.toml har_demo.toml
nano har_demo.toml                                   # sửa dòng esp = "..."
echo "token = \"$(.venv-har/bin/python -m har new-token)\"" >> har_demo.toml
chmod 600 har_demo.toml
```

`har_demo.toml` chứa token nên không được đưa lên Git (đã có trong `.gitignore`). Trang web bắt
buộc có token khi mở cho cả mạng (`host = "0.0.0.0"`); chỉ khi `host = "127.0.0.1"` mới được bỏ.

**Tùy chọn — chạy demo như dịch vụ tự khởi động cùng Pi4.** Script `deploy/install_pi.sh` chép mã,
mô hình và dữ liệu vào `/opt/har`, tạo `/etc/har/har_demo.toml` kèm token, rồi cài dịch vụ systemd
`har-demo`:

```bash
bash deploy/install_pi.sh
sudo nano /etc/har/har_demo.toml          # sửa esp = "..." rồi:
sudo systemctl restart har-demo
journalctl -u har-demo -f                 # xem log
```

Script chép mô hình mẫu `har_runs/own_rf_01` và dữ liệu mẫu; dùng mô hình của bạn thì sửa `run_dir`
trong `/etc/har/har_demo.toml` và chép thư mục mô hình vào `/opt/har/har_runs/`. Script và dịch vụ
**chưa được chạy thử trên Pi4 thật**; nếu gặp lỗi, dùng cách chạy tay ở mục 5.

## 5. Sử dụng hằng ngày

1. **Hiệu chỉnh:** đặt bộ đeo nằm yên trên bàn, bật nguồn ESP32 (hoặc bấm nút EN) và giữ yên
   khoảng 7 giây. Nếu bị cầm hay đeo lúc này, hiệu chỉnh bị từ chối và tự thử lại sau 3 giây.
2. **Đeo** đúng cách ở mục 2.
3. Trên Pi4 (qua SSH), chọn **một** trong hai cách dưới đây. IP ESP32 lấy từ `har_demo.toml`;
   muốn đổi tạm thì thêm `--esp <IP>:8765` vào lệnh.

**Cách A — xem trên trang web**

```bash
cd ~/har-baseline
.venv-har/bin/python -m har demo --config har_demo.toml
```

Mở `http://<IP-Pi4>:8080/?token=<token>` trên điện thoại hoặc laptop (token nằm trong
`har_demo.toml`). Trình duyệt nhớ token, các lần sau chỉ cần `http://<IP-Pi4>:8080`. Trang mở sẵn
chế độ **Trực tiếp**: hoạt động hiện tại, độ tin cậy và tốc độ nhận mẫu. Nút **Phát lại** chạy lại
các phiên trong `data_dir` (và ngắt kết nối ESP32); bấm **Trực tiếp** để quay lại. Dừng bằng Ctrl+C.

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
```

Cột phần trăm là xác suất trung bình 3 cửa sổ gần nhất; dưới 60% có thêm `(không chắc)`.

Ở cả hai cách, Pi4 gửi hoạt động về ESP32 mỗi giây để hiện trên OLED (nếu có). Cả hai lệnh cũng
chạy được trên laptop cùng mạng với ESP32. Không dùng file cấu hình thì truyền thẳng tham số, ví dụ
`python -m har live --run-dir har_runs/own_rf_01 --esp 192.168.1.50:8765`.

## 6. Thu dữ liệu của bạn

Mỗi **phiên** là một lần ghi một hoạt động, cho ra hai file `<session_id>.csv` và
`<session_id>.json`. Dữ liệu tự thu nên để trong thư mục riêng, ví dụ `data/my/`. Thư mục `data/`
đã nằm trong `.gitignore` (trừ dữ liệu mẫu), nên dữ liệu của bạn không bị đưa lên Git.

**Kế hoạch thu** (giống dữ liệu mẫu):

- **Buổi train:** 4 phiên × 120 s cho mỗi hoạt động, vào `data/my/train/`.
- **Buổi test:** thu vào **một ngày khác**, 2 phiên × 120 s cho mỗi hoạt động, vào `data/my/test/`.
- Nhãn đúng một trong `walk`, `sit`, `stand`, `lie`; thêm `stairs_up`, `stairs_down` nếu muốn
  mô hình nhận ra cầu thang (xem đoạn "Thu dữ liệu cầu thang" bên dưới).
- Trong một buổi, thu xen kẽ walk → sit → stand → lie, không thu một hoạt động nhiều lần liền nhau.
- Hiệu chỉnh ESP32 trên bàn trước (chờ `[CAL] DONE`) rồi mới đeo. Luôn đeo cùng vị trí và hướng.
- Nếu firmware có phát hiện nghi té, nên build với `-D FALL_DETECT=0` khi thu dữ liệu để còi không
  kêu giữa phiên (xem mục 9).

**Thu qua Wi-Fi** (ESP32 nạp `esp32dev_wifi`), trên Pi4 hoặc laptop cùng mạng. Vào tư thế rồi chạy:

```bash
cd ~/har-baseline
python3 -m collector --tcp <IP-ESP32>:8765 --duration 120 --label walk --output data/my/train
```

Tìm ESP32 tự động thay cho IP: `--discover` (cần `sudo apt install python3-zeroconf`).

**Thu qua USB** (ESP32 nạp `esp32dev`, cắm vào Pi4; cần `sudo apt install python3-serial`):

```bash
python3 -m collector --port /dev/ttyUSB0 --duration 120 --label walk --output data/my/train
```

Nếu báo `Permission denied`, chạy `sudo usermod -aG dialout "$USER"` rồi đăng nhập SSH lại. Xem
danh sách cổng bằng `python3 -m serial.tools.list_ports -v`.

Tham số:

- `--duration`: số giây ghi, tính từ mẫu hợp lệ đầu tiên (không tính thời gian hiệu chỉnh).
- `--label`: nhãn phiên, chỉ gồm `[A-Za-z0-9_-]`.
- `--output`: thư mục đích (mặc định `data`).
- Ctrl+C dừng sớm; phần đã ghi được giữ lại với trạng thái `interrupted`.

**Kiểm tra một phiên.** File JSON có trạng thái kết thúc và thống kê chất lượng. Phiên tốt có
`status = completed`, tốc độ 49–51 Hz, 0 mẫu thiếu, trùng hay đảo thứ tự, và 0 khoảng trống
> 40 ms. Các trạng thái khác: `interrupted`, `no_data`, `wait_timeout`, `stream_changed` (ESP32
reset giữa chừng, hãy thu lại phiên), `serial_error`, `connection_lost`, hoặc `recording` nếu tiến
trình bị tắt đột ngột.

Mã thoát của `collector`: 0 hoàn tất; 130 dừng bằng Ctrl+C; 3 không nhận được dữ liệu; 4 stream
đổi giữa chừng; 5 lỗi cổng serial hoặc mất kết nối TCP; 6 lỗi đọc ghi file; 2 sai tham số.

Cột của CSV: `session_id,label,stream_id,seq,device_time_us,host_elapsed_s,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c`.

**Áp suất.** Nếu bộ đeo có BMP280, `collector` tự ghi thêm file `<session_id>.baro.csv` (cột
`session_id,stream_id,seq,device_time_us,pressure_pa,temp_c`, khoảng 10 dòng mỗi giây) và ghi tên
file vào trường `baro_file` của JSON. Không có BMP280 thì không có file này.

**Thu dữ liệu cầu thang.** Cần BMP280 và cần file áp suất ở **mọi** phiên, kể cả phiên
walk/sit/stand/lie, vì mô hình cầu thang dùng áp suất cho mọi cửa sổ. Dữ liệu mẫu `data/har_own`
thu trước khi có BMP280 nên không dùng chung được; hãy thu lại cả 6 hoạt động.

- Nhãn `stairs_up` (đi lên) và `stairs_down` (đi xuống), mỗi nhãn ít nhất 4 phiên ở buổi train và
  1 phiên ở buổi test, giống các hoạt động khác.
- Một lần đi cầu thang thường ngắn hơn 120 s, nên dùng `--duration 40` hoặc dài hơn nếu tòa nhà
  có nhiều tầng. 5 giây đầu và 5 giây cuối mỗi phiên bị bỏ khi huấn luyện, nên hãy bắt đầu bước
  ngay khi lệnh chạy và đi liên tục đến hết thời gian.
- Không thu trong thang máy và không dừng lại ở chiếu nghỉ giữa phiên.

```bash
python3 -m collector --tcp <IP-ESP32>:8765 --duration 40 --label stairs_up --output data/my/train
```

## 7. Huấn luyện mô hình của bạn

Huấn luyện trên laptop (nhanh hơn Pi4), rồi chép thư mục mô hình sang Pi4. Mỗi lần huấn luyện cần
một thư mục mô hình **mới** (lệnh không ghi đè thư mục đã có):

```powershell
& ".\.venv-har\Scripts\python.exe" -m har train-own --train-dir data/my/train `
    --test-dir data/my/test --run-dir har_runs/my_rf_01
```

Lệnh in ra các phiên bị loại kèm lý do (trạng thái khác `completed`, thang đo khác ±4 g/±500 °/s,
nhãn lạ, lỗi truyền, quá ngắn, thiếu file áp suất đã khai báo), chọn cấu hình bằng
cross-validation trên buổi train, rồi chấm trên buổi test.

Nếu buổi train có phiên `stairs_up` hoặc `stairs_down`, mô hình học 6 hoạt động và dùng thêm đặc
trưng **độ dốc áp suất** (Pa/giây trong mỗi cửa sổ 2,56 s). Khi đó mọi phiên phải có file
`.baro.csv`, nếu không lệnh báo lỗi và liệt kê các phiên thiếu. Mô hình có cầu thang cũng cần
BMP280 khi chạy `demo` và `live`; nếu ESP32 không gửi dòng `BARO`, trang web báo "Mô hình cần dữ
liệu áp suất…" và không đưa ra kết luận.

Kết quả nằm trong `har_runs/my_rf_01/`:

- `model.joblib`, `metadata.json`: mô hình, dùng cho `demo` và `live`.
- `report.md`: macro-F1, ma trận nhầm lẫn, độ chính xác theo từng phiên. Đọc file này để quyết định
  mô hình đã dùng được chưa.

Dùng mô hình mới: sửa `run_dir = "har_runs/my_rf_01"` (và `data_dir = "data/my"` nếu muốn phát
lại dữ liệu của bạn) trong `har_demo.toml`. Thư mục `har_runs/` cũng nằm trong `.gitignore`, trừ
mô hình mẫu.

Đo tốc độ suy luận trên Pi4 (mỗi kết luận phải xong trong 1,28 s):

```bash
.venv-har/bin/python -m har benchmark --run-dir har_runs/my_rf_01 --csv data/my/test/<phiên>.csv --output /tmp/benchmark.json
```

Chi tiết về đặc trưng, cách chia dữ liệu, cách chọn cấu hình và mô hình đối chiếu trên dữ liệu
công khai UCI HAR: [`har/README.md`](har/README.md).

## 8. Nhận diện lên / xuống cầu thang

Ngoài đi bộ, ngồi, đứng, nằm, hệ thống nhận ra được **lên cầu thang** (`stairs_up`) và **xuống
cầu thang** (`stairs_down`) khi bộ đeo có cảm biến áp suất **BMP280**.

### Vì sao cần BMP280

MPU6050 không đo được độ cao, nên đi trên mặt phẳng và đi cầu thang cho tín hiệu chuyển động gần
giống nhau. Áp suất không khí giảm khoảng **12 Pa cho mỗi mét lên cao** (một tầng nhà khoảng 3 m,
tức chừng 36 Pa), còn nhiễu của BMP280 với bộ lọc đang dùng chỉ cỡ 1–2 Pa:

| Tình huống | Áp suất trong vài giây |
| --- | --- |
| Đi trên mặt phẳng | Gần như không đổi |
| Lên cầu thang | Giảm đều, khoảng 2–4 Pa/s |
| Xuống cầu thang | Tăng đều, khoảng 2–4 Pa/s |
| Đứng trong thang máy | Đổi nhanh nhưng không có bước chân, nên không tính là cầu thang |

Áp suất tuyệt đối thay đổi theo thời tiết và theo tầng nhà, nên chỉ dùng **độ dốc** (mức thay đổi
theo thời gian), không dùng giá trị tuyệt đối. Nhiệt độ của BMP280 và độ ẩm của AHT20 (nếu module
có) không dùng để nhận diện.

### Hai cách nhận diện

| | Cách 1: trên ESP32 | Cách 2: mô hình trên Pi4 |
| --- | --- | --- |
| Cần huấn luyện | Không, chạy ngay khi gắn BMP280 | Có: thu dữ liệu cầu thang rồi huấn luyện lại |
| Kết quả hiện ở | OLED (`LEN THANG` / `XUONG THANG`) và sự kiện `EVT,...,stairs` | Trang web và terminal (`Lên cầu thang` / `Xuống cầu thang`), OLED |
| Độ chính xác | Chưa đo; ngưỡng ước tính từ vật lý | Đo được, ghi trong `report.md` của mô hình |
| Tắt bằng | `-D STAIRS_DETECT=0` khi build | Dùng mô hình không có lớp cầu thang |

Hai cách chạy song song. Khi ESP32 đang báo cầu thang, màn hình hiện kết quả của ESP32, đè lên
kết quả Pi4 gửi về.

### Cách 1: trên ESP32 (dùng ngay)

1. Nối BMP280 chung bus với MPU6050: VCC → 3V3, GND → GND, SDA → GPIO21, SCL → GPIO22. Thêm tụ
   100 nF giữa VCC và GND sát BMP280.
2. Nạp `hw_test` để kiểm tra (mục 3): phải có dòng `[CHECK] BMP280 PASS`. Đặt yên rồi nâng bộ đeo
   lên khoảng 1 m: giá trị `p=` phải giảm khoảng 12 Pa.
3. Nạp lại `esp32dev_wifi`. Log có dòng `[BARO] BMP280 at 0x76; BARO records at 10 Hz.`
4. Đeo và đi cầu thang. Sau khoảng 5–8 giây đi liên tục, log hiện `[STAIRS] up` (hoặc `down`),
   OLED hiện `LEN THANG` (hoặc `XUONG THANG`). Đi tiếp trên mặt phẳng khoảng 2 giây thì log hiện
   `[STAIRS] ended`.

Cách hoạt động (`src/stairs_detector.h`): báo "lên" hoặc "xuống" khi trong 2 giây liền cả ba điều
sau cùng đúng:

- Người đeo đang bước đi: độ lệch chuẩn của độ lớn gia tốc trong 2 s từ 0,06 g trở lên.
- Độ dốc áp suất trong 5 s gần nhất có độ lớn 1,2–10 Pa/s (khoảng 0,1–0,8 m/s theo chiều đứng).
- Hai nửa của 5 s đó thay đổi cùng chiều, để bỏ qua một cú nhảy áp suất do đóng cửa hay bật quạt.

Các ngưỡng được ước tính từ vật lý, **chưa chỉnh trên dữ liệu cầu thang thật**; hãy thử trên cầu
thang thật trước khi tin vào kết quả.

### Cách 2: mô hình trên Pi4

1. Thu dữ liệu cho **cả 6 hoạt động** bằng bộ đeo có BMP280 (mục 6, đoạn "Thu dữ liệu cầu
   thang"). `collector` tự ghi áp suất vào file `<phiên>.baro.csv`.
2. Huấn luyện bằng `har train-own` (mục 7). Có phiên cầu thang trong dữ liệu thì mô hình tự học 6
   hoạt động và dùng thêm đặc trưng độ dốc áp suất.
3. Sửa `run_dir` trong `har_demo.toml` sang mô hình mới rồi chạy `har demo` hoặc `har live` như ở
   mục 5.

Dữ liệu mẫu `data/har_own` thu trước khi có BMP280, nên **mô hình mẫu `own_rf_01` chưa có lớp cầu
thang** và không dùng chung dữ liệu với mô hình cầu thang được.

## 9. Tham khảo: firmware bộ đeo

Cả hai bản firmware (`esp32dev` và `esp32dev_wifi`) điều khiển các phần dưới đây. Phần nào không
gắn thì firmware tự bỏ qua.

| Phần | Chân | Hoạt động |
| --- | --- | --- |
| MPU6050, BMP280 | SDA 21, SCL 22 | BMP280 (0x76/0x77) được đọc sau mỗi mẫu `DATA` thứ 5, tức 10 lần/giây, để nhận ra cầu thang |
| OLED 0,96" 128×64 | SDA 19, SCL 18 | Bus I2C riêng để việc vẽ không làm trễ mẫu 50 Hz. Địa chỉ 0x3C hoặc 0x3D |
| LED xanh, LED đỏ | 26, 27 | Xem bảng đèn bên dưới |
| Nút nhấn | 32 → GND | Nhấn: bật màn hình 10 giây, hủy cảnh báo. Giữ 2 giây: gửi SOS |
| Còi, motor rung | 25, 33 | Qua transistor S8050. Kêu khi có cảnh báo, bíp ngắn khi nhấn nút |
| Đo pin | 34 | Cầu chia 100 kΩ + 100 kΩ. Ngoài khoảng 2,5–4,5 V thì coi như không có pin |

| Đèn | Nghĩa |
| --- | --- |
| Xanh nháy nhanh | Đang hiệu chỉnh gyro, giữ yên thiết bị |
| Xanh nháy chậm | Có Wi-Fi, Pi4 chưa kết nối |
| Xanh chớp ngắn mỗi 2 giây | Đang gửi dữ liệu |
| Đỏ sáng liên tục | Lỗi cảm biến MPU6050 |
| Đỏ nháy chậm | Mất Wi-Fi |
| Đỏ chớp đôi mỗi 3 giây | Pin yếu (từ 15% trở xuống) |
| Đỏ nháy nhanh, còi kêu | Cảnh báo té. Còi tự im sau 60 giây, đèn nháy đến khi hủy |

Màn hình tắt khi không dùng và bật lại khi nhấn nút, khi có cảnh báo, hoặc khi cảm biến chưa sẵn
sàng. Dòng chữ lớn là hoạt động Pi4 gửi về (hoặc trạng thái thiết bị); ba dòng nhỏ là pin, Wi-Fi và
kết nối với Pi4. Chữ là tiếng Việt không dấu. Phần trăm pin chỉ là ước lượng từ điện áp.

**Tùy chọn khi build**, thêm vào `build_flags` trong `platformio.ini`:

- `-D OLED_SH1106=1`: màn hình dùng chip SH1106 thay vì SSD1306. Thử cờ này nếu hình bị lệch 2
  điểm ảnh hoặc có sọc nhiễu ở mép.
- `-D BUZZER_PASSIVE=1`: còi thụ động, cần xung 2,7 kHz. Dùng khi trong `hw_test` chỉ phím `t`
  làm còi kêu.
- `-D FALL_DETECT=0`: tắt phát hiện nghi té.
- `-D STAIRS_DETECT=0`: tắt nhận diện cầu thang trên thiết bị.

Nhận diện cầu thang trên thiết bị: xem [mục 8](#8-nhận-diện-lên--xuống-cầu-thang).

**Phát hiện nghi té** (`src/fall_detector.h`). ESP32 tự bật cảnh báo, không cần Pi4, khi thấy đủ
ba điều theo thứ tự:

1. Va đập: độ lớn gia tốc đạt 2,5 g trở lên.
2. Chờ 1 giây cho hết nảy, lăn.
3. Trong 2 giây tiếp theo, mọi mẫu gần 1 g (nằm yên) và trục Y lệch khỏi phương thẳng đứng hơn
   khoảng 60° (|ay| ≤ 0,5 g).

Khi đó thiết bị gửi `EVT,1,...,fall_suspect,<seq>` rồi bật còi và đèn đỏ; người đeo nhấn nút để
hủy. Ngồi phịch xuống hay nhảy có va đập nhưng sau đó vẫn thẳng người nên bị bỏ qua; nằm xuống nhẹ
thì không có va đập. Thả người xuống giường vẫn có thể báo nhầm. Các ngưỡng là giá trị khởi đầu,
**chưa được chỉnh trên dữ liệu té thật** và dựa trên cách đeo ở mục 2; hãy coi mỗi lần báo là
"nghi té".

## 10. Tham khảo: giao thức

ESP32 gửi mỗi bản ghi một dòng văn bản: qua USB 115200 baud (`esp32dev`), hoặc qua TCP cổng 8765,
mỗi lúc một client (`esp32dev_wifi`).

```text
DATA,1,<stream_id>,<seq>,<device_time_us>,<ax_g>,<ay_g>,<az_g>,<gx_dps>,<gy_dps>,<gz_dps>,<temp_c>
[NET],1,<stream_id>,<queue_dropped_total>,<unobserved_total>
BARO,1,<stream_id>,<seq>,<device_time_us>,<pressure_pa>,<temp_c>
EVT,1,<stream_id>,<device_time_us>,<name>,<value>
STAT,1,<stream_id>,<device_time_us>,<vbat_mv>,<percent>,<rssi_dbm>,<flags>
```

- `DATA`: một mẫu 50 Hz. `stream_id` gồm 16 ký tự hex, đổi mỗi lần hiệu chỉnh xong; `seq` bắt đầu
  lại từ 0. `device_time_us` là đồng hồ micro giây của ESP32. Gyro đã trừ bias; gia tốc còn trọng
  lực. Ví dụ: `DATA,1,7a31b25c809fd416,12,8340000,-0.921,0.051,0.132,0.120,-0.080,0.050,29.40`.
- `[NET]`: mỗi giây (chỉ bản Wi-Fi), đếm số mẫu bị bỏ khi mạng chậm. ESP32 vẫn giữ nhịp 50 Hz.
- `BARO`: áp suất, `seq` là số thứ tự của mẫu `DATA` vừa đọc trước đó.
- `EVT`: `button` (nhấn nút, `value` là số lần), `sos` (giữ nút 2 giây), `fall_suspect` (`value`
  là `seq` lúc đó), `stairs` (`value` 1 lên, −1 xuống, 0 kết thúc), `alert_on`, `alert_cancel`.
- `STAT`: mỗi 10 giây. `vbat_mv = 0` và `percent = -1` nghĩa là không đo được pin. `flags` là tổng
  của: 1 = BMP280 hoạt động, 2 = có OLED, 4 = đang cảnh báo, 8 = pin yếu.
- `stream_id` để trống cho đến khi hiệu chỉnh gyro xong.
- Dòng bắt đầu bằng `[SCAN]`, `[CAL]`, `[ID]`, `[READY]`, `[WIFI]`, `[BARO]`, `[UI]`, `[FALL]`,
  `[STAIRS]`, `[ERROR]`… là thông báo, không phải dữ liệu.

`collector` đọc `DATA`, `[NET]` và `BARO` (ghi vào `.baro.csv`). `har` đọc `DATA`, `[NET]`, và
`BARO` khi mô hình có đặc trưng áp suất. Các dòng khác bị bỏ qua. Áp suất đi bằng dòng `BARO`
riêng để dòng `DATA,1` giữ nguyên 12 trường, nên dữ liệu và mô hình cũ vẫn dùng được.

Lệnh gửi về ESP32, mỗi lệnh một dòng (qua TCP, hoặc gõ vào Serial Monitor để thử):

```text
CMD,1,ACT,<label>     hoạt động vừa nhận diện: walk, sit, stand, lie, stairs_up, stairs_down…
CMD,1,ALERT,<0|1>     bật / tắt cảnh báo té
```

Nhãn gồm chữ thường, số và dấu gạch dưới, tối đa 15 ký tự. `har demo` và `har live` (chế độ trực
tiếp) gửi `ACT` mỗi giây khi có kết quả mới; quá 5 giây không có `ACT` thì màn hình hiện `--`. Hiện chưa có chương trình nào gửi `ALERT` (cảnh báo do chính ESP32
bật); gõ tay vào Serial Monitor để thử còi và đèn.

## 11. Kiểm tra phần mềm

Chạy từ thư mục gốc của repo.

Build cả ba bản firmware (bản Wi-Fi vẫn build được khi chưa có `src/wifi_secrets.h`, chỉ không vào
được mạng):

```powershell
$pio = "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe"
& $pio run -e esp32dev -e esp32dev_wifi -e hw_test
```

Test C++ chạy trên máy tính (cần `g++`):

```bash
for t in calibration data_stream net_protocol bmp280 button battery indicator \
         wearable_protocol display_view fall_detector stairs_detector; do
  g++ -std=c++11 -Wall -Wextra -Werror test/${t}_test.cpp -o ${t}_test && ./${t}_test
done
```

Test Python (`collector` không cần pyserial; `har` cần các gói trong `requirements-har.txt`):

```text
python -m unittest discover -s collector/tests -t . -v
python -m unittest discover -s har/tests -t . -v
```

## Xử lý sự cố

| Thông báo | Nguyên nhân và cách xử lý |
| --- | --- |
| `Đang tìm ESP32 (…)… lần thử N` | Sai IP, ESP32 chưa vào mạng hoặc khác mạng với Pi4. Xem lại IP trong log Serial. |
| `ESP32 đang hiệu chỉnh — để yên trên bàn` | ESP32 vừa bật hoặc reset. Đặt yên trên bàn đến khi hết thông báo rồi đeo lại. |
| `ESP32 đang bận …` | ESP32 chỉ nhận một kết nối. Tắt `collector`, `demo` hoặc `live` khác đang chạy; ngay sau khi rớt Wi-Fi có thể phải chờ vài giây. |
| `Mất kết nối — đang thử lại` | 5 giây không nhận dữ liệu (mất Wi-Fi, hết pin). Chương trình tự kết nối lại. |
| `ESP32 vừa khởi động lại` | ESP32 reset và đã hiệu chỉnh lại; nếu nó reset khi đang đeo, xem bước hiệu chỉnh ở mục 5. |
| `đặt token trong har_demo.toml …` | `har demo` từ chối mở cho cả mạng khi chưa có token. Thêm token như ở mục 4, hoặc đặt `host = "127.0.0.1"` nếu chỉ xem trên chính máy đó. |
| Trang báo `token required` (401) | Mở lại bằng `http://<IP-Pi4>:8080/?token=<token>`. |
| Build lỗi khi tạo file tạm | Đường dẫn dự án có dấu tiếng Việt; xem ghi chú đầu mục 3. |
| `collector` báo `Permission denied` | Chạy `sudo usermod -aG dialout "$USER"` rồi đăng nhập lại. |
| Nhận diện sai nhiều | Kiểm tra cách đeo (mục 2). Nếu người đeo hoặc cách đeo khác dữ liệu mẫu, thu dữ liệu và huấn luyện lại (mục 6–7). |
| `Mô hình cần dữ liệu áp suất…` | Mô hình có lớp cầu thang nhưng ESP32 không gửi dòng `BARO`. Kiểm tra BMP280 bằng `hw_test`, hoặc dùng mô hình không có cầu thang. |
| `stairs sessions need barometer data in every session` | Khi huấn luyện cầu thang, mọi phiên phải có `.baro.csv`. Thu lại các phiên được liệt kê với bộ đeo có BMP280. |

## Giấy phép

Mã nguồn phát hành theo giấy phép MIT — xem [`LICENSE`](LICENSE). Dữ liệu UCI HAR (chỉ dùng để
đối chiếu, xem `har/README.md`) theo giấy phép CC BY 4.0, không kèm trong repo, tải bằng
`har prepare`.
