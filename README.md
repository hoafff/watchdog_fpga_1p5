# Watchdog Monitor for Kiwi 1P5

## 1. Giới thiệu
Dự án này triển khai một khối **RTL Watchdog Monitor** trên board **Kiwi 1P5 (Gowin GW1N-UV1P5)**, mô phỏng nguyên lý watchdog tương tự **TPS3431** và cho phép cấu hình tham số hoạt động qua **UART**.

Thiết kế hỗ trợ:
- giám sát tín hiệu kick `WDI` theo **falling edge**
- timeout watchdog theo tham số `tWD_ms`
- assert `WDO` mức **active-low** trong thời gian `tRST_ms`
- hỗ trợ `EN`, `ENOUT`, `arm_delay_us`
- cấu hình runtime qua UART
- testbench mô phỏng đầy đủ các case chính

---

## 2. Mục tiêu bám theo đề
Thiết kế bám theo yêu cầu đề thi:
- `WDI` được ghi nhận theo **cạnh xuống**
- khi timeout thì `WDO` kéo thấp trong `tRST_ms`, sau đó nhả và bắt đầu chu kỳ mới
- khi `EN=0`, watchdog disable, bỏ qua `WDI`, `ENOUT=0`, `WDO` ở trạng thái nhả
- sau khi enable, `WDI` bị ignore trong `arm_delay_us`
- UART dùng **9600 bps, 8N1**
- có register map bắt buộc gồm `CTRL`, `tWD_ms`, `tRST_ms`, `arm_delay_us`, `STATUS`

---

## 3. Quyết định thiết kế đã chốt

### 3.1 Ngôn ngữ và flow
- RTL synthesizable: **Verilog-2001**
- Testbench: **SystemVerilog**
- Mô phỏng: **QuestaSim 10.7c**
- UART protocol: **9600 8N1**

### 3.2 Mô phỏng open-drain
TPS3431 thật sử dụng ngõ ra open-drain cho `WDO` và `ENOUT`. Trong thiết kế FPGA này, `WDO` và `ENOUT` được triển khai theo kiểu **push-pull**, nhưng vẫn giữ đúng quy ước:
- `WDO`: **active-low**
- `ENOUT`: **active-high**

Lý do chọn cách này:
- đơn giản hơn khi triển khai trên FPGA
- dễ mô phỏng
- dễ demo bằng LED trên board

### 3.3 Quy ước enable
- `CTRL.EN_SW`: enable bằng software
- `btn_en_n` (S2): tín hiệu enable phần cứng, active-low ở mức vật lý
- `en_pin_level`: mức đã debounce của S2
- **`EN_EFFECTIVE = CTRL.EN_SW & en_pin_level`**

Ý nghĩa:
- sau reset, watchdog ở trạng thái disable an toàn vì `EN_SW=0`
- sau khi software bật `EN_SW=1`, watchdog chỉ thực sự chạy khi nút S2 ở trạng thái cho phép

### 3.4 Quy ước chọn nguồn kick
- `CTRL.WDI_SRC = 0`: nhận kick từ **button S1**
- `CTRL.WDI_SRC = 1`: nhận kick từ **UART KICK**

Chỉ nguồn đang được chọn mới tạo kick hợp lệ.

### 3.5 CLR_FAULT
Thiết kế **có implement `CLR_FAULT`**:
- `CTRL.bit2 = CLR_FAULT`
- kiểu **write-1-to-clear**
- tạo pulse 1 chu kỳ để nhả `WDO` sớm khi đang fault

---

## 4. Kiến trúc module
Dự án được tách module rõ ràng:

- `timebase_gen.v`
  - tạo `tick_us`, `tick_ms`
- `button_conditioner.v`
  - đồng bộ + debounce cho S1/S2
- `watchdog_core.v`
  - FSM watchdog và timer
- `regfile.v`
  - lưu cấu hình và tạo `STATUS`
- `uart_rx.v`
  - nhận UART
- `uart_tx.v`
  - phát UART
- `uart_protocol.v`
  - parse frame, checksum, decode command, tạo response
- `top_watchdog_kiwi1p5.v`
  - top-level nối toàn bộ module với IO board

