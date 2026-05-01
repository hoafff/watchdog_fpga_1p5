#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Menu tiếng Việt cho demo Kiwi 1P5 Watchdog qua UART.
Đã tối ưu hóa cho mục đích trình diễn (Demo/Quay video).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

try:
    import serial
    import serial.tools.list_ports
except ModuleNotFoundError:
    print("Chưa có thư viện pyserial.")
    print("Cài bằng lệnh: python -m pip install pyserial")
    raise


SYNC = 0x55

CMD_WRITE_REG = 0x01
CMD_READ_REG = 0x02
CMD_KICK = 0x03
CMD_GET_STATUS = 0x04

ADDR_CTRL = 0x00
ADDR_TWD_MS = 0x04
ADDR_TRST_MS = 0x08
ADDR_ARM_DELAY_US = 0x0C
ADDR_STATUS = 0x10

ERR_CODES = {
    0x01: "bad sync",
    0x02: "bad len",
    0x03: "checksum error",
    0x04: "invalid address",
    0x05: "invalid access",
    0x06: "source not enabled / command not allowed in current mode",
}


def xor_checksum(data: bytes) -> int:
    chk = 0
    for b in data:
        chk ^= b
    return chk & 0xFF


def build_frame(cmd: int, addr: int, payload: bytes = b"") -> bytes:
    body = bytes([cmd & 0xFF, addr & 0xFF, len(payload) & 0xFF]) + payload
    chk = xor_checksum(body)
    return bytes([SYNC]) + body + bytes([chk])


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


@dataclass
class Response:
    raw: bytes
    ok: bool
    cmd: int
    addr: int
    payload: bytes
    error_code: Optional[int] = None


@dataclass
class Status:
    raw: int

    @property
    def en_effective(self) -> int:
        return (self.raw >> 0) & 1

    @property
    def fault_active(self) -> int:
        return (self.raw >> 1) & 1

    @property
    def enout(self) -> int:
        return (self.raw >> 2) & 1

    @property
    def wdo(self) -> int:
        return (self.raw >> 3) & 1

    @property
    def last_kick_src(self) -> int:
        return (self.raw >> 4) & 1

    @property
    def last_kick_src_name(self) -> str:
        return "UART" if self.last_kick_src else "Nút S1"


@dataclass
class TestResult:
    name: str
    result: str = "CHƯA CHẠY"
    detail: str = ""


@dataclass
class AppState:
    port: str
    baud: int
    timeout: float
    twd_ms: int = 1600
    trst_ms: int = 200
    arm_us: int = 150
    results: Dict[str, TestResult] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for key, name in [
            ("uart_connect", "Kết nối UART"),
            ("setcfg", "Ghi cấu hình thời gian"),
            ("status", "Đọc trạng thái"),
            ("button_mode", "Demo nút S1/S2"),
            ("uart_kick", "UART kick không timeout"),
            ("timeout", "Dừng kick sinh fault"),
            ("clear_fault", "Xóa fault"),
            ("disable", "Disable watchdog"),
        ]:
            self.results.setdefault(key, TestResult(name=name))

    def mark(self, key: str, result: str, detail: str = "") -> None:
        self.results[key].result = result
        self.results[key].detail = detail
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {self.results[key].name}: {result}"
        if detail:
            line += f" - {detail}"
        self.log(line)

    def log(self, line: str) -> None:
        self.log_lines.append(line)
        # Chỉ in log ẩn nếu không phải ở màn hình chính
        # print(line) 


