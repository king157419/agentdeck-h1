# Hub v1.3 implementation and verification

Implemented `brief-hub-v1_3.md`: Windows global hotkeys, combined USB/hotkey
backends, and a standalone or combined tkinter overlay. No dependencies added.

Before editing, saved the complete `pc/` tree in
`_rollback/hub-v1_2b/pre-v1_3-20261117-122407/pc/`, preserving the existing
`hub-v1_2b` backup files. Firmware source was unchanged.

## Changed files

| File | Change |
| --- | --- |
| `pc/hub.py` | Parse combined backends; run inputs independently; keep Tk on the main thread and HTTP in a background thread; stop and join services on exit or startup failure. |
| `pc/hub_hotkey.py` | Parse F13–F24 and Ctrl/Shift/Alt combinations; register with no repeat; tolerate individual conflicts; dispatch shared actions; toggle actual voice state; reject stale decisions; unregister on exit. |
| `pc/hub_overlay.py` | Pure display model; six selectable slots; request/risk details; persistent approval buttons with request IDs captured on press; adaptive height; dragging; Windows no-activation handling. |
| `pc/hub_keys.json` | Add the 17 default hotkey bindings, independent of USB profiles. |
| `pc/hub_README.md` | Document hardware-free setup, VIA/QMK, Stream Deck, mouse-only operation, mappings, and offline checks. |
| `pc/test_hub_hotkey.py` | 15 offline hotkey tests with native API substitutes. |
| `pc/test_hub_overlay.py` | 15 offline model, callback, layout lifecycle, and native adapter tests. |
| `pc/test_hub_runtime.py` | Five offline startup/shutdown tests covering every backend/overlay combination and overlay startup failure. |

Reuse decision: compose Hub's existing locked `state()` and `action()` methods,
the existing Win32 message structure, and Python standard-library APIs. Both new
inputs preserve the existing approval, audit, voice, and window rules. Separate
approval logic or new input dependencies were unnecessary.

## Actual verification output

Interpreter: `D:/conda/miniconda3/python.exe`. All 21 commands exited 0.
Full stdout/stderr: [hub-v1_3-tests.txt](hub-v1_3-tests.txt).

| Command | Output summary |
| --- | --- |
| `pc/test_ui.py` | `UI: 7 groups passed` |
| `pc/test_daemon.py` | `daemon offline tests: 10 groups passed` |
| `pc/test_pc.py` | `PC and firmware loop: 4 groups passed` |
| `pc/test_deck.py` | `AgentDeck offline tests: 55 groups passed` |
| `pc/test_deck_exclusive.py` | `deck exclusive offline tests: 9 groups passed` |
| `pc/test_deck_input.py` | `deck Raw Input offline tests: 4 groups passed` |
| `pc/test_deck_keymap.py` | `Keymap offline tests: 13 groups passed` |
| `pc/test_deck_probe.py` | `deck probe offline tests: 7 groups passed` |
| `pc/test_deck_usb.py` | `deck USB offline tests: 24 groups passed` |
| `pc/test_focus_lock.py` | `focus lock offline tests: 4 groups passed` |
| `pc/test_hub.py` | `Ran 111 tests in 1.513s` / `OK` |
| `pc/test_hub_desktop.py` | `Ran 30 tests in 0.160s` / `OK` |
| `pc/test_hub_doctor.py` | `Ran 7 tests in 0.088s` / `OK` |
| `pc/test_hub_install.py` | `Ran 9 tests in 0.067s` / `OK` |
| `pc/test_hub_relay.py` | `Ran 4 tests in 0.140s` / `OK` |
| `pc/test_hub_hotkey.py` | `Ran 15 tests in 0.017s` / `OK` |
| `pc/test_hub_overlay.py` | `Ran 15 tests in 0.008s` / `OK` |
| `pc/test_hub_runtime.py` | `Ran 5 tests in 0.104s` / `OK` |
| `research/selftest_hub_replay.py` | `12 PASS / 0 FAIL` |
| `pc/sim.py` | `Rendered 42 scenarios -> D:\desk\hardware\h1\lcd1602\preview-sim.png` |
| `-m compileall -q pc` | No output; exit 0. |

Some legacy commands include other suites, so their counts overlap. The three
new suites contain 35 tests in total. No configured lint/typecheck tools were
found; `ruff`, `pyflakes`, and `mypy` are not installed in the specified Python.

## Remaining live validation

As requested in the brief, actual Windows hotkey registration, Stream Deck/VIA
key output, overlay appearance, and foreground focus behavior are left to the
Claude main session. The offline checks did not create windows, register real
hotkeys, access COM4, upload firmware, or install hooks.

Launch for hardware-free live validation:

```text
D:/conda/miniconda3/python.exe pc/hub.py --backend hotkey --overlay --no-lcd
```
