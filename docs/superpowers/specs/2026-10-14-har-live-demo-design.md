# Demo nhận diện walk/sit/stand/lie — trực tiếp và phát lại

## 1. Phạm vi đã thống nhất

Demo cho người xem thấy mô hình `har_runs/own_rf_01` (bước 3B, test macro-F1 0.9747)
nhận diện **bốn trạng thái walk/sit/stand/lie** từ MPU6050 đeo ở eo. Cầu thang không
thuộc demo.

- **Hai chế độ:** *trực tiếp* (người dùng đeo cảm biến, ESP32 → Pi4) là chính;
  *phát lại* CSV đã ghi là dự phòng khi Wi-Fi/cảm biến trục trặc.
- **Hai giao diện:** trang web bảng điều khiển (`har demo`) và dòng lệnh (`har live`).
- **Máy chạy:** Pi4 đọc ESP32, chạy mô hình và phục vụ web; laptop/điện thoại chỉ mở
  trình duyệt `http://192.168.1.19:8080`.
- **Công nghệ:** chỉ thư viện chuẩn Python (`http.server`, `threading`) + Server-Sent
  Events; HTML/CSS/JS thuần, không CDN, không Node. Không thêm gói nào vào
  `requirements-har.txt`.

**Ngoài phạm vi:** cầu thang; tích hợp vào MotionSense; lưu phiên trực tiếp thành CSV
(collector đã làm việc này); đăng nhập; nhiều người dùng; sửa firmware, collector hoặc
mô hình.

## 2. Kiến trúc

```
ESP32 ──TCP 8765──▶ ┌──────────── Pi4: python -m har demo ────────────┐
                    │ Nguồn mẫu ─▶ Bộ cắt cửa sổ ─▶ Bộ dự đoán ─▶ Phát │──SSE──▶ trình duyệt
CSV đã ghi ───────▶ │ (trực tiếp    (128/64, như       (RF + trung   tin  │
                    │  | phát lại)   lúc train)          bình 3)          │
                    └──────────────────────────────────────────────────┘
```

### 2.1 Thành phần (tất cả trong `har/`)

| File | Trách nhiệm |
| --- | --- |
| `stream_windows.py` | `StreamWindower`: nhận từng mẫu, trả cửa sổ `(128, 6)` mỗi 64 mẫu |
| `live_predict.py` | `LivePredictor`: nạp mô hình một lần, dự đoán từng cửa sổ, trung bình 3 cửa sổ |
| `sources.py` | `EspSource` (TCP tới ESP32) và `ReplaySource` (CSV theo nhịp 50 Hz) |
| `demo_server.py` | HTTP server, luồng SSE, điều phối một nguồn đang chạy |
| `demo_static/index.html` | Trang bảng điều khiển (HTML/CSS/JS trong một file) |
| `fake_esp32.py` | ESP32 giả: TCP server phát một CSV đúng giao thức `DATA,1,…` |
| `cli.py` (sửa) | Thêm lệnh `demo`, `live`, `fake-esp32` |

Phần parse giao thức và TCP dùng lại `collector/protocol.py` (`parse_line`, `Sample`,
`ParseError`) và `collector/tcp_transport.py` (`TcpTransport`, `ConnectionLost`);
không viết lại. `collector/` không bị sửa.

### 2.2 Lệnh

```text
python -m har demo --run-dir har_runs/own_rf_01 --esp 192.168.1.2:8765 \
    --data-dir data/har_own [--host 0.0.0.0] [--port 8080]
python -m har live --run-dir har_runs/own_rf_01 --esp 192.168.1.2:8765
python -m har fake-esp32 --csv <phiên>.csv [--host 127.0.0.1] [--port 8765] [--speed 1]
```

- `demo` khởi động ở chế độ **trực tiếp**; đổi chế độ trên trang web.
- `--data-dir` chứa `train/` và/hoặc `test/` theo bố cục bước 3B.
- Lỗi cấu hình (không nạp được mô hình, `--data-dir` không tồn tại, `--esp` sai cú pháp)
  → in lỗi, exit 1, **trước khi** mở cổng.
