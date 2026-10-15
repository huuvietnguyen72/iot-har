# Tiêu chí nghiệm thu bước 2 — Wi-Fi 50 Hz, pin dự phòng, đeo ở eo

## 1. Phạm vi và trạng thái

Áp dụng cho thiết kế `2026-10-10-mpu6050-wifi-collector-design.md` cùng thư mục.
Đây là bộ tiêu chí cần đạt sau triển khai, không phải báo cáo đã nghiệm thu.
Source hiện tại mới có collector USB; các lựa chọn TCP/discovery trong thiết kế
chưa phải lệnh có thể dùng ngay.

Mục tiêu: ESP32 + MPU6050 dùng pin dự phòng, truyền 50 Hz tới Pi4 đặt cố định,
lưu dữ liệu đúng khi dùng Wi-Fi nhà và hotspot iPhone 12, sau đó thử đeo ở eo.
Các ngưỡng bổ sung dưới đây là tiêu chí kỹ thuật của project, không phải chứng
nhận độ chính xác cảm biến hoặc đánh giá mô hình nhận diện hoạt động.

## 2. Điều kiện trước khi đo

- Pi4 dùng nguồn USB-C; ESP32 dùng pin dự phòng trong phép thử nguồn và đeo.
- Không có dây USB truyền dữ liệu từ ESP32 tới Pi4 trong phép thử Wi-Fi.
- ESP32 và Pi4 cùng mạng 2.4 GHz. Hotspot iPhone bật Maximize Compatibility.
- Ghi phiên bản firmware/collector hoặc SHA-256 các artifact, loại mạng,
  endpoint, cấu hình cảm biến, nguồn cấp và vị trí thử; không ghi mật khẩu.
- Calibration hoàn tất khi giữ cảm biến yên. Duration chỉ tính từ DATA hợp lệ đầu.
- Tất cả phiên dùng label `test`. Ghi chú thao tác và thời điểm gây lỗi riêng.
- Tách phiên bình thường với phiên cố tình gây lỗi; không chấm phiên reset hoặc
  mất Wi-Fi bằng yêu cầu zero-loss của một phiên bình thường.
- Phiên thất bại phải giữ bằng chứng. Sau sửa lỗi, chạy lại nhóm bị ảnh hưởng;
  không xóa phiên lỗi để chỉ trình bày các lần đạt.

## 3. Chuẩn chung cho một phiên thu sạch

Gọi N là số hàng CSV không tính header và T là thời lượng yêu cầu, đơn vị giây.

| Hạng mục | Điều kiện đạt |
| --- | --- |
| Kết thúc | `status=completed`, exit code 0 |
| Đường truyền | Metadata `transport=tcp`, endpoint đúng ESP32 được thử |
| Tốc độ | 49–51 Hz theo timestamp thiết bị, không dùng timestamp nhận trên Pi |
| Công thức | `(N - 1) / ((time_last_us - time_first_us) / 1000000)` |
| Số mẫu | `49*T <= N <= 51*T` |
| Thời gian thiết bị | `T - 1 <= device_span_s <= T + 1` |
| Nhịp mẫu | Timestamp tăng nghiêm ngặt; `max_gap_us <= 40000`, `gaps_over_40ms=0` |
| Liên tục | `missing_by_seq=duplicates=out_of_order=timestamp_errors=0` |
| Định dạng | `data_errors=oversize_lines=telemetry_errors=0`; số đo đều hữu hạn |
| CSV | Đúng 13 cột, N khớp `samples_written`; không có hàng log |
| Phiên/stream | Một session_id, một stream_id, một label; khớp JSON |
| Host elapsed | Mẫu đầu bằng 0; tăng không giảm, có thể trùng do nhận cùng chunk |
| Bộ đếm firmware | Có snapshot đầu/cuối cùng stream; không tăng queue_dropped_total hoặc unobserved_total giữa hai snapshot |
| Tính nhất quán | Tính lại seq gap, time gap, span và rate từ CSV khớp JSON |

Sai số đối chiếu do làm tròn: span tối đa 0.000001 giây, rate tối đa 0.001 Hz.
Seq đầu phiên có thể khác 0 nếu ESP32 đã phát từ trước. Bộ đếm firmware tuyệt
đối khác 0 từ trước phiên không làm phiên này thất bại; chấm mức tăng trong phiên.
Thiếu snapshot thì kết luận thiếu bằng chứng bộ đếm, không coi null là 0.

| T yêu cầu | Khoảng N được chấp nhận | Khoảng device_span_s |
| --- | --- | --- |
| 60 giây | 2940–3060 | 59–61 giây |
| 300 giây (5 phút) | 14700–15300 | 299–301 giây |
| 600 giây (10 phút) | 29400–30600 | 599–601 giây |

