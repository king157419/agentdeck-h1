@echo off
chcp 65001 >nul
setlocal DisableDelayedExpansion
set "AGENTDECK_CAPTURE_SELF=%~f0"
set "AGENTDECK_CAPTURE_DIR=%~dp0"

rem Official sequence and keywords, checked before implementation:
rem https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/how-to-capture-a-usb-event-trace
rem This script only records ETW. It never opens or writes to a USB/HID device.
powershell.exe -NoProfile -Command "$p = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()); if ($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 0 }; exit 1"
if not errorlevel 1 goto elevated
echo 请在 UAC 提示中选择“是”，随后在新窗口按步骤操作。
powershell.exe -NoProfile -Command "try { $q = [char]34; $p = Start-Process -FilePath $env:ComSpec -ArgumentList ('/d /s /c ' + $q + $q + $env:AGENTDECK_CAPTURE_SELF + $q + $q) -Verb RunAs -Wait -PassThru -ErrorAction Stop; exit $p.ExitCode } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 goto elevation_failed
exit /b 0

:elevated
set "AGENTDECK_CAPTURE_SESSION=AgentDeckLight-%RANDOM%-%RANDOM%"
set "AGENTDECK_CAPTURE_STEM=%AGENTDECK_CAPTURE_DIR%%AGENTDECK_CAPTURE_SESSION%"
echo 正在建立 USB 只读跟踪，请稍候……
logman create trace -n "%AGENTDECK_CAPTURE_SESSION%" -o "%AGENTDECK_CAPTURE_STEM%.etl" -nb 128 640 -bs 128
if errorlevel 1 goto create_failed
logman update trace -n "%AGENTDECK_CAPTURE_SESSION%" -p Microsoft-Windows-USB-USBXHCI "(Default,PartialDataBusTrace)"
if errorlevel 1 goto failed
logman update trace -n "%AGENTDECK_CAPTURE_SESSION%" -p Microsoft-Windows-USB-UCX "(Default,PartialDataBusTrace)"
if errorlevel 1 goto failed
logman update trace -n "%AGENTDECK_CAPTURE_SESSION%" -p Microsoft-Windows-USB-USBHUB3 "(Default,PartialDataBusTrace)"
if errorlevel 1 goto failed
logman update trace -n "%AGENTDECK_CAPTURE_SESSION%" -p Microsoft-Windows-USB-USBPORT
if errorlevel 1 goto failed
logman update trace -n "%AGENTDECK_CAPTURE_SESSION%" -p Microsoft-Windows-USB-USBHUB
if errorlevel 1 goto failed
logman update trace -n "%AGENTDECK_CAPTURE_SESSION%" -p Microsoft-Windows-Kernel-IoTrace 0 2
if errorlevel 1 goto failed
logman start -n "%AGENTDECK_CAPTURE_SESSION%"
if errorlevel 1 goto failed
echo.
echo 已开始抓包。请在 CXT Hub 依次操作，每步完成后停 3 秒：
echo 1. 将第 1 颗键改成红色，停 3 秒。
echo 2. 将第 1 颗键改成绿色，停 3 秒。
echo 3. 将第 1 颗键改成蓝色，停 3 秒。
echo 4. 将第 2 颗键改成红色，停 3 秒。
echo 5. 将亮度调到最低，停 3 秒。
echo 6. 将亮度调到最高，停 3 秒。
echo.
echo 操作期间保持本窗口打开；六步完成后回到这里按回车停止。
set /p "AGENTDECK_CAPTURE_DONE=> "
logman stop -n "%AGENTDECK_CAPTURE_SESSION%"
if errorlevel 1 goto stop_failed
logman delete -n "%AGENTDECK_CAPTURE_SESSION%"
if errorlevel 1 goto delete_failed
rem Logman may append _000001. Move only this run's exact known output path.
powershell.exe -NoProfile -Command "try { $source = $env:AGENTDECK_CAPTURE_STEM + '_000001.etl'; if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { $source = $env:AGENTDECK_CAPTURE_STEM + '.etl' }; if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'No ETL output was generated.' }; $target = Join-Path $env:AGENTDECK_CAPTURE_DIR 'light.etl'; if (Test-Path -LiteralPath $target) { $backup = Join-Path $env:AGENTDECK_CAPTURE_DIR ('light-previous-' + [Guid]::NewGuid().ToString('N') + '.etl'); Move-Item -LiteralPath $target -Destination $backup -ErrorAction Stop }; Move-Item -LiteralPath $source -Destination $target -ErrorAction Stop; Write-Host $target } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 goto output_failed
echo.
echo 抓包完成，文件："%AGENTDECK_CAPTURE_DIR%light.etl"
echo 如有旧 light.etl，已另存为 light-previous-*.etl。
pause
exit /b 0

:failed
echo 跟踪配置或启动失败，正在清理本次会话。
logman stop -n "%AGENTDECK_CAPTURE_SESSION%" >nul 2>&1
logman delete -n "%AGENTDECK_CAPTURE_SESSION%"
goto unsuccessful

:stop_failed
echo 停止失败。请保留本窗口并手动执行下面两条命令：
echo logman stop -n "%AGENTDECK_CAPTURE_SESSION%"
echo logman delete -n "%AGENTDECK_CAPTURE_SESSION%"
goto unsuccessful

:delete_failed
echo 跟踪已停止，但删除会话失败。请手动执行：
echo logman delete -n "%AGENTDECK_CAPTURE_SESSION%"
goto unsuccessful

:output_failed
echo 无法整理输出，原始 ETL 如已生成则保留于："%AGENTDECK_CAPTURE_STEM%*.etl"
goto unsuccessful

:create_failed
echo 无法建立跟踪，未修改其他跟踪会话。
goto unsuccessful

:elevation_failed
echo 提权未完成，请重新双击并在 UAC 中选择“是”。

:unsuccessful
echo 本次未完成抓包。
pause
exit /b 1
