#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Menu tiếng Việt cho demo Kiwi 1P5 Watchdog qua UART.

Cách dùng:
    python demo\\watchdog_menu_vi.py --port COM9

Yêu cầu:
    python -m pip install pyserial

Protocol:
    UART 9600 8N1
    Frame: [0x55][CMD][ADDR][LEN][DATA...][CHK]
    CHK = XOR từ CMD đến DATA
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
from typing import Dict, Optional, Tuple

try:
    import serial
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
    twd_ms: int = 2000
    trst_ms: int = 2000
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
        print(line)


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
        # READ dùng LEN=0. Không gửi width trong payload để tránh ERR_BAD_LEN.
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
    """Bật ANSI color trên Windows Terminal / PowerShell mới, nếu có hỗ trợ."""
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
    # Giới hạn để menu không quá rộng trên màn hình lớn, vẫn gọn trên terminal nhỏ.
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
    input(color("\nNhấn Enter để tiếp tục...", "dim"))


def normalize_choice(raw: str) -> str:
    aliases = {
        "q": "0", "quit": "0", "exit": "0", "thoat": "0", "thoát": "0",
        "s": "1", "status": "1", "trangthai": "1", "trạng thái": "1",
        "cfg": "2", "config": "2", "cau hinh": "2", "cấu hình": "2",
        "button": "3", "btn": "3", "nut": "3", "nút": "3",
        "uart": "4", "kick": "4", "auto": "4",
        "clear": "5", "xoa": "5", "xóa": "5",
        "disable": "6", "off": "6", "tat": "6", "tắt": "6",
        "mon": "7", "monitor": "7", "live": "7",
        "raw": "8", "rw": "8",
        "demo": "9", "flow": "9",
        "check": "10", "checklist": "10",
        "report": "11", "bao cao": "11", "báo cáo": "11",
    }
    key = raw.strip().lower()
    return aliases.get(key, key)


def ask_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    return int(raw, 0)


def ask_yes_no(prompt: str) -> bool:
    while True:
        raw = input(f"{prompt} (y/n): ").strip().lower()
        if raw in ("y", "yes", "co", "có", "1"):
            return True
        if raw in ("n", "no", "khong", "không", "0"):
            return False
        print("Nhập y hoặc n.")


def print_status(status: Status) -> None:
    lines = [
        f"STATUS raw      : {color(f'0x{status.raw:08X}', 'cyan')}",
        f"EN_EFFECTIVE    : {status.en_effective}  {on_off_badge(status.en_effective, 'BẬT', 'TẮT')}  {muted('watchdog effective enable')}",
        f"FAULT_ACTIVE    : {status.fault_active}  "
        f"{color(' ĐANG FAULT ', 'red') if status.fault_active else color(' KHÔNG FAULT ', 'green')}",
        f"ENOUT           : {status.enout}  {on_off_badge(status.enout, 'MONITOR', 'IDLE')}",
        f"WDO             : {status.wdo}  "
        f"{color(' BÌNH THƯỜNG ', 'green') if status.wdo else color(' ASSERT FAULT/RESET ', 'red')}",
        f"LAST_KICK_SRC   : {status.last_kick_src}  {color(status.last_kick_src_name, 'yellow')}",
    ]
    print()
    print_box("TRẠNG THÁI WATCHDOG", lines)


