@echo off
rem Start the AgentDeck Hub without a console window. Pass --usb to add the USB backend.
setlocal
cd /d "%~dp0"
set "BACKEND=hotkey"
if /i "%~1"=="--usb" set "BACKEND=usb,hotkey"
curl -s -m 1 http://127.0.0.1:47800/health >nul 2>&1 && (echo Hub already running. & goto :eof)
start "" "D:\conda\miniconda3\pythonw.exe" pc\hub.py --backend %BACKEND% --overlay --require-nonce
call :wait
goto :eof

:wait
for /l %%i in (1,1,20) do (
  curl -s -m 1 http://127.0.0.1:47800/health >nul 2>&1 && (echo Hub is up. & exit /b 0)
  timeout /t 1 /nobreak >nul
)
echo Hub did not answer /health within 20 s.
exit /b 1