class WatchdogUart:
    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 1.0, verbose: bool = False):
        self.verbose = verbose
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=timeout,
        )

    def close(self) -> None:
        self.ser.close()

    def read_exact(self, n: int) -> bytes:
        data = self.ser.read(n)
        if len(data) != n:
            raise TimeoutError(f"Timeout khi đọc {n} byte, chỉ nhận được {len(data)} byte")
        return data

    def read_response(self) -> Response:
        while True:
            b = self.read_exact(1)[0]
            if b == SYNC:
                break

        header = self.read_exact(3)
        cmd, addr_or_orig_cmd, length = header
        payload = self.read_exact(length)
        chk = self.read_exact(1)[0]
        calc = xor_checksum(header + payload)
        raw = bytes([SYNC]) + header + payload + bytes([chk])

        if chk != calc:
            raise ValueError(
                f"Sai checksum RX: recv=0x{chk:02X}, calc=0x{calc:02X}, raw={hexdump(raw)}"
            )

        if cmd == 0x7F:
            err = payload[0] if payload else None
            return Response(raw=raw, ok=False, cmd=addr_or_orig_cmd, addr=0, payload=b"", error_code=err)

        return Response(raw=raw, ok=True, cmd=cmd, addr=addr_or_orig_cmd, payload=payload)

    def transact(self, cmd: int, addr: int, payload: bytes = b"") -> Response:
        frame = build_frame(cmd, addr, payload)
        if self.verbose:
            print(f"TX: {hexdump(frame)}")

        self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()

        rsp = self.read_response()
        if self.verbose:
            print(f"RX: {hexdump(rsp.raw)}")

        if not rsp.ok:
            msg = ERR_CODES.get(rsp.error_code, f"unknown error {rsp.error_code}")
            raise RuntimeError(f"Lệnh 0x{cmd:02X} lỗi: {msg}")
        return rsp

    def read_reg(self, addr: int, width: int) -> int:
        rsp = self.transact(CMD_READ_REG, addr, b"")
        if len(rsp.payload) != width:
            raise RuntimeError(f"Độ dài phản hồi sai: {len(rsp.payload)} != {width}")
        return int.from_bytes(rsp.payload, "big")

    def write_reg(self, addr: int, value: int, width: int) -> Response:
        return self.transact(CMD_WRITE_REG, addr, value.to_bytes(width, "big"))

    def get_status(self) -> Status:
        rsp = self.transact(CMD_GET_STATUS, ADDR_STATUS, b"")
        if len(rsp.payload) != 4:
            raise RuntimeError(f"STATUS length sai: {len(rsp.payload)}")
        return Status(int.from_bytes(rsp.payload, "big"))

    def kick(self) -> Response:
        return self.transact(CMD_KICK, 0x00, b"")


def _enable_ansi_on_windows() -> None:
    if os.name == "nt":
        os.system("")


_enable_ansi_on_windows()

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "white": "\033[37m",
}


def colors_enabled() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not os.environ.get("WATCHDOG_NO_COLOR")


def color(text: object, style: str) -> str:
    text = str(text)
    if not colors_enabled():
        return text
    return f"{ANSI.get(style, '')}{text}{ANSI['reset']}"


def visible_len(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def pad_visible(text: str, width: int, align: str = "left") -> str:
    extra = max(0, width - visible_len(text))
    if align == "center":
        left = extra // 2
        return " " * left + text + " " * (extra - left)
    if align == "right":
        return " " * extra + text
    return text + " " * extra


def ui_width() -> int:
    return max(76, min(104, shutil.get_terminal_size((92, 24)).columns))


def print_box(title: str, lines: list[str], width: Optional[int] = None) -> None:
    width = width or ui_width()
    inner = width - 4
    print("╭" + "─" * (width - 2) + "╮")
    print("│" + pad_visible(color(title, "bold"), width - 2, "center") + "│")
    print("├" + "─" * (width - 2) + "┤")
    for line in lines:
        print("│ " + pad_visible(line, inner) + " │")
    print("╰" + "─" * (width - 2) + "╯")


def result_badge(result: str) -> str:
    label = result.strip().upper()
    if label == "PASS":
        return color("  PASS  ", "green")
    if label == "FAIL":
        return color("  FAIL  ", "red")
    if "CẦN" in label:
        return color(" XEM LẠI ", "yellow")
    if "CHƯA" in label:
        return color("CHƯA CHẠY", "dim")
    return label


def on_off_badge(value: int, on_text: str = "ON", off_text: str = "OFF") -> str:
    return color(f" {on_text} ", "green") if value else color(f" {off_text} ", "dim")


def hotkey(key: str) -> str:
    return color(f"[{key:>2}]", "cyan")


def muted(text: object) -> str:
    return color(text, "dim")


def clear_screen() -> None:
    if os.environ.get("WATCHDOG_NO_CLEAR"):
        return
    os.system("cls" if os.name == "nt" else "clear")


def pause() -> None:
    input(color("\n>>> Nhấn Enter để tiếp tục...", "cyan"))


def handle_serial_error(e: Exception) -> str:
    if isinstance(e, serial.SerialException):
        return "MẤT KẾT NỐI COM (Cáp lỏng hoặc bị chiếm)"
    return str(e)


def normalize_choice(raw: str) -> str:
    aliases = {
        "q": "0", "quit": "0", "exit": "0", "thoat": "0", "thoát": "0",
        "s": "1", "status": "1", 
        "cfg": "2", "config": "2",
        "button": "3", "btn": "3",
        "uart": "4", "kick": "4",
        "clear": "5", "xoa": "5",
        "disable": "6", "off": "6",
        "mon": "7", "monitor": "7", "live": "7",
        "demo": "8", "flow": "8",
        "check": "9", "checklist": "9",
        "d": "d", "debug": "d", "nang cao": "d", "nâng cao": "d"
    }
    key = raw.strip().lower()
    return aliases.get(key, key)


def ask_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw, 0)
    except ValueError:
        print(color("Giá trị không hợp lệ, dùng mặc định.", "red"))
        return default