Không dùng rate đạt để bỏ qua gap: trung bình 50 Hz vẫn có thể chứa khoảng ngừng
hoặc mẫu dồn. TCP gom mẫu khi nhận là hợp lệ nếu timestamp thiết bị vẫn đúng.
Snapshot firmware cuối chỉ phản ánh lần quan sát cuối; không chứng minh không
mất mẫu ngoài phần được quan sát hoặc rằng mọi byte đã gửi đều được Pi lưu.

## 4. Ma trận nghiệm thu bắt buộc

### AC-01 — Build, regression và hợp đồng phần mềm

- Build thành công cả bản USB và Wi-Fi trên môi trường PlatformIO của project.
- Chạy executable C++ stream/calibration và tests mới cho bộ đệm; exit code 0.
- Chạy toàn bộ tests Python cũ và mới trên laptop và Python 3.11 của Pi4; không
  có failure/error. Số test phải ghi theo lần chạy thật, không mặc định 53.
- Test TCP bằng socket loopback thật: chia/gộp chunk, timeout không phải EOF,
  partial write, FIN/RST, NET lỗi, stream đổi, lỗi file và deadline trong chunk.
- Test discovery 0/1/nhiều thiết bị; không chọn ngẫu nhiên khi có nhiều ESP32.
- USB vẫn mở cổng với DTR/RTS=False, POSIX exclusive; có phiên USB smoke 60 giây
  sau thay đổi phần chung, đạt các mục tương ứng của chuẩn sạch (không yêu cầu NET).
- Bằng chứng: lệnh, exit code, log build/tests và CSV/JSON USB smoke.

### AC-02 — Wi-Fi nhà và hotspot iPhone đều thu được

- Mỗi mạng chạy 3 phiên sạch liên tiếp, mỗi phiên 60 giây trên bàn.
- Cả 6 phiên phải đạt toàn bộ chuẩn sạch ở mục 3. Lần đầu trên mỗi mạng bắt đầu
  sau power-on ESP32 để kiểm tra boot, calibration và kết nối thực tế.
- Kiểm tra khám phá tự động trên từng mạng. Nếu mạng chặn mDNS nhưng TCP qua IP
  hoạt động, cho phép đạt truyền dữ liệu với điều kiện ghi rõ cách nhập IP trên mạng đó.
- Chức năng discovery vẫn phải có ít nhất một phép thử mạng thật hỗ trợ multicast
  và các test phần mềm AC-01. Không tự kết luận mDNS bị chặn chỉ từ một lần timeout.
- Nếu ESP32/Pi4 không trao đổi TCP trực tiếp được qua hotspot: AC-02 chưa đạt,
  không dùng phiên Wi-Fi nhà để thay thế.
- Bằng chứng: 6 cặp CSV/JSON, kết quả discovery/IP, tên loại mạng và setup thực tế.

### AC-03 — Đổi mạng không cần nạp lại firmware

- Thử một vòng nhà -> hotspot -> nhà. Sau cấu hình ban đầu, không sửa/nạp firmware
  hoặc ghi IP cố định vào source để thực hiện vòng chuyển này.
- Khi không có mạng nhà, ESP32 thử hotspot theo chính sách 10 giây/lần thử,
  chờ 3 giây sau vòng thất bại. Xác minh bằng test điều khiển thời gian và log.
- Pi4 có profile cả hai mạng; xác nhận thực tế cả hai thiết bị vào cùng mạng
  trước khi chạy collector. Giữ mạng đang hoạt động ổn định, không cưỡng bức roam
  chỉ vì xuất hiện mạng ưu tiên cao hơn.
- Tại mỗi chặng mới chạy một phiên sạch 60 giây; được dùng phiên này trong AC-02
  nếu đúng điều kiện và được ghi rõ ID phiên.
- Kết nối TCP có timeout 5 giây; discovery 5 giây khi không thấy thiết bị.
  Không yêu cầu DHCP/hotspot của môi trường luôn hoàn tất trong đúng 5 giây.
- Bằng chứng: hash firmware trước/sau giống nhau, log kết nối và ID phiên từng mạng.

### AC-04 — Pin dự phòng hoạt động ổn định

- ESP32 dùng pin dự phòng USB, không dùng nguồn từ laptop/Pi4; Pi4 vẫn dùng USB-C.
- Chạy 10 phút trên bàn cho mỗi loại mạng: 2 phiên, mỗi phiên đạt chuẩn sạch.
- Không reset/brownout/watchdog, không tự ngắt pin, không calibration lại giữa phiên;
  một stream_id xuyên suốt mỗi phiên.
- Bằng chứng: ảnh/sơ đồ nguồn, loại pin dự phòng, 2 cặp CSV/JSON và log chẩn đoán.
- Kết quả chỉ chứng minh thời gian đã thử; không suy ra pin dùng được cả ngày.

### AC-05 — Đeo ở eo và đi lại trong vùng thử

