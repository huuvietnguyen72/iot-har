# Bước 2 — Bộ thu MPU6050 Wi-Fi 50 Hz và thử đeo ở eo

## 1. Trạng thái và căn cứ

Thiết kế tổng thể đã được người dùng đồng ý trong hội thoại. Văn bản này cụ thể
hóa các quyết định để người dùng duyệt trước khi lập kế hoạch triển khai.

Căn cứ: source hiện tại và kết quả thử bước 1. Firmware USB đã
có phiên 60 giây trên Pi4: 3002 mẫu, 50.0 Hz, các bộ đếm chất lượng đều bằng 0.
Đã thử SIGINT và reset giữa phiên. Thử rút USB giữa phiên chưa thực hiện.
Các kết quả đó là bằng chứng USB, không phải bằng chứng Wi-Fi.

## 2. Mục tiêu và bố trí

- MPU6050 nối ESP32: VCC=3V3, GND chung, SDA21, SCL22, AD0=GND, địa chỉ 0x68.
- ESP32 và MPU6050 đeo ở eo/thắt lưng, dùng pin dự phòng qua USB của ESP32.
- Pi4 đặt cố định, cấp điện bằng bộ nguồn USB-C, nhận dữ liệu và lưu CSV/JSON.
- Ở nhà: ESP32 và Pi4 cùng router Wi-Fi 2.4 GHz.
- Mang đi: ESP32 và Pi4 cùng hotspot iPhone 12, bật Maximize Compatibility.
- Laptop vào cùng mạng khi cần SSH điều khiển Pi4.
- Bước này kiểm chứng truyền Wi-Fi, nguồn di động và gắn cảm biến khi di chuyển.
  Dùng nhãn `test`; huấn luyện ML và giao diện MotionSense thuộc bước sau.

## 3. Kiến trúc được chọn

Chọn TCP trực tiếp thay cho UDP hoặc MQTT. ESP32 mở TCP server, Pi4 là client.
TCP giữ thứ tự byte nhưng không đảm bảo nhịp lấy mẫu hoặc không mất mẫu ở đầu
ESP32. Vì vậy vẫn kiểm tra seq, timestamp và thống kê bỏ mẫu phía firmware.

Luồng dữ liệu:

```text
MPU6050 -> tác vụ lấy mẫu 50 Hz -> bộ đệm hữu hạn -> tác vụ mạng TCP
                                                          |
Pi4: TCP adapter -> line reader -> parser -> quality -> CSV/JSON
```

- Chỉ tác vụ lấy mẫu sở hữu I2C, calibration, seq và timestamp.
- Tác vụ mạng sở hữu Wi-Fi, TCP client và việc gửi byte.
- Tác vụ lấy mẫu không gọi kết nối Wi-Fi hoặc gửi TCP; không chờ client chậm.
- Bộ đệm và trạng thái dùng chung phải được đồng bộ; không chờ mạng khi giữ khóa.
- Không bật phát USB DATA đồng thời trong bản Wi-Fi. USB vẫn dùng nạp firmware
  và xem log chẩn đoán; bản USB riêng tiếp tục phục vụ đối chiếu.

## 4. Lấy mẫu, bộ đệm và nhận diện stream

- Giữ khoảng lấy mẫu 20 ms, không phát bù bằng mẫu giả khi trễ.
- Giữ calibration: ổn định 2 giây, 500 mẫu DATA_RDY mới, thử lại sau 3 giây khi
  chuyển động; lỗi I2C dẫn đến khởi tạo và calibration lại.
- Timestamp lấy bằng đồng hồ đơn điệu 64 bit ngay sau đọc frame.
- `seq` uint32 tăng một lần cho mỗi frame hợp lệ đã lấy, trước quyết định giữ
  hay bỏ mẫu. Mẫu lỗi I2C không được biến thành DATA hợp lệ.
- Mỗi calibration thành công tạo `stream_id` mới và đặt seq=0.
- Khi stream bị vô hiệu do lỗi cảm biến hoặc bắt đầu calibration lại, xóa mẫu
  đang chờ của stream cũ. Bản ghi TCP đã gửi một phần phải hoàn tất đúng stream
  cũ hoặc đóng socket; không nối phần còn lại với bản ghi stream mới.
- Mất Wi-Fi hoặc đổi client không làm calibration lại hoặc đặt seq=0.
- Nếu seq sắp tràn uint32, kết thúc stream và khởi tạo/calibration lại trước
  khi phát seq=0; không để collector hiểu nhầm wrap là đảo thứ tự trong một stream.
- Bộ đệm tối đa 100 mẫu, tương đương khoảng 2 giây ở 50 Hz.
- Đầy bộ đệm: bỏ mẫu cũ nhất để giữ mẫu mới; tăng `queue_dropped_total`.
- Không có client: vẫn lấy mẫu nhưng không tích lũy backlog để phát về sau;
  tăng `unobserved_total` cho mẫu không có bên thu.