def ask_yes_no(prompt: str) -> bool:
    while True:
        raw = input(f"{prompt} (y/n): ").strip().lower()
        if raw in ("y", "yes", "co", "có", "1", ""):
            return True
        if raw in ("n", "no", "khong", "không", "0"):
            return False
        print("Nhập y hoặc n (Mặc định: Yes nếu nhấn Enter).")


def print_status(status: Status) -> None:
    # Lấy nhị phân của byte thấp nhất để hiển thị trực quan các bit
    b_src = (status.raw >> 4) & 1
    b_wdo = (status.raw >> 3) & 1
    b_enout = (status.raw >> 2) & 1
    b_fault = (status.raw >> 1) & 1
    b_en = (status.raw >> 0) & 1
    bin_str = f"0b_000{b_src}_{b_wdo}_{b_enout}_{b_fault}_{b_en}"

    lines = [
        f"STATUS raw      : {color(f'0x{status.raw:08X}', 'cyan')}  ({muted(bin_str)})",
        f"EN_EFFECTIVE    : {status.en_effective}  {on_off_badge(status.en_effective, 'BẬT', 'TẮT')}  {muted('watchdog effective enable')}",
        f"FAULT_ACTIVE    : {status.fault_active}  "
        f"{color(' ĐANG FAULT ', 'red') if status.fault_active else color(' KHÔNG FAULT ', 'green')}",
        f"ENOUT           : {status.enout}  {on_off_badge(status.enout, 'MONITOR', 'IDLE')}",
        f"WDO             : {status.wdo}  "
        f"{color(' BÌNH THƯỜNG ', 'green') if status.wdo else color(' ASSERT FAULT/RESET ', 'red')}",
        f"LAST_KICK_SRC   : {status.last_kick_src}  {color(status.last_kick_src_name, 'yellow')}",
    ]
    print()
    print_box("TRẠNG THÁI WATCHDOG HIỆN TẠI", lines)


def print_board_hint() -> None:
    print()
    print_box(
        "GỢI Ý ĐÈN/NÚT TRÊN BOARD",
        [
            f"{color('S1', 'yellow'):<4}: nút kick watchdog ở chế độ button",
            f"{color('S2', 'yellow'):<4}: enable phần cứng (Nhấn giữ = Disable)",
            f"{color('D3', 'yellow'):<4}: Sáng đỏ khi báo FAULT / WDO",
            f"{color('D4', 'yellow'):<4}: Sáng xanh khi ENOUT báo watchdog đang monitor",
        ],
    )
    print()


def connect_once(state: AppState, verbose: bool = False) -> WatchdogUart:
    return WatchdogUart(state.port, state.baud, state.timeout, verbose=verbose)


def action_status(state: AppState) -> None:
    try:
        dev = connect_once(state)
        try:
            status = dev.get_status()
        finally:
            dev.close()
        print_status(status)
        state.mark("status", "PASS", f"STATUS=0x{status.raw:08X}")
    except Exception as e:
        msg = handle_serial_error(e)
        state.mark("status", "FAIL", msg)
        print(color(f"\n[!] LỖI: {msg}", "red"))


