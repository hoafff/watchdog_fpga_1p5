# RTL Watchdog Monitor for Kiwi 1P5

## 1. Mục tiêu
Thiết kế RTL watchdog monitor tương tự TPS3431 trên board Kiwi 1P5 (Gowin GW1N-UV1P5), có:
- theo dõi kick `WDI` theo cạnh xuống,
- timeout thì kéo `WDO` xuống mức active-low trong thời gian `tRST_ms`,
- hỗ trợ `EN`, `ENOUT`, `arm_delay_us`,
- cho phép cấu hình runtime qua UART,
- có top-level chạy được trên board,
- có testbench bao phủ đầy đủ các case chính.

## 2. Quy ước thiết kế đã chốt
- RTL synthesizable: **Verilog-2001**.
- Testbench: **SystemVerilog**.
- UART cấu hình: **9600 bps, 8N1**.
- `WDO` và `ENOUT` trên FPGA dùng **push-pull** để mô phỏng open-drain.
- Ưu tiên **đúng đề thi** hơn là bám y nguyên mọi chi tiết của TPS3431 nếu có mâu thuẫn.
- `WDI` hợp lệ là **falling edge** của nguồn đang được chọn.
- `EN_EFFECTIVE = CTRL.EN_SW & en_pin_level`.
- `CTRL.WDI_SRC = 0` chọn button S1, `CTRL.WDI_SRC = 1` chọn UART `KICK`.
- Dữ liệu nhiều byte trên UART dùng **big-endian (MSB first)**.

## 3. Kiến trúc module
- `timebase_gen.v`: tạo `tick_us` và `tick_ms` từ clock hệ thống.
- `button_conditioner.v`: đồng bộ + debounce cho S1/S2, xuất level sạch và pulse cạnh xuống.
- `watchdog_core.v`: FSM `DISABLED / ARM_DELAY / MONITOR / FAULT_HOLD`.
- `regfile.v`: lưu `CTRL`, `tWD_ms`, `tRST_ms`, `arm_delay_us` và tạo `STATUS`.
- `uart_rx.v`, `uart_tx.v`, `uart_protocol.v`: xử lý giao tiếp UART và protocol frame.
- `top_watchdog_kiwi1p5.v`: nối các module con với IO của board.

## 4. Register map
- `0x00 CTRL` (R/W, 32-bit)
  - bit0 `EN_SW`
  - bit1 `WDI_SRC`
  - bit2 `CLR_FAULT` (write-1-to-clear, pulse 1 chu kỳ)
- `0x04 tWD_ms` (R/W, 32-bit)
- `0x08 tRST_ms` (R/W, 32-bit)
- `0x0C arm_delay_us` (R/W, 16-bit)
- `0x10 STATUS` (R, 32-bit)
  - bit0 `EN_EFFECTIVE`
  - bit1 `FAULT_ACTIVE`
  - bit2 `ENOUT`
  - bit3 `WDO`
  - bit4 `LAST_KICK_SRC`

## 5. Giao thức UART
Frame RX/TX:
```text
[0x55][CMD][ADDR][LEN][DATA...][CHK]