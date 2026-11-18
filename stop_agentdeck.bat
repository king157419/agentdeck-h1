@echo off
rem Stop only processes whose command line contains pc/hub.py (the Hub), nothing else.
powershell -NoProfile -Command "$n=0; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'pc[\\/]hub\.py' -and $_.Name -match '^pythonw?\.exe$' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $n++; Write-Host ('Stopped PID ' + $_.ProcessId) }; if ($n -eq 0) { Write-Host 'No hub process found.' }"