- Khi client ngắt hoặc kết nối mới: loại backlog của kết nối trước, tính vào
  `unobserved_total`. Không gửi lại dữ liệu cũ cho một phiên mới.
- Bộ đếm firmware tính trong từng stream, reset cùng stream_id. Không cộng
  chúng vào `missing_by_seq` vì có thể đếm trùng cùng một mất mẫu.
- Mẫu đang gửi nhưng bị bỏ trước khi hoàn tất cũng tăng `unobserved_total`.
  Gửi thành công vào socket không chứng minh Pi đã ghi xuống đĩa; các bộ đếm
  này chỉ mô tả những mẫu firmware biết đã bỏ, không phải xác nhận nhận end-to-end.
- Seq gap chỉ mô tả phần nằm giữa các mẫu đã nhận; không suy ra số mẫu mất trước
  mẫu đầu hoặc sau mẫu cuối chỉ từ CSV.

## 5. Hợp đồng TCP và giao thức

- TCP port mặc định: 8765; phục vụ một client ghi dữ liệu tại một thời điểm.
- Client thứ hai bị đóng, không chiếm kết nối đang thu.
- DATA v1 giữ nguyên 12 trường và độ chính xác số như bước 1; LF/CRLF hợp lệ.
- CSV giữ nguyên 13 cột. Không thêm log vào hàng CSV.
- Socket gửi phải có thời hạn hoặc vận hành non-blocking trong tác vụ mạng.
  Không tiến triển gửi trong 3 giây thì đóng client; sampling vẫn tiếp tục.
- Phải xử lý partial write: giữ offset của bản ghi đang gửi; không chèn log hay
  DATA khác giữa bản ghi. Khi đóng kết nối, bỏ phần bản ghi chưa gửi hết.
- Tất cả dòng điều khiển và DATA không quá 512 byte trước LF.
- Bổ sung dòng điều khiển phiên bản 1, gửi trước DATA đầu tiên của mỗi kết nối
  và khoảng mỗi giây khi có client:

```text
[NET],1,stream_id,queue_dropped_total,unobserved_total
```

- Trước calibration thành công đầu tiên chưa có stream hợp lệ nên chưa gửi NET.
  Khi stream thay đổi, gửi NET tương ứng trước DATA của stream mới.
- NET không phải DATA; collector đọc riêng và lưu snapshot bộ đếm trong metadata.
- NET lỗi được đếm riêng (`telemetry_errors`), không biến thành lỗi DATA hoặc
  ghi đè snapshot hợp lệ. Dùng cùng giới hạn dòng 512 byte.
- Snapshot đầu/cuối kèm thời điểm nhận phía host; nếu chưa nhận telemetry thì
  ghi null, không ghi 0 để giả định không mất mẫu. Snapshot cuối là lần quan sát
  cuối, không khẳng định là tổng tại thời điểm mất mạng.
- Dữ liệu đi trong LAN/hotspot, không có broker hoặc dịch vụ cloud. TCP chưa có
  TLS/xác thực ứng dụng; dùng mạng riêng, không cấu hình port forwarding.

## 6. Hai mạng Wi-Fi và khám phá thiết bị

- Firmware lưu tối đa hai cấu hình có thứ tự: mạng nhà, hotspot iPhone.
- Khi chưa kết nối, thử mạng nhà trước rồi hotspot; mỗi lần kết nối có giới hạn
  10 giây. Sau một vòng thất bại, chờ 3 giây trước khi thử tiếp.
- Giữ mạng đang kết nối ổn định. Không tự chuyển từ hotspot sang mạng nhà giữa
  phiên chỉ vì mạng nhà vừa xuất hiện. Ưu tiên áp dụng khi cần kết nối lại.
- Pi4 lưu hai profile với ưu tiên tương ứng. Cần xác định trình quản lý mạng
  đang hoạt động trước khi cấu hình; không giả định Bookworm luôn dùng cùng một cấu hình.
- Không đổi mạng Pi4 đang dùng cho SSH nếu chưa có phương án kết nối lại rõ ràng.
- Mật khẩu đặt trong cấu hình cục bộ bị ignore, tách khỏi mã nguồn và file mẫu;
  không đưa mật khẩu vào log, DATA, metadata hoặc đặc tả.
- Không ghi cứng IP ESP32/Pi4: dùng DHCP.
- ESP32 quảng bá mDNS service `_mpu6050._tcp.local.` với cổng TCP, tên thiết bị
  duy nhất và TXT `protocol=1`. Tên host gồm hậu tố nhận diện từng ESP32.
- Collector hỗ trợ khám phá bằng Python `zeroconf` (phụ thuộc tùy chọn):
  không tìm được trong 5 giây thì báo lỗi; tìm nhiều thiết bị thì liệt kê và yêu
  cầu chọn địa chỉ thay vì chọn ngẫu nhiên.