- `fake-esp32` phát lặp lại CSV vô hạn, mỗi vòng một `stream_id` mới; Ctrl+C để dừng.

### 2.3 Triển khai Pi4

Chép `har/` và `collector/` vào `~/har-baseline` (cùng venv `.venv-har` bước 3B), cùng
`har_runs/own_rf_01/` và dữ liệu `data/har_own/{train,test}`. Chạy từ `~/har-baseline`.
Cổng web **8080** (8765 là cổng ESP32).

## 3. Xử lý dữ liệu

### 3.1 Bộ cắt cửa sổ dạng luồng

`StreamWindower.push(sample)` dùng **đúng quy tắc** của `har/collector_csv.py`:

- Kênh: `ax, ay, az` (g) và `gx, gy, gz` đổi °/s → rad/s (`np.deg2rad`).
- Bắt đầu đoạn mới khi đổi `stream_id`, đổi phiên/nhãn (phát lại), `seq` nhảy (> +1),
  hoặc `device_time_us` cách mẫu trước > 40 000 µs. `seq` hoặc thời gian không tăng
  → bắt đầu đoạn mới (trực tiếp không được dừng vì một mẫu lỗi).
- Trong một đoạn: cửa sổ đầu khi đủ 128 mẫu, sau đó mỗi 64 mẫu một cửa sổ.
- Mỗi lần bắt đầu đoạn mới, windower báo `reset` để bộ dự đoán xoá bộ trung bình.
- Mỗi cửa sổ kèm `start_seq, end_seq, start_time_us, end_time_us, label` (nhãn thật
  khi phát lại; `None` khi trực tiếp).

### 3.2 Bộ dự đoán

- Nạp `load_bundle(run_dir)` một lần; `n_jobs=1`; `threadpool_limits(1)`.
- Mỗi cửa sổ: `extract_features` → `predict_proba` → xác suất thô; đo thời gian dự đoán.
- **Làm mượt:** trung bình xác suất của tối đa 3 cửa sổ gần nhất trong cùng đoạn.
  Trạng thái hiển thị = lớp có xác suất trung bình cao nhất.
- **Không chắc:** xác suất trung bình cao nhất < 0.60 → cờ `uncertain=True`
  (vẫn hiển thị lớp cao nhất).
- Thứ tự lớp lấy từ `estimator.classes_`.

### 3.3 Nguồn mẫu

- **`EspSource`:** `TcpTransport` + tách dòng + `parse_line`. Dòng không phải `DATA`
  (ví dụ `[NET]`) bỏ qua; `ParseError` → tăng `parse_errors`, bỏ qua dòng.
  Kết nối lỗi hoặc mất → chờ 3 s rồi thử lại, không giới hạn số lần.
  Tình trạng: `connecting` (kèm số lần thử), `calibrating` (đã kết nối, chưa có `DATA`),
  `streaming`, `lost` (mất kết nối, đang thử lại), `busy` (kết nối bị đóng trước khi
  nhận được dòng nào — ESP32 đang phục vụ client khác).
  Mất mẫu = tổng `seq` bị nhảy; tốc độ Hz đo trên 5 s gần nhất; > 2 s không có mẫu
  khi đang `streaming` → hiện "Mất tín hiệu".
- **`ReplaySource`:** đọc CSV collector (cùng header với `collector_csv.HEADER`), phát
  mẫu theo nhịp `device_time_us` chia tốc độ `1 | 2 | 4`. Đồng hồ và hàm ngủ được
  truyền vào để test không phải chờ thật. Một danh sách phiên được phát nối tiếp
  (một phiên, hoặc "cả buổi test" = mọi phiên trong `test/` theo `started_utc`),
  không nghỉ giữa các phiên; hết danh sách thì dừng ở tình trạng `finished`.