- Gắn cố định MPU6050 và ESP32; dây không tuột, cảm biến không đổi vị trí gắn hoặc
  hướng trục giữa phiên. Ghi vị trí trên eo, hướng trục, cách cố định và nguồn cấp.
- Mỗi mạng chạy một phiên 5 phút: đứng yên 30 giây, đi bộ bình thường 240 giây,
  đứng yên 30 giây cuối. Không lắc mạnh có chủ ý để thay thế phép thử đi bộ.
- Cả hai phiên đạt chuẩn sạch; không có reset, mất nguồn hoặc mất kết nối.
- Ghi tuyến đường, khoảng cách xa nhất ước lượng tới router/iPhone, vật cản và
  nơi đặt iPhone. Kết luận phạm vi hoạt động chỉ áp dụng vùng đó.
- Tính thống kê từng trục và rà dấu hiệu gần/chạm thang đo; báo kết quả và giới
  hạn kiểm chứng. Với gyro đã trừ bias, phải biết bias để đối chiếu giới hạn raw.
- Nếu không có raw/bias cần thiết, ghi chưa xác nhận được clipping; không suy từ
  độ lớn vector >250 dps hoặc >2 g rằng từng trục đã bão hòa.
- Clipping không tự làm giao thức truyền thất bại, nhưng là vấn đề cần xử lý trước
  dữ liệu huấn luyện. Không gọi dữ liệu là sẵn sàng ML khi chưa đánh giá điểm này.
- Bằng chứng: 2 cặp CSV/JSON, ghi chú vị trí/trục/tuyến đường, báo cáo chất lượng
  và thang đo; label vẫn là `test`.

### AC-06 — Phản ứng chuyển động và trở về trạng thái đứng yên

- Thử một phiên 40 giây trên Wi-Fi sau calibration: yên 10 giây, xoay nhẹ qua lại
  20 giây, đặt yên 10 giây cuối. Ghi mốc thao tác tương đối từ mẫu đầu.
- Phiên đạt chuẩn sạch; có ít nhất một trục gyro đổi dấu khi đảo chiều xoay.
- Trong đoạn xoay, đỉnh độ lớn gyro >=10 dps để chứng minh đã thực sự tạo chuyển động.
- Trong 5 giây cuối khi đã đặt yên: trung bình độ lớn gyro <=2 dps và trị tuyệt
  đối trung bình mỗi trục <=1 dps. Tính đoạn bằng device_time_us, không dựa vào
  mốc progress hoặc thời gian gói tới Pi.
- Gia tốc thay đổi khi nghiêng, nhưng không yêu cầu độ lớn đúng 1.000 g vì gia tốc
  chưa hiệu chỉnh. Không đổi cấu hình cảm biến chỉ để ép kết quả đạt.
- Bằng chứng: CSV/JSON, mốc thao tác và thống kê các cửa sổ yên/xoay/yên.

### AC-07 — Lỗi, ngắt phiên và phục hồi đúng

Thực hiện từng phép thử riêng sau khi đã ghi ít nhất 10 giây. Không áp dụng yêu
cầu đủ số mẫu hoặc zero-error của phiên sạch cho phần cố tình gây gián đoạn.

| Tác động | Điều kiện đạt |
| --- | --- |
| Ctrl+C trên collector | `interrupted`, mã 130; finalize một lần, giữ CSV/JSON |
| Tắt Wi-Fi/hotspot đang dùng | `connection_lost` mã 5 nếu socket báo ngắt; hoặc `no_data` mã 3 nếu socket im lặng; không báo completed |
| Nhấn EN/RST trên ESP32 | Phiên cũ kết thúc `connection_lost`/`no_data`; nếu nhận DATA stream mới trước khi kết thúc thì `stream_changed` mã 4; không ghi stream mới vào CSV cũ |
| Rút USB cấp nguồn ESP32 | `connection_lost` hoặc `no_data`, giữ dữ liệu trước ngắt; đây là ngắt nguồn, không phải rút USB serial trên Pi |
| Kết nối client thứ hai | Client thứ hai bị từ chối/đóng; phiên client đầu tiếp tục sạch |
| Khôi phục mạng/nguồn rồi chạy lại | Tệp mới, session_id mới, không gửi lại backlog phiên cũ; phiên sạch 60 giây sau phục hồi |

- Thử mất mạng trên cả hai loại mạng. Reset, ngắt nguồn, SIGINT và client thứ hai
  cần ít nhất một lần trên phần cứng thật; các trạng thái còn lại có test phần mềm.
- TCP read timeout 50 ms không kết thúc phiên. `no_data` xảy ra sau 3 giây từ
  mẫu hợp lệ cuối, chấp nhận tối đa 0.5 giây trễ xử lý trong phép thử bình thường.
  Mốc tính không phải thời điểm bấm nút: dữ liệu TCP đã đệm có thể còn được nhận.