- Nhập IP trực tiếp không cần zeroconf. mDNS chỉ hoạt động khi mạng cho phép;
  phải kiểm chứng riêng trên hotspot iPhone thực tế.
- Nếu hotspot chặn trao đổi giữa các client thì nhập IP cũng không khắc phục
  được; ghi nhận điều kiện không đạt và quyết định lại mạng, không tuyên bố đã hỗ trợ.

## 7. Collector và vòng đời phiên

Các lệnh dự kiến, chạy từ thư mục chứa package:

```text
python3 -m collector --port /dev/ttyUSB0 --duration 60 --label test --output data
python3 -m collector --tcp 192.168.1.50:8765 --duration 60 --label test --output data
python3 -m collector --discover --duration 60 --label test --output data
```

IP ở lệnh mẫu chỉ minh họa, không phải địa chỉ đã xác nhận của ESP32.

- Bắt buộc đúng một trong `--port`, `--tcp`, `--discover`.
- TCP connect timeout 5 giây, read timeout 50 ms; không đợi đủ một chunk mới
  chuyển byte cho line reader. Timeout đọc không được coi là EOF.
- TCP EOF phải kết thúc phiên `connection_lost`, không chờ đủ duration.
- Lỗi socket sau kết nối cũng là `connection_lost`; lỗi mở/kết nối/khám phá trả
  mã 5 và không in thông báo lưu thành công.
- Chờ DATA đầu tối đa 60 giây sau khi mở transport; duration tính từ mẫu hợp lệ
  đầu tiên, không tính calibration. Dòng tiến độ recording cũng tính từ mẫu đầu.
- 3 giây không có mẫu được chấp nhận sau khi bắt đầu: `no_data`, kể cả vẫn nhận
  NET/log. NET không kéo dài thời gian sống của phiên không có dữ liệu cảm biến.
- DATA từ stream mới: `stream_changed`, không ghi mẫu đó vào CSV cũ.
- Đủ thời lượng: `completed`; Ctrl+C: `interrupted`, giữ dữ liệu đã ghi.
- Không tự nối lại trong cùng phiên. Người vận hành chạy lệnh mới sau mất mạng;
  tạo file mới và bỏ phần dòng dở của transport trước.
- Trước khi kết luận completed, kiểm tra không nhận thêm mẫu sau deadline khi
  xử lý chunk nhiều dòng. Không kéo dài phiên bởi backlog hoặc progress callback.
- Giữ cơ chế file độc quyền, flush mỗi 50 hàng, JSON thay thế nguyên tử.
- Mã thoát: 0 completed; 130 interrupted; 3 no_data/wait_timeout;
  4 stream_changed; 5 serial_error/connection_lost/mở transport/khám phá;
  6 lỗi file; 2 tham số sai.

## 8. Metadata và chất lượng

- Giữ các khóa cũ và stats bước 1, thêm `transport` là `serial` hoặc `tcp`.
- USB giữ port/baud. TCP có endpoint đã kết nối, chế độ tìm địa chỉ, port/baud
  serial là null. Không dùng IP giả hoặc baud giả để lấp trường metadata.
- Metadata TCP có `firmware_counters_first`, `firmware_counters_last` và
  `telemetry_errors`; snapshot có stream_id và `host_since_open_s` tính từ lúc
  mở transport. Đây là mốc khác với host_elapsed_s của hàng CSV.
- Trước DATA đầu, giữ NET tạm theo stream_id; khi nhận DATA đầu thì chỉ gắn NET
  cùng stream vào phiên. NET stream khác sau khi đã ghi không được ghi đè snapshot
  phiên hiện tại; DATA stream khác sẽ kết thúc phiên như quy định ở mục 7.
- Tính device_span_s và sample_rate_hz bằng timestamp ESP32; host_elapsed_s
  chỉ phản ánh thời điểm Pi nhận. TCP có thể gom nhiều mẫu vào cùng một chunk.
- Không gọi phiên là sạch chỉ vì DATA lỗi bằng 0: kiểm tra cả gaps timestamp,
  missing_by_seq và bộ đếm firmware quan sát được trong phiên.
- Thu giữa một stream đang chạy có seq đầu khác 0 là hợp lệ; snapshot bộ đếm
  tuyệt đối khác 0 từ trước phiên không tự động là lỗi của phiên hiện tại.

## 9. Nguồn và gắn ở eo

- ESP32 lấy nguồn từ pin dự phòng qua cổng USB; MPU6050 lấy 3V3 từ ESP32.
- Kiểm tra pin không tự ngắt và board không reset trong phiên thử ít nhất 10 phút.
- Cố định MPU6050 và ESP32, tránh dây nhảy lỏng, tránh cảm biến đung đưa độc lập
  với cơ thể. Ghi vị trí trước/sau/trái/phải ở eo và hướng các trục trong ghi chú phiên.
