# Hub replay implementation results

Implemented `research/brief-hub-replay.md`. Before editing, copied `pc/` and
`lcd1602/` into `_rollback/hub-v1_2/pc/` and `_rollback/hub-v1_2/lcd1602/`;
existing backups were preserved. Firmware was not modified.

## Mapping

Use `D:/conda/miniconda3/python.exe pc/hub.py --backend usb --profile v2_emulation`
when the user wants the physical keyboard to drive Hub. The existing default
profile is unchanged. The complete physical labeling table, HID codes and
pending confirmations are in [pc/hub_keys.md](../pc/hub_keys.md).

| Physical key | HID binding | Action |
| --- | --- | --- |
| E | `hid:0x08` | `slot 1` |
| B | `hid:0x05` | `slot 2` |
| Factory Ctrl+Z | `ctrl+hid:0x1D` | `slot 3` |
| Space | `hid:0x2C` | `slot 4` |
| Knob 2 press Q | `hid:0x14` | `slot 5` |
| Knob 3 press V | `hid:0x19` | `slot 6` |
| G | `hid:0x0A` | `approve` |
| Factory Ctrl+F | `ctrl+hid:0x09` | `deny` |
| Hold / release H | `hid:0x0B` | `voice_down` / `voice_up` |
| Knob 1 press L | `hid:0x0F` | `screenshot` |
| Knob 4 press Ctrl+0 | `ctrl+hid:0x27` | Alternate `interrupt` |
| Knob 1 clockwise / counterclockwise S / F | `hid:0x16` / `hid:0x09` | `cycle +1` / `cycle -1` |
| Knob 2 clockwise / counterclockwise R / P | `hid:0x15` / `hid:0x13` | `cycle +1` / `cycle -1` |
| Knob 3 clockwise / counterclockwise - / = | `hid:0x2D` / `hid:0x2E` | `cycle +1` / `cycle -1` |
| Knob 4 clockwise / counterclockwise ] / [ | `hid:0x30` / `hid:0x2F` | `cycle +1` / `cycle -1` |

Five logical Ctrl+session prompt bindings are included, with physical output
explicitly pending user confirmation: Ctrl+E/B/Space/Q/V map to
`prompt continue/tests/commit/tests/summary`. They are tested with synthetic
reports, not claimed as measured factory shortcuts. Main-keyboard Ctrl does
not modify the macro keyboard's USB reports. Ctrl+slot 3 and Ctrl+deny cannot
be distinguished from the existing factory Ctrl+Z and Ctrl+F reports; those
two physical chords require another confirmed key. No conflicting or guessed
factory code was added. The measured Ctrl+0 key provides interrupt now.

## Replay output

Command: `D:/conda/miniconda3/python.exe research/selftest_hub_replay.py`

```text
Hub replay self-test (local HTTP; LCD/USB/desktop disabled)
Result | Check
-------|------
PASS | Voice/screenshot and synthetic prompt chords (decode only)
PASS | Temporary process, random port, token and six sessions
PASS | Low risk: approve key returns Codex allow
PASS | High risk: two distinct approve presses required
PASS | Critical: immediate native fallback; approve stays locked
PASS | Deny: factory Ctrl then F returns Codex deny
PASS | Session keys select all six corresponding slots
PASS | All four knobs cycle both ways with wraparound
PASS | Factory Ctrl-first macro, repeat and consumed Ctrl
PASS | Confirmed Ctrl+0 alternate interrupt denies pending
PASS | Decisions persisted in the temporary audit chain
PASS | Temporary Hub startup and cleanup
12 PASS / 0 FAIL
Physical Ctrl+session chords remain pending user confirmation; see pc/hub_keys.md.
```

The child Hub uses `--port 0 --home <temporary> --backend none --no-lcd
--no-desktop --profile v2_emulation`. Permission hooks use actual `relay()` calls,
and literal eight-byte reports pass through actual `ReportState` and `USBKeys`
before authenticated `POST /action`. Voice, screenshot and synthetic prompt
checks use a recorder without desktop effects. Token, audit, diagnostics and
child logs stay in the temporary home; pending hooks and the child are cleaned
up. No serial/USB access, hook installation, window focusing or native key
injection occurred.

## Existing tests

All 15 `pc/test_*.py` scripts passed using `D:/conda/miniconda3/python.exe`.
The exact captured stdout/stderr is in [hub-replay-tests.txt](hub-replay-tests.txt).

| Script | Actual result |
| --- | --- |
| `test_ui.py` | `UI: 7 groups passed` |
| `test_daemon.py` | `daemon offline tests: 10 groups passed` |
| `test_pc.py` | `PC and firmware loop: 4 groups passed` |
| `test_deck.py` | `AgentDeck offline tests: 55 groups passed` |
| `test_deck_exclusive.py` | `deck exclusive offline tests: 9 groups passed` |
| `test_deck_input.py` | `deck Raw Input offline tests: 4 groups passed` |
| `test_deck_keymap.py` | `Keymap offline tests: 13 groups passed` |
| `test_deck_probe.py` | `deck probe offline tests: 7 groups passed` |
| `test_deck_usb.py` | `deck USB offline tests: 24 groups passed` |
| `test_focus_lock.py` | `focus lock offline tests: 4 groups passed` |
| `test_hub.py` | `Ran 111 tests` / `OK` |
| `test_hub_desktop.py` | `Ran 30 tests` / `OK` |
| `test_hub_doctor.py` | `Ran 7 tests` / `OK` |
| `test_hub_install.py` | `Ran 9 tests` / `OK` |
| `test_hub_relay.py` | `Ran 4 tests` / `OK` |

AST parsing, byte compilation and `tabnanny` indentation checks passed for all
five changed Python files. JSON validation confirmed that default bindings are
unchanged and every v2 binding uses a measured code or is explicitly marked
pending. No project linter/typechecker configuration or installed ruff, mypy
or pyflakes was available; no dependencies were added. LCD rendering was not
changed, so `pc/sim.py` was not needed.

## Changed files

- `pc/hub.py`: opt-in named key profiles; explicit LCD/desktop output switches.
- `pc/hub_keys.json`: additive `v2_emulation` profile and pending confirmations.
- `pc/hub_keys.md`: physical key label table and unconfirmed chord limitations.
- `pc/hub_relay.py`: failure diagnostics honor the supplied temporary home.
- `pc/hub_README.md`: profile, isolated output switches and replay instructions.
- `pc/test_hub.py`: profile selection, disabled outputs and CLI regression tests.
- `pc/test_hub_relay.py`: temporary-home failure logging regression test.
- `research/selftest_hub_replay.py`: isolated process and boot-report replay.
- `research/hub-replay-results.md`: this result report.
- `research/hub-replay-tests.txt`: complete existing-test output.
- `research/hub-replay-output.txt`: exact replay output.

The implementation reuses the existing decoder, binding dispatcher, relay,
HTTP action path and down/up pairing. No firmware, sprites, protocol, device
keymap or default bindings changed. Remaining hardware confirmation is limited
to the documented Ctrl gestures; live physical press/release and native desktop
behavior were not exercised by this offline replay.
