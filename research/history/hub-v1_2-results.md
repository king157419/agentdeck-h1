# Hub v1.2 implementation and verification

Implemented `brief-hub-v1_2.md` with offline substitutes throughout verification.

Before editing, copied the current complete `pc/` and `lcd1602/` folders into
`_rollback/hub-v1_1/pc/` and `_rollback/hub-v1_1/lcd1602/`. Existing files at the
backup root were preserved.

Changed files:

| File | Change |
| --- | --- |
| `pc/hub.py` | HTTP/USB press and release dispatch, paired physical releases, transient LCD notices, guard lifecycle, approval/input blocking and completion generation checks. |
| `pc/hub_desktop.py` | Original-session/window snapshot, 100 ms daemon guard, 60-second timeout, native window existence check, focus recovery counts/logs, stop/retry handling and compatible immediate down/up. |
| `pc/hub_keys.json` | Default H down/up binding; strings remain compatible. |
| `pc/test_hub.py` | HTTP, USB, LCD, lifecycle, stale completion and failed-close integration coverage. |
| `pc/test_hub_desktop.py` | Injected windows, clock and tick tests for recovery, limits, loss, concurrent release and failure handling. |
| `pc/hub_README.md` | v1.2 actions, binding format, guard behavior and limitations. |
| `pc/hub_test_output.txt` | Complete stdout/stderr and exit codes from every test script and simulator. |
| `research/hub-v1_2-results.md` | This report. |

Reused the existing deck activation logic, including AttachThreadInput fallback,
and the existing LCD scrolling name field. Added no dependencies or firmware
protocol. Firmware source and the regenerated preview image are byte-identical
to the snapshot.

Voice release stops and joins the guard; successful start/release sends exactly
two Win+H combinations. Duplicate transitions cannot toggle another interval.
Timeout, window loss or failed recovery also stop the guard. A failed closing
shortcut keeps dictation ownership and blocks approval/window/input actions;
an explicit `voice_up` retries closing without starting another guard. This
also covers failure to start the guard thread. No voice path approves, pastes
text, sends Enter or sends Esc.

All commands below used `D:/conda/miniconda3/python.exe` from the project root.
Every command exited 0. The output column contains actual output excerpts;
the complete output is in `pc/hub_test_output.txt`.

| Script | Actual output |
| --- | --- |
| `pc/test_ui.py` | `UI: 7 groups passed` |
| `pc/test_daemon.py` | `daemon offline tests: 10 groups passed` |
| `pc/test_pc.py` | `PC and firmware loop: 4 groups passed` |
| `pc/test_hub.py` | `Ran 107 tests in 1.447s` / `OK` |
| `pc/test_hub_desktop.py` | `Ran 30 tests in 0.174s` / `OK` |
| `pc/test_hub_doctor.py` | `Ran 7 tests in 0.100s` / `OK` |
| `pc/test_hub_install.py` | `Ran 9 tests in 0.065s` / `OK` |
| `pc/test_hub_relay.py` | `Ran 3 tests in 0.143s` / `OK` |
| `pc/test_deck.py` | `AgentDeck offline tests: 55 groups passed` |
| `pc/test_deck_exclusive.py` | `deck exclusive offline tests: 9 groups passed` |
| `pc/test_deck_input.py` | `deck Raw Input offline tests: 4 groups passed` |
| `pc/test_deck_keymap.py` | `Keymap offline tests: 13 groups passed` |
| `pc/test_deck_probe.py` | `deck probe offline tests: 7 groups passed` |
| `pc/test_deck_usb.py` | `deck USB offline tests: 24 groups passed` |
| `pc/test_focus_lock.py` | `focus lock offline tests: 4 groups passed` |
| `pc/sim.py` | `Rendered 42 scenarios -> D:\desk\hardware\h1\lcd1602\preview-sim.png` |

Static verification: `AST + py_compile: 4 files OK`; `hub_keys.json: valid JSON`.
There is no configured linter/type checker, and ruff/mypy are not installed.
Warning/error messages in the test log exercise injected failure paths.

Remaining verification limits: Windows speech input and physical-device behavior
were not exercised. A 100 ms focus check cannot eliminate the interval before
the next check or establish Windows' internal dictation toggle state. No COM4
access, firmware upload, real key injection, hook installation or driver/keymap
changes occurred.
