@echo off
setlocal
cd /d "%~dp0"
set "AGENTDECK_PYTHON=D:\conda\miniconda3\python.exe"
rem PyInstaller resolves conda DLLs (ffi, tcl/tk, ssl, bz2) via PATH; without this the exe dies on import _ctypes.
set "PATH=D:\conda\miniconda3;D:\conda\miniconda3\Library\bin;D:\conda\miniconda3\DLLs;%PATH%"
if not exist "%AGENTDECK_PYTHON%" (
  echo Python not found: %AGENTDECK_PYTHON%
  exit /b 1
)
"%AGENTDECK_PYTHON%" -c "import PyInstaller; assert PyInstaller.__version__ == '6.11.1', 'PyInstaller 6.11.1 required'"
if errorlevel 1 exit /b 1
"%AGENTDECK_PYTHON%" pc\agentdeck_icon.py
if errorlevel 1 exit /b 1
"%AGENTDECK_PYTHON%" -m PyInstaller --noconfirm --clean --distpath dist --workpath build agentdeck.spec
if errorlevel 1 exit /b 1
if not exist "dist\AgentDeck\AgentDeck.exe" exit /b 1
if not exist "dist\AgentDeck\AgentDeck-relay.exe" exit /b 1
if not exist "dist\AgentDeck\_internal\ffi*.dll" (echo Missing ffi DLL in bundle & exit /b 1)
echo Built: %CD%\dist\AgentDeck\AgentDeck.exe
echo Relay: %CD%\dist\AgentDeck\AgentDeck-relay.exe
exit /b 0
