# Bước 3B — Nhận diện walk/sit/stand/lie trên dữ liệu MPU6050 đeo ở eo

## 1. Phạm vi đã thống nhất

Người dùng chọn **phương án A**: dữ liệu do **một người** (người dùng) đeo. Vì chỉ có
một người, mô hình được đánh giá theo **phiên** và theo **buổi**, không theo người.
Kết quả chỉ nói về người này với cách đeo này; không suy rộng cho người khác.

Đầu ra: tập dữ liệu có nhãn do người dùng thu, mô hình Random Forest huấn luyện lại
trên dữ liệu đó, báo cáo đánh giá trên một buổi test giữ riêng, và benchmark Pi4.

Dùng lại pipeline bước 3A: cửa sổ 128 mẫu (2.56 s), bước trượt 64, 70 đặc trưng
(`har/features.py`), lưới 24 cấu hình Random Forest (`har/tune.py`), artifact
(`har/artifact.py`), bộ đọc CSV collector (`har/collector_csv.py`).

**Ngoài phạm vi:** sửa firmware hoặc collector; đặc trưng tần số; gộp dữ liệu UCI vào
huấn luyện; lớp cầu thang (bước 4); suy luận trực tiếp trên stream; giao diện
MotionSense (bước 5).

## 2. Quy trình thu dữ liệu

### 2.1 Số lượng và bố trí buổi

| Tập | Buổi | Phiên mỗi hoạt động | Thời lượng | Thư mục |
| --- | --- | ---: | ---: | --- |
| train | 1 buổi | 4 | 120 s | `data/har_own/train/` |
| test | 1 buổi khác | 2 | 120 s | `data/har_own/test/` |

Tổng 16 phiên train + 8 phiên test, khoảng 48 phút ghi.

- Buổi test **phải khác** buổi train: ngày khác, hoặc cách ít nhất vài giờ và đã thay
  quần áo. Đây là điều kiện bắt buộc để điểm cuối không lạc quan.
- Trong mỗi buổi thu **xen kẽ** hoạt động: walk → sit → stand → lie → walk → …
  Không thu các phiên cùng hoạt động liên tiếp nhau.
- Vì cả 4 phiên train thuộc một buổi, điểm cross-validation trên train chỉ dùng để
  **chọn cấu hình**; con số báo cáo độ chính xác là điểm trên buổi test.

### 2.2 Các bước mỗi phiên

1. **Hiệu chỉnh trên bàn:** bật ESP32 (firmware `esp32dev_wifi`) khi cảm biến nằm yên
   trên mặt phẳng; chờ `[CAL] DONE`. Hiệu chỉnh gyro bị từ chối nếu cảm biến đeo
   trên người lúc khởi động. Không cần reset ESP32 giữa các phiên.
2. **Đeo ở eo**, luôn cùng vị trí và cùng hướng: kẹp bên hông phải ở thắt lưng,
   mặt chip MPU6050 hướng ra ngoài, cổng USB của ESP32 chúc xuống. Nếu người dùng
   đổi quy ước hướng, phải giữ một hướng duy nhất cho mọi phiên train và test.
3. **Vào tư thế** rồi chạy collector trên Pi4 (dò lại IP ESP32 mỗi buổi):

   ```bash
   python3 -m collector --tcp <ESP_IP>:8765 --duration 120 --label walk --output data/har_own/train
   ```

   Nhãn chỉ dùng `walk`, `sit`, `stand`, `lie`. Buổi test dùng `--output data/har_own/test`.
4. **Tháo cảm biến** sau mỗi phiên; lần đeo lại kế tiếp là một phiên độc lập.

Hành vi trong phiên:

- `walk`: đi bình thường, có rẽ.
- `sit`: ngồi ghế, cho phép cử động nhẹ.
- `stand`: đứng tự nhiên.
- `lie`: nằm ngửa hoặc nghiêng; thay đổi tư thế giữa các phiên.

Sau mỗi buổi, chép `data/har_own/<split>/` (cả `.csv` và `.json`) từ Pi4 về laptop
vào cùng đường dẫn trong dự án.

## 3. Nạp dữ liệu — `har/own_dataset.py`

Hàm `load_own_sessions(directory, split)` trả về `(WindowSet, sessions)`:
`WindowSet` giống kiểu dữ liệu UCI (`subjects` = `session_id`); `sessions` là danh sách
mô tả từng phiên được nhận hoặc bị loại.