def print_board_hint() -> None:
    print()
    print_box(
        "GỢI Ý LED / NÚT TRÊN BOARD",
        [
            f"{color('S1', 'yellow'):<4}: nút kick watchdog ở chế độ button",
            f"{color('S2', 'yellow'):<4}: enable phần cứng",
            f"{color('D3', 'yellow'):<4}: fault / WDO",
            f"{color('D4', 'yellow'):<4}: ENOUT / watchdog đang monitor",
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
        state.mark("status", "FAIL", str(e))


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
        state.mark(
            "setcfg",
            "PASS",
            f"tWD={state.twd_ms} ms, tRST={state.trst_ms} ms, arm={state.arm_us} us",
        )
    except Exception as e:
        state.mark("setcfg", "FAIL", str(e))


def action_button_demo(state: AppState) -> None:
    print_board_hint()
    print("Bước này cấu hình watchdog dùng nút S1 làm nguồn kick.")
    print("Khuyến nghị: tWD_ms >= 2000 để bấm tay kịp.")
    print()

    if state.twd_ms < 1000:
        print(f"tWD_ms hiện tại là {state.twd_ms} ms, hơi nhanh cho bấm tay.")
        if ask_yes_no("Đổi nhanh sang tWD=2000 ms, tRST=2000 ms không"):
            state.twd_ms = 2000
            state.trst_ms = 2000
            state.arm_us = 150
            try:
                dev = connect_once(state)
                try:
                    dev.write_reg(ADDR_TWD_MS, state.twd_ms, 4)
                    dev.write_reg(ADDR_TRST_MS, state.trst_ms, 4)
                    dev.write_reg(ADDR_ARM_DELAY_US, state.arm_us, 2)
                finally:
                    dev.close()
                state.mark("setcfg", "PASS", "Đã đổi sang cấu hình dễ demo nút")
            except Exception as e:
                state.mark("setcfg", "FAIL", str(e))
                return

    try:
        dev = connect_once(state)
        try:
            dev.write_reg(ADDR_CTRL, 0x00000001, 4)  # EN_SW=1, WDI_SRC=button
            time.sleep(0.2)
            status = dev.get_status()
        finally:
            dev.close()

        print_status(status)
        print()
        print("Hướng dẫn quay demo nút:")
        print("  1) Thả S2 để enable phần cứng.")
        print("  2) D4 nên sáng sau arm delay.")
        print("  3) Bấm S1 định kỳ trước khi hết tWD_ms, D3 phải tắt.")
        print("  4) Dừng bấm S1 lâu hơn tWD_ms, D3 phải sáng báo fault.")
        print("  5) Nhấn/giữ S2 để disable, D3/D4 phải tắt hoặc về trạng thái disable.")
        print()
        ok = ask_yes_no("Quan sát trên board có đúng như mô tả không")
        state.mark("button_mode", "PASS" if ok else "FAIL", "Người dùng xác nhận từ board")
    except Exception as e:
        state.mark("button_mode", "FAIL", str(e))


def action_uart_auto_test(state: AppState) -> None:
    print()
    print("Test tự động UART:")
    print("  - Set nguồn kick = UART")
    print("  - Gửi kick định kỳ")
    print("  - Kiểm tra không fault khi còn kick")
    print("  - Dừng kick và chờ timeout")
    print("  - Kiểm tra có fault")
    print()

    if state.twd_ms < 300:
        print("tWD_ms quá nhỏ cho test UART ổn định, tự đổi thành 1000 ms.")
        state.twd_ms = 1000
        state.trst_ms = max(state.trst_ms, 1000)

    interval = max(0.05, min(0.5, state.twd_ms / 3000.0))
    kick_count = 10

    try:
        dev = connect_once(state)
        try:
            dev.write_reg(ADDR_TWD_MS, state.twd_ms, 4)
            dev.write_reg(ADDR_TRST_MS, state.trst_ms, 4)
            dev.write_reg(ADDR_ARM_DELAY_US, state.arm_us, 2)
            dev.write_reg(ADDR_CTRL, 0x00000003, 4)  # EN_SW=1, WDI_SRC=UART
            time.sleep(0.2)

            pass_during_kick = True
            for i in range(kick_count):
                rsp = dev.kick()
                status = Status(int.from_bytes(rsp.payload, "big")) if len(rsp.payload) == 4 else dev.get_status()
                print(
                    f"KICK {i + 1:02d}/{kick_count}: "
                    f"FAULT={status.fault_active}, WDO={status.wdo}, SRC={status.last_kick_src_name}"
                )
                if status.fault_active != 0 or status.wdo != 1 or status.last_kick_src != 1:
                    pass_during_kick = False
                time.sleep(interval)

            status_after_kick = dev.get_status()
            print_status(status_after_kick)

            if pass_during_kick and status_after_kick.fault_active == 0:
                state.mark("uart_kick", "PASS", "Kick UART giữ watchdog không fault")
            else:
                state.mark("uart_kick", "FAIL", f"STATUS=0x{status_after_kick.raw:08X}")

            wait_s = max(0.3, state.twd_ms / 1000.0 + 0.25)
            print(f"\nDừng kick, chờ {wait_s:.2f} giây để kiểm tra timeout...")
            time.sleep(wait_s)
            status_timeout = dev.get_status()
            print_status(status_timeout)

            if status_timeout.fault_active == 1 and status_timeout.wdo == 0:
                state.mark("timeout", "PASS", "Dừng kick thì sinh fault đúng")
            else:
                state.mark("timeout", "FAIL", f"STATUS=0x{status_timeout.raw:08X}")

        finally:
            dev.close()

    except Exception as e:
        state.mark("uart_kick", "FAIL", str(e))


def action_clear_fault(state: AppState) -> None:
    print()
    print("Có 2 kiểu xóa fault:")
    print("  1) Clear rồi vẫn enable: có thể fault lại nếu không kick kịp.")
    print("  2) Clear rồi disable: trạng thái đứng yên, dễ quay video hơn.")
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
        state.mark("clear_fault", "FAIL", str(e))


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
        state.mark("disable", "FAIL", str(e))


def action_live_monitor(state: AppState) -> None:
    print()
    print("Theo dõi trạng thái liên tục. Nhấn Ctrl+C để dừng.")
    try:
        dev = connect_once(state)
        try:
            while True:
                status = dev.get_status()
                print(
                    f"{datetime.now().strftime('%H:%M:%S')} | "
                    f"RAW=0x{status.raw:08X} | "
                    f"EN={status.en_effective} | "
                    f"FAULT={status.fault_active} | "
                    f"ENOUT={status.enout} | "
                    f"WDO={status.wdo} | "
                    f"SRC={status.last_kick_src_name}"
                )
                time.sleep(0.5)
        finally:
            dev.close()
    except KeyboardInterrupt:
        print("\nĐã dừng theo dõi.")
    except Exception as e:
        print(f"Lỗi monitor: {e}")


def action_raw_rw(state: AppState) -> None:
    print()
    print("Raw read/write register")
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
        print(f"Lỗi raw R/W: {e}")


def action_full_demo_script(state: AppState) -> None:
    print()
    print("Chế độ này chạy flow khuyến nghị để quay video:")
    print("  1) Set cấu hình dễ demo")
    print("  2) Test UART tự động")
    print("  3) Clear fault")
    print("  4) Chuyển sang button mode và hướng dẫn bấm S1/S2")
    print()

    if ask_yes_no("Set cấu hình tWD=2000 ms, tRST=2000 ms, arm=150 us"):
        state.twd_ms = 2000
        state.trst_ms = 2000
        state.arm_us = 150
        action_setcfg_no_prompt(state)

    action_uart_auto_test(state)
    action_clear_fault_quick_disabled(state)
    action_button_demo(state)


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
        state.mark("setcfg", "FAIL", str(e))


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
        state.mark("clear_fault", "FAIL", str(e))


def show_checklist(state: AppState) -> None:
    lines: list[str] = []
    for item in state.results.values():
        lines.append(f"{item.name:<32} : {result_badge(item.result)}")
        if item.detail:
            lines.append(f"  {muted('↳')} {item.detail}")

    lines.extend(
        [
            "",
            color("CẤU HÌNH HIỆN TẠI", "bold"),
            f"PORT   : {color(state.port, 'cyan')}",
            f"BAUD   : {state.baud}",
            f"tWD    : {state.twd_ms} ms",
            f"tRST   : {state.trst_ms} ms",
            f"ARM    : {state.arm_us} us",
        ]
    )
    print()
    print_box("CHECKLIST TEST", lines)


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


def test_connection(state: AppState) -> None:
    try:
        dev = connect_once(state)
        try:
            status = dev.get_status()
        finally:
            dev.close()
        state.mark("uart_connect", "PASS", f"Đọc được STATUS=0x{status.raw:08X}")
    except Exception as e:
        state.mark("uart_connect", "FAIL", str(e))


def print_menu(state: AppState) -> None:
    done = sum(1 for item in state.results.values() if item.result == "PASS")
    total = len(state.results)
    failed = sum(1 for item in state.results.values() if item.result == "FAIL")

    lines = [
        f"Port {color(state.port, 'cyan')}  |  Baud {state.baud}  |  "
        f"tWD {color(str(state.twd_ms) + ' ms', 'yellow')}  |  "
        f"tRST {state.trst_ms} ms  |  ARM {state.arm_us} us",
        f"Checklist: {color(str(done) + '/' + str(total) + ' PASS', 'green')}"
        + (f"  |  {color(str(failed) + ' FAIL', 'red')}" if failed else ""),
        "",
        color("THAO TÁC NHANH", "bold"),
        f"{hotkey('1')} Xem trạng thái hiện tại        {muted('đọc STATUS/WDO/ENOUT')}",
        f"{hotkey('7')} Theo dõi trạng thái liên tục   {muted('live monitor, Ctrl+C để dừng')}",
        f"{hotkey('10')} Xem checklist PASS/FAIL       {muted('tổng hợp kết quả test')}",
        "",
        color("CẤU HÌNH / TEST DEMO", "bold"),
        f"{hotkey('2')} Cấu hình thời gian demo        {muted('tWD, tRST, arm delay')}",
        f"{hotkey('3')} Demo nút S1/S2                 {muted('button mode')}",
        f"{hotkey('4')} Test UART kick tự động         {muted('auto kick + timeout')}",
        f"{hotkey('9')} Chạy flow demo khuyến nghị     {muted('flow quay video')}",
        "",
        color("ĐIỀU KHIỂN / DEBUG", "bold"),
        f"{hotkey('5')} Xóa fault                      {muted('clear fault')}",
        f"{hotkey('6')} Disable watchdog               {muted('tắt watchdog')}",
        f"{hotkey('8')} Raw read/write register        {muted('debug register')}",
        f"{hotkey('11')} Lưu báo cáo test ra file      {muted('reports/*.txt')}",
        f"{hotkey('0')} Thoát                          {muted('hoặc nhập q')}",
        "",
        muted("Mẹo: có thể nhập alias như status, cfg, uart, demo, check, report, q."),
    ]
    print()
    print_box("MENU DEMO WATCHDOG KIWI 1P5 - TIẾNG VIỆT", lines)


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
        port = input("Nhập cổng COM của board, ví dụ COM9: ").strip()
    if not port:
        print("Chưa nhập COM port.")
        return 2

    state = AppState(port=port, baud=args.baud, timeout=args.timeout)

    clear_screen()
    print("Đang kiểm tra kết nối UART...")
    test_connection(state)

    while True:
        print_menu(state)
        choice = normalize_choice(input(color("Chọn mục (0-11 hoặc q): ", "bold")).strip())

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
            action_raw_rw(state)
            pause()
        elif choice == "9":
            action_full_demo_script(state)
            pause()
        elif choice == "10":
            show_checklist(state)
            pause()
        elif choice == "11":
            path = save_report(state)
            print(f"Đã lưu báo cáo: {path}")
            pause()
        elif choice == "0":
            print("Thoát menu.")
            return 0
        else:
            print("Lựa chọn không hợp lệ.")
            pause()

        clear_screen()


if __name__ == "__main__":
    raise SystemExit(main())
