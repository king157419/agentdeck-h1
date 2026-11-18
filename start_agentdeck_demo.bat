@echo off
rem Start the Hub (hotkey backend + overlay), then run the scripted pitch demo in this console.
rem Pass --virtual to also open the software twin (pc\hub_virtual_device.py).
rem Pass --usb to add the USB backend; other arguments (--step, --speed N) go to hub_demo.py.
setlocal
cd /d "%~dp0"
set "BACKEND=hotkey"
set "DEMOARGS=%*"
set "VIRTUAL="
echo %* | find /i "--virtual" >nul && set "VIRTUAL=1"
if /i "%~1"=="--usb" (
  set "BACKEND=usb,hotkey"
  shift
  set "DEMOARGS=%1 %2 %3 %4 %5 %6 %7 %8 %9"
)
curl -s -m 1 http://127.0.0.1:47800/health >nul 2>&1 && goto :demo
start "" "D:\conda\miniconda3\pythonw.exe" pc\hub.py --backend %BACKEND% --overlay --require-nonce
set "UP="
for /l %%i in (1,1,20) do if not defined UP (
  curl -s -m 1 http://127.0.0.1:47800/health >nul 2>&1 && set "UP=1"
  if not defined UP timeout /t 1 /nobreak >nul
)
if not defined UP (
  echo Hub did not answer /health within 20 s.
  pause
  exit /b 1
)

:demo
if defined VIRTUAL call set "DEMOARGS=%%DEMOARGS:--virtual=%%"
if defined VIRTUAL start "" "D:\conda\miniconda3\pythonw.exe" pc\hub_virtual_device.py --topmost
echo Hub is up. Starting the demo (Ctrl+C stops and cleans up).
"D:\conda\miniconda3\python.exe" pc\hub_demo.py %DEMOARGS%
echo.
"D:\conda\miniconda3\python.exe" pc\hub_demo.py --cleanup
pause
