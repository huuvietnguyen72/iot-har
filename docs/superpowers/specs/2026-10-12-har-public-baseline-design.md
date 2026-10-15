# Bước 3A — Pipeline HAR và baseline bằng dữ liệu công khai

## 1. Phạm vi đã thống nhất

Người dùng chọn triển khai bước 3A trong khi AC-04 (nguồn di động) và AC-05
(đeo ở eo) của bước 2 tạm hoãn. Thiết kế dùng UCI HAR và mô hình Random Forest,
huấn luyện trên laptop và thử suy luận trên Pi4. (Bản đầu so sánh thêm Logistic
Regression; người dùng đã chốt chuyển sang Random Forest để khớp tài liệu đối chiếu.)

Đầu ra là mô hình baseline thật, báo cáo đánh giá và pipeline tái lập được trên
dữ liệu công khai. Không đánh đồng kết quả này với độ chính xác trên MPU6050 của
project. Dữ liệu `test` trên bàn hiện có không được gán nhãn hoạt động người.

Không thay firmware, collector hoặc yêu cầu phần cứng trong bước 3A. Chưa làm
nhận diện trực tiếp trên stream, giao diện MotionSense, hoặc nhận diện cầu thang.

## 2. Dữ liệu và nguồn

- UCI Human Activity Recognition Using Smartphones, DOI 10.24432/C54S4K.
- Nguồn: https://archive.ics.uci.edu/dataset/240/human+activity+recognition+using+smartphones
- Archive: https://archive.ics.uci.edu/static/public/240/human+activity+recognition+using+smartphones.zip
- Giấy phép CC BY 4.0; giữ README, attribution và citation nguồn trong tài liệu.
- 30 người, Samsung Galaxy S II gắn ở eo, gia tốc và gyro 50 Hz. Không khẳng định
  điện thoại này dùng MPU6050.
- Dữ liệu tín hiệu được lọc và chia sẵn cửa sổ 128 mẫu (2.56 giây), chồng lấn 50%.
  Không gọi chúng là raw liên tục chưa xử lý; không ghép các cửa sổ rồi cắt lại.
- Chỉ dùng bốn lớp: UCI 1 -> `walk`, 4 -> `sit`, 5 -> `stand`, 6 -> `lie`.
  Loại lớp 2/3 (cầu thang) khỏi lần thực nghiệm này, ghi số cửa sổ bị loại.
- MotionSense chưa chọn: vị trí túi quần và không có lớp nằm nên không đủ bốn lớp.

Tín hiệu mỗi split lấy từ `train/Inertial Signals/` hoặc `test/Inertial Signals/`:

```text
total_acc_x_<split>.txt, total_acc_y_<split>.txt, total_acc_z_<split>.txt
body_gyro_x_<split>.txt, body_gyro_y_<split>.txt, body_gyro_z_<split>.txt
y_<split>.txt, subject_<split>.txt
```

Mỗi hàng tín hiệu có 128 giá trị; số hàng của sáu file tín hiệu, nhãn và subject
phải khớp. Đọc nhãn/subject bằng integer, kiểm tra hữu hạn và đúng shape trước train.
Không dùng bộ 561 đặc trưng có sẵn để thay cho pipeline đặc trưng của project.

Lưu archive/dữ liệu ngoài source dưới thư mục riêng cho ML, không trộn vào `data/`
đang chứa phiên collector. Download có timeout, báo tiến độ, dùng file tạm rồi
rename khi hoàn tất; kiểm tra ZIP, không giải nén đường dẫn vượt thư mục đích.
Ghi URL và SHA-256 archive thực tế trong manifest. Cache chỉ tái dùng khi checksum
khớp manifest; không suy đoán checksum trước khi tải.

## 3. Dạng dữ liệu thống nhất

- Một cửa sổ có shape `(128, 6)`, thứ tự `ax, ay, az, gx, gy, gz`.
- Gia tốc đơn vị g, giữ trọng lực; gyro đơn vị rad/s để khớp UCI.
- Dữ liệu collector sau này có gyro dps thì đổi bằng `dps * pi / 180`.
- Nguồn UCI đã có window nên lưu subject, split và row index, không tạo timestamp
  phần cứng giả. Nguồn collector dùng device_time_us, session_id và stream_id thật.