def action_setcfg(state: AppState) -> None:
    print("\nNhập thông số demo. Bấm Enter để dùng giá trị mặc định.")
    state.twd_ms = ask_int("tWD_ms - quá thời gian này mà không kick thì fault", state.twd_ms)
    state.trst_ms = ask_int("tRST_ms - thời gian giữ fault/WDO", state.trst_ms)
    state.arm_us = ask_int("arm_delay_us - delay trước khi vào monitor", state.arm_us)

    try:
        dev = connect_once(state)
        try:
            dev.write_reg(ADDR_TWD_MS, state.twd_ms, 4)
            dev.write_reg(ADDR_TRST_MS, state.trst_ms, 4)
            dev.write_reg(ADDR_ARM_DELAY_US, state.arm_us, 2)
            status = dev.get_status()
        finally:
            dev.close()

        print_status(status)
        state.mark("setcfg", "PASS", f"tWD={state.twd_ms} ms, tRST={state.trst_ms} ms, arm={state.arm_us} us")
    except Exception as e:
        msg = handle_serial_error(e)
        state.mark("setcfg", "FAIL", msg)
        print(color(f"\n[!] LỖI: {msg}", "red"))


def action_button_demo(state: AppState) -> None:
    print_board_hint()
    print("MỤC TIÊU: Cấu hình watchdog dùng nút S1 làm nguồn kick.")
    
    if state.twd_ms < 1000:
        print(color(f"\n[!] tWD_ms hiện tại là {state.twd_ms} ms, quá nhanh cho bấm tay.", "yellow"))
        if ask_yes_no("Đổi nhanh sang tWD=1600 ms, tRST=200 ms để dễ quay video không?"):
            state.twd_ms = 1600
            state.trst_ms = 200
            state.arm_us = 150
            action_setcfg_no_prompt(state)

    try:
        dev = connect_once(state)
        try:
            dev.write_reg(ADDR_CTRL, 0x00000001, 4)  # EN_SW=1, WDI_SRC=button
            time.sleep(0.2)
            status = dev.get_status()
        finally:
            dev.close()

        print_status(status)
        print(color("\n--- HƯỚNG DẪN QUAY DEMO NÚT ---", "cyan"))
        print("  1) Nhả S2 để enable phần cứng.")
        print("  2) Chờ xíu, đèn D4 sẽ sáng lên (Đã vào Monitor).")
        print("  3) Bấm S1 định kỳ trước khi hết tWD_ms, quan sát đèn D3 tắt.")
        print(color("  4) Dừng bấm S1, chờ hết tWD_ms -> Đèn D3 SÁNG LÊN báo FAULT.", "red"))
        print("  5) Nhấn/giữ S2 để disable, D3/D4 tắt hết.")
        print()
        ok = ask_yes_no("Quan sát trên board có đúng như mô tả không?")
        state.mark("button_mode", "PASS" if ok else "FAIL", "Người dùng xác nhận từ board")
    except Exception as e:
        msg = handle_serial_error(e)
        state.mark("button_mode", "FAIL", msg)
        print(color(f"\n[!] LỖI: {msg}", "red"))