- Giữ cảm biến yên trên bàn khoảng 7 giây cho calibration hoàn tất, sau đó mới
  gắn lên người và bắt đầu phiên di chuyển. Khi reset, thực hiện lại bước giữ yên.
- Giữ thang đo ±2 g, ±250 °/s, DLPF=3, tốc độ nội bộ 100 Hz khi đối chiếu Wi-Fi.
- Trước thu dữ liệu ML, kiểm tra clipping từng trục theo thang đo và bias gyro.
  Độ lớn vector gyro vượt 250 °/s hoặc vector gia tốc vượt 2 g tự nó không chứng
  minh từng trục bị clipping. Không tự đổi thang đo mà bỏ qua hệ số quy đổi và metadata.
- Khoảng 0.94 g khi đứng yên là sai lệch gia tốc còn tồn tại, không coi là đã
  hiệu chỉnh gia tốc chính xác. Bộ lọc chống aliasing cho 50 Hz cần đánh giá trước ML.

## 10. Kiểm chứng và tiêu chí đạt

Bộ checklist đo được, số lần lặp, điều kiện PASS/FAIL/BLOCKED và hồ sơ bằng chứng
được cụ thể hóa tại
[`2026-10-10-mpu6050-wifi-acceptance.md`](2026-10-10-mpu6050-wifi-acceptance.md).
Áp dụng đầy đủ AC-01 đến AC-08 khi nghiệm thu bước 2. Các mục bên dưới tóm tắt
phạm vi kiểm chứng; đạt một phiên 60 giây không thay thế toàn bộ checklist.

### Phần mềm

- Regression USB: C++ stream/calibration, Python parser/reader/tracker/writer/CLI.
- Bộ đệm: đầy bỏ cũ, tăng bộ đếm đúng, seq gap, xóa backlog qua client/stream.
- TCP: chia chunk, partial write, read timeout khác EOF, client thứ hai,
  connect failure, FIN, reset socket, NET lỗi/thiếu, snapshot không bị trộn stream.
- Thử mạng chậm hơn tốc độ lấy mẫu: sampling vẫn giữ nhịp; dữ liệu bỏ được báo,
  không có bộ nhớ tăng vô hạn hoặc gửi lại backlog của phiên đã đóng.
- Kiểm tra chỉ một lựa chọn transport; discovery có 0/1/nhiều kết quả.
- Fake test không thay thế bằng chứng phần cứng; dùng loopback socket thật cho
  kiểm thử tích hợp TCP và đọc lại CSV/JSON.
- Build cả firmware USB và Wi-Fi; giữ build_dir không dấu trong `[platformio]`.

### Thiết bị thật

1. Trên Wi-Fi nhà: phiên 60 giây trên bàn, 49–51 Hz, khoảng 2940–3060 mẫu,
   CSV khớp JSON, một stream, tất cả bộ đếm lỗi dữ liệu bằng 0, không gap >40 ms,
   không tăng queue_dropped_total trong phần telemetry quan sát được của phiên.
2. Thử Ctrl+C, client đóng, ESP32 reset, mất Wi-Fi và kết nối lại: file được giữ,
   đúng trạng thái; không tự nối dữ liệu của hai phiên.
3. Lặp phiên 60 giây trên hotspot iPhone 12; xác minh cả khám phá và TCP thực tế.
   Nếu mDNS bị chặn nhưng TCP trực tiếp hoạt động, ghi rõ cần nhập IP trên mạng đó.
4. Dùng pin dự phòng: phiên 10 phút trên bàn xác nhận nguồn, kết nối và chất lượng.
5. Đeo ở eo: phiên test di chuyển, kiểm tra nhịp mẫu, mất kết nối, độ chắc của gắn
   cảm biến và dấu hiệu chạm thang đo. Chỉ kết luận trong vùng đã thử, không suy ra
   phạm vi phủ sóng hoặc thời lượng pin cả ngày.

## 11. Phạm vi file dự kiến

- Firmware: `src/main.cpp`, các module lấy mẫu/bộ đệm/mạng mới, `platformio.ini`.
- Cấu hình Wi-Fi mẫu và `.gitignore` cho thông tin mạng cục bộ.
- Python: adapter TCP, discovery, điều phối transport trong `cli.py`/`collect.py`,
  NET telemetry và metadata trong `recorder.py`/`session.py`.
- Tests C++/Python theo các thành phần và hành vi mới; README hướng dẫn hai mạng,
  cấp nguồn, vị trí gắn và xử lý lỗi; lưu bằng chứng nghiệm thu trong project.
- Source và dữ liệu người dùng hiện có phải được bảo toàn. Không commit/push
  hoặc tự thiết lập Git trong project này.
