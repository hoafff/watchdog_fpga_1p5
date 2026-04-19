#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RTL_DIR="$ROOT_DIR/rtl"
TB_DIR="$ROOT_DIR/tb"
BUILD_DIR="$ROOT_DIR/build"
SIM_OUT="$BUILD_DIR/tb_top.vvp"
VCD_OUT="$BUILD_DIR/tb_top.vcd"

mkdir -p "$BUILD_DIR"
rm -f "$SIM_OUT" "$VCD_OUT"

echo "[run_tb.sh] compiling with Icarus Verilog..."
iverilog -g2012 \
  -I "$TB_DIR" \
  -o "$SIM_OUT" \
  "$RTL_DIR/timebase_gen.v" \
  "$RTL_DIR/button_conditioner.v" \
  "$RTL_DIR/watchdog_core.v" \
  "$RTL_DIR/regfile.v" \
  "$RTL_DIR/uart_rx.v" \
  "$RTL_DIR/uart_tx.v" \
  "$RTL_DIR/uart_protocol.v" \
  "$RTL_DIR/top_watchdog_kiwi1p5.v" \
  "$TB_DIR/tb_uart_host.sv" \
  "$TB_DIR/tb_top.sv"

echo "[run_tb.sh] running simulation..."
(
  cd "$BUILD_DIR"
  vvp "$SIM_OUT"
)

if [[ -f "$VCD_OUT" ]]; then
  echo "[run_tb.sh] waveform: $VCD_OUT"
  if [[ "${NO_GUI:-0}" != "1" ]] && command -v gtkwave >/dev/null 2>&1; then
    echo "[run_tb.sh] opening GTKWave..."
    gtkwave "$VCD_OUT" >/dev/null 2>&1 &
  fi
else
  echo "[run_tb.sh] warning: VCD file not found at $VCD_OUT"
fi