- **Danh sách phiên** (`/api/sessions`): đọc JSON trong `train/` và `test/`, chỉ giữ phiên
  qua được kiểm tra metadata của `har/own_dataset.py` (cùng quy tắc với `train-own`).
  Mỗi mục: `session_id, split, label, started_utc`.

### 3.4 Server và SSE

- `ThreadingHTTPServer`; luồng nguồn mẫu riêng; dự đoán chạy trong luồng nguồn
  (≈ 40 ms mỗi 1.28 s trên Pi4).
- Chỉ một nguồn chạy tại một thời điểm. Đổi chế độ: dừng nguồn cũ (đóng socket ESP32)
  rồi mới chạy nguồn mới; xoá lịch sử, windower, bộ trung bình.
- Endpoint:

| Phương thức | Đường dẫn | Mô tả |
| --- | --- | --- |
| GET | `/` | `demo_static/index.html` |
| GET | `/events` | SSE; gửi `snapshot` ngay khi kết nối, sau đó các sự kiện |
| GET | `/api/sessions` | Danh sách phiên phát lại |
| POST | `/api/mode` | JSON `{"mode":"live"}` hoặc `{"mode":"replay","sessions":[id…],"speed":1\|2\|4}` |

- `/api/mode` chỉ nhận `session_id` có trong danh sách; id lạ, tốc độ lạ, JSON sai
  → 400 kèm thông báo. Đường dẫn khác → 404.
- Sự kiện SSE (JSON):
  - `samples`: lô mẫu gửi mỗi ~0.2 s (`t` giây tương đối, `ax, ay, az` g) cho biểu đồ.
  - `prediction`: `time`, `raw_label`, `raw_probabilities`, `label`, `probabilities`,
    `uncertain`, `true_label` (phát lại), `predict_ms`.
  - `status`: `mode`, `state`, `attempt`, `rate_hz`, `missing`, `parse_errors`,
    `predict_p95_ms`, `session` (phát lại), `replay_accuracy` (phát lại).
  - `snapshot`: trạng thái hiện tại + lịch sử dự đoán (tối đa 2 000 mục) + tình trạng.
- Nhiều trình duyệt nhận cùng luồng; client chậm/ngắt bị bỏ khỏi danh sách phát.
- Mặc định `--host 0.0.0.0`: mọi máy trong mạng nhà xem và đổi chế độ được, không có
  đăng nhập (chấp nhận cho demo). `--host 127.0.0.1` để giới hạn trong máy.

## 4. Giao diện

### 4.1 Trang web (bố cục "bảng điều khiển", tiếng Việt)

- **Thanh trên:** nút *Trực tiếp* / *Phát lại*; dòng tình trạng (kết nối, Hz, mất mẫu,
  lỗi dòng, p95 dự đoán).
- **Ô trạng thái:** biểu tượng + tên (Đi bộ / Ngồi / Đứng / Nằm) + độ tin cậy %;
  nhãn "không chắc" màu xám khi `uncertain`; "Đang thu tín hiệu…" trước cửa sổ đầu
  tiên của đoạn.
- **Thanh xác suất** bốn lớp (đã làm mượt).
- **Biểu đồ** gia tốc X/Y/Z 10 s gần nhất (SVG hoặc canvas tự vẽ).
- **Dải lịch sử:** gộp các dự đoán liên tiếp cùng lớp thành đoạn, kèm thời lượng
  (số dự đoán × 1.28 s).
- **Phát lại:** chọn một phiên hoặc "cả buổi test", tốc độ 1×/2×/4×; thêm dải
  "nhãn thật" dưới dải dự đoán và accuracy cộng dồn của trạng thái hiển thị, kèm ghi
  chú: *phát lại không bỏ 5 s đầu/cuối như lúc đánh giá nên có thể thấp hơn 0.975*.
