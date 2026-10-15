# Dữ liệu MPU6050 đeo ở eo — 1 người (phương án A)

Nguồn: phiên collector có nhãn do một người đeo; đánh giá theo phiên/buổi, không theo người.

Cross-validation chạy trên một buổi train nên chỉ dùng để chọn cấu hình; điểm báo cáo là buổi test giữ riêng.

## Chọn cấu hình

Phương pháp: GroupKFold 4 fold theo thứ tự phiên trong từng hoạt động (buổi train); chọn bằng macro-F1 trung bình, không dùng test.

**Cấu hình chọn:** `{'n_estimators': 300, 'max_features': 'sqrt', 'min_samples_leaf': 4, 'max_depth': None, 'class_weight': 'balanced_subsample'}` — CV macro-F1 0.929203 ± 0.054102.

| n_estimators | max_features | min_samples_leaf | max_depth | class_weight | CV macro-F1 |
| ---: | --- | ---: | ---: | --- | ---: |
| 300 | sqrt | 4 | None | balanced_subsample | 0.929203 ± 0.054102 |
| 300 | sqrt | 4 | 16 | balanced_subsample | 0.929203 ± 0.054102 |
| 300 | sqrt | 1 | None | balanced_subsample | 0.924767 ± 0.059302 |
| 300 | sqrt | 1 | 16 | balanced_subsample | 0.924767 ± 0.059302 |
| 300 | sqrt | 2 | None | balanced_subsample | 0.923381 ± 0.059917 |
| 300 | sqrt | 2 | 16 | balanced_subsample | 0.923381 ± 0.059917 |
| 300 | 0.3 | 1 | None | balanced_subsample | 0.906865 ± 0.083222 |
| 300 | 0.3 | 1 | 16 | balanced_subsample | 0.906865 ± 0.083222 |
| 300 | 0.3 | 4 | None | balanced_subsample | 0.869769 ± 0.148538 |
| 300 | 0.3 | 4 | 16 | balanced_subsample | 0.869769 ± 0.148538 |
| 300 | 0.3 | 2 | None | balanced_subsample | 0.868792 ± 0.147240 |
| 300 | 0.3 | 2 | 16 | balanced_subsample | 0.868792 ± 0.147240 |
| 300 | 0.3 | 4 | None | None | 0.867076 ± 0.153041 |
| 300 | 0.3 | 4 | 16 | None | 0.867076 ± 0.153041 |
| 300 | 0.3 | 2 | None | None | 0.865323 ± 0.151543 |
| 300 | 0.3 | 2 | 16 | None | 0.865323 ± 0.151543 |
| 300 | 0.3 | 1 | None | None | 0.862536 ± 0.148603 |
| 300 | 0.3 | 1 | 16 | None | 0.862536 ± 0.148603 |
| 300 | sqrt | 4 | None | None | 0.859913 ± 0.163548 |
| 300 | sqrt | 4 | 16 | None | 0.859913 ± 0.163548 |
| 300 | sqrt | 2 | None | None | 0.857388 ± 0.162653 |
| 300 | sqrt | 2 | 16 | None | 0.857388 ± 0.162653 |
| 300 | sqrt | 1 | None | None | 0.853983 ± 0.162290 |
| 300 | sqrt | 1 | 16 | None | 0.853983 ± 0.162290 |

OOB trên tập train (ước lượng, không thay test): 0.981793

## Buổi test giữ riêng

| Model | Accuracy | Macro-F1 |
| --- | ---: | ---: |
| selected | 0.974702 | 0.974713 |
| dummy | 0.250000 | 0.100000 |
| compare (har_runs\uci_rf_tuned_01) | 0.251488 | 0.105609 |

## Selected model per-class metrics

| Label | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| walk | 0.963636 | 0.946429 | 0.954955 | 168 |
| sit | 0.988024 | 0.982143 | 0.985075 | 168 |
| stand | 0.947674 | 0.970238 | 0.958824 | 168 |
| lie | 1.000000 | 1.000000 | 1.000000 | 168 |

## Confusion matrix (hàng thật, cột dự đoán)

| True / predicted | walk | sit | stand | lie |
| --- | ---: | ---: | ---: | ---: |
| walk | 159 | 0 | 9 | 0 |
| sit | 3 | 165 | 0 | 0 |
| stand | 3 | 2 | 163 | 0 |
| lie | 0 | 0 | 0 | 168 |

## Độ chính xác theo từng phiên test

| Phiên | Nhãn | Cửa sổ | Accuracy |
| --- | --- | ---: | ---: |
| 20261014T042223Z-e1354d0d | walk | 84 | 0.940476 |
| 20261014T042452Z-4c72e587 | sit | 84 | 0.964286 |
| 20261014T042734Z-e2078589 | stand | 84 | 1.000000 |
| 20261014T043015Z-c926a3f4 | lie | 84 | 1.000000 |
| 20261014T043243Z-65b2ae69 | walk | 84 | 0.952381 |
| 20261014T043522Z-22a220b4 | sit | 84 | 1.000000 |
| 20261014T043804Z-11560071 | stand | 84 | 0.940476 |
| 20261014T044016Z-14a8c400 | lie | 84 | 1.000000 |

Macro-F1 target >=0.85: **True**.
Better than Dummy on test: **True**.

## Warnings