- Không chuẩn hóa từng cửa sổ bằng cách trừ trung bình gia tốc: làm mất tín hiệu
  hướng trọng lực hữu ích cho ngồi/đứng/nằm. Scaler học trên feature của tập train.
- Không suy ra hướng gắn smartphone giống MPU6050. Đây là khác biệt miền dữ liệu
  phải được đánh giá khi có dữ liệu đeo thực tế.

## 4. Đặc trưng và ranh giới pipeline

Từ sáu trục, thêm độ lớn vector gia tốc và gyro thành tám kênh. Với mỗi kênh
tính tám đặc trưng theo cùng thứ tự: mean, std (ddof=0), min, max, median, RMS,
mean absolute value, IQR (percentile 75 - percentile 25). Tổng 64 đặc trưng.

Thêm sáu tương quan: ax/ay, ax/az, ay/az, gx/gy, gx/gz, gy/gz. Kênh hằng có
độ lệch chuẩn bằng 0 thì tương quan định nghĩa là 0 để tránh NaN. Tổng 70 đặc trưng.
Lưu tên và thứ tự feature cùng model; reject input sai shape hoặc không hữu hạn.

Thiết kế tách các phần: tải/kiểm tra dữ liệu, adapter, feature extraction, split,
train/evaluate, lưu artifact, predict và benchmark. Các phép biến đổi dùng cùng
hàm khi train và predict, không có hai bản feature extraction khác nhau.

Adapter collector phục vụ kiểm tra đường suy luận với CSV hiện có. Cắt cửa sổ
128 mẫu, stride 64, không vượt session/stream hoặc đoạn có seq gap/timestamp
không tăng/gap >40 ms. Ghi số cửa sổ bị loại, không nội suy bù mẫu trong bước này.
Chỉ CSV này không đủ suy ra subject: dữ liệu thu có nhãn sau này cần manifest
subject/session riêng. Label `test` phải bị loại khỏi việc huấn luyện có giám sát.

## 5. Chia dữ liệu để tránh rò rỉ

- Giữ nguyên test chính thức của UCI làm test cuối; không dùng để chọn model,
  feature, seed hoặc tham số.
- Chọn cấu hình bằng **cross-validation theo người (GroupKFold, n_splits=5) trên
  tập train chính thức**: mỗi fold giữ nguyên người; không trộn cửa sổ của một
  người giữa train và test của fold.
- Kiểm tra train và test chính thức không giao subject; mỗi fold train có đủ bốn lớp.
  Nếu không đạt thì báo lỗi, không âm thầm chia lại bằng random windows.
- Hai cửa sổ chồng lấn của một người không được nằm ở hai phía của một fold.
- Chọn cấu hình theo macro-F1 trung bình CV (kèm độ lệch chuẩn), rồi refit đúng cấu
  hình đó trên toàn bộ train chính thức và chấm test cuối đúng một lần.

## 6. Mô hình và chọn cấu hình

Mô hình là Random Forest. Thay vì một cấu hình cố định, dùng một **lưới nhỏ khai báo
trước** và chọn bằng cross-validation theo người trên tập train (không dùng test):

```text
n_estimators = 300
max_features = {sqrt, 0.3}
min_samples_leaf = {1, 2, 4}
max_depth = {None, 16}
class_weight = {None, balanced_subsample}
```

- Chọn cấu hình theo macro-F1 trung bình CV cao nhất; bằng nhau trong 1e-6 thì chọn
  cấu hình đơn giản hơn (ít ràng buộc: không giới hạn độ sâu, min_samples_leaf nhỏ,
  không cân bằng lớp, max_features=sqrt), rồi theo thứ tự khóa ổn định.
- Refit cấu hình đã chọn với `random_state=42`, `n_jobs=-1`, `oob_score=True`.
- OOB chỉ là ước lượng trên tập train, hiển thị riêng, không thay thế chỉ số test.
- DummyClassifier(strategy="most_frequent") làm mốc; không bao giờ được chọn.

Không chỉnh tham số dựa trên test và không chấm nhiều cấu hình trên test rồi chọn lại.
Test cuối chỉ chấm cấu hình đã chọn và Dummy. Ghi thời gian train; không tune trên
test để làm kết quả đẹp hơn.

## 7. Đánh giá và đầu ra

- Accuracy, macro-F1, precision/recall/F1/support từng lớp và confusion matrix
  theo thứ tự `walk, sit, stand, lie`. Confusion matrix ghi rõ hàng là nhãn thật.
