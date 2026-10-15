# Bằng chứng bước 3B — Random Forest trên dữ liệu MPU6050 đeo ở eo (phương án A)

Ngày: 2026-10-14. Đặc tả: `../specs/2026-10-13-har-own-data-design.md`.
Kế hoạch: `../plans/2026-10-13-har-own-data.md` (Task 9). Package: `har/` (`train-own`).

## Quyết định

- Phương án **A**: 1 người đeo; chia và đánh giá **theo phiên/buổi**, không theo người.
- Buổi train (2026-10-13) để chọn cấu hình bằng CV; buổi test (2026-10-14, khác ngày)
  chấm đúng một lần.
- Không trộn dataset công khai vào huấn luyện; UCI chỉ dùng để so sánh (`--compare-run`).
- Phiên chính thức: **`har_runs/own_rf_01`**.

## Dữ liệu

Thu bằng collector trên Pi4 qua Wi-Fi (`192.168.1.2:8765`), 120 s/phiên, xen kẽ
walk → sit → stand → lie, hiệu chỉnh gyro trên bàn rồi đeo eo hông phải.

| Buổi | Thư mục | walk | sit | stand | lie | Cửa sổ (sau cắt 5 s hai đầu) |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Train 2026-10-13 | `data/har_own/train` | 4 | 4 | 4 | 5 | 336 / 336 / 336 / 420 |
| Test 2026-10-14 | `data/har_own/test` | 2 | 2 | 2 | 2 | 168 / 168 / 168 / 168 |

- Mọi phiên test: `completed`, 6002 mẫu, 50.0 Hz, 0 lỗi, 0 mất mẫu, 0 khoảng trống > 40 ms.
- Không phiên nào bị loại. Các phiên stand của buổi train ban đầu bị ghi vào `test/` và đã được
  chuyển sang `train/` theo xác nhận của người dùng; phiên lie thứ 5 được giữ (vào fold 0).
- Dữ liệu chép Pi4 → laptop bằng `scp`; SHA-256 của cả 16 file test khớp hai phía.
- Hướng trọng lực trung bình: phiên lie test thứ 2 (`20261014T044016Z`) có
  ax −0.16 / ay 0.38 / az −0.28 g, khác hẳn mọi phiên lie train (ax ≈ −0.8 g), tức là một tư thế
  nằm khác; mô hình vẫn đúng 100% phiên đó.

## Phần mềm

- Laptop: `python -m unittest discover -s har/tests -t .` → **62 test OK**.
- Pi4 (`~/har-baseline`, `.venv-har`): đồng bộ `har/` mới (bản cũ sao lưu ở
  `~/har-baseline/har.bak-20261014`; gỡ `split.py`/`tests/test_split.py` sót từ 2026-10-12)
  → **62 test OK**.

## Huấn luyện

```text
python -m har train-own --train-dir data/har_own/train --test-dir data/har_own/test \
    --run-dir har_runs/own_rf_01 --compare-run har_runs/uci_rf_tuned_01
```

Cấu hình thắng (GroupKFold 4 theo thứ tự phiên trong từng hoạt động):
**`{n_estimators: 300, max_features: sqrt, min_samples_leaf: 4, max_depth: None,
class_weight: balanced_subsample}`**, CV macro-F1 **0.9292 ± 0.0541**. OOB train 0.9818.

## Kết quả buổi test (chấm một lần)

| Model | Accuracy | Macro-F1 |
| --- | ---: | ---: |
| **Random Forest (own_rf_01)** | 0.974702 | **0.974713** |
| Dummy | 0.250000 | 0.100000 |
| UCI `uci_rf_tuned_01` trên cùng buổi test | 0.251488 | 0.105609 |

`beats_dummy=True`, mục tiêu macro-F1 ≥ 0.85: **đạt** (AC-4).

| Lớp | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| walk | 0.9636 | 0.9464 | 0.9550 |
| sit | 0.9880 | 0.9821 | 0.9851 |
| stand | 0.9477 | 0.9702 | 0.9588 |
| lie | 1.0000 | 1.0000 | 1.0000 |

Confusion matrix (hàng thật × cột dự đoán walk/sit/stand/lie):

```text
[[159,   0,   9,   0],
 [  3, 165,   0,   0],
 [  3,   2, 163,   0],
 [  0,   0,   0, 168]]
```

Nhầm nhiều nhất: walk → stand (9 cửa sổ). Theo phiên: walk 0.940 / 0.952, sit 0.964 / 1.000,
stand 1.000 / 0.940, lie 1.000 / 1.000.

Mô hình UCI gần như bằng Dummy trên dữ liệu MPU6050 → khác hệ trục/tiền xử lý giữa smartphone
và MPU6050; xác nhận cần dữ liệu riêng.

## Benchmark và so khớp laptop/Pi4 (AC-6)

CSV: `data/har_own/test/20261014T042223Z-e1354d0d.csv` (walk), 92 cửa sổ (replay không cắt
5 s hai đầu), dự đoán 92/92 `walk`.

| Máy | median | p95 | Ngưỡng p95 < 1.28 s |
| --- | ---: | ---: | --- |
| Laptop (Windows 11, Python 3.13) | 0.004532 s | 0.006933 s | Đạt |
| Pi4 (aarch64, Python 3.11) | 0.040064 s | 0.040594 s | **Đạt** |

- Cùng `model_sha256` `800948f96e76c396c180d931d4020c67cda666b7e126bc80249ff8e54bec7332`.
- `prediction` giống hệt 92/92 cửa sổ; `probabilities` lệch tối đa 3.3e-16 (làm tròn dấu phẩy
  động x86 vs ARM), không ảnh hưởng nhãn.

## Artifact

`har_runs/own_rf_01/`: `model.joblib`, `metadata.json`, `selection.json`, `report.json`,
`report.md`, `sessions.json`, `status.json`, `replay.json`, `replay-pi4.json`,
`benchmark-laptop.json`, `benchmark-pi4.json`. Bản sao trên Pi4: `~/har-baseline/har_runs/own_rf_01/`.

## Giới hạn

- Một người, hai buổi liên tiếp, cùng cách đeo: điểm này áp dụng cho đúng người/cách đeo đó,
  chưa phải khả năng tổng quát cho người khác.
- Buổi test chỉ 2 phiên/lớp; khoảng tin cậy rộng. CV ± 0.054 cho thấy dao động giữa các phiên.
- `replay.json` vẫn mang `scope` cũ `public_dataset_model_replay_not_activity_validation`
  (hằng số từ bước 3A); nhãn này không còn đúng với mô hình dữ liệu riêng — nên sửa ở lần chỉnh `har/` sau.
- Chưa có cầu thang (bước 4).
