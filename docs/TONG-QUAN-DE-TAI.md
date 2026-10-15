# Tổng quan đề tài: nhận diện hoạt động bằng ESP32 + MPU6050

*Cập nhật 2026-10-15. Tài liệu đọc hiểu: đề tài làm gì, hệ thống gồm những phần nào, dữ liệu đi
qua đâu, mô hình được huấn luyện thế nào và hiện còn hạn chế gì.*

---

## 1. Đề tài làm gì

Đeo một cảm biến quán tính (MPU6050) ở eo, máy tính nhỏ (Raspberry Pi 4) đọc tín hiệu và cho biết
người đeo đang **đi bộ (walk), ngồi (sit), đứng (stand) hay nằm (lie)** — gần như theo thời gian
thực (mỗi 1,28 s có một kết luận mới). Lên/xuống cầu thang tạm chưa làm.

Đây là bài toán **HAR — Human Activity Recognition**, giải bằng **học máy có giám sát**:
thu dữ liệu có nhãn → dạy mô hình → dùng mô hình đoán nhãn cho tín hiệu mới.

---

## 2. Kiến trúc tổng thể

```text
 ┌────────────── đeo ở eo ──────────────┐        Wi-Fi (TCP 8765)         ┌──────────── Raspberry Pi 4 ────────────┐
 │ MPU6050 ──I2C──► ESP32 (firmware)    │ ─── DATA,1,… 50 dòng/giây ────► │ collector  → ghi phiên CSV + JSON       │
 │  gia tốc ±4 g, gyro ±500 °/s, 50 Hz  │      [NET] mỗi 1 s              │ har demo   → mô hình + web :8080        │
 └──────────────────────────────────────┘                                 │ har live   → in kết quả ra terminal     │
                                                                          └───────────────┬────────────────────────┘
                                                                                          │ trình duyệt (SSE)
                                                                          laptop / điện thoại: http://<IP-Pi4>:8080
 Laptop: phát triển code, huấn luyện mô hình (har train-own), chạy test.
```

Ba khối phần mềm:

| Khối | Ở đâu | Việc chính |
| --- | --- | --- |
| **Firmware** (`src/`) | ESP32 | Đọc MPU6050 50 Hz, hiệu chỉnh gyro lúc khởi động, gửi từng mẫu qua USB hoặc Wi-Fi |
| **collector** (`collector/`) | Pi4 | Kết nối ESP32, ghi một **phiên** có nhãn ra CSV + JSON, thống kê chất lượng truyền |
| **har** (`har/`) | Laptop (huấn luyện), Pi4 (chạy) | Cắt cửa sổ, trích đặc trưng, huấn luyện Random Forest, đánh giá, demo trực tiếp/phát lại |

---

## 3. Phần cứng và firmware (ESP32)

- Nối dây: MPU6050 VCC=3V3, GND, SDA=GPIO21, SCL=GPIO22 (địa chỉ I2C 0x68).
- Lấy mẫu **50 Hz**; thang đo **±4 g** (gia tốc) và **±500 °/s** (gyro).
- **Hiệu chỉnh lúc khởi động:** phải đặt cảm biến **yên trên bàn** khoảng 7 s; firmware lấy 500 mẫu
  để tính **độ lệch (bias) của gyro** rồi trừ đi. **Gia tốc không được hiệu chỉnh** — vẫn chứa
  trọng lực (đây là điều mô hình dùng để biết tư thế).
- Mỗi lần hiệu chỉnh thành công sinh một **stream_id** mới (16 ký tự hex) và `seq` đếm lại từ 0.
- Hai bản build: USB (`esp32dev`) và Wi-Fi (`esp32dev_wifi`, TCP cổng 8765, **chỉ 1 client một lúc**).

**Giao thức v1** (mỗi dòng một bản ghi):

```text
DATA,1,<stream_id>,<seq>,<device_time_us>,<ax_g>,<ay_g>,<az_g>,<gx_dps>,<gy_dps>,<gz_dps>,<temp_c>
[NET],1,<stream_id>,<số mẫu bị bỏ>,<số mẫu không quan sát>     ← telemetry mỗi 1 s
```

Trong lúc đang hiệu chỉnh, dòng `[NET]` có `stream_id` **rỗng** (`[NET],1,,0,0`).

---

## 4. Thu dữ liệu (collector trên Pi4)

Một **phiên** = một lần ghi liên tục **một hoạt động** với **một nhãn**, ví dụ:

```bash
python3 -m collector --tcp 192.168.1.2:8765 --duration 120 --label sit --output data
```

Kết quả mỗi phiên là hai tệp cùng tên:

- **CSV**: mỗi dòng một mẫu — `session_id, label, stream_id, seq, device_time_us, host_elapsed_s,
  ax_g, ay_g, az_g, gx_dps, gy_dps, gz_dps, temp_c`.