def action_uart_auto_test(state: AppState) -> None:
    print(color("\n[TEST TỰ ĐỘNG UART]", "cyan"))
    print("  - Bước 1: Set nguồn kick = UART")
    print("  - Bước 2: Gửi kick định kỳ và check WDO")
    print("  - Bước 3: Dừng kick, chờ timeout để check fault\n")

    if state.twd_ms < 300:
        print(color(f"[!] tWD_ms hiện tại là {state.twd_ms} ms. Hơi ngắn, tự đổi thành 1000 ms.", "yellow"))
        state.twd_ms = 1000
        state.trst_ms = max(state.trst_ms, 1000)

    default_interval_ms = int(max(50, state.twd_ms / 3))
    interval_ms = ask_int("Nhập khoảng thời gian giữa 2 lần gửi Kick (ms)", default_interval_ms)
    interval_s = interval_ms / 1000.0
    
    kick_count = ask_int("Nhập số lần muốn gửi Kick để demo", 10)

    try:
        dev = connect_once(state)
        try:
            dev.write_reg(ADDR_TWD_MS, state.twd_ms, 4)
            dev.write_reg(ADDR_TRST_MS, state.trst_ms, 4)
            dev.write_reg(ADDR_ARM_DELAY_US, state.arm_us, 2)
            dev.write_reg(ADDR_CTRL, 0x00000003, 4)  # EN_SW=1, WDI_SRC=UART
            time.sleep(0.2)

            print(color("\n>>> ĐANG CHẠY: Gửi lệnh Kick liên tục...", "yellow"))
            pass_during_kick = True
            for i in range(kick_count):
                rsp = dev.kick()
                status = Status(int.from_bytes(rsp.payload, "big")) if len(rsp.payload) == 4 else dev.get_status()
                
                # Highlight fault status during kick
                fault_txt = color("CÓ FAULT", "red") if status.fault_active else color("OK", "green")
                print(f"  [Kick {i + 1:02d}/{kick_count}] Gửi sau {interval_ms}ms -> Trạng thái: {fault_txt}")
                
                if status.fault_active != 0 or status.wdo != 1 or status.last_kick_src != 1:
                    pass_during_kick = False
                time.sleep(interval_s)

            if pass_during_kick:
                state.mark("uart_kick", "PASS", "Kick UART giữ watchdog an toàn")
            else:
                state.mark("uart_kick", "FAIL", "Bị Fault ngay cả khi đang kick")

            wait_s = max(0.3, state.twd_ms / 1000.0 + 0.25)
            print(color(f"\n>>> ĐANG CHẠY: Dừng kick đột ngột! Đếm ngược {wait_s:.1f}s chờ Timeout sinh Fault...", "yellow"))
            
            # Progress bar cho Timeout
            steps = 20
            for s in range(steps + 1):
                percent = int(s / steps * 100)
                bar = '█' * s + '░' * (steps - s)
                print(f"\r  Chờ đợi: [{bar}] {percent}%", end="", flush=True)
                time.sleep(wait_s / steps)
            print() # Xuống dòng
            
            status_timeout = dev.get_status()
            print_status(status_timeout)

            if status_timeout.fault_active == 1 and status_timeout.wdo == 0:
                print(color("=> THÀNH CÔNG: Đã sinh FAULT đúng kỳ vọng!", "green"))
                state.mark("timeout", "PASS", "Dừng kick thì sinh fault đúng")
            else:
                print(color("=> THẤT BẠI: Chưa thấy sinh FAULT!", "red"))
                state.mark("timeout", "FAIL", f"STATUS=0x{status_timeout.raw:08X}")

        finally:
            dev.close()

    except Exception as e:
        msg = handle_serial_error(e)
        state.mark("uart_kick", "FAIL", msg)
        print(color(f"\n[!] LỖI: {msg}", "red"))


def action_clear_fault(state: AppState) -> None:
    print()
    print("CÁCH XÓA FAULT:")
    print("  1) Clear rồi vẫn Enable (Dễ bị fault lại ngay nếu không kick kịp)")
    print("  2) Clear rồi Disable (Trạng thái đứng yên, dễ quay video nhất)")
    choice = input("Chọn 1 hoặc 2 [2]: ").strip() or "2"

    value = 0x00000005 if choice == "1" else 0x00000004

    try:
        dev = connect_once(state)
        try:
            rsp = dev.write_reg(ADDR_CTRL, value, 4)
            status = Status(int.from_bytes(rsp.payload, "big")) if len(rsp.payload) == 4 else dev.get_status()
        finally:
            dev.close()

        print_status(status)
        if status.fault_active == 0 and status.wdo == 1:
            state.mark("clear_fault", "PASS", f"CTRL=0x{value:08X}")
        else:
            state.mark("clear_fault", "CẦN XEM LẠI", f"STATUS=0x{status.raw:08X}")
    except Exception as e:
        msg = handle_serial_error(e)
        state.mark("clear_fault", "FAIL", msg)
        print(color(f"\n[!] LỖI: {msg}", "red"))


def action_disable(state: AppState) -> None:
    try:
        dev = connect_once(state)
        try:
            rsp = dev.write_reg(ADDR_CTRL, 0x00000000, 4)
            status = Status(int.from_bytes(rsp.payload, "big")) if len(rsp.payload) == 4 else dev.get_status()
        finally:
            dev.close()

        print_status(status)
        if status.en_effective == 0:
            state.mark("disable", "PASS", "Watchdog disabled")
        else:
            state.mark("disable", "CẦN XEM LẠI", f"STATUS=0x{status.raw:08X}")
    except Exception as e:
        msg = handle_serial_error(e)
        state.mark("disable", "FAIL", msg)
        print(color(f"\n[!] LỖI: {msg}", "red"))


