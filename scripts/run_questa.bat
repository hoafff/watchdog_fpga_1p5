@echo off
setlocal

set SCRIPT_DIR=%~dp0
set ROOT_DIR=%SCRIPT_DIR%..

pushd "%ROOT_DIR%"
vsim -do scripts/run_questa.do
set RC=%ERRORLEVEL%
popd

exit /b %RC%
