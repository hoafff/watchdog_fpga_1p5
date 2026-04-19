@echo off
setlocal

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set ROOT_DIR=%%~fI
set RTL_DIR=%ROOT_DIR%\rtl
set TB_DIR=%ROOT_DIR%\tb
set BUILD_DIR=%ROOT_DIR%\build
set SIM_OUT=%BUILD_DIR%\tb_top.vvp
set VCD_OUT=%BUILD_DIR%\tb_top.vcd

if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
if exist "%SIM_OUT%" del /f /q "%SIM_OUT%"
if exist "%VCD_OUT%" del /f /q "%VCD_OUT%"

echo [run_tb.bat] compiling with Icarus Verilog...
iverilog -g2012 -I "%TB_DIR%" -o "%SIM_OUT%" ^
  "%RTL_DIR%\timebase_gen.v" ^
  "%RTL_DIR%\button_conditioner.v" ^
  "%RTL_DIR%\watchdog_core.v" ^
  "%RTL_DIR%\regfile.v" ^
  "%RTL_DIR%\uart_rx.v" ^
  "%RTL_DIR%\uart_tx.v" ^
  "%RTL_DIR%\uart_protocol.v" ^
  "%RTL_DIR%\top_watchdog_kiwi1p5.v" ^
  "%TB_DIR%\tb_uart_host.sv" ^
  "%TB_DIR%\tb_top.sv"
if errorlevel 1 goto :fail

echo [run_tb.bat] running simulation...
pushd "%BUILD_DIR%"
vvp "%SIM_OUT%"
if errorlevel 1 (
  popd
  goto :fail
)
popd

if exist "%VCD_OUT%" (
  echo [run_tb.bat] waveform: %VCD_OUT%
  where gtkwave >nul 2>nul
  if not errorlevel 1 (
    echo [run_tb.bat] opening GTKWave...
    start "" gtkwave "%VCD_OUT%"
  )
) else (
  echo [run_tb.bat] warning: VCD file not found at %VCD_OUT%
)

echo [run_tb.bat] done.
exit /b 0

:fail
echo [run_tb.bat] failed.
exit /b 1