- Thông báo theo tình trạng: "Đang tìm ESP32 (…)… lần thử N", "ESP32 đang hiệu chỉnh —
  để yên trên bàn", "Mất kết nối — đang thử lại", "ESP32 vừa khởi động lại",
  "ESP32 đang bận — tắt collector hoặc chương trình khác đang đọc", "Mất tín hiệu".
- Tải lại trang hoặc mất mạng: `EventSource` tự nối lại, nhận `snapshot`, không mất lịch sử.
- Không có URL bên ngoài trong trang.

### 4.2 Dòng lệnh (`har live`)

Chỉ chế độ trực tiếp. Mỗi dự đoán một dòng:

```text
12:01:03  ĐI BỘ   96%   (thô: walk 0.94)   50.0 Hz  mất 0
```

Dòng thay đổi tình trạng in riêng (đang tìm, hiệu chỉnh, mất kết nối, bận). Ctrl+C
thoát với mã 0.

## 5. Kiểm thử

Unittest, chạy được trên laptop và Pi4, không cần phần cứng; dùng `har/tests/fixtures.py`
(`write_own_session`, …) và `fake_esp32` trên cổng 0.

| Test | Điều kiện |
| --- | --- |
| `StreamWindower` | Đưa từng dòng CSV fixture (có khoảng trống > 40 ms, nhảy `seq`, đổi phiên) → cửa sổ và metadata **giống hệt** `load_collector_windows` (`np.array_equal`) |
| `LivePredictor` | Xác suất thô từng cửa sổ = `predict_windows` theo lô; trung bình ≤ 3 cửa sổ; `reset` xoá ảnh hưởng cũ; ngưỡng 0.60 |
| `ReplaySource` | Nhịp đúng ở 1× và 4× (đồng hồ giả); nối nhiều phiên; nhãn thật đi kèm |
| `EspSource` + `fake_esp32` | Nhận đủ mẫu; tự nối lại sau khi server giả đóng; `busy` khi bị đóng trước dòng đầu; `calibrating` khi chỉ có dòng không phải `DATA`; dòng hỏng tăng `parse_errors` |
| Server | `GET /` 200; `/api/sessions` đúng; `/events` gửi `snapshot` rồi `prediction` khi phát lại fixture; `/api/mode` id lạ/tốc độ lạ → 400; đường dẫn lạ → 404; trang không chứa `http://`/`https://` ngoài |
| CLI | `har live` nối `fake_esp32` in dòng dự đoán; `--run-dir` sai → exit 1; `--esp` sai cú pháp → exit 1 |
| Hồi quy | 62 test hiện có vẫn OK |

## 6. Tiêu chí nghiệm thu

- **AC-1:** toàn bộ test OK trên laptop và Pi4.
- **AC-2:** phát lại một phiên test qua đường demo → dãy `raw_label` giống hệt
  `prediction` trong `replay.json` của `predict-csv` cho cùng CSV (92/92 cửa sổ phiên
  `20261014T042223Z-e1354d0d`).
- **AC-3 (laptop, không phần cứng):** `fake-esp32` + `har demo` → trang
  `http://localhost:8080` cập nhật trực tiếp; `har live` in dòng dự đoán.
- **AC-4 (Pi4, phát lại):** laptop mở `http://192.168.1.19:8080`, phát cả buổi test ở
  4× → chạy hết không lỗi, accuracy hiển thị ≥ 0.90.
- **AC-5 (Pi4, trực tiếp):** người dùng đeo cảm biến, làm walk → sit → stand → lie
  mỗi hoạt động ~30 s → trạng thái hiển thị đúng trong ≤ 5 s sau mỗi lần đổi; `har live`
  qua SSH chạy được.
- **AC-6 (phục hồi):** rút nguồn ESP32 khi đang trực tiếp → "Mất kết nối"; đặt lên bàn,
  cắm lại → tự chạy tiếp, không khởi động lại server. Collector đang chạy → "ESP32 đang bận".
- **AC-7:** `predict_p95_ms` trên Pi4 trong lúc demo < 1 280 ms.