Với mỗi `*.json` trong thư mục, theo thứ tự tên file:

1. **Kiểm tra metadata.** Phiên bị loại (kèm lý do, không dừng lệnh) nếu:
   - `protocol_version != 1` hoặc `status != "completed"`;
   - `sensor_config.accel_range_g != 4`, `gyro_range_dps != 500` hoặc
     `output_interval_ms != 20`;
   - `label` không thuộc `walk/sit/stand/lie`;
   - một trong `stats.data_errors`, `missing_by_seq`, `duplicates`, `out_of_order`,
     `gaps_over_40ms` khác 0;
   - `csv_file` rỗng hoặc file CSV không tồn tại trong cùng thư mục.
2. **Tạo cửa sổ** bằng `load_collector_windows(csv)`; gyro đã đổi sang rad/s.
   Nhãn CSV phải khớp `label` trong JSON, nếu không thì loại phiên.
3. **Cắt đầu cuối:** gọi `t0`/`t1` là `device_time_us` của mẫu đầu/cuối phiên. Bỏ cửa
   sổ có `start_time_us < t0 + 5 s` hoặc `end_time_us > t1 − 5 s`. Phiên còn 0 cửa sổ
   thì bị loại.

Mỗi mục trong `sessions`: `session_id`, `label`, `started_utc`, `accepted`, `reason`
(nếu bị loại), `windows` (sau khi cắt), `trimmed_windows`, `csv_sha256`.

**Lỗi dừng lệnh** (`ValueError`):

- tập train có hoạt động nào dưới 4 phiên được nhận;
- tập test thiếu bất kỳ hoạt động nào;
- một `session_id` xuất hiện ở cả train và test;
- thư mục không có file JSON nào.

## 4. Chia fold cho cross-validation

Trong tập train, với từng hoạt động, xếp các phiên được nhận theo `started_utc` và
đánh số thứ tự `1, 2, 3, …`. Nhóm fold của mọi cửa sổ trong phiên là
`(thứ tự − 1) mod 4`. Cross-validation dùng `GroupKFold(n_splits=4)` trên nhóm này,
nên fold k giữ ra phiên thứ k (và k+4, …) của **mỗi** hoạt động; fold nào cũng đủ 4 lớp.

Lý do không dùng trực tiếp `session_id` làm nhóm: `GroupKFold` cân bằng theo kích
thước nhóm chứ không theo lớp, có thể tạo fold test thiếu một lớp và làm méo macro-F1.

## 5. Huấn luyện — sửa `har/train.py` và `har/tune.py`

- `train_baseline(...)` thêm tham số từ khóa: `cv_groups=None` (mặc định dùng
  `train.subjects`), `n_splits=N_SPLITS`, `title=None` (tiêu đề báo cáo) và
  `extra=None` (dict gộp vào kết quả, ví dụ danh sách phiên, so sánh UCI).
  Giá trị mặc định giữ nguyên hành vi `har train` của UCI; 38 test hiện có phải đạt.
- Kiểm tra train/test không chung `subjects` vẫn áp dụng (ở đây là `session_id`).
- `excluded_stairs` chỉ ghi khi dữ liệu là UCI; với dữ liệu riêng ghi 0.
- Lưới cấu hình, tiêu chí chọn (macro-F1 trung bình, hòa thì chọn cấu hình đơn giản),
  `DummyClassifier(most_frequent)` và cờ `quality_goal_met` (macro-F1 ≥ 0.85) giữ nguyên.
- `dataset_manifest` cho dữ liệu riêng: `{"source": "own", "train_dir", "test_dir",
  "train_sessions": [session_id…], "test_sessions": [...], "csv_sha256": {...}}`.

## 6. CLI — lệnh `har train-own`

```powershell
& ".\.venv-har\Scripts\python.exe" -m har train-own --train-dir data/har_own/train `
    --test-dir data/har_own/test --run-dir har_runs/own_rf_01 `
    [--compare-run har_runs/uci_rf_tuned_01]
```

- In danh sách phiên bị loại kèm lý do, rồi số phiên/cửa sổ mỗi lớp của train và test.
- `--compare-run`: nạp model có sẵn bằng `load_bundle`, dự đoán trên tập test riêng,
  ghi `accuracy`/`macro_f1`/`confusion_matrix` vào `report.json` dưới khóa
  `comparison`, và thêm một dòng trong bảng test của `report.md`.
