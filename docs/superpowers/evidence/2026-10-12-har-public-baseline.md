# Bằng chứng bước 3A — Baseline Random Forest (chọn cấu hình bằng CV)

Ngày: 2026-10-12. Đặc tả: `../specs/2026-10-12-har-public-baseline-design.md`.
Kế hoạch: `../plans/2026-10-12-har-public-baseline.md`. Package: `har/`.

## Quyết định

- Chỉ dùng **Random Forest**; `DummyClassifier` làm mốc.
- Chọn cấu hình bằng **GroupKFold 5 fold theo người trên tập train chính thức**
  (không dùng test), rồi refit trên toàn train và chấm test đúng một lần.
- Lưới khai báo trước (24 cấu hình): `n_estimators=300`, `max_features∈{sqrt,0.3}`,
  `min_samples_leaf∈{1,2,4}`, `max_depth∈{None,16}`, `class_weight∈{None,balanced_subsample}`.
- Phiên chính thức: **`har_runs/uci_rf_tuned_01`**.

Các phiên cũ giữ làm lịch sử: `uci_baseline_01` (LR), `uci_rf_01` (RF 200),
`uci_rf50_01` (RF 50).

## Môi trường

- Laptop: Python 3.13.5 (Windows). Pi4: Python 3.11.2 (aarch64), Debian 12.
- Thư viện (dùng chung): numpy 2.2.6, scipy 1.15.3, scikit-learn 1.7.2,
  joblib 1.5.2, threadpoolctl 3.6.0.

## Dữ liệu UCI HAR

- URL: https://archive.ics.uci.edu/static/public/240/human+activity+recognition+using+smartphones.zip
- SHA-256: `c00b803081a5c797cd5e4b83700a9810b38d53d9d84e01917e090e1fdbc81031`
- Cửa sổ bốn lớp: train 5293, test 2056. Loại cầu thang: train 2059, test 891.
- Cửa sổ 128×6 (2.56 s ở 50 Hz); 70 đặc trưng (8 kênh × 8 thống kê + 6 tương quan).

## Phần mềm

- `python -m unittest discover -s har/tests -t .` → **38 test OK** (thêm `test_tune`, bỏ `test_split`).
- Regression collector **84 test OK**; firmware `esp32dev`/`esp32dev_wifi` build SUCCESS.

## Huấn luyện (chọn cấu hình bằng GroupKFold)

```text
python -m har train --data-dir har_data --run-dir har_runs/uci_rf_tuned_01
```

Cấu hình thắng: **`{n_estimators: 300, max_features: sqrt, min_samples_leaf: 4,
max_depth: 16, class_weight: balanced_subsample}`**, CV macro-F1 **0.9357 ± 0.0266**.

Năm cấu hình đứng đầu (CV macro-F1):

| n_estimators | max_features | min_samples_leaf | max_depth | class_weight | CV macro-F1 |
| ---: | --- | ---: | ---: | --- | ---: |
| 300 | sqrt | 4 | 16 | balanced_subsample | 0.9357 ± 0.0266 |
| 300 | sqrt | 4 | None | balanced_subsample | 0.9355 ± 0.0267 |
| 300 | sqrt | 4 | None | None | 0.9343 ± 0.0279 |
| 300 | sqrt | 4 | 16 | None | 0.9339 ± 0.0274 |
| 300 | sqrt | 2 | 16 | None | 0.9337 ± 0.0273 |

Kết quả test chính thức (chấm đúng một lần):

| Giai đoạn | Accuracy | Macro-F1 |
| --- | ---: | ---: |
| Test Random Forest | 0.931420 | **0.930605** |
| Test Dummy | 0.261187 | 0.103548 |

OOB trên tập train (ước lượng, không thay test): 0.9866.

`beats_dummy=True`, `quality_goal_met=True` (macro-F1 test ≥0.85).

Confusion matrix test (hàng thật × cột dự đoán walk/sit/stand/lie):

```text
[[496,   0,   0,   0],
 [  0, 397,  94,   0],
 [  0,  47, 485,   0],
 [  0,   0,   0, 537]]
```

walk và lie gần như hoàn hảo; sit/stand nhầm lẫn nhau (94 và 47).

## Benchmark (feature extraction + predict 1 cửa sổ)

| Máy | median | p95 | Ngưỡng p95 <1.28 s |
| --- | ---: | ---: | --- |
| Laptop (Python 3.13) | 0.004868 s | 0.006381 s | Đạt |
| Pi4 (Python 3.11, aarch64) | 0.039226 s | 0.039731 s | **Đạt** |

So khớp hai máy trên cùng CSV tham chiếu (`data/20261011T103102Z-c9f5351c.csv`):
45 cửa sổ, **dự đoán giống hệt nhau**, cùng thứ tự nhãn, cùng `model_sha256`.

## Artifact

`har_runs/uci_rf_tuned_01/`: `model.joblib`, `metadata.json`, `selection.json`
(lưu cả 24 cấu hình CV), `report.json`, `report.md`, `status.json`, `replay.json`,
`benchmark-laptop.json`, `benchmark-pi4.json`, `replay-pi4.json`.

Replay `replay.json` scope `public_dataset_model_replay_not_activity_validation`:
chỉ kiểm tra đường đọc CSV → cửa sổ → suy luận, **không** đánh giá hoạt động người.

## So sánh các phiên (cùng 70 đặc trưng cửa sổ)

| Phiên | Model | Test macro-F1 | Laptop p95 |
| --- | --- | ---: | ---: |
| uci_baseline_01 | LR (lịch sử) | 0.9277 | 0.0008 s |
| uci_rf_01 | RF 200 cây | 0.9312 | 0.0049 s |
| uci_rf50_01 | RF 50 cây | 0.9278 | 0.0019 s |
| **uci_rf_tuned_01** | **RF chọn bằng CV** | **0.9306** | **0.0064 s** |

Chú ý: cấu hình chọn theo CV không nhất thiết cho test cao nhất; chọn theo CV là cách
trung thực (không dùng test để chọn).

## Giới hạn

- Baseline trên smartphone dataset công khai; chưa phải độ chính xác MPU6050 đeo ở eo.
- Chưa dùng 561 đặc trưng/reduced5 của MotionSense (đã chốt không cần khớp tài liệu).
- Chưa có dữ liệu hoạt động người thật (AC-04/05 chờ pin).
