# har — nhận diện walk / sit / stand / lie

Package Python cắt dữ liệu thành cửa sổ, trích đặc trưng, huấn luyện và đánh giá Random Forest,
và chạy demo trực tiếp hoặc phát lại. Huấn luyện trên laptop; suy luận trên Pi4 hoặc laptop.
Hướng dẫn từng bước cho người mới nằm ở [README chính](../README.md); file này là phần tham khảo.

| Lệnh | Dùng để |
| --- | --- |
| `train-own` | Huấn luyện trên dữ liệu MPU6050 tự thu (mô hình dùng cho demo); có thể thêm lớp cầu thang |
| `demo` | Trang web: trực tiếp từ ESP32 hoặc phát lại phiên đã thu |
| `live` | In kết quả trực tiếp ra terminal |
| `fake-esp32` | Giả lập ESP32 bằng một file CSV đã thu, để thử không cần phần cứng |
| `new-token` | Tạo token truy cập cho trang web |
| `predict-csv`, `benchmark` | Chạy lại suy luận trên một CSV; đo tốc độ suy luận |
| `prepare`, `train` | Tải và huấn luyện trên dữ liệu công khai UCI HAR (chỉ để đối chiếu) |

Xem tham số của từng lệnh: `python -m har <lệnh> --help`.

## Cài đặt

Cần Python 3.11 trở lên (file cấu hình đọc bằng `tomllib`).

```powershell
py -3.13 -m venv .venv-har
& ".\.venv-har\Scripts\python.exe" -m pip install -r requirements-har.txt
& ".\.venv-har\Scripts\python.exe" -m unittest discover -s har/tests -t . -v
```

Dùng cùng `requirements-har.txt` trên laptop và Pi4: `metadata.json` của mô hình ghi lại phiên bản
thư viện, và mô hình chỉ nạp được khi phiên bản khớp.

## Quy ước dữ liệu

- Một cửa sổ: shape `(128, 6)` = 2,56 giây ở 50 Hz, thứ tự `ax, ay, az, gx, gy, gz`; hai cửa sổ
  liên tiếp cách nhau 64 mẫu.
- Gia tốc đơn vị **g** (giữ trọng lực); gyro đơn vị **rad/s**. CSV của `collector` ghi gyro bằng
  °/s, `har` đổi sang rad/s khi đọc.
- Không trừ trung bình gia tốc theo cửa sổ: hướng trọng lực là thông tin chính để phân biệt
  sit/stand/lie.
- Cửa sổ bị cắt khi mất mẫu (nhảy `seq`) hoặc có khoảng trống > 40 ms.
- Nhãn: luôn có `walk`, `sit`, `stand`, `lie`; thêm `stairs_up`, `stairs_down` khi dữ liệu train có.
- Áp suất (nếu có `.baro.csv`): độ dốc bình phương tối thiểu (Pa/s) của các lần đọc BMP280 nằm
  trong thời gian của cửa sổ, cần ít nhất 10 lần đọc (`har/pressure.py`). Cửa sổ thiếu áp suất
  bị bỏ khi huấn luyện mô hình có áp suất.

## Đặc trưng và mô hình

- 70 đặc trưng: 8 kênh (`ax..gz`, độ lớn gia tốc, độ lớn gyro) × 8 thống kê (mean, std, min, max,
  median, rms, mean_abs, iqr), cộng 6 hệ số tương quan giữa các trục.
- Mô hình có lớp cầu thang dùng thêm đặc trưng thứ 71 `pressure_slope_pa_s`.
- **Random Forest**, `n_estimators=300`; chọn `max_features ∈ {sqrt, 0.3}`,
  `min_samples_leaf ∈ {1, 2, 4}`, `max_depth ∈ {None, 16}`,
  `class_weight ∈ {None, balanced_subsample}` bằng cross-validation, chấm theo **macro-F1**.
- `DummyClassifier(most_frequent)` làm mốc; mô hình được chọn phải tốt hơn Dummy trên tập test.

## Huấn luyện trên dữ liệu tự thu (`train-own`)

Cách thu dữ liệu: README chính, mục 6. Huấn luyện:

```powershell
& ".\.venv-har\Scripts\python.exe" -m har train-own --train-dir data/my/train `
    --test-dir data/my/test --run-dir har_runs/my_rf_01