- **JSON metadata**: nhãn, thời điểm bắt đầu (UTC), cấu hình cảm biến, trạng thái (`completed`/`interrupted`…),
  thống kê chất lượng (mất mẫu, khoảng trống > 40 ms, lỗi dòng).

Các module: `protocol.py` (đọc dòng DATA), `line_reader.py` (ghép dòng), `tcp_transport.py` (TCP),
`quality.py` (theo dõi liên tục/khoảng trống), `telemetry.py` (dòng NET), `session.py` (ghi CSV/JSON),
`recorder.py` + `collect.py` (vòng thu), `discovery.py` (tìm ESP32 qua mDNS), `cli.py` (lệnh).

---

## 5. Gói `har` — các module

| Nhóm | Module | Vai trò |
| --- | --- | --- |
| Cấu hình | `config.py` | Nhãn, kích thước cửa sổ 128, bước 64, danh sách kênh/thống kê |
| Dữ liệu | `dataset.py` | Tải & đọc UCI HAR (bước 3A) |
| | `collector_csv.py` | Đọc CSV collector → cửa sổ (128, 6) |
| | `own_dataset.py` | Đọc phiên của bạn, kiểm tra metadata, loại phiên lỗi, cắt 5 s hai đầu, chia fold |
| Học máy | `features.py` | 70 đặc trưng cho mỗi cửa sổ |
| | `tune.py` | Lưới cấu hình + cross-validation để chọn cấu hình |
| | `train.py` / `train_own.py` | Huấn luyện bước 3A (UCI) / 3B (dữ liệu của bạn) |
| | `artifact.py` | Lưu/nạp mô hình (`model.joblib` + `metadata.json`, kiểm tra phiên bản & SHA-256) |
| | `inference.py`, `report.py` | Dự đoán hàng loạt, benchmark, báo cáo |
| Demo | `stream_windows.py` | Cắt cửa sổ **từng mẫu một** (giống hệt cách cắt lúc huấn luyện) |
| | `live_predict.py` | Dự đoán 1 cửa sổ + làm mượt 3 cửa sổ + cờ "không chắc" |
| | `live_pipeline.py` | Ghép mẫu → cửa sổ → dự đoán → sự kiện; đo Hz, mất mẫu, khởi động lại |
| | `sources.py` | Nguồn dữ liệu: ESP32 qua TCP (tự kết nối lại) hoặc phát lại CSV (1×/2×/4×) |
| | `demo_server.py`, `demo_static/index.html` | Web server + trang bảng điều khiển (SSE) |
| | `live_terminal.py` | `har live`: in kết quả ra terminal |
| | `fake_esp32.py` | ESP32 giả (phát CSV qua TCP) để test không cần phần cứng |
| | `cli.py` | Lệnh `prepare, train, train-own, predict-csv, benchmark, demo, live, fake-esp32` |

Bộ test: `har/tests/` (127 test), chạy được trên laptop và Pi4.

---

## 6. Dữ liệu đã dùng

**Bước 3A — dữ liệu công khai UCI HAR** (để dựng và kiểm chứng pipeline): 30 người, điện thoại
gắn ở eo, 50 Hz; chỉ giữ 4 lớp walk/sit/stand/lie. Mô hình `har_runs/uci_rf_tuned_01` đạt
macro-F1 0,93 trên test UCI — nhưng trên MPU6050 của bạn chỉ **0,106** (cảm biến/cách đeo khác hẳn),
nên phải thu dữ liệu riêng.

**Bước 3B — dữ liệu của bạn** (`data/har_own/`, 1 người, đeo ở eo):

| Buổi | Ngày | Số phiên | Ghi chú |
| --- | --- | --- | --- |
| train | 2026-10-13 | 17 (walk 4, sit 4, stand 4, lie 5), ~120 s/phiên | dùng để **học** |
| test | 2026-10-14 | 8 (2 phiên/hoạt động) | buổi khác, chỉ dùng để **chấm** |

---

## 7. Cách huấn luyện mô hình (từng bước)

Lệnh: `python -m har train-own --train-dir data/har_own/train --test-dir data/har_own/test --run-dir har_runs/own_rf_01`

### Bước 1 — Gắn nhãn (học có giám sát)
Nhãn đến từ `--label` lúc thu: mọi mẫu trong phiên `sit` đều mang nhãn `sit`. Mô hình chỉ học
được những gì các nhãn này thể hiện.