---

## 5. Hành vi watchdog
FSM gồm 4 trạng thái:
- `ST_DISABLED`
- `ST_ARM_DELAY`
- `ST_MONITOR`
- `ST_FAULT_HOLD`

### 5.1 ST_DISABLED
- `WDO = 1`
- `ENOUT = 0`
- bỏ qua mọi kick
- nếu `EN_EFFECTIVE=1` thì sang `ST_ARM_DELAY`

### 5.2 ST_ARM_DELAY
- `WDO = 1`
- `ENOUT = 0`
- bỏ qua kick trong thời gian `arm_delay_us`
- hết `arm_delay_us` thì sang `ST_MONITOR`
- nếu mất enable giữa chừng thì quay về `ST_DISABLED`

### 5.3 ST_MONITOR
- `ENOUT = 1`
- `WDO = 1`
- đếm timeout `tWD_ms`
- có kick hợp lệ thì reset timer watchdog
- nếu timeout thì sang `ST_FAULT_HOLD`

### 5.4 ST_FAULT_HOLD
- `ENOUT = 1`
- `WDO = 0` trong `tRST_ms`
- hết `tRST_ms` thì nhả `WDO` và quay lại `ST_MONITOR`
- nếu có `CLR_FAULT` thì nhả sớm và quay lại `ST_MONITOR`
- nếu mất enable thì quay `ST_DISABLED`

---

## 6. Register map

### 0x00 - CTRL (R/W, 32-bit)
- bit0: `EN_SW`
- bit1: `WDI_SRC`
- bit2: `CLR_FAULT` (write-1-to-clear)
- bit31:3: reserved = 0

### 0x04 - tWD_ms (R/W, 32-bit)
- timeout watchdog
- đơn vị: ms
- default: `1600`

### 0x08 - tRST_ms (R/W, 32-bit)
- thời gian giữ `WDO` khi fault
- đơn vị: ms
- default: `200`

### 0x0C - arm_delay_us (R/W, 16-bit)
- thời gian ignore `WDI` sau enable
- đơn vị: us
- default: `150`

### 0x10 - STATUS (R, 32-bit)
- bit0: `EN_EFFECTIVE`
- bit1: `FAULT_ACTIVE`
- bit2: `ENOUT`
- bit3: `WDO`
- bit4: `LAST_KICK_SRC`
- bit31:5: reserved = 0

---

## 7. UART protocol

### 7.1 Frame format
```text
[0x55][CMD][ADDR][LEN][DATA...][CHK]
```

Trong đó:
- `CHK = XOR` của tất cả byte từ `CMD` đến hết `DATA`
- dữ liệu nhiều byte truyền theo **big-endian (MSB first)**

### 7.2 Command codes
- `0x01` = `WRITE_REG`
- `0x02` = `READ_REG`
- `0x03` = `KICK`
- `0x04` = `GET_STATUS`

### 7.3 Response OK
```text
[0x55][CMD|0x80][ADDR][LEN][DATA...][CHK]
```

### 7.4 Response lỗi
```text
[0x55][0x7F][CMD][0x01][ERR_CODE][CHK]
```

### 7.5 Error code
- `0x01` = bad sync
- `0x02` = bad len
- `0x03` = checksum error
- `0x04` = invalid address
- `0x05` = invalid access
- `0x06` = command not allowed / source not enabled

### 7.6 Quy ước lệnh
- `WRITE_REG`: ghi thanh ghi, phản hồi bằng `STATUS`
- `READ_REG`: đọc giá trị đúng theo địa chỉ
- `KICK`: chỉ hợp lệ khi `WDI_SRC = UART`
- `GET_STATUS`: trả nhanh `STATUS`

---

## 8. Mapping board Kiwi 1P5

### Input
- `clk_27m`    -> `SYS_CLK`
- `btn_wdi_n`  -> S1 / `IOR1B` / pin 35
- `btn_en_n`   -> S2 / `IOR1A` / pin 36
- `uart_rx_i`  -> `IOR11B` / pin 33

