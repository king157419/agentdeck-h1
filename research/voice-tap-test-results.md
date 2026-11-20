# Voice tap test results

Interpreter: `D:/conda/miniconda3/python.exe -X utf8`.

All 43 `pc/test_*.py` scripts were run as separate Python processes from the project root. Each process used an isolated temporary HOME/USERPROFILE. Final result: **43/43 exit 0**.

The initial full run exposed two keyboard-adapter test errors because a fake action returned None. The feedback guard was corrected to accept non-dict results. `test_hub_keyboard.py`, `test_hub.py`, `test_hub_voice_tap.py` and `test_hub_keypad.py` were rerun successfully; the table uses their final results.

| Script | Exit | Actual output summary |
| --- | --- | --- |
| `pc/test_agentdeck_app.py` | 0 | Ran 139 tests in 1.358s; OK |
| `pc/test_capture_etl.py` | 0 | Ran 18 tests in 2.707s; OK |
| `pc/test_daemon.py` | 0 | daemon offline tests: 10 groups passed |
| `pc/test_deck.py` | 0 | AgentDeck offline tests: 61 groups passed |
| `pc/test_deck_exclusive.py` | 0 | deck exclusive offline tests: 9 groups passed |
| `pc/test_deck_input.py` | 0 | deck Raw Input offline tests: 5 groups passed |
| `pc/test_deck_keymap.py` | 0 | Keymap offline tests: 13 groups passed |
| `pc/test_deck_probe.py` | 0 | deck probe offline tests: 7 groups passed |
| `pc/test_deck_usb.py` | 0 | deck USB offline tests: 26 groups passed |
| `pc/test_focus_lock.py` | 0 | focus lock offline tests: 4 groups passed |
| `pc/test_hub.py` | 0 | Ran 164 tests in 6.845s; OK |
| `pc/test_hub_app_support.py` | 0 | Ran 24 tests in 0.596s; OK |
| `pc/test_hub_app_switch.py` | 0 | Ran 10 tests in 3.088s; OK |
| `pc/test_hub_demo.py` | 0 | Ran 10 tests in 0.553s; OK |
| `pc/test_hub_desktop.py` | 0 | Ran 70 tests in 0.463s; OK |
| `pc/test_hub_desktop_mac.py` | 0 | Ran 35 tests in 0.125s; OK |
| `pc/test_hub_doctor.py` | 0 | Ran 17 tests in 0.432s; OK |
| `pc/test_hub_fixes.py` | 0 | Ran 24 tests in 4.890s; OK |
| `pc/test_hub_gate.py` | 0 | Ran 20 tests in 2.428s; OK |
| `pc/test_hub_hold.py` | 0 | Ran 30 tests in 1.094s; OK |
| `pc/test_hub_hotkey.py` | 0 | Ran 36 tests in 0.030s; OK |
| `pc/test_hub_input_capture.py` | 0 | Ran 7 tests in 0.244s; OK |
| `pc/test_hub_install.py` | 0 | Ran 40 tests in 1.830s; OK |
| `pc/test_hub_keyboard.py` | 0 | Ran 27 tests in 0.055s; OK |
| `pc/test_hub_keypad.py` | 0 | Ran 44 tests in 2.925s; OK |
| `pc/test_hub_macos_fix.py` | 0 | Ran 3 tests in 0.057s; OK |
| `pc/test_hub_nonce.py` | 0 | Ran 33 tests in 1.219s; OK |
| `pc/test_hub_nonce_integration.py` | 0 | Ran 16 tests in 1.318s; OK |
| `pc/test_hub_overlay.py` | 0 | Ran 38 tests in 0.245s; OK |
| `pc/test_hub_overlay_position.py` | 0 | Ran 10 tests in 0.035s; OK |
| `pc/test_hub_relay.py` | 0 | Ran 45 tests in 5.336s; OK |
| `pc/test_hub_risk.py` | 0 | Ran 4 tests in 0.008s; OK |
| `pc/test_hub_runtime.py` | 0 | Ran 8 tests in 0.658s; OK |
| `pc/test_hub_screenshot.py` | 0 | Ran 14 tests in 0.123s; OK |
| `pc/test_hub_tk_wake.py` | 0 | Ran 18 tests in 19.480s; OK |
| `pc/test_hub_ui_live.py` | 0 | Ran 15 tests in 32.200s; OK |
| `pc/test_hub_virtual_device.py` | 0 | Ran 15 tests in 0.004s; OK |
| `pc/test_hub_virtual_nonce_integration.py` | 0 | Ran 7 tests in 5.299s; OK |
| `pc/test_hub_voice_tap.py` | 0 | Ran 9 tests in 0.050s; OK |
| `pc/test_hub_watchdog.py` | 0 | Ran 6 tests in 4.031s; OK |
| `pc/test_pc.py` | 0 | PC and firmware loop: 4 groups passed |
| `pc/test_ui.py` | 0 | UI: 7 groups passed |
| `pc/test_verify_real_session.py` | 0 | Ran 20 tests in 53.234s; OK |

Additional checks:

- New tap regressions: 9 tests passed. The tray recording/save test also passed in the application suite (139 tests).
- Existing hold/toggle desktop suite: 70 tests passed.
- `python pc/sim.py`: `Rendered 42 scenarios -> D:\desk\hardware\h1\lcd1602\preview-sim.png` (exit 0).
- `git -c core.whitespace=cr-at-eol diff --check` for the changed tracked Python files: exit 0. All 5 changed/new Python files passed AST parsing; added/changed lines have no trailing whitespace.
- No configured lint/typecheck task was found; ruff, mypy and pyright are not installed. No dependencies were installed.
- Manual PDF: generated using the brief's report.py command from a temporary Markdown copy, exit 0. 12 pages; all rendered pages passed visual inspection. Text extraction confirms tap, single-tap and Right Alt instructions.
- Real keyboard/Typeless interaction was not exercised; input is mocked. No firmware upload, serial access, EXE packaging or git commit was performed.

Raw execution logs: `C:\Users\king\AppData\Local\Temp\agentdeck-voice-tap-u94ofi35\tests`.
