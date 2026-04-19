# Watchdog Monitor for Kiwi 1P5

## 1. Giới thiệu
Dự án này triển khai một khối **RTL Watchdog Monitor** trên board **Kiwi 1P5 (Gowin GW1N-UV1P5)**, mô phỏng nguyên lý watchdog tương tự **TPS3431** và cho phép cấu hình tham số hoạt động qua **UART**.

Thiết kế hỗ trợ:
- giám sát tín hiệu kick `WDI` theo **falling edge**,
- timeout watchdog theo tham số `tWD_ms`,
- assert `WDO` mức **active-low** trong thời gian `tRST_ms`,
- hỗ trợ `EN`, `ENOUT`, `arm_delay_us`,
- cấu hình runtime qua UART,
- testbench mô phỏng đầy đủ các case chính.

## 2. Mục tiêu bám theo đề
Thiết kế bám theo yêu cầu đề thi:
- `WDI` được ghi nhận theo **cạnh xuống**,
- khi timeout thì `WDO` kéo thấp trong `tRST_ms`, sau đó nhả và bắt đầu chu kỳ mới,
- khi `EN=0`, watchdog disable, bỏ qua `WDI`, `ENOUT=0`, `WDO` ở trạng thái nhả,
- sau khi enable, `WDI` bị ignore trong `arm_delay_us`,
- UART dùng **9600 bps, 8N1**,
- có register map bắt buộc gồm `CTRL`, `tWD_ms`, `tRST_ms`, `arm_delay_us`, `STATUS`.

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
- đơn giản hơn khi triển khai trên FPGA,
- dễ mô phỏng,
- dễ demo bằng LED trên board.

### 3.3 Quy ước enable
- `CTRL.EN_SW`: enable bằng software
- `btn_en_n` (S2): tín hiệu enable phần cứng, active-low ở mức vật lý
- `en_pin_level`: mức đã debounce của S2
- **`EN_EFFECTIVE = CTRL.EN_SW & en_pin_level`**

Ý nghĩa:
- sau reset, watchdog ở trạng thái disable an toàn vì `EN_SW=0`,
- sau khi software bật `EN_SW=1`, watchdog chỉ thực sự chạy khi nút S2 ở trạng thái cho phép.

### 3.4 Quy ước chọn nguồn kick
- `CTRL.WDI_SRC = 0`: nhận kick từ **button S1**
- `CTRL.WDI_SRC = 1`: nhận kick từ **UART KICK**

Chỉ nguồn đang được chọn mới tạo kick hợp lệ.

### 3.5 CLR_FAULT
Thiết kế **có implement `CLR_FAULT`**:
- `CTRL.bit2 = CLR_FAULT`
- kiểu **write-1-to-clear**
- tạo pulse 1 chu kỳ để nhả `WDO` sớm khi đang fault

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

## 7. UART protocol
### 7.1 Frame format
```text
[0x55][CMD][ADDR][LEN][DATA...][CHK]