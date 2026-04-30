#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UART test tool for Kiwi 1P5 Watchdog demo.

Protocol assumptions:
- UART: 9600 8N1
- TX frame: [0x55][CMD][ADDR][LEN][DATA...][CHK]
- CHK = XOR of bytes from CMD through DATA
- Multi-byte values are big-endian
- OK response:  [0x55][CMD|0x80][ADDR][LEN][DATA...][CHK]
- ERR response: [0x55][0x7F][CMD][0x01][ERR_CODE][CHK]

Register map:
0x00 CTRL         R/W 32
0x04 tWD_ms       R/W 32
0x08 tRST_ms      R/W 32
0x0C arm_delay_us R/W 16
0x10 STATUS       R   32
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Optional

import serial


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
    0x07: "uart frame error",
}

def xor_checksum(data: bytes) -> int:
    chk = 0
    for b in data:
        chk ^= b
    return chk & 0xFF


def build_frame(cmd: int, addr: int, payload: bytes = b"") -> bytes:
    if not 0 <= cmd <= 0xFF:
        raise ValueError("cmd out of range")
    if not 0 <= addr <= 0xFF:
        raise ValueError("addr out of range")
    if len(payload) > 0xFF:
        raise ValueError("payload too long")

    body = bytes([cmd, addr, len(payload)]) + payload
    chk = xor_checksum(body)
    return bytes([SYNC]) + body + bytes([chk])


@dataclass
class Response:
    raw: bytes
    ok: bool
    cmd: int
    addr: int
    payload: bytes
    error_code: Optional[int] = None

    def payload_u32(self) -> Optional[int]:
        if len(self.payload) == 4:
            return int.from_bytes(self.payload, "big")
        return None

    def payload_u16(self) -> Optional[int]:
        if len(self.payload) == 2:
            return int.from_bytes(self.payload, "big")
        return None


def read_exact(ser: serial.Serial, n: int) -> bytes:
    data = ser.read(n)
    if len(data) != n:
        raise TimeoutError(f"Timeout while reading {n} bytes, got {len(data)}")
    return data


def read_response(ser: serial.Serial) -> Response:
    # hunt sync
    while True:
        b = read_exact(ser, 1)[0]
        if b == SYNC:
            break

    header = read_exact(ser, 3)
    cmd, addr_or_orig_cmd, length = header
    payload = read_exact(ser, length)
    chk = read_exact(ser, 1)[0]

    calc = xor_checksum(header + payload)
    raw = bytes([SYNC]) + header + payload + bytes([chk])

    if chk != calc:
        raise ValueError(
            f"Bad response checksum: recv=0x{chk:02X}, calc=0x{calc:02X}, raw={raw.hex(' ')}"
        )

    if cmd == 0x7F:
        if length != 1:
            raise ValueError(f"Error response LEN must be 1, got {length}")
        return Response(
            raw=raw,
            ok=False,
            cmd=addr_or_orig_cmd,
            addr=0,
            payload=b"",
            error_code=payload[0],
        )

    return Response(
        raw=raw,
        ok=True,
        cmd=cmd,
        addr=addr_or_orig_cmd,
        payload=payload,
    )


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def print_status_word(status: int) -> None:
    en_effective = (status >> 0) & 1
    fault_active = (status >> 1) & 1
    enout = (status >> 2) & 1
    wdo = (status >> 3) & 1
    last_kick_src = (status >> 4) & 1

    print(f"STATUS = 0x{status:08X}")
    print(f"  EN_EFFECTIVE : {en_effective}")
    print(f"  FAULT_ACTIVE : {fault_active}")
    print(f"  ENOUT        : {enout}")
    print(f"  WDO          : {wdo}")
    print(f"  LAST_KICK_SRC: {last_kick_src} ({'uart' if last_kick_src else 'button'})")