def action_live_monitor(state: AppState) -> None:
    print(color("\n[LIVE MONITOR] Theo dõi trạng thái liên tục. Nhấn Ctrl+C để dừng.", "cyan"))
    try:
        dev = connect_once(state)
        try:
            while True:
                status = dev.get_status()
                # Dùng \r để in đè lên dòng cũ, tránh giật màn hình
                sys.stdout.write(
                    f"\r[{datetime.now().strftime('%H:%M:%S')}] "
                    f"RAW: 0x{status.raw:08X} | "
                    f"EN: {status.en_effective} | "
                    f"FAULT: {color('1 (LỖI)', 'red') if status.fault_active else color('0 (OK)', 'green')} | "
                    f"ENOUT: {status.enout} | "
                    f"SRC: {status.last_kick_src_name:<6}"
                )
                sys.stdout.flush()
                time.sleep(0.2)
        finally:
            dev.close()
    except KeyboardInterrupt:
        print("\n\nĐã dừng theo dõi.")
    except Exception as e:
        msg = handle_serial_error(e)
        print(color(f"\n\n[!] LỖI Monitor: {msg}", "red"))


def action_full_demo_script(state: AppState) -> None:
    clear_screen()
    print(color("="*60, "bold"))
    print(color("      BẮT ĐẦU KỊCH BẢN DEMO KHUYẾN NGHỊ (4 GIAI ĐOẠN)", "cyan"))
    print(color("="*60, "bold"))

    # --- GIAI ĐOẠN 1 ---
    print(color("\n[GIAI ĐOẠN 1/4] CẤU HÌNH THỜI GIAN", "yellow"))
    if ask_yes_no("Bạn có muốn dùng cấu hình khuyến nghị (tWD=1600ms, tRST=200ms) không?"):
        state.twd_ms = 1600
        state.trst_ms = 200
        state.arm_us = 150
        action_setcfg_no_prompt(state)
    else:
        print("\nMời bạn tự nhập cấu hình mới:")
        action_setcfg(state)
    pause()

    # --- GIAI ĐOẠN 2 ---
    clear_screen()
    print(color("\n[GIAI ĐOẠN 2/4] TEST UART KICK AUTO & TIMEOUT FAULT", "yellow"))
    print("Lưu ý: Bạn hãy chuẩn bị quay camera vào đèn D3 trên board.")
    action_uart_auto_test(state)
    pause()

    # --- GIAI ĐOẠN 3 ---
    clear_screen()
    print(color("\n[GIAI ĐOẠN 3/4] XÓA FAULT", "yellow"))
    action_clear_fault_quick_disabled(state)
    pause()

    # --- GIAI ĐOẠN 4 ---
    clear_screen()
    print(color("\n[GIAI ĐOẠN 4/4] DEMO NÚT BẤM CỨNG (S1/S2)", "yellow"))
    action_button_demo(state)
    
    print(color("\nĐÃ HOÀN THÀNH KỊCH BẢN DEMO!", "green"))


def action_setcfg_no_prompt(state: AppState) -> None:
    try:
        dev = connect_once(state)
        try:
            dev.write_reg(ADDR_TWD_MS, state.twd_ms, 4)
            dev.write_reg(ADDR_TRST_MS, state.trst_ms, 4)
            dev.write_reg(ADDR_ARM_DELAY_US, state.arm_us, 2)
            status = dev.get_status()
        finally:
            dev.close()
        print_status(status)
        state.mark("setcfg", "PASS", f"tWD={state.twd_ms}, tRST={state.trst_ms}, arm={state.arm_us}")
    except Exception as e:
        msg = handle_serial_error(e)
        state.mark("setcfg", "FAIL", msg)
        print(color(f"\n[!] LỖI: {msg}", "red"))


