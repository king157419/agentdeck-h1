@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "AGENTDECK_DIR=%USERPROFILE%\.agentdeck"
set "AGENTDECK_MAINTENANCE=%AGENTDECK_DIR%\maintenance"
if not exist "%AGENTDECK_DIR%\" mkdir "%AGENTDECK_DIR%" || exit /b 1
type nul > "%AGENTDECK_MAINTENANCE%" || exit /b 1

taskkill /IM AgentDeck.exe /F
if errorlevel 1 (
    powershell.exe -NoProfile -NonInteractive -Command "if (Get-Process -Name AgentDeck -ErrorAction SilentlyContinue) { exit 1 }; exit 0"
    if errorlevel 1 (
        del /q "%AGENTDECK_MAINTENANCE%"
        exit /b 1
    )
)
if /i "%~1"=="build" (
    call build_exe.bat
    if errorlevel 1 (
        del /q "%AGENTDECK_MAINTENANCE%"
        exit /b 1
    )
)

del /q "%AGENTDECK_MAINTENANCE%"
if exist "%AGENTDECK_MAINTENANCE%" exit /b 1
schtasks /Run /TN AgentDeck
if errorlevel 1 exit /b 1

powershell.exe -NoProfile -NonInteractive -Command "$timer = [Diagnostics.Stopwatch]::StartNew(); while ($timer.ElapsedMilliseconds -lt 15000) { $app = Get-Process -Name AgentDeck -ErrorAction SilentlyContinue; if ($app) { foreach ($process in $app) { Write-Output ('AgentDeck PID: ' + $process.Id) }; exit 0 }; Start-Sleep -Milliseconds 200 }; Write-Error 'AgentDeck did not start within 15 seconds'; exit 1"
exit /b %errorlevel%