- Kiểm tra deadline bằng fake clock đúng 3 giây và log monotonic trên Pi khi thử thật.
- Có thể xuất hiện DATA lỗi khi bản ghi bị cắt lúc reset. Phải đếm, bỏ dòng lỗi
  và giữ những hàng hợp lệ; không mặc định bất kỳ `data_errors=1` nào cũng do reset
  nếu thiếu raw log để xác nhận nguyên nhân.
- Sau phục hồi, seq/stream đúng quy tắc: Wi-Fi reconnect không tự reset seq/stream;
  ESP32 reboot/calibration lại thì stream_id mới. CSV không trộn hai stream.
- Bằng chứng: timestamp tác động, log/exit code thật, CSV/JSON trước và sau lỗi.
  Khi dùng `timeout` để gửi SIGINT phải tách mã của wrapper khỏi mã của collector.

### AC-08 — Nghẽn mạng không chặn lấy mẫu hoặc che mất dữ liệu

- Test bộ đệm bằng đầu vào có số mẫu biết trước: capacity=100; thêm mẫu thứ 101
  bỏ đúng mẫu cũ nhất và tăng queue_dropped_total đúng 1; thứ tự mẫu còn lại đúng.
- Không có client: seq tiếp tục tăng theo frame hợp lệ; tăng unobserved_total,
  không tích lũy backlog để đẩy sang phiên sau.
- Thử client chậm để thực sự tạo backpressure; ghi số byte gửi/queue occupancy
  để xác nhận đã nghẽn. Chỉ tạm ngừng đọc trong thời gian ngắn chưa chứng minh
  nghẽn, vì TCP có thể vẫn chứa dữ liệu trong bộ đệm hệ điều hành.
- Sampling trên ESP32 vẫn 49–51 Hz, không gap >40 ms do việc gửi mạng, không
  watchdog; đo qua chẩn đoán tác vụ lấy mẫu, không suy ra từ CSV vốn bị mất mẫu.
- Queue không vượt 100 mẫu; bản ghi đang gửi dở và bộ đệm socket có giới hạn riêng.
  Không cấp phát bộ đệm tăng vô hạn, không nối hai bản ghi vào một dòng hỏng.
- Mất tiến triển gửi 3 giây -> firmware đóng client; test deadline bằng clock
  điều khiển được. Sampling vẫn tiếp tục sau khi đóng kết nối.
- Mẫu bỏ phải xuất hiện trong bộ đếm firmware; seq gap trong phần nhận được phải
  được collector đếm. Không yêu cầu hai bộ đếm bằng nhau và không cộng trùng.
- Khi stream/client đổi, snapshot và backlog cũ không được gắn sang phiên mới.
- Bằng chứng: tests bộ đệm/partial-write, log thử backpressure trên ESP32 thật,
  snapshot bộ đếm và phiên sạch sau phục hồi.

## 5. Hồ sơ bằng chứng và cách chấm cuối cùng

Lưu một bảng ghi nhận với các cột:

```text
acceptance_id | network | artifact_version | session_id | csv_path | json_path
log_path | operator_action | observed_result | PASS/FAIL/BLOCKED | limitation
```

- Mỗi dòng PASS phải có bằng chứng tương ứng, không chỉ ảnh dòng `rate=50.0`.
- Lưu log đầy đủ, không cắt đầu log vì có thể bỏ mất lỗi boot/calibration.
- Dùng timestamp thiết bị cho nhịp mẫu và timestamp monotonic host cho timeout.
  Giờ UTC trong tên file là thời gian lưu trữ; không dùng để suy ra độ trễ mạng.
- Nghiệm thu bước 2 đầy đủ khi AC-01 đến AC-08 đều PASS, cả A và B có bằng chứng
  truyền thật, nguồn/đeo đạt trong vùng thử. Ghi riêng giới hạn discovery theo mạng.
- Thiếu mạng, pin, thao tác tay hoặc log cần thiết -> BLOCKED/chưa nghiệm thu mục
  đó, không dùng test giả lập để thay bằng kết quả thiết bị thật.
- Nếu chỉ đạt mạng nhà thì kết luận đạt trên mạng nhà, chưa đạt trọn bước 2.
- Việc thu đúng 50 Hz không chứng minh độ trễ thấp, độ chính xác cảm biến, hiệu quả
  chống aliasing hoặc độ chính xác AI. Các nội dung đó có tiêu chí riêng ở bước ML.

Thứ tự chạy: AC-01 -> AC-02/03 -> AC-07/08 -> AC-04 -> AC-06 -> AC-05.
Có thể dùng chung bằng chứng khi cùng phiên đáp ứng đủ điều kiện của nhiều mục;
không dùng phiên cố tình gây lỗi thay cho phiên sạch.
