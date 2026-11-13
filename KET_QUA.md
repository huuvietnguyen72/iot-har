# Kết quả của mô hình mẫu

Đây là số liệu của mô hình mẫu `har_runs/own_rf_01` đi kèm repo, huấn luyện từ dữ liệu mẫu
`data/har_own`. Nếu bạn huấn luyện mô hình của mình (README, mục 7), `har train-own` sinh ra một
`report.md` tương tự trong thư mục mô hình mới.

## Dữ liệu

- Một người đeo, một cách đeo: hông phải, mặt chip MPU6050 hướng ra ngoài.
- Buổi train ngày 13/10/2026: 17 phiên × 120 s. Buổi test ngày 14/10/2026: 8 phiên × 120 s
  (2 phiên mỗi hoạt động). Hai buổi khác ngày, nên test không lẫn dữ liệu của buổi train.
- Cửa sổ 128 mẫu (2,56 s), bước 64 mẫu; 70 đặc trưng thống kê.

## Độ chính xác trên buổi test

| Mô hình | Accuracy | Macro-F1 |
| --- | ---: | ---: |
| Random Forest (mô hình mẫu) | 0,975 | **0,975** |
| Dummy (luôn đoán một lớp) | 0,250 | 0,100 |
| Random Forest huấn luyện trên UCI HAR (smartphone), chấm trên dữ liệu MPU6050 | 0,251 | 0,106 |

| Hoạt động | Precision | Recall | F1 | Số cửa sổ |
| --- | ---: | ---: | ---: | ---: |
| walk | 0,964 | 0,946 | 0,955 | 168 |
| sit | 0,988 | 0,982 | 0,985 | 168 |
| stand | 0,948 | 0,970 | 0,959 | 168 |
| lie | 1,000 | 1,000 | 1,000 | 168 |

Ma trận nhầm lẫn (hàng: thật, cột: dự đoán):

| | walk | sit | stand | lie |
| --- | ---: | ---: | ---: | ---: |
| walk | 159 | 0 | 9 | 0 |
| sit | 3 | 165 | 0 | 0 |
| stand | 3 | 2 | 163 | 0 |
| lie | 0 | 0 | 0 | 168 |

Cấu hình được chọn bằng cross-validation 4 fold trên buổi train (macro-F1 CV 0,929 ± 0,054):
`n_estimators=300, max_features=sqrt, min_samples_leaf=4, max_depth=None,
class_weight=balanced_subsample`.

Mô hình huấn luyện trên dữ liệu công khai UCI HAR đạt macro-F1 0,931 trên tập test của UCI, nhưng
chỉ 0,106 trên dữ liệu MPU6050, gần bằng Dummy. Lý do là hệ trục và cách gắn của smartphone khác
MPU6050, nên dự án phải tự thu dữ liệu.

## Tốc độ suy luận

Thời gian trích đặc trưng và dự đoán một cửa sổ, 200 lần đo:

| Máy | Trung vị | p95 |
| --- | ---: | ---: |
| Raspberry Pi 4 | 40 ms | 41 ms |
| Laptop (Windows 11) | 5 ms | 7 ms |

Cả hai đều dưới ngưỡng 1,28 s (mỗi kết luận mới cách nhau 64 mẫu).

## Truyền dữ liệu

Phiên 60 s qua Wi-Fi, ở cả mạng nhà và hotspot iPhone, đạt 50 Hz, không mất mẫu. ESP32 tự chuyển
sang hotspot khi mạng nhà mất.

## Giới hạn

- Dữ liệu của **một người**, **một cách đeo**; chưa kiểm chứng trên người khác hay hướng đeo khác.
- Buổi test chỉ có 2 phiên mỗi hoạt động, nên con số trên còn dao động nhiều.
- Mô hình mẫu chưa có lớp lên/xuống cầu thang: dữ liệu mẫu thu trước khi có BMP280. Phần mềm đã
  hỗ trợ (README, mục 8), nhưng cần thu dữ liệu cầu thang có áp suất rồi huấn luyện lại.
- Nhận diện cầu thang trên ESP32 và phát hiện nghi té dùng ngưỡng ước tính, chưa được kiểm chứng
  trên dữ liệu thật.
- Phần bộ đeo (nút, LED, còi, pin, OLED, BMP280) chưa chạy trên mạch thật.
