# 用 venv 里的 pio 重新编译（可在任意目录运行）。用法: .\build.ps1 [额外 pio 参数]
$ErrorActionPreference = 'Stop'
$proj = $PSScriptRoot
$pio  = Join-Path $proj '..\..\.pio-venv\Scripts\pio.exe'
if (-not (Test-Path $pio)) { throw "找不到 $pio ，请先重建 venv：D:\conda\miniconda3\python.exe -m venv D:\desk\hardware\.pio-venv ; 再 pip install platformio" }
& $pio run -d $proj @args
if ($LASTEXITCODE -eq 0) {
  $f = Join-Path $proj '.pio\build\esp32dev\firmware.bin'
  "OK: $f ($((Get-Item $f).Length) bytes)"
}
exit $LASTEXITCODE