### Bước 2 — Lọc và cắt
- Loại phiên không đạt (không `completed`, sai thang đo, nhãn lạ, lỗi truyền, thiếu CSV, quá ngắn).
- Bỏ **5 s đầu và 5 s cuối** mỗi phiên (lúc đang vào/ra tư thế).
- Cắt **cửa sổ 128 mẫu = 2,56 s**, trượt **64 mẫu = 1,28 s** (chồng nhau một nửa).
  Cắt đoạn mới nếu mất mẫu hoặc trống > 40 ms. Gyro đổi sang rad/s.
- Mỗi cửa sổ = **một mẫu học**, mang nhãn của phiên.

### Bước 3 — Trích 70 đặc trưng cho mỗi cửa sổ
- 8 kênh: `ax, ay, az, gx, gy, gz`, độ lớn gia tốc, độ lớn gyro.
- 8 thống kê mỗi kênh: mean, std, min, max, median, rms, trung bình trị tuyệt đối, iqr → 64 số.
- 6 tương quan giữa các trục (ax–ay, ax–az, ay–az, gx–gy, gx–gz, gy–gz).

Ý nghĩa trực quan: **mean/median của ax, ay, az** cho biết cảm biến đang nghiêng thế nào so với
trọng lực (tư thế); **std/rms/iqr và gyro** cho biết mức chuyển động (đi bộ hay đứng yên).

### Bước 4 — Mô hình Random Forest
300 cây quyết định; mỗi cây học các luật dạng "nếu `ax_mean` < … và `acc_mag_std` < … thì …";
kết quả là **xác suất** cho 4 lớp (trung bình phiếu của các cây).

### Bước 5 — Chọn cấu hình bằng cross-validation theo phiên
- Lưới 24 cấu hình khai báo trước: `max_features ∈ {sqrt, 0.3}`, `min_samples_leaf ∈ {1, 2, 4}`,
  `max_depth ∈ {None, 16}`, `class_weight ∈ {None, balanced_subsample}`.
- **GroupKFold 4 fold theo phiên**: fold k giữ ra phiên thứ k của mỗi hoạt động, học trên phần còn lại.
  Chia theo phiên (không chia ngẫu nhiên theo cửa sổ) để cửa sổ chồng nhau của cùng một phiên
  không lọt sang cả hai phía — tránh điểm ảo.
- Thước đo **macro-F1** (trung bình F1 của 4 lớp, lớp nào cũng quan trọng như nhau).
- Cấu hình thắng: `{300 cây, max_features=sqrt, min_samples_leaf=4, max_depth=None, class_weight=balanced_subsample}`,
  CV macro-F1 **0,929**. Huấn luyện lại trên toàn bộ train với cấu hình này.

### Bước 6 — Chấm một lần trên buổi test
Buổi test (ngày khác) chỉ dùng **một lần** ở cuối: **macro-F1 0,975**, accuracy ~97,5%.
Thời gian dự đoán p95: laptop 6,9 ms, Pi4 ~40 ms / cửa sổ.

### Bước 7 — Lưu mô hình
`har_runs/own_rf_01/`: `model.joblib`, `metadata.json` (danh sách đặc trưng, đơn vị, phiên bản thư viện,
SHA-256), `selection.json` (kết quả CV), `report.json/.md`, `sessions.json` (phiên dùng/loại).

---

## 8. Chạy demo (suy luận)

```bash
# Trên Pi4 (~/har-baseline)
./.venv-har/bin/python -m har demo --run-dir har_runs/own_rf_01 --esp 192.168.1.2:8765 --data-dir /home/pi/data/har_own
# rồi mở http://192.168.1.19:8080
./.venv-har/bin/python -m har live --run-dir har_runs/own_rf_01 --esp 192.168.1.2:8765   # bản terminal
```

Luồng xử lý:

```text
mẫu 50 Hz → cắt cửa sổ (giống lúc học) → 70 đặc trưng → Random Forest → xác suất thô
          → trung bình 3 cửa sổ gần nhất → nhãn hiển thị (dưới 60% ghi "không chắc")
```

- **Trực tiếp**: đọc ESP32 qua TCP, tự kết nối lại; báo "đang hiệu chỉnh", "đang bận" (ESP32 đang
  phục vụ chương trình khác), "mất tín hiệu" (> 2 s không có mẫu), "mất kết nối" (> 5 s không có dòng).
- **Phát lại**: chạy lại CSV đã ghi ở 1×/2×/4×, hiện thêm dải nhãn thật và accuracy cộng dồn.
- Trang web: trạng thái lớn + thanh xác suất, biểu đồ gia tốc 10 s, dải lịch sử dự đoán.

---

## 9. Kết quả nghiệm thu demo (2026-10-14/15)

| Hạng mục | Kết quả |
| --- | --- |
| Test tự động (laptop & Pi4) | 127/127 OK |
| Phát lại khớp dự đoán hàng loạt | 92/92 cửa sổ giống hệt |
| Phát lại cả buổi test trên Pi4 (4×) | accuracy **98,1%** (722/736), p95 76 ms |
| Trực tiếp: kết nối | 50 Hz, mất 0 mẫu, p95 ~99 ms |
| **Trực tiếp: nhận diện khi đeo thật** | **chưa đạt** — xem mục 10 |