```

- `--run-dir` phải là thư mục chưa tồn tại; lệnh không ghi đè mô hình cũ.
- Có phiên `stairs_up`/`stairs_down` trong train thì mô hình học 6 lớp và dùng đặc trưng áp suất;
  mọi phiên (train và test) phải có `.baro.csv`. Có áp suất nhưng không có phiên cầu thang thì mô
  hình vẫn chỉ dùng 70 đặc trưng chuyển động. Buổi test không được có hoạt động mà train không có.
- `--compare-run <thư mục mô hình>` (tùy chọn): chấm thêm một mô hình có sẵn trên cùng buổi test.
- Phiên bị loại (trạng thái khác `completed`, thang đo khác ±4 g/±500 °/s, nhãn lạ, có lỗi truyền,
  thiếu CSV, quá ngắn) được in kèm lý do và ghi vào `sessions.json`.
- Mỗi phiên bỏ 5 s đầu và 5 s cuối (lúc vào và ra tư thế).
- Buổi train cần ít nhất 4 phiên hợp lệ mỗi hoạt động, buổi test ít nhất 1.
- Cross-validation 4 fold chia theo phiên: phiên thứ k (theo giờ thu) của mỗi hoạt động vào fold
  (k − 1) mod 4. Cross-validation chỉ để chọn cấu hình; điểm báo cáo lấy từ buổi test.

## Demo trực tiếp và phát lại (`demo`, `live`)

Web server dùng thư viện chuẩn, không cần cài thêm gói. Trên Pi4 cần cả `har/` và `collector/`.

Cấu hình đặt trong file TOML (mẫu: [`har_demo.example.toml`](har_demo.example.toml)) với các khóa
`esp`, `run_dir`, `data_dir`, `host` (mặc định `0.0.0.0`), `port` (mặc định 8080), `token`. Tham số
dòng lệnh cùng tên ghi đè giá trị trong file.

```bash
python -m har new-token                       # ghi kết quả vào har_demo.toml: token = "..."
python -m har demo --config har_demo.toml     # mở http://<IP-Pi4>:8080/?token=<token>
python -m har live --config har_demo.toml     # in ra terminal; không cần token
python -m har live --run-dir har_runs/own_rf_01 --esp 192.168.1.50:8765   # không dùng file cấu hình
python -m har fake-esp32 --csv data/har_own/test/<phiên>.csv --port 8765  # ESP32 giả
```

- Kết quả hiển thị là trung bình xác suất 3 cửa sổ gần nhất; dưới 60% thì ghi "không chắc".
- `--esp` nên là địa chỉ IP; dùng tên máy có thể làm việc dừng hoặc đổi chế độ chậm hơn.
- Ở chế độ trực tiếp, mỗi giây Pi4 gửi về ESP32 dòng `CMD,1,ACT,<nhãn>` với kết quả mới nhất để bộ
  đeo hiện trên OLED. Không gửi khi đang phát lại, khi dữ liệu trễ quá 2 giây, hoặc khi chưa có cửa
  sổ nào được phân loại. Firmware không có phần bộ đeo sẽ bỏ qua dòng này.
- ESP32 chỉ nhận một kết nối: tắt `collector` trước khi chạy demo trực tiếp (nếu không, trang báo
  "ESP32 đang bận"). Chuyển sang *Phát lại* sẽ ngắt kết nối ESP32. 5 s không nhận được dòng nào thì
  coi là mất kết nối và tự kết nối lại. Khi trang báo "Lỗi: …", bấm *Trực tiếp* để chạy lại.
- `fake-esp32` đổi stream id mỗi vòng lặp CSV nên trang báo "ESP32 vừa khởi động lại" mỗi vòng;
  `--speed` tua nhanh (mặc định 1.0). Nếu cạnh CSV có `.baro.csv`, nó gửi cả dòng `BARO`.
- Mô hình có đặc trưng áp suất: `demo`/`live` đọc dòng `BARO` từ ESP32, chế độ phát lại đọc
  `.baro.csv` cạnh CSV. Thiếu áp suất thì không đưa ra kết luận và trang báo "Mô hình cần dữ liệu
  áp suất…".
- `har live` trả mã 1 nếu nguồn ESP32 dừng vì lỗi, 0 khi Ctrl+C, 130 nếu Ctrl+C lúc đang khởi động.
- **Token:** khi lắng nghe ngoài `127.0.0.1`, `demo` từ chối chạy nếu chưa có `token`. Trình duyệt
  gửi token qua `?token=` lần đầu, sau đó trang đặt cookie `HttpOnly` nên không cần gõ lại; công cụ
  khác gửi header `Authorization: Bearer <token>`. Sai hoặc thiếu token trả 401. Token chỉ là một
  lớp bảo vệ trong mạng nội bộ: kết nối là HTTP thường, không mã hóa.
- `GET /health` (cũng cần token) trả JSON trạng thái: mã 200 khi đang nhận dữ liệu hoặc phát lại,
  503 khi chưa có dữ liệu hoặc dữ liệu bị trễ.
- `deploy/install_pi.sh` cài demo thành dịch vụ systemd `har-demo` trong `/opt/har`, cấu hình ở
  `/etc/har/har_demo.toml`. Chưa chạy thử trên Pi4 thật.

## Thư mục mô hình

`har train-own` và `har train` tạo trong `--run-dir`:

| File | Nội dung |
| --- | --- |
| `model.joblib` | Mô hình đã huấn luyện |
| `metadata.json` | Schema, nhãn, tên đặc trưng (70, hoặc 71 nếu có áp suất), đơn vị, phiên bản thư viện, seed, hash của mô hình |
| `report.md`, `report.json` | Điểm trên tập test, ma trận nhầm lẫn, độ chính xác từng phiên |
| `selection.json` | Điểm cross-validation của từng cấu hình |
| `sessions.json` | Phiên được dùng và phiên bị loại (chỉ `train-own`) |
| `status.json` | `training`, `completed` hoặc `failed` |

`demo`, `live`, `predict-csv`, `benchmark` chỉ cần `model.joblib` và `metadata.json`; nạp sai
schema, phiên bản hay hash sẽ báo lỗi. Mô hình mẫu `har_runs/own_rf_01` trong repo chỉ giữ hai file
này; số liệu của nó nằm ở [`KET_QUA.md`](../KET_QUA.md).

## Đối chiếu với dữ liệu công khai UCI HAR (tùy chọn)

Dùng để so sánh, không phải để chạy demo. Mô hình huấn luyện trên UCI không dùng được trực tiếp cho
MPU6050 vì hệ trục và cách gắn khác (xem `KET_QUA.md`).

- Dữ liệu: UCI Human Activity Recognition Using Smartphones, DOI 10.24432/C54S4K,
  https://archive.ics.uci.edu/dataset/240/human+activity+recognition+using+smartphones.
  Giấy phép CC BY 4.0; trích dẫn Reyes-Ortiz et al. (2013). Không kèm trong repo.
- 30 người, Samsung Galaxy S II gắn ở eo, gia tốc + gyro 50 Hz. Chỉ dùng bốn lớp:
  1 → `walk`, 4 → `sit`, 5 → `stand`, 6 → `lie`; lớp cầu thang (2, 3) bị loại.
- Cross-validation GroupKFold 5 fold theo người; tập test chính thức của UCI giữ riêng để chấm.

```powershell
& ".\.venv-har\Scripts\python.exe" -m har prepare --data-dir har_data
& ".\.venv-har\Scripts\python.exe" -m har train --data-dir har_data --run-dir har_runs/uci_rf_01
```

## Chạy lại suy luận và đo tốc độ

```powershell
& ".\.venv-har\Scripts\python.exe" -m har predict-csv --run-dir <thư mục mô hình> --csv <phiên>.csv --output replay.json
& ".\.venv-har\Scripts\python.exe" -m har benchmark --run-dir <thư mục mô hình> --csv <phiên>.csv --output benchmark.json
```

Với mô hình có áp suất, hai lệnh này đọc `.baro.csv` cạnh CSV và chỉ dùng các cửa sổ có áp suất.
`predict-csv` chỉ chạy lại đường suy luận trên một CSV, **không** chấm độ chính xác (kết quả có
`scope = model_replay_not_activity_validation`); điểm chính thức nằm trong `report.md`.
`benchmark` đo thời gian trích đặc trưng + dự đoán một cửa sổ; tiêu chí là p95 dưới 1,28 s.
