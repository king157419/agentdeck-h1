# Task: Agent status screen v0.1 (software only)

Work only inside `D:\desk\hardware\h1`. Do NOT open the serial port, do NOT upload to the board, do NOT touch
`~/.claude`, `~/.codex`, `~/.dsh`, and do not start background processes. I will upload and verify on hardware.
Read these first: `lcd1602/README.md`, `lcd1602/main.py`, `lcd1602/lcd1602.py`, `pc/agent_lcd.py`,
`pc/dsh_watch.py`, `pc/preview.py`. Keep code comments in Chinese like the existing files. Python on this
machine: `D:\conda\miniconda3\python.exe` (has pyserial, zstandard, PIL).

Hardware: ESP32 running MicroPython 1.28, 1602A character LCD (HD44780, 16x2, 5x8 cells, single colour,
ROM A00, 8 CGRAM glyphs that can be redefined on the fly). Session keys start with `cc` (Claude Code),
`cx` (Codex), `ds` (DeepSeek harness).

## A. Firmware (lcd1602/) -> VERSION "0.1"

Split so logic is testable on a PC: put everything except hardware setup and the serial loop into a new
`lcd1602/ui.py` (pure logic + a class taking an lcd-like object with `show(row, bytes)` and
`glyph(idx, rows)` and a `led(value)` callback, and taking `now` in ms as an argument). `main.py` stays thin.
Must run on MicroPython: no typing module, no dataclasses, use `time.ticks_ms/ticks_diff` only in main.py.

1. Layout
   - Row 0: `[sprite][sprite] <tool> <STATE>` where tool is `Claude`, `Codex`, `DSK` (unknown prefix: `Agent`)
     and STATE is `READY` (idle), `THINK`, `TOOL`, `WAIT!`, `DONE`, `ERROR`.
   - Row 1: `[sprite][sprite] <project name>` and, right-aligned, the per-session mini icon ribbon when
     there are 2+ sessions, otherwise the elapsed time in the current state (`12s`, `5m`, `2h`; none for idle).
     If the project name does not fit the space left, scroll it as a slow marquee (pause 2 s at each end,
     1 char per 400 ms). Names can now be up to 24 chars (`clean(...)` limit).
2. Sprites: the left 2x2 cells are one 10x16 pixel sprite. Store sprites in the source as 16 strings of 10
   chars (`#` lit, `.` dark) so a human can edit them, convert once at boot into 4 glyphs (8 bytes each).
   Implement generic transforms on the 10x16 bitmap: shift up/down/left/right by 1 px.
   One mascot per tool, original pixel art, bold enough to read from 1 m (mind the 1 px gap between cells):
   - Claude: a small blocky crab-like critter (boxy body, two dark eyes, little side claws, four short legs).
   - Codex: a terminal window with a `>_` prompt inside.
   - DSK: a whale with a spout.
   - Unknown: keep the current robot.
   Plus three big 10x16 status symbols: `!`, a check mark, a cross.
3. Make the states look clearly different (current complaint: thinking and done look alike):
   - READY: mascot still; a blink/second frame for 150 ms every 5 s is enough.
   - THINK: mascot bobs up/down 1 px every 600 ms; a spinner glyph right after the word `THINK`.
   - TOOL: mascot shakes left/right 1 px every 200 ms; `>` / `0x7E` alternating after the word `TOOL`.
   - WAIT!: left 2x2 alternates big `!` and the mascot every 400 ms; the word alternates `WAIT!` and `>YOU<`;
     board LED blinks.
   - DONE: big check mark for the first 3 s, then the mascot with the small check glyph after `DONE`.
   - ERROR: big cross and mascot alternating every 500 ms; LED blinks.
   CGRAM budget: slots 0-3 sprite, 4 wait icon (2 frames), 5 done, 6 error, 7 spinner. Only rewrite a glyph
   when its bytes actually changed.
4. No sessions and no focus: row 0 `[robot, eyes shut] Agent Monitor`, row 1 `ready to work`.
5. New serial command `focus <target>` (reply `ok focus <target>`):
   - `<target>` is a full session key, or a tool prefix `cc` / `cx` / `ds`, or `-` to clear.
   - A focus expires 60 s after it was last sent (the PC re-sends it as a heartbeat).
   - While a focus is active it overrides the automatic priority: show that session; for a tool prefix show
     the most recently updated session of that tool; if that tool has no session show its mascot with
     `<tool> READY` and row 1 `ready to work`.
   - Sessions waiting elsewhere must still be noticeable: ribbon icon blinks and the LED blinks.
   - Without focus keep the existing priority: wait > error > just done (5 s) > tool > think > done > idle,
     rotating every 3 s among equals.