### Output
- `uart_tx_o`    -> `IOR11A` / pin 34
- `led_wdo_o`    -> `IOR17A` / pin 27 (D3)
- `led_enout_o`  -> `IOR15B` / pin 28 (D4)

### Quy ước LED demo
- **D3 sáng = fault active**
- **D4 sáng = ENOUT active**

Nếu polarity LED trên board thực tế ngược với mong muốn hiển thị, việc đảo mức chỉ được xử lý tại **top-level**, không thay đổi logic bên trong `watchdog_core`.

---

## 9. Cách chạy mô phỏng
Mô phỏng được kiểm tra bằng **QuestaSim 10.7c**.

### 9.1 Compile và run
Ví dụ command line:
```tcl
vlog -reportprogress 300 -sv +incdir+../tb \
  ../rtl/timebase_gen.v \
  ../rtl/button_conditioner.v \
  ../rtl/watchdog_core.v \
  ../rtl/regfile.v \
  ../rtl/uart_rx.v \
  ../rtl/uart_tx.v \
  ../rtl/uart_protocol.v \
  ../rtl/top_watchdog_kiwi1p5.v \
  ../tb/tb_uart_host.sv \
  ../tb/tb_top.sv

vsim work.tb_top
run -all
```

Hoặc dùng script:
```tcl
do scripts/run_questa.do
```

---

## 10. Kết quả verification
Testbench hiện tại bao phủ **8 case**:

1. reset default
2. enable và arm delay
3. normal kick bằng button
4. timeout và fault hold
5. disable giữa chừng
6. UART write/read register
7. UART KICK + GET_STATUS
8. CLR_FAULT + protocol error

### Trạng thái hiện tại
- Compile: **pass**
- Simulation: **pass**
- Kết quả: **all 8 cases pass trên QuestaSim**

---

## 11. Lưu ý triển khai
- `WRITE_REG` và `KICK` trong `uart_protocol.v` đã được xử lý để response phản ánh đúng trạng thái mới sau update
- testbench kiểm tra không chỉ frame hợp lệ mà còn kiểm tra đúng **payload data**
- `LAST_KICK_SRC` chỉ cập nhật khi có kick hợp lệ thực sự được chấp nhận

---

## 12. Tài liệu tham chiếu
- Đề thi Watchdog Monitor v1.2
- Datasheet TPS3431
- Kiwi 1P5 brief / pinout / user manual

---

## 13. Công việc còn lại
- kiểm tra lại file `.cst` trong project Gowin cuối cùng
- synth / place & route trên Gowin EDA
- nạp board Kiwi 1P5
- kiểm tra LED/UART trên phần cứng
- chụp waveform và ảnh demo thực tế để nộp kèm

---

## 14. How to Demo on Board

### 14.1 Chuẩn bị
- Board: **Kiwi 1P5**
- Nguồn và kết nối: cắm **USB Type-C** vào board
- Tool nạp: **Gowin EDA Programmer**
- Kết nối UART: dùng **USB-UART onboard** của Kiwi 1P5
- Terminal PC: có thể dùng serial terminal hoặc script Python để gửi frame UART

### 14.2 Nạp bitstream
1. Mở project trong **Gowin EDA**
2. Run synth / place & route
3. Mở programmer và nạp bitstream vào board Kiwi 1P5
4. Sau khi nạp xong, giữ board ở trạng thái idle để kiểm tra trạng thái mặc định sau reset

### 14.3 Trạng thái mặc định sau reset
Sau khi reset hoặc sau khi vừa nạp:
- watchdog ở trạng thái **disable**
- `ENOUT = 0`
- `WDO` ở trạng thái nhả
- theo quy ước LED demo:
  - **D3 tắt** = chưa fault
  - **D4 tắt** = watchdog chưa enable xong

### 14.4 Chức năng các nút và LED
- **S1**: nguồn kick `WDI` bằng tay
- **S2**: enable/disable phần cứng
- **D3**: hiển thị `WDO`
- **D4**: hiển thị `ENOUT`

Quy ước demo dùng trong bài:
- **D3 sáng = fault active**
- **D4 sáng = ENOUT active**

### 14.5 Kịch bản demo đề xuất

