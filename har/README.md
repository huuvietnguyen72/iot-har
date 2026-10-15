# har — Baseline HAR bốn hoạt động (bước 3A)

Package này dựng pipeline nhận diện bốn hoạt động `walk`, `sit`, `stand`, `lie`
bằng dữ liệu công khai **UCI HAR**, huấn luyện trên laptop và thử suy luận trên Pi4.

## Dữ liệu và ghi công

- UCI Human Activity Recognition Using Smartphones, DOI 10.24432/C54S4K.
- Nguồn: https://archive.ics.uci.edu/dataset/240/human+activity+recognition+using+smartphones
- Giấy phép CC BY 4.0. Trích dẫn: Reyes-Ortiz et al. (2013).
- 30 người, Samsung Galaxy S II gắn ở eo, gia tốc + gyro 50 Hz. **Không** khẳng định
  smartphone này dùng MPU6050.
- Chỉ dùng bốn lớp UCI: 1 -> `walk`, 4 -> `sit`, 5 -> `stand`, 6 -> `lie`.
  Lớp cầu thang (2/3) bị loại và được đếm trong báo cáo.

## Quy ước dữ liệu

- Một cửa sổ: shape `(128, 6)` = 2.56 giây ở 50 Hz, thứ tự `ax, ay, az, gx, gy, gz`.
- Gia tốc đơn vị **g** (giữ trọng lực); gyro đơn vị **rad/s** để khớp UCI.
- CSV collector ghi gyro bằng **°/s**, adapter đổi sang rad/s bằng `dps * pi / 180`.
- Không trừ trung bình gia tốc theo từng cửa sổ (giữ tín hiệu trọng lực cho sit/stand/lie).

## Đặc trưng và mô hình

- Bảy mươi đặc trưng: tám kênh (`ax..gz`, độ lớn gia tốc, độ lớn gyro) × tám thống kê
  (mean, std, min, max, median, rms, mean_abs, iqr), cộng sáu tương quan trục.
- Mô hình chính: **Random Forest**, chọn cấu hình bằng **GroupKFold 5 fold theo người**
  trên tập train (lưới khai báo trước: `n_estimators=300`, `max_features∈{sqrt,0.3}`,
  `min_samples_leaf∈{1,2,4}`, `max_depth∈{None,16}`, `class_weight∈{None,balanced_subsample}`).
- Chấm bằng **macro-F1**; test chính thức của UCI giữ riêng cho đánh giá cuối.
  `DummyClassifier(most_frequent)` làm mốc (không bao giờ được chọn). Cấu hình chọn
  phải tốt hơn Dummy trên test.

## Lệnh

```powershell
py -3.13 -m venv .venv-har
& ".\.venv-har\Scripts\python.exe" -m pip install -r requirements-har.txt
& ".\.venv-har\Scripts\python.exe" -m pip check
& ".\.venv-har\Scripts\python.exe" -m unittest discover -s har/tests -t . -v
& ".\.venv-har\Scripts\python.exe" -m har prepare --data-dir har_data
& ".\.venv-har\Scripts\python.exe" -m har train --data-dir har_data --run-dir har_runs/uci_baseline_01
& ".\.venv-har\Scripts\python.exe" -m har predict-csv --run-dir har_runs/uci_baseline_01 --csv data/<session>.csv --output har_runs/uci_baseline_01/replay.json
& ".\.venv-har\Scripts\python.exe" -m har benchmark --run-dir har_runs/uci_baseline_01 --csv data/<session>.csv --output har_runs/uci_baseline_01/benchmark-laptop.json
```

Trên Pi4 (Python 3.11, aarch64), dùng cùng `requirements-har.txt` để lưu/nạp model
tương thích, rồi chạy `unittest` và `benchmark`.

## Dữ liệu riêng — bước 3B (`train-own`)

Dữ liệu đã thu có sẵn trong repo: `data/har_own/train/` (buổi 2026-10-13) và
`data/har_own/test/` (buổi 2026-10-14). Muốn thu lại:

- Buổi train 4 phiên × 120 s mỗi hoạt động vào `data/har_own/train/`; buổi test **khác ngày**
  2 phiên mỗi hoạt động vào `data/har_own/test/`; nhãn `walk|sit|stand|lie`.
- Trong một buổi thu xen kẽ walk → sit → stand → lie, không thu cùng hoạt động liên tiếp.
- Bật ESP32 khi cảm biến nằm yên trên bàn, chờ `[CAL] DONE` rồi mới đeo.
- Luôn đeo cùng vị trí và hướng: hông phải ở thắt lưng, mặt chip hướng ra ngoài, cổng USB chúc xuống.
- Mỗi phiên: vào tư thế rồi chạy
  `python3 -m collector --tcp <ESP_IP>:8765 --duration 120 --label walk --output data/har_own/train`;
  tháo cảm biến sau mỗi phiên.

