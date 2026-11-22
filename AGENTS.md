# h1 — Agent status display (ESP32 + 1602A character LCD)

Read `lcd1602/README.md` first: it documents the screen layout, serial protocol, files and commands.

- Firmware is MicroPython in `lcd1602/` (`main.py`, `ui.py`, `lcd1602.py`). `ui.py` must stay runnable under CPython so the offline tests work.
- PC side is in `pc/` (hooks, daemon, preview, simulator, tests).
- Use `D:\conda\miniconda3\python.exe` as `python`.
- After any change run, from the project root: `python pc/test_ui.py`, `python pc/test_daemon.py`, `python pc/test_pc.py`, and `python pc/sim.py` when the display output changed. Report the real output.
- Do not open the serial port (COM4) or upload firmware; the user does that. Do not touch `wokwi/`, `backup/`, `_rollback/`.
- Before editing firmware, copy the current `lcd1602/` and `pc/` into `_rollback/<current version>/` if that folder does not exist yet.
- Keep changes small and say which files changed. Functionality comes first; do not rework sprites or animations unless the task says so.
- 重启 AgentDeck 只用 `restart_agentdeck.bat`（通过计划任务启动）。用 `Start-Process` 或直接运行 exe 会让 Claude 在退出时把 AgentDeck 一起关掉。