#### Demo 1 - Enable watchdog
1. Gửi lệnh UART để set `CTRL.EN_SW = 1`
2. Đảm bảo S2 đang ở trạng thái thả
3. Chờ hết `arm_delay_us`
4. Quan sát:
   - `ENOUT` lên mức active
   - **D4 sáng**
   - `WDO` chưa fault nên **D3 tắt**

#### Demo 2 - Kick bằng nút S1
1. Cấu hình `CTRL.WDI_SRC = 0` để chọn nguồn kick từ button
2. Khi watchdog đang chạy, nhấn S1 định kỳ trước khi hết `tWD_ms`
3. Quan sát:
   - watchdog không timeout
   - `WDO` không bị assert
   - **D3 vẫn tắt**
   - **D4 vẫn sáng**

#### Demo 3 - Timeout watchdog
1. Giữ watchdog ở trạng thái enable
2. Không nhấn S1 và không gửi UART KICK
3. Chờ quá `tWD_ms`
4. Quan sát:
   - watchdog timeout
   - `WDO` bị assert active-low trong `tRST_ms`
   - **D3 sáng** trong khoảng fault hold
   - sau khi hết `tRST_ms`, `WDO` nhả ra và hệ thống quay lại monitor

#### Demo 4 - Disable watchdog bằng S2
1. Khi watchdog đang monitor hoặc đang fault hold, nhấn S2
2. Quan sát:
   - watchdog quay về trạng thái disable
   - `ENOUT = 0`
   - `WDO` nhả
   - **D4 tắt**
   - **D3 tắt**

#### Demo 5 - UART cấu hình tham số
1. Dùng UART gửi lệnh `WRITE_REG` để thay đổi:
   - `tWD_ms`
   - `tRST_ms`
   - `arm_delay_us`
2. Dùng `READ_REG` đọc lại để xác nhận giá trị
3. Có thể giảm `tWD_ms` xuống nhỏ để demo timeout nhanh hơn trước giám khảo

#### Demo 6 - UART KICK
1. Set `CTRL.WDI_SRC = 1`
2. Gửi lệnh `KICK`
3. Quan sát:
   - watchdog timer được reset
   - không sinh fault nếu kick đúng hạn
4. Dùng `GET_STATUS` để kiểm tra `LAST_KICK_SRC = UART`

#### Demo 7 - CLR_FAULT
1. Tạo fault bằng cách để watchdog timeout
2. Khi `WDO` đang assert, gửi `WRITE_REG CTRL` với bit `CLR_FAULT = 1`
3. Quan sát:
   - fault được nhả sớm
   - `WDO` trở về trạng thái nhả
   - hệ thống quay lại monitor

### 14.6 Gợi ý demo nhanh trước giám khảo
Để demo trực quan và không phải chờ lâu:
- cấu hình `tWD_ms` nhỏ hơn mặc định, ví dụ vài chục ms
- cấu hình `tRST_ms` nhỏ hơn mặc định
- giữ `arm_delay_us` đủ ngắn để thấy `ENOUT` lên nhanh

Cách này giúp trình bày rõ:
- enable
- arm delay
- kick hợp lệ
- timeout
- clear fault
- read/write register qua UART

### 14.7 Lưu ý khi demo
- Nút S1 và S2 là **active-low**, nên khi nhấn sẽ kéo tín hiệu xuống mức `0`
- Nếu LED trên board có polarity ngược với mong muốn hiển thị, chỉ xử lý ở top-level mapping
- UART dùng **9600 8N1**, dữ liệu nhiều byte truyền theo **big-endian**
- Nếu dùng terminal tay, cần gửi đúng format frame:
  `[0x55][CMD][ADDR][LEN][DATA...][CHK]`

### 14.8 Kết quả mong đợi khi demo thành công
- Có thể enable watchdog bằng software + phần cứng
- `ENOUT` lên sau `arm_delay_us`
- `WDO` fault đúng khi timeout
- fault được giữ đúng `tRST_ms`
- hỗ trợ read/write register qua UART
- hỗ trợ `KICK`, `GET_STATUS`, `CLR_FAULT`
- LED và UART phản ánh đúng trạng thái hệ thống