- In `selected_config`, `test_macro_f1`, `goal_met` như lệnh `train`.
- Mã thoát giống CLI hiện tại: 0 thành công, 1 lỗi `ValueError/OSError/KeyError`.

## 7. Đầu ra trong `har_runs/<run-id>/`

Như bước 3A (`model.joblib`, `metadata.json`, `selection.json`, `report.json`,
`report.md`, `status.json`), thêm:

- `sessions.json`: danh sách phiên train/test (mục 3) và nhóm fold của từng phiên train.
- Trong `report.md`:
  - tiêu đề "Dữ liệu MPU6050 đeo ở eo — 1 người (phương án A)";
  - ghi chú: CV trên một buổi chỉ để chọn cấu hình; điểm báo cáo là buổi test;
  - bảng **độ chính xác theo từng phiên test** (session_id, nhãn, số cửa sổ, accuracy);
  - dòng so sánh mô hình UCI nếu có `--compare-run`.

Benchmark và replay dùng lại lệnh `har benchmark` / `har predict-csv` hiện có.

## 8. Kiểm thử tự động

Dùng `unittest`, dữ liệu tổng hợp ghi ra thư mục tạm (CSV + JSON đúng định dạng collector).

- `test_own_dataset.py`:
  - phiên hợp lệ được nhận, số cửa sổ đúng sau khi cắt 5 s đầu/cuối;
  - mỗi lý do loại có một test: status, thang đo, nhãn ngoài danh sách, chỉ số lỗi,
    thiếu CSV, nhãn CSV khác JSON, còn 0 cửa sổ sau khi cắt;
  - lỗi khi trùng `session_id` giữa train và test, khi train có lớp dưới 4 phiên,
    khi test thiếu lớp, khi thư mục rỗng.
- Chia fold: thứ tự theo `started_utc` (không theo tên file), phiên thứ 5 vào nhóm 0,
  mọi fold có đủ 4 lớp.
- `train_baseline` chạy với `cv_groups` và `n_splits=4` trên fixture tổng hợp
  (`MINI_GRID`); test UCI cũ không đổi.
- CLI `train-own` chạy trọn trên tập tổng hợp nhỏ (lưới rút gọn qua patch), kiểm tra
  có `sessions.json`, `report.md`, và khóa `comparison` khi có `--compare-run`.

Lệnh: `& ".\.venv-har\Scripts\python.exe" -m unittest discover -s har/tests -t . -v`

## 9. Tiêu chí nghiệm thu

| Mã | Tiêu chí |
| --- | --- |
| AC-1 | 16 phiên train và 8 phiên test được nhận (đủ 4/2 phiên mỗi hoạt động); phiên bị loại được thu lại. |
| AC-2 | Toàn bộ test `har/` đạt (38 test cũ + test mới). |
| AC-3 | `train-own` hoàn tất; báo cáo có macro-F1 buổi test, confusion matrix, độ chính xác từng phiên test; mô hình chọn tốt hơn Dummy. |
| AC-4 | Mục tiêu macro-F1 ≥ 0.85 trên buổi test. **Không phải điều kiện bắt buộc**: nếu chưa đạt, ghi phân tích confusion và đề xuất bước tiếp (đặc trưng tần số, thêm phiên, kiểm tra hướng đeo). |
| AC-5 | Có so sánh mô hình UCI (`har_runs/uci_rf_tuned_01`) trên cùng buổi test. |
| AC-6 | Benchmark Pi4: p95 < 1.28 s; dự đoán replay trên laptop và Pi4 giống hệt nhau. |

Hồ sơ kết quả: `docs/superpowers/evidence/<ngày>-har-own-data.md`.

## 10. Rủi ro đã biết

- Một người, một buổi train: mô hình có thể học thói quen của buổi đó; buổi test riêng
  là kiểm soát chính.
- Bias gia tốc ~0.94 g chưa hiệu chỉnh: không ảnh hưởng nếu mọi phiên cùng cảm biến và
  cùng hướng đeo; sẽ ảnh hưởng nếu đổi cảm biến.
- `sit` và `stand` khác nhau chủ yếu ở góc nghiêng hông; dễ nhầm nếu hướng đeo lệch.
- Collector ghi cứng thang đo trong JSON; kiểm tra ở mục 3 chỉ đúng khi dữ liệu thu
  bằng firmware hiện tại (±4 g/±500 °/s).