---

## 10. Hạn chế đã phát hiện khi chạy trực tiếp

**Mô hình phụ thuộc mạnh vào góc nghiêng tuyệt đối của cảm biến.** Khoảng **62%** "mức quan trọng"
của mô hình nằm ở các đặc trưng mức trung bình của ax/ay/az (hướng trọng lực). Từ dữ liệu đã thu:

| Tư thế (lúc thu) | ax | ay | az |
| --- | --- | --- | --- |
| đứng | +0,20 | **−0,98** | ~0 |
| ngồi (ngả lưng ~35° so với đứng) | −0,37 | −0,86 | +0,20 |
| nằm | −0,82 | −0,21 | +0,28 |

Mọi phiên đều cùng một cách đeo và cùng một kiểu ngồi, nên điểm test cao nhưng **không kiểm tra**
được trường hợp đeo khác / ngồi khác. Khi đeo thật:

1. **Đeo lật 180°** → trục Y ngược dấu → mọi tư thế tĩnh thành "nằm".
2. **Đeo lệch góc ~20–25°** (đứng cho ax ≈ +0,45, az ≈ −0,39) → hướng chưa từng thấy → đoán sai,
   thậm chí ngồi yên mà ra "đi bộ".
3. **Ngồi thẳng lưng** → hông gần như thẳng đứng như khi đứng → bị nhận là "đứng". Đây là giới hạn
   vật lý của cảm biến đặt ở eo, thu thêm dữ liệu cũng không xoá hết.

**Hướng cải thiện (chưa chọn):**

| Hướng | Ý tưởng | Đánh đổi |
| --- | --- | --- |
| A. Đeo ở đùi | Ngồi: đùi nằm ngang; đứng: đùi thẳng đứng → sit/stand tách rõ | Thu lại toàn bộ dữ liệu |
| B. Giữ eo, thu đa dạng | Đánh dấu vị trí/chiều trên đai; phiên "ngồi" gồm ngồi thẳng, dựa lưng, cúi | Ngồi thẳng yên vẫn dễ nhầm đứng |
| C. Eo + hiệu chỉnh khi đứng | Đứng yên 5 s đầu mỗi phiên/demo để xoay tín hiệu về cùng hướng | Cần thêm code; vẫn còn giới hạn ngồi thẳng |

Dù chọn hướng nào, nguyên tắc: **dữ liệu có nhãn phải bao phủ các cách đeo và cách làm động tác
sẽ gặp lúc dùng thật**, và buổi test nên được đeo lại từ đầu (tháo ra đeo lại) để kiểm tra điều đó.

---

## 11. Thuật ngữ

| Thuật ngữ | Nghĩa |
| --- | --- |
| Học có giám sát | Học từ dữ liệu đã có đáp án (nhãn) |
| Phiên (session) | Một lần ghi liên tục một hoạt động, một nhãn |
| Cửa sổ (window) | Đoạn 2,56 s (128 mẫu) — đơn vị để trích đặc trưng và dự đoán |
| Đặc trưng (feature) | Con số tóm tắt cửa sổ (trung bình, độ lệch chuẩn, …) |
| Random Forest | Tập nhiều cây quyết định bỏ phiếu |
| Cross-validation (CV) | Chia train thành nhiều phần, lần lượt giữ một phần để thử, dùng để chọn cấu hình |
| GroupKFold | CV mà các mẫu cùng nhóm (cùng phiên) luôn ở cùng một phía |
| Macro-F1 | Trung bình F1 của các lớp; F1 cân bằng giữa "đoán đúng bao nhiêu" và "bỏ sót bao nhiêu" |
| p95 | 95% số lần dự đoán nhanh hơn giá trị này |
| Làm mượt (smoothing) | Trung bình xác suất 3 cửa sổ gần nhất để kết quả bớt nhảy |
| Domain shift | Dữ liệu lúc dùng khác dữ liệu lúc học (ví dụ đeo lệch góc) → mô hình kém đi |

---

## 12. Tài liệu chi tiết

- Firmware & giao thức: `README.md`
- Gói `har` và lệnh: `har/README.md`
- Đặc tả: `docs/superpowers/specs/` — 3A `2026-10-12-har-public-baseline-design.md`,
  3B `2026-10-13-har-own-data-design.md`, demo `2026-10-14-har-live-demo-design.md`
- Hồ sơ nghiệm thu: `docs/superpowers/evidence/` — `2026-10-12-har-public-baseline.md`, `2026-10-14-har-own-data.md`