6. Keep everything else compatible: `set/end/clear/list/ping/dump`, TTLs, max 8 sessions with eviction,
   periodic LCD re-init, never crash the loop on a bad line.

## B. PC side (pc/)

1. New `pc/daemon.py`: one background process (single instance via binding 127.0.0.1:47613, same as now)
   that runs BOTH the existing DeepSeek-harness log watching (reuse `dsh_watch`, refactor it into a
   `tick()`-style API if needed; keep `python dsh_watch.py -v` working) AND a new foreground-window watcher.
   `agent_lcd.ensure_watcher()` must launch `daemon.py` (always, not only when `~/.dsh` exists).
2. Foreground watcher (ctypes only: `GetForegroundWindow`, `GetWindowTextW`, `GetWindowThreadProcessId`,
   `QueryFullProcessImageNameW`), poll every 300 ms, send `focus ...` only when the target changes, plus a
   heartbeat every 20 s. Mapping, by process name (case-insensitive) then title:
   - `claude.exe` -> `cc`
   - `DeepSeek Harness.exe` -> `ds`; its title is `<session title> ? DeepSeek Harness`; if you can map the
     title to a session (the session log has `session/title` events) send that session key, else `ds`.
   - `ChatGPT.exe`, `Codex.exe` -> `cx`
   - terminals/editors (`WindowsTerminal.exe`, `conhost.exe`, `OpenConsole.exe`, `pwsh.exe`, `powershell.exe`,
     `cmd.exe`, `Code.exe`, `Cursor.exe`, `wezterm-gui.exe`, `alacritty.exe`): if the title contains the
     project name of a session currently on the board (ask the board with `list`, at most once per focus
     change) -> that session key; else if the title contains `claude` -> `cc`; `codex` -> `cx`; else `-`.
   - anything else -> `-`.
   Serial errors must never crash the daemon. Put the mapping table at the top of the file so it is easy to edit.
3. `agent_lcd.py`: names sent with `set` may be up to 24 chars; `doctor` reports the daemon; `demo` shows
   all states for all three tools and a focus change.
4. `preview.py`: update the `sheet` scenarios for the new layout (each tool's mascot, every state, both
   WAIT frames, big check, marquee, ribbon, focus on a tool with no session).
5. New `pc/sim.py`: runs `lcd1602/ui.py` under CPython with a fake LCD and renders a contact sheet PNG of
   the same scenarios WITHOUT hardware (reuse `preview.render` and its font loader). Run it, look at the
   PNG yourself if you can, and fix the artwork until each mascot and each state is recognisable.
   Save the result as `lcd1602/preview-sim.png`.
6. Add `pc/test_ui.py` (plain asserts, no pytest needed): layout strings for each state, marquee, focus
   override and expiry, eviction, bad commands. Run it and make it pass.

## C. Docs

1. Update `lcd1602/README.md` for v0.1 (layout, states, focus, files, upload command now includes `ui.py`).
2. Write `docs/v0.0-记录.md` in Chinese: a short, plain record of version 0.0, faithful to these points
   from the owner (do not invent extra claims):
   - What 0.0 is: ESP32 + 1602 screen over USB; adapted Claude Code, Codex, DeepSeek harness; shows tool,
     state and project name.
   - Shortcomings: (a) single letters C/X/D for tools are too crude, want fuller names or the tools' own
     icons; (b) the left icon should be a per-tool mascot such as Claude's little crab instead of the split
     robot; (c) states are not distinct enough (looking left/right when working vs. smiling with arms up
     when done); (d) no standby hint such as "ready to work" / "waiting for your input"; (e) the screen only
     changes when a session sends something; it should follow the mouse/keyboard focus so it feels like
     human-machine collaboration.
   - How and toward what goal we improve: software first on the existing hardware (v0.1 addresses a-e).
   - Hardware/connection ideas deferred because of current hardware limits: the USB cable is bulky;
     options later are a small Type-C dongle plugged straight into the PC, HDMI, or a small wireless USB
     receiver like a Bluetooth mouse (then placement and not losing it become questions).

## D. Finish

Print a short report: files changed, test results, anything you could not verify without hardware.