def action_clear_fault_quick_disabled(state: AppState) -> None:
    try:
        dev = connect_once(state)
        try:
            rsp = dev.write_reg(ADDR_CTRL, 0x00000004, 4)
            status = Status(int.from_bytes(rsp.payload, "big")) if len(rsp.payload) == 4 else dev.get_status()
        finally:
            dev.close()
        print_status(status)
        state.mark("clear_fault", "PASS" if status.fault_active == 0 else "CẦN XEM LẠI", "Clear + disable")
    except Exception as e:
        msg = handle_serial_error(e)
        state.mark("clear_fault", "FAIL", msg)
        print(color(f"\n[!] LỖI: {msg}", "red"))


def show_checklist(state: AppState) -> None:
    lines: list[str] = []
    for item in state.results.values():
        lines.append(f"{item.name:<25} : {result_badge(item.result)}")
        if item.detail:
            lines.append(f"  {muted('↳')} {item.detail}")
    print()
    print_box("TỔNG HỢP CHECKLIST TEST", lines)


def action_raw_rw(state: AppState) -> None:
    print("\nRaw read/write register")
    print("  1) Read")
    print("  2) Write")
    choice = input("Chọn [1]: ").strip() or "1"
    try:
        dev = connect_once(state, verbose=True)
        try:
            if choice == "1":
                addr = ask_int("Địa chỉ register", ADDR_STATUS)
                width = ask_int("Width byte, 2 hoặc 4", 4)
                value = dev.read_reg(addr, width)
                print(f"READ 0x{addr:02X} = 0x{value:0{width * 2}X} ({value})")
            else:
                addr = ask_int("Địa chỉ register", ADDR_CTRL)
                value = ask_int("Giá trị", 0)
                width = ask_int("Width byte, 2 hoặc 4", 4)
                rsp = dev.write_reg(addr, value, width)
                print(f"WRITE OK, payload phản hồi: {hexdump(rsp.payload)}")
        finally:
            dev.close()
    except Exception as e:
        print(color(f"Lỗi raw R/W: {e}", "red"))