Huấn luyện lại (`--compare-run` là tùy chọn, chấm thêm một mô hình có sẵn trên cùng buổi test):

```powershell
& ".\.venv-har\Scripts\python.exe" -m har train-own --train-dir data/har_own/train `
    --test-dir data/har_own/test --run-dir har_runs/own_rf_01 `
    --compare-run har_runs/uci_rf_tuned_01
```

- Phiên bị loại (status khác `completed`, thang đo khác 4 g/500 dps, nhãn lạ, có lỗi
  truyền, thiếu CSV, quá ngắn) được in kèm lý do và ghi vào `sessions.json`.
- Mỗi phiên bỏ 5 s đầu và 5 s cuối. CV dùng 4 fold: fold k giữ ra phiên thứ k của mỗi hoạt động.
- Điểm báo cáo là buổi test; CV chỉ để chọn cấu hình.

## Demo trực tiếp / phát lại (`demo`, `live`)

Không cần cài thêm gói
(web server dùng thư viện chuẩn). Trên Pi4 chạy từ `~/har-baseline` (cần cả `har/` và `collector/`).
Tham số thêm: `demo --host/--port` (mặc định `0.0.0.0:8080`), `fake-esp32 --speed` (mặc định 1.0).

```bash
# Trang web (mở http://<IP-Pi4>:8080 trên laptop/điện thoại)
python -m har demo --run-dir har_runs/own_rf_01 --esp 192.168.1.2:8765 --data-dir data/har_own
# Dòng lệnh (chỉ trực tiếp; Ctrl+C để dừng)
python -m har live --run-dir har_runs/own_rf_01 --esp 192.168.1.2:8765
# Thử trên laptop không cần phần cứng: ESP32 giả rồi trỏ demo vào nó
python -m har fake-esp32 --csv data/har_own/test/<phiên>.csv --port 8765
python -m har demo --run-dir har_runs/own_rf_01 --esp 127.0.0.1:8765 --data-dir data/har_own --host 127.0.0.1
```

- Cửa sổ cắt giống `collector_csv` (128/64, gyro → rad/s, cắt khi mất mẫu hoặc trống > 40 ms);
  trạng thái hiển thị là trung bình xác suất 3 cửa sổ; dưới 60% ghi "không chắc".
- `--esp` nên là địa chỉ IP (tên máy có thể làm việc dừng/đổi chế độ chậm hơn).
- ESP32 chỉ nhận một kết nối: tắt collector trước khi chạy demo trực tiếp (nếu không, trang báo
  "ESP32 đang bận"). Chuyển sang *Phát lại* sẽ ngắt kết nối ESP32. 5 s không nhận được dòng nào
  được coi là mất kết nối; demo tự kết nối lại (ngay sau khi rớt Wi-Fi có thể thấy "đang bận" vài
  giây vì ESP32 chưa bỏ kết nối cũ). Khi trang báo "Lỗi: …", bấm *Trực tiếp* để chạy lại.
- `fake-esp32` đổi stream id mỗi vòng lặp CSV nên trang sẽ báo "ESP32 vừa khởi động lại" mỗi vòng.
- `har live` trả mã 1 nếu nguồn ESP32 dừng vì lỗi, 0 khi Ctrl+C, 130 nếu Ctrl+C lúc đang khởi động.
- Không có đăng nhập: mọi máy trong mạng xem và đổi chế độ được; dùng `--host 127.0.0.1` để giới hạn.

## Artifact

- `har_runs/<run-id>/`: `model.joblib`, `metadata.json` (schema, 70 feature names, đơn vị,
  versions, seed, hash model, split), `selection.json`, `report.json`, `report.md`, `status.json`.
- `metadata.json` khóa theo phiên bản thư viện; nạp sai schema/version/hash sẽ báo lỗi.

## Giới hạn

- Đây là baseline trên **dữ liệu smartphone công khai**, chưa phải độ chính xác trên
  MPU6050 đeo ở eo. Không lấy điểm UCI để suy ra điểm phần cứng.
- `predict-csv` chỉ replay đường suy luận và **không** xác nhận hoạt động người:
  dữ liệu `test` trên bàn không có nhãn hoạt động.
- Khi có nguồn di động (AC-04/05), thu `walk/sit/stand/lie` với nhãn và subject/session
  rõ ràng rồi huấn luyện/kiểm định lại bằng pipeline này; kiểm tra clipping từng trục,
  hướng gắn, bias gia tốc và bộ lọc chống aliasing trước khi kết luận.