class WatchdogUart:
    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 1.0):
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

    def transact(self, cmd: int, addr: int, payload: bytes = b"", quiet: bool = False) -> Response:
        frame = build_frame(cmd, addr, payload)
        if not quiet:
            print(f"TX: {hexdump(frame)}")
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()
        rsp = read_response(self.ser)
        if not quiet:
            print(f"RX: {hexdump(rsp.raw)}")
        return rsp

    def read_reg(self, addr: int, width: int) -> int:
        rsp = self.transact(CMD_READ_REG, addr, b"")
        if not rsp.ok:
            raise RuntimeError(f"READ_REG error: {ERR_CODES.get(rsp.error_code, rsp.error_code)}")
        if len(rsp.payload) != width:
            raise RuntimeError(f"Unexpected READ_REG length: {len(rsp.payload)} != {width}")
        return int.from_bytes(rsp.payload, "big")

    def write_reg(self, addr: int, value: int, width: int) -> Response:
        payload = value.to_bytes(width, "big")
        rsp = self.transact(CMD_WRITE_REG, addr, payload)
        if not rsp.ok:
            raise RuntimeError(f"WRITE_REG error: {ERR_CODES.get(rsp.error_code, rsp.error_code)}")
        return rsp

    def get_status(self) -> int:
        rsp = self.transact(CMD_GET_STATUS, ADDR_STATUS, b"")
        if not rsp.ok:
            raise RuntimeError(f"GET_STATUS error: {ERR_CODES.get(rsp.error_code, rsp.error_code)}")
        if len(rsp.payload) != 4:
            raise RuntimeError(f"Unexpected STATUS length: {len(rsp.payload)}")
        return int.from_bytes(rsp.payload, "big")

    def kick(self) -> Response:
        rsp = self.transact(CMD_KICK, 0x00, b"")
        if not rsp.ok:
            raise RuntimeError(f"KICK error: {ERR_CODES.get(rsp.error_code, rsp.error_code)}")
        return rsp


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="UART tester for Kiwi 1P5 watchdog")
    p.add_argument("--port", required=True, help="COM port, e.g. COM7")
    p.add_argument("--baud", type=int, default=9600, help="UART baudrate (default: 9600)")
    p.add_argument("--timeout", type=float, default=1.0, help="serial timeout in seconds")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Read STATUS and decode it")

    rd = sub.add_parser("read", help="Read a register")
    rd.add_argument("addr", type=lambda x: int(x, 0), help="register address, e.g. 0x10")
    rd.add_argument("width", type=int, choices=[2, 4], help="register width in bytes")

    wr = sub.add_parser("write", help="Write a register")
    wr.add_argument("addr", type=lambda x: int(x, 0), help="register address")
    wr.add_argument("value", type=lambda x: int(x, 0), help="value")
    wr.add_argument("width", type=int, choices=[2, 4], help="register width in bytes")

    sub.add_parser("enable_button", help="CTRL=0x00000001 (EN_SW=1, WDI_SRC=button)")
    sub.add_parser("enable_uart", help="CTRL=0x00000003 (EN_SW=1, WDI_SRC=uart)")
    sub.add_parser("disable", help="CTRL=0x00000000")

    kick = sub.add_parser("kick", help="Send one KICK command")
    kick.add_argument("--count", type=int, default=1, help="number of kicks")
    kick.add_argument("--interval", type=float, default=0.2, help="seconds between kicks")

    cfg = sub.add_parser("setcfg", help="Set watchdog timings")
    cfg.add_argument("--twd-ms", type=int, help="tWD in ms")
    cfg.add_argument("--trst-ms", type=int, help="tRST in ms")
    cfg.add_argument("--arm-us", type=int, help="arm_delay in us")

    demo = sub.add_parser("demo_uart", help="Enable UART kick mode and kick periodically")
    demo.add_argument("--interval", type=float, default=0.2, help="kick interval in seconds")
    demo.add_argument("--count", type=int, default=20, help="number of kicks")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    dev = WatchdogUart(args.port, args.baud, args.timeout)

    try:
        if args.cmd == "status":
            status = dev.get_status()
            print_status_word(status)
            return 0

        if args.cmd == "read":
            value = dev.read_reg(args.addr, args.width)
            print(f"READ  addr=0x{args.addr:02X} value=0x{value:0{args.width * 2}X} ({value})")
            return 0

        if args.cmd == "write":
            rsp = dev.write_reg(args.addr, args.value, args.width)
            print(f"WRITE OK, response payload: {rsp.payload.hex(' ')}")
            if len(rsp.payload) == 4:
                print_status_word(int.from_bytes(rsp.payload, "big"))
            return 0

        if args.cmd == "enable_button":
            rsp = dev.write_reg(ADDR_CTRL, 0x00000001, 4)
            print("Enabled: button source")
            if len(rsp.payload) == 4:
                print_status_word(int.from_bytes(rsp.payload, "big"))
            return 0

        if args.cmd == "enable_uart":
            rsp = dev.write_reg(ADDR_CTRL, 0x00000003, 4)
            print("Enabled: uart source")
            if len(rsp.payload) == 4:
                print_status_word(int.from_bytes(rsp.payload, "big"))
            return 0

        if args.cmd == "disable":
            rsp = dev.write_reg(ADDR_CTRL, 0x00000000, 4)
            print("Disabled")
            if len(rsp.payload) == 4:
                print_status_word(int.from_bytes(rsp.payload, "big"))
            return 0

        if args.cmd == "kick":
            for i in range(args.count):
                rsp = dev.kick()
                print(f"KICK {i + 1}/{args.count} OK")
                if len(rsp.payload) == 4:
                    print_status_word(int.from_bytes(rsp.payload, "big"))
                if i != args.count - 1:
                    time.sleep(args.interval)
            return 0

        if args.cmd == "setcfg":
            if args.twd_ms is not None:
                dev.write_reg(ADDR_TWD_MS, args.twd_ms, 4)
                print(f"tWD_ms set to {args.twd_ms}")
            if args.trst_ms is not None:
                dev.write_reg(ADDR_TRST_MS, args.trst_ms, 4)
                print(f"tRST_ms set to {args.trst_ms}")
            if args.arm_us is not None:
                dev.write_reg(ADDR_ARM_DELAY_US, args.arm_us, 2)
                print(f"arm_delay_us set to {args.arm_us}")

            status = dev.get_status()
            print_status_word(status)
            return 0

        if args.cmd == "demo_uart":
            dev.write_reg(ADDR_CTRL, 0x00000003, 4)
            print("UART kick mode enabled")
            time.sleep(0.3)
            for i in range(args.count):
                dev.kick()
                print(f"Periodic kick {i + 1}/{args.count}")
                time.sleep(args.interval)
            status = dev.get_status()
            print_status_word(status)
            return 0

        print("Unknown command")
        return 2

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        dev.close()


if __name__ == "__main__":
    raise SystemExit(main())