def save_report(state: AppState) -> str:
    os.makedirs("reports", exist_ok=True)
    path = os.path.join("reports", f"watchdog_menu_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

    lines = []
    lines.append("BÁO CÁO TEST WATCHDOG KIWI 1P5")
    lines.append("=" * 45)
    lines.append(f"Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Port    : {state.port}")
    lines.append(f"Baud    : {state.baud}")
    lines.append(f"tWD_ms  : {state.twd_ms}")
    lines.append(f"tRST_ms : {state.trst_ms}")
    lines.append(f"arm_us  : {state.arm_us}")
    lines.append("")
    lines.append("CHECKLIST:")
    for item in state.results.values():
        lines.append(f"- {item.name}: {item.result}")
        if item.detail:
            lines.append(f"  {item.detail}")
    lines.append("")
    lines.append("LOG:")
    lines.extend(state.log_lines)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return path


def action_debug_menu(state: AppState) -> None:
    while True:
        clear_screen()
        lines = [
            f"{hotkey('1')} Ghi/Đọc Raw Register",
            f"{hotkey('2')} Lưu báo cáo tiến độ ra file TXT",
            f"{hotkey('0')} Quay lại menu chính"
        ]
        print_box("MENU DEBUG / NÂNG CAO", lines)
        
        c = input("Chọn: ").strip()
        if c == '1':
            action_raw_rw(state)
            pause()
        elif c == '2':
            path = save_report(state)
            print(color(f"\nĐã lưu báo cáo tại: {path}", "green"))
            pause()
        elif c in ('0', 'q', 'quit', 'exit'):
            break


def print_menu(state: AppState) -> None:
    done = sum(1 for item in state.results.values() if item.result == "PASS")
    total = len(state.results)
    failed = sum(1 for item in state.results.values() if item.result == "FAIL")

    lines = [
        f"Port {color(state.port, 'cyan')}  |  Baud {state.baud}  |  "
        f"tWD {color(str(state.twd_ms) + ' ms', 'yellow')}  |  "
        f"tRST {state.trst_ms} ms",
        f"Tiến độ: {color(str(done) + '/' + str(total) + ' PASS', 'green')}"
        + (f"  |  {color(str(failed) + ' FAIL', 'red')}" if failed else ""),
        ""
    ]

    # Hiển thị trực tiếp các checklist quan trọng lên Menu
    lines.append(color("TRẠNG THÁI DEMO TÓM TẮT", "bold"))
    for key in ["setcfg", "uart_kick", "timeout", "button_mode", "clear_fault"]:
        if key in state.results:
            item = state.results[key]
            lines.append(f"  {item.name:<25} : {result_badge(item.result)}")
            
    lines.extend([
        "",
        color("MENU ĐIỀU KHIỂN", "bold"),
        f"{hotkey('1')} Xem trạng thái hiện tại        {hotkey('7')} Live Monitor (Trực tiếp)",
        f"{hotkey('2')} Cấu hình thời gian tWD/tRST    {hotkey('8')} {color('Chạy Kịch bản Demo 4 bước', 'yellow')}",
        f"{hotkey('3')} Demo nút S1/S2                 {hotkey('9')} Xem toàn bộ Checklist",
        f"{hotkey('4')} Test UART kick tự động",
        "",
        f"{hotkey('5')} Xóa fault / Clear              {hotkey('D')} Menu Debug / Lưu báo cáo",
        f"{hotkey('6')} Tắt Watchdog (Disable)         {hotkey('0')} Thoát chương trình",
    ])
    print()
    print_box("WATCHDOG KIWI 1P5 DEMO TOOL", lines)


def test_connection(state: AppState) -> None:
    try:
        dev = connect_once(state)
        try:
            status = dev.get_status()
        finally:
            dev.close()
        state.mark("uart_connect", "PASS", f"Đọc được STATUS=0x{status.raw:08X}")
    except Exception as e:
        msg = handle_serial_error(e)
        state.mark("uart_connect", "FAIL", msg)
        print(color(f"\n[CẢNH BÁO MỞ ĐẦU] Kết nối thất bại. Lỗi: {msg}", "red"))
        print("Hãy kiểm tra lại dây cáp, cổng COM hoặc tốc độ Baud đang sử dụng.")
        time.sleep(2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Menu tiếng Việt cho demo Watchdog Kiwi 1P5")
    parser.add_argument("--port", default=None, help="COM port, ví dụ COM9")
    parser.add_argument("--baud", type=int, default=9600, help="Baudrate, mặc định 9600")
    parser.add_argument("--timeout", type=float, default=1.0, help="Serial timeout, mặc định 1.0 giây")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    port = args.port
    if not port:
        # Tự động quét và liệt kê cổng COM
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            port = input("Không tìm thấy cổng COM nào. Nhập tay (VD: COM9): ").strip()
        else:
            print("Danh sách cổng COM đang kết nối:")
            for i, p in enumerate(ports):
                print(f"  [{i+1}] {p.device} - {p.description}")
            print(f"  [0] Nhập tay thủ công")
            
            idx = ask_int("Chọn cổng COM", 1)
            if idx == 0:
                port = input("Nhập cổng COM: ").strip()
            elif 1 <= idx <= len(ports):
                port = ports[idx-1].device
            else:
                port = ports[0].device
                
    if not port:
        print("Chưa nhập COM port. Thoát.")
        return 2

    state = AppState(port=port, baud=args.baud, timeout=args.timeout)

    clear_screen()
    print(f"Đang kiểm tra kết nối UART tại {port}...")
    test_connection(state)

    while True:
        print_menu(state)
        choice = normalize_choice(input(color("Chọn mục (0-9 hoặc D): ", "bold")).strip())

        if choice == "1":
            action_status(state)
            pause()
        elif choice == "2":
            action_setcfg(state)
            pause()
        elif choice == "3":
            action_button_demo(state)
            pause()
        elif choice == "4":
            action_uart_auto_test(state)
            pause()
        elif choice == "5":
            action_clear_fault(state)
            pause()
        elif choice == "6":
            action_disable(state)
            pause()
        elif choice == "7":
            action_live_monitor(state)
            pause()
        elif choice == "8":
            action_full_demo_script(state)
            pause()
        elif choice == "9":
            show_checklist(state)
            pause()
        elif choice == "d":
            action_debug_menu(state)
        elif choice == "0":
            print("Thoát menu. Hẹn gặp lại!")
            return 0
        else:
            print("Lựa chọn không hợp lệ.")
            pause()

        clear_screen()


if __name__ == "__main__":
    raise SystemExit(main())