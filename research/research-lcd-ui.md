**1602A agent status display: research and UI designs**
Researched 2026-11-11. Linked builds/examples are evidence; UI layouts, priorities and glyphs below are proposed for this device.

**1. What people actually built**

| Build / primary source | What is worth borrowing |
|---|---|
| [Claude Desktop Buddy](https://github.com/anthropics/claude-desktop-buddy), public ESP32/M5StickCPlus reference build | Sleeping, working, attention and celebration pets; borrow the impatient permission-wait pose and keeping attention active until resolved. |
| [claude-monitor](https://github.com/icefoxj/claude-monitor), public firmware | AtomS3R shows the most urgent session plus session dots; Tab5 shows named tiles. Borrow dominant-state arbitration, persistent session context and stale-host indication. |
| [managents](https://github.com/tonylook/managents), MIT ESP32 USB display | Four-inch display with separate Claude Code/OpenCode/Codex session cards. Borrow stable identity, project names and distinct waiting/error treatment. |
| [Vibe Lamp](https://github.com/laofahai/vibe-lamp), MIT ESP32 lamp with PCB files | Claude/Codex hooks and generic event API. Borrow needs-you-first priority and heartbeat-based connection-loss handling; translate colours into shapes and motion. |
| [Tokibot](https://github.com/a-lottes/tokibot), physical Raspberry Pi e-ink pet | Expressive moods plus working/waiting/done totals. Borrow urgency overriding decorative mood changes; reserve animation for the LCD version. |
| [agent-pet](https://github.com/rpegorov/agent-pet), MIT macOS overlay, **not hardware** | Explicit Claude Code, Codex and DeepSeek Harness support with permission bubbles. Borrow its shared state vocabulary and event-driven reactions. |
| [Codex Micro](https://www.worklouder.cc/setup/codex-micro), commercial hardware | Six agent keys with live thread status. Borrow fixed spatial assignments and distinct requires-input/complete/error signals; RGB itself will not transfer. |
| [RevSpace BuildStatusTrafficLight](https://revspace.nl/BuildStatusTrafficLight), [ESP8266 source](https://github.com/bertrik/buildstatuslight) | Actual Jenkins toy traffic light distinguishes failed compilation/tests, success and unknown/in-progress. Borrow explicit unknown status. |
| [Build Light](https://github.com/tantalic/build-light), deployed open-source GPIO indicator | Documented installation aggregates about 30 Jenkins projects. Borrow worst-state aggregation: any failure, otherwise any building, otherwise success. |

| HD44780 example | What is worth borrowing |
|---|---|
| [LCDBigNumbers](https://github.com/ArminJo/LCDBigNumbers) | Working 1602 fonts include 1x2, 2x2 and 3x2-cell digits. Borrow a two-row waiting count; reserve the font's CGRAM bank. |
| [SmoothProgress](https://github.com/Gjorgjevikj/SmoothProgress) | Partial-fill bars use four shared glyphs plus one mutable edge per independent bar (four bars fit eight slots). Borrow subcell movement; show percent only with real progress. |
| [LiquidCrystal CustomCharacter](https://github.com/arduino-libraries/LiquidCrystal/blob/master/examples/CustomCharacter/CustomCharacter.ino) | Official arms-up/down animation example. Borrow large two-pose silhouette changes rather than tiny facial detail alone. |
| [Ashish Derhgawen's PC-mounted 16x2](https://ashishrd.blogspot.com/2010/01/adding-small-hd44780-lcd-display_29.html) | Photographed build explains animation by rewriting CGRAM while character positions stay fixed. Borrow streaming frames from host/ESP32 memory. |
| [LiquidCrystal Scroll](https://github.com/arduino-libraries/LiquidCrystal/blob/master/examples/Scroll/Scroll.ino) | Working character-step marquee. Borrow slow movement with pauses for optional details; critical labels should stay still. |
| [Joseph Rautenbach's smooth scrolling](https://joeraut.com/posts/smooth-scrolling-text-on-character-lcds/) | Actual Arduino Leonardo demo regenerates shifted pixel windows into CGRAM. Borrow only for a dedicated detail view: smooth scrolling consumes glyph slots. |
| [Arduino LCD 1602 game](https://projecthub.arduino.cc/ELEDTROLED/video-game-with-arduino-and-lcd-1602-62d036) | Complete sketch composes a jumping hero across two rows from ROM/custom parts. Borrow multi-cell composition; this is a two-row precedent, not a supplied 2x2 pet. |

**2. Three concepts for this exact screen**

Common rules: C=Claude, O=Codex, D=DeepSeek; IDs 1-9 are stable global session slots, regardless of agent distribution. Project labels are unique aliases derived from names; retain the full names on the host. W/E count waiting/error sessions; N counts all sessions.
Priority: waiting > error > newly done (4 seconds) > tool > thinking > idle; older done ranks below active work. Rotate equal-priority projects every 3 seconds. While any session waits, rotate only among waiting sessions. Clear waits/errors from explicit host events.
All mockups have exactly 16 cells between the bars; labels and border bars are outside the LCD. Icon stand-ins: .=idle, *=thinking spinner, >=tool, ?=waiting exclamation, +=done check, !=error cross. Empty slots are spaces.

**A. Beacon counter — the most legible aggregate**
A 3x2-cell numeral counts sessions in the displayed state; a-f mark its six screen positions, not literal letters or permanent glyph IDs. Examples below count 9/4/2/2/2/1 respectively. The right side gives state and totals; row two names the selected project.
```text
idle   |abc IDLE  W0E0N9|
       |def C1:WEB      |
think  |abc THINK W0E0N9|
       |def C1:WEB      |
tool   |abc TOOL  W0E0N9|
       |def C1:WEB      |
wait   |abc WAIT! W2E1N9|
       |def C1:WEB      |
done   |abc DONE  W0E0N9|
       |def C1:WEB      |
error  |abc ERROR W0E1N9|
       |def C1:WEB      |
```
Multiple sessions: aggregate counts plus the urgent project carousel; up to nine project-name characters after C1:. Best at one metre when “how many need me?” matters most.
Animation: idle/error steady; thinking/tool blink the project separator colon slowly/quickly; wait pulses normal/heavier digit strokes at 1 Hz while WAIT! stays fixed; done holds its count for 4 seconds.
CGRAM: use [LCDBigNumbers 3x2 variant 3](https://github.com/ArminJo/LCDBigNumbers/blob/master/src/LCDBigNumbers.hpp), whose eight font primitives occupy slots 0-7 and need no ROM block. Pulse by replacing that bank, never loading extra icons. All other content is ROM text. Tradeoff: individual session states are hidden.

**B. Dispatch board — three agent lanes**
Three compact groups show agent, session count and that agent's highest-priority state. Example distribution is 3 Claude + 2 Codex + 4 DeepSeek; counts need not be equal. Bottom row identifies the selected session and project (up to seven name characters).
```text
idle   |C3. O2. D4. W0E0|
       |C1:WEB     IDLE |
think  |C3* O2. D4. W0E0|
       |C1:WEB     THINK|
tool   |C3> O2* D4. W0E0|
       |C1:WEB     TOOL |
wait   |C3> O2! D4? W2E1|
       |D8:WEB     WAIT!|
done   |C3+ O2* D4. W0E0|
       |C1:WEB     DONE |
error  |C3! O2* D4. W0E1|
       |C1:WEB     ERROR|
```
Multiple sessions: all three agent totals, each agent's urgent state, global W/E counts and the urgent project carousel are always available. Best for spotting which harness needs attention.
Animation: idle steady; thinking rotates; tool chevrons step; wait alternates plain/boxed exclamation at 1 Hz; done ticks once; error stays crossed. Text remains fixed between carousel steps.
CGRAM: 0 idle dot, 1 thinking spinner, 2 tool chevron, 3 wait, 4 done, 5 error; 6-7 spare. Rewrite animated slots in place. Tradeoff: within-agent detail is aggregated, and all information uses normal-height cells.

**C. Lookout — a small pet with a nine-session ribbon**
A 2x2-cell robot sits at left: a/b are top-left/right, c/d bottom-left/right. Top row is agent + global slot + five-character project alias + explicit state; bottom row has all nine session icons in slot order, then W/E totals.
```text
idle   |abC1:WEB   IDLE |
       |cd......... W0E0|
think  |abC1:WEB   THINK|
       |cd*........ W0E0|
tool   |abC1:WEB   TOOL |
       |cd>*....... W0E0|
wait   |abC1:WEB   WAIT!|
       |cd??*>!+... W2E1|
done   |abC1:WEB   DONE |
       |cd+*>...... W0E0|
error  |abC1:WEB   ERROR|
       |cd!*>...... W0E1|
```
Multiple sessions: all nine states remain visible, with identity/project supplied by the foreground carousel. At one metre, use the robot's motion, WAIT! and W count; the nine tiny icons are closer-reading detail.
Animation: idle blinks occasionally; thinking looks left/right; tool pumps arms and steps feet; wait raises both arms and pulses every waiting icon; done waves with a smile; error briefly shivers, then holds crossed eyes.
CGRAM: 0=a, 1=b, 2=c, 3=d; 4=wait, 5=done, 6=error, 7=thinking spinner. Idle '.' and tool '>' use ROM. Exactly eight resident glyphs; all thinking icons share phase, as do all waiting icons.

**3. Recommendation and actual glyphs**

Choose **C, Lookout**: a memorable attention signal, explicit action word and all nine session states fit together. The five-character project alias is its main compromise; use stable disambiguated names such as API-1/API-2. A is preferable if a physical distance test demands a larger count.
The following is the complete recommended bank and frame data. These are original proposed bitmaps, visually checked in a raster preview with cell gaps; physical LCD contrast, ghosting and one-metre recognition remain to be tested.
Each token is one 5-bit row, top to bottom; 1=lit, leftmost bit=leftmost pixel. Read each column vertically for its eight rows. Physical cell gaps remain: the mascot is not a seamless 10x16 bitmap.
For every state, a0/b0/c0/d0 are phase 0 in slots 0/1/2/3; a1/b1/c1/d1 replace those same slots for phase 1. Both phases live in ESP32 memory; only one resides in CGRAM.
```text
IDLE       a0    b0    c0    d0     a1    b1    c1    d1
           00010 00000 00010 01000  00010 00000 00010 01000
           00010 00000 00111 11100  00010 00000 00111 11100
           01111 11110 01010 01010  01111 11110 01010 01010
           01000 00010 01011 11010  01000 00010 01011 11010
           01010 01010 00011 11000  01000 00010 00011 11000
           01010 01010 00010 01000  01010 01010 00010 01000
           01001 10010 00110 01100  01001 10010 00110 01100
           01111 11110 00000 00000  01111 11110 00000 00000
THINK      a0    b0    c0    d0     a1    b1    c1    d1
           00010 00000 00010 01000  00010 00000 00010 01000
           00010 00000 00111 11100  00010 00000 00111 11100
           01111 11110 01010 01010  01111 11110 01010 01010
           01000 00010 01011 11010  01000 00010 01011 11010
           01100 10010 00011 11000  01010 01010 00011 11000
           01100 10010 00010 01000  01010 01010 00010 01000
           01001 10010 00110 01100  01001 10010 00110 01100
           01111 11110 00000 00000  01111 11110 00000 00000
TOOL       a0    b0    c0    d0     a1    b1    c1    d1
           00010 00000 00010 01000  00010 00000 00010 01000
           00010 00000 00111 11100  00010 00000 00111 11100
           01111 11110 10010 01001  01111 11110 01010 01010
           01000 00010 01011 11010  01000 00010 10011 11001
           01010 01010 00011 11000  01010 01010 00011 11000
           01010 01010 00110 01000  01010 01010 00010 01100
           01001 10010 01100 01100  01001 10010 00110 00110
           01111 11110 00000 00000  01111 11110 00000 00000
WAIT       a0    b0    c0    d0     a1    b1    c1    d1
           00010 00000 00010 01000  00010 00000 10010 01001
           00010 00000 00111 11100  00010 00000 10111 11101
           01111 11110 01010 01010  01111 11110 01010 01010
           01010 01010 01011 11010  01010 01010 00011 11000
           01010 01010 00011 11000  01010 01010 00011 11000
           01001 10010 00010 01000  01001 10010 00010 01000
           01001 10010 00110 01100  01001 10010 00110 01100
           01111 11110 00000 00000  01111 11110 00000 00000
DONE       a0    b0    c0    d0     a1    b1    c1    d1
           00010 00000 10010 01000  00010 00000 00010 01001
           00010 00000 10111 11100  00010 00000 00111 11101
           01111 11110 01010 01010  01111 11110 01010 01010
           01010 01010 00011 11010  01010 01010 01011 11000
           01000 00010 00011 11000  01000 00010 00011 11000
           01010 01010 00010 01000  01010 01010 00010 01000
           01001 10010 00110 01100  01001 10010 00110 01100
           01111 11110 00000 00000  01111 11110 00000 00000
ERROR      a0    b0    c0    d0     a1    b1    c1    d1
           00010 00000 00010 01000  00100 00000 00010 01000
           00010 00000 00111 11100  00010 00000 00111 11100
           01111 11110 01010 01010  01111 11110 10010 01001
           01101 10110 01011 11010  01101 10110 01011 11010
           01010 01010 00011 11000  01010 01010 00011 11000
           01101 10110 00010 01000  01101 10110 00010 01000
           01001 10010 00110 01100  01001 10010 00110 01100
           01111 11110 00000 00000  01111 11110 00000 00000
```
Mini-icon/spinner columns below are also eight rows each. WAIT0/WAIT1 alternate in slot 4; DONE stays in 5; ERROR in 6; SPIN0-3 rotate through slot 7. ASCII stand-ins in mockups are replaced by these glyph codes.
```text
WAIT0  WAIT1  DONE   ERROR  SPIN0  SPIN1  SPIN2  SPIN3 
00100  11111  00000  00000  00000  00000  00000  00000 
01110  10001  00001  11011  00100  10000  00000  00001 
01110  10101  00011  01110  00100  01000  00000  00010 
01110  10101  10110  00100  00100  00100  11111  00100 
00100  10001  11100  01110  00100  00010  00000  01000 
00000  10101  01000  11011  00100  00001  00000  10000 
00100  11111  00000  00000  00000  00000  00000  00000 
00000  00000  00000  00000  00000  00000  00000  00000 
```
ROM '.' and '>' supply the remaining two mini states; their bitmaps are already in A00 and consume no CGRAM. A custom diagonal spinner avoids relying on the missing ROM backslash.

**Timing and implementation notes**

- Idle: phase 0 normally, phase 1 for 150 ms every 5 seconds. Think: toggle every 500 ms; spinner: next frame every 250 ms.
- Tool: toggle every 250 ms; this means activity, not percentage progress. Wait: toggle robot and slot 4 every 500 ms, leaving WAIT! and W/E counts continuously readable.
- Done: alternate waving phases every 350 ms for 2 seconds, then hold the smile. Error: alternate every 250 ms for 1 second, then hold phase 0 until cleared.
- One foreground mascot only. Never repurpose slots 4-7 for its frames; rewriting slot 7 intentionally animates every thinking session together. Four mascot slots are rewritten sequentially, so updates are not atomic.
- Cache two 16-byte row buffers and the eight current glyph definitions. Write only changed characters/glyphs; never clear the display for an animation frame. Keep cursor/automatic blink off.
- After any CGRAM write, explicitly restore the DDRAM cursor before writing text. Use raw LCD character codes 0-7, not Unicode symbols; verify the MicroPython driver preserves code 0.
- The [Hitachi HD44780U datasheet, pp. 17, 19, 24, 27](https://www.sparkfun.com/datasheets/LCD/HD44780.pdf) documents A00, eight 5x8 glyphs, row-bit ordering and addressing. Standard 16x2 row starts are 0x00/0x40; Set-CGRAM uses 0x40 | (slot << 3), followed by eight row bytes. Follow driver busy/delay rules.
- A00 0x5C is yen and 0x7E is a right arrow, not backslash/tilde. [MicroPython-compatible python_lcd](https://github.com/dhylands/python_lcd/blob/master/lcd/lcd_api.py) is a useful custom-character API reference. Sanitize project names to the supported ROM subset.
- Hardware display-shift moves both rows; implement any quiet-view name marquee by rewriting just its text window. Keep critical views still.
- A 20 Hz transport budget does not imply 20 Hz visible animation: start at 2-4 frame changes/second and tune for this module's LCD response. Prioritize incoming wait events over decorative frames.
- Normalize actual harness events on the host: explicit input/permission requested = waiting; tool-start/end = tool transition; turn completed = done; no activity alone cannot distinguish done, idle or waiting. Transport staleness is separate: on heartbeat loss, freeze all activity animation and replace the foreground state with STALE.
- Before hardware sign-off: replay mixed nine-session events; confirm a new wait takes foreground immediately, multiple waits rotate without disappearing, W/E counts stay truthful, all CGRAM users change only as intended, and unplugged host never looks idle.