- Báo kết quả cross-validation của lưới Random Forest (mean ± std) và lựa chọn; test
  cuối chỉ dùng cấu hình đã chọn và Dummy, không chấm lại rồi chọn theo test.
- Báo cáo JSON máy đọc được và Markdown người đọc được, không điền số liệu giả.
- Artifact: estimator/pipeline, config cấu hình đã chọn, feature names, label mapping,
  đơn vị, sample rate, window/stride, manifest dữ liệu, kết quả CV, phiên bản Python,
  NumPy/scikit-learn và seed. Phiên chạy có thư mục riêng, không ghi đè phiên cũ.
- Kiểm thử save/reload model cho dự đoán giống nhau trên cùng cửa sổ.
- CLI có các thao tác riêng cho prepare, train, predict-CSV và benchmark.
  Không tự tải dataset hoặc train khi người dùng chỉ import package.

## 8. Môi trường và Pi4

- Package ML riêng trong project, ví dụ `har/`, không thêm dependency ML bắt
  buộc vào collector. Dùng NumPy, scikit-learn và joblib; không cần GPU/deep learning.
- Môi trường ảo riêng trên laptop; Pi4 dùng Python 3.11. Cố định phiên bản tương
  thích cả hai môi trường, ghi chúng vào requirements và artifact.
- Chạy tests pipeline trên laptop và Pi4; chuyển model đã train sang Pi4 để
  suy luận, không bắt buộc Pi4 huấn luyện hai model.
- Benchmark gồm feature extraction và predict một cửa sổ (không gồm đọc đĩa),
  dùng monotonic clock, 10 lần warm-up, 200 lần đo; báo median và p95.
- Thời gian p95 <1.28 giây (stride 64 ở 50 Hz) là điều kiện tốc độ để sẵn sàng
  cho một bước suy luận trực tiếp sau này. Ghi đúng model/cấu hình threads khi đo.

## 9. Tiêu chí nghiệm thu bước 3A

1. Download có manifest/checksum; shape, nhãn, đơn vị và attribution kiểm chứng.
2. Test feature/window/group CV/invalid input/save-reload đạt; regression
   collector không bị ảnh hưởng. Các tests hành vi không chỉ mô phỏng model.
3. Thực nghiệm thực trên UCI hoàn tất, đủ bốn lớp, không giao subject. Báo kết quả
   GroupKFold của lưới và Dummy; test cuối chỉ chấm cấu hình đã chọn và Dummy.
4. Cấu hình chọn phải tốt hơn Dummy trên macro-F1 test cuối để gọi baseline hữu ích.
   Nếu không tốt hơn, báo kết quả chưa đạt, không tune trên test.
5. Macro-F1 test >=0.85 là mục tiêu chất lượng ban đầu, không phải kết quả được
   hứa trước. Nếu thấp hơn, vẫn giao báo cáo trung thực và ghi mục tiêu chưa đạt;
   thay đổi thiết kế cần phiên thực nghiệm mới, không thay split để tăng điểm.
6. Artifact reload dự đoán nhất quán; benchmark Pi4 đạt p95 <1.28 giây.
7. CSV collector nhãn `test` chỉ dùng kiểm tra đọc/window/predict, không dùng làm
   accuracy/nhãn thật, không kết luận mô hình nhận diện hoạt động đúng trên người.

## 10. Việc sau bước 3A

Khi có nguồn di động, hoàn tất AC-04/05, thu `walk/sit/stand/lie` với nhãn thật,
subject và session rõ ràng, rồi kiểm định/học lại bằng pipeline này. Kiểm tra
clipping từng trục, hướng gắn, bias gia tốc và lọc chống aliasing trước kết luận
dữ liệu phù hợp ML. Không cần smartphone dataset cùng chip mới làm baseline được,
nhưng không lấy điểm UCI để suy ra điểm MPU6050.

Nguồn phương pháp tránh leakage:
https://scikit-learn.org/stable/common_pitfalls.html

Không commit/push hoặc tự tạo Git; bảo toàn dữ liệu/source hiện có. Người dùng
đã duyệt đặc tả trong hội thoại ngày 2026-10-12. Kế hoạch triển khai:
[`../plans/2026-10-12-har-public-baseline.md`](../plans/2026-10-12-har-public-baseline.md).
