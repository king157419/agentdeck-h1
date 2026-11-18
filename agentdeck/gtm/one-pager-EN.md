# AgentDeck (Working Title; Rebranding to *Baton* / "点将台") · Investor One-Pager

**One-liner: A cross-agent Codex Micro — plus physical hardware 2FA for irreversible agent actions.** A $99 desktop controller + free cross-agent local software hub that lets one developer command 3–10 parallel AI coding agents without touching mouse or keyboard. *(Nov 2026 · Pre-Seed / Accelerator · FX basis: **1 USD = 7.1 CNY**)*

**Problem.** Power developers run 3–10 coding agents at once (Claude Code, Codex, Cursor, Gemini CLI, Qwen Code…). The bottleneck is now the human: (1) missing idle agents waiting for input (Claude Code issue #13024, 81+ reactions; #36885); (2) generic macro pads send blind keystrokes into the active window—one focus shift approves the wrong terminal; (3) in Anthropic's auto-mode study (*n* = 1,053), humans rubber-stamped **97%** of prompts and caught only **13.6%** of dangerous actions. Once auto mode handles routine `ls`/`pytest` runs, what requires human oversight is gating irreversible actions (`git push --force`, prod `kubectl`, DB writes, secret edits).

**Solution.** A single-SKU USB-C console: a 3.5" 6-split IPS bar screen aligned above 6 RGB low-profile mechanical session keys, plus `✓` / `✗` / Push-to-Talk full mechanical keys, `Ctrl`, Screenshot, metal scroll wheel, and onboard MEMS mic.
- **Direct hook replies, never blind keystrokes:** `✓` / `✗` answer official `PermissionRequest` and `PreToolUse` hooks (`allow` / `deny`) with SHA-256 hash-chained local audit logs.
- **Hardware 2FA for agents:** Low-risk clears in one press; high-risk requires a double-press; critical commands (`curl … | sh`) lock out on-device and fall back to the terminal prompt; if the hub is offline, routine edits pass through while high-risk ops fail safe without bricking the IDE.
- **Free local software wedge:** Stream Deck, Ulanzi D200, or VIA/QMK macro pads work today by mapping keys to `F13–F24` hotkeys and viewing 6 slots in an always-on-top desktop mini-overlay *(native on-key screen plugins not yet built)*.

**What Works Today (Verified Only)**
- **End-to-end local Hub via real OS processes (`v1.0–v1.2`):** Verified `hub_relay.py` → `hub.py` → key action → hook return with Codex-format events *(process test; not yet run inside live logged-in agent sessions)*. Low-risk single-press `allow` (~202 ms); `git push --force` holds on first press ("press again") and clears on second; `✗` returns `deny`; `curl | sh` falls back to terminal in 533 ms (`✓` returns `locked`); offline fallback verified.
- **Hardware-free mode (`v1.3`):** `F13–F24` global hotkeys + non-focus-stealing 6-slot overlay. Verified on Windows with real OS key events (`F19` → `allow`, `F20` → `deny`), rendering `ASK` states and red `HIGH`-risk alerts.
- **Auto-mode High-Risk Gate (`v1.4`, `PreToolUse`):** Double-press `✓` returns `{}` (native agent rules still apply); `✗`/timeout returns `deny`. Verified with real processes, real OS hotkeys, and a 5-session demo runner (`hub_demo.py`). **Live auto-mode session test pending.**
- **Tests & USB isolation:** **264** unit tests (`test_hub*.py`, incl. demo & virtual v2 device) + **12/12** HID report replay self-tests passing. Prototype macro pad isolated via WinUSB raw reads so keys never leak to other windows (10/10 combo replay); early state machine proven on ESP32 + 1602 LCD.
- **Unverified / Not Yet Built:** Daily use in live Claude Code / Codex sessions; physical keys → Hub v1.4; `PreToolUse` gate in a live auto-mode session; device-reported `shown_nonce` check *(unbuilt)*; Stream Deck/D200 native screen plugins *(unbuilt)*; v2 3.5" bar-screen unit *(unbuilt; ~$30 Waveshare ESP32-S3 3.49" dev board sourced for hand-built unit)*; Chinese CLIs; macOS; written factory quotes; external users (0 today).

**Market & Benchmark.** Big tech validated demand in 2026: **OpenAI × Work Louder's $230 Codex Micro sold out in ~12 hours**; **Logitech launched the $99.99 MX Keypad** (Sept 2026, supporting Claude Code/Codex); **Anthropic open-sourced `claude-desktop-buddy`** (~2.7k stars). On JetBrains' narrow 22M pro developer base, global TAM is **~$870M** and SAM is **~$290M**. 3-year hardware SOM: **14.5k–43.6k units ($1.44M–$4.31M)** globally + **3.3k–9.9k units (¥1.65M–4.94M)** in China (modeled separately) = **~18k–54k units, ~$1.69M–$5.00M (¥12.0M–35.5M)** *[Estimate, hardware only; SaaS incremental]*. *Key sensitivity:* multi-agent share (33% from one *n* = 1,100 survey).

**Competition.** Codex Micro ($230) is Codex-only, screenless, and mic-less; MX Keypad ($99.99) has membrane keys, no mic, and no high-risk gate; Ulanzi Vibe Key (¥269–299 / ~$60–70) has a mic, no screen, and uses shortcut macros; VibeKeys and open-source `puritysb/AgentDeck` (free on Ulanzi D200 store) show hook status across agents without hardware 2FA. We combine **local + cloud + Chinese cross-agent slots, non-misfiring hook replies, and physical hardware 2FA**. Hardware clones take 6 months; our moat is the monthly-maintained multi-vendor adapter layer, cross-agent risk policies, and enterprise compliance auditing.

**Business Model.** **Single Hardware SKU** at **$99** ($79 early bird; ¥499 / ¥399) + **Pro** at **$3.99/mo** (¥19/mo: repo-aware code voice correction, mobile status board, Cloud Agent / GitHub PR slot bridge) + **Team** at **~$5.50–$8.30/seat/mo** (¥39–59/mo: SSO, compliance dashboard, self-hosted Docker, MCP allowlists). Profitable near **10k units/yr**, loss-making at **1k**; gross margin disclosed after 2–3 written factory quotes *(internal model estimates ~52% overseas product GM at 10k)*.

**The Ask.** **$700k at $3.5M post-money** (20% equity; ¥5.0M at ¥25.0M post at **1 USD = 7.1 CNY**) across **two $350k (¥2.5M) tranches** — **OR standard accelerator terms (e.g., YC standard deal, a16z speedrun, HF0)**. Tranche 1 ($350k) at signing; Tranche 2 ($350k) upon **WAU ≥ 2,000 AND ≥ $70k (¥500k) crowdfunding orders (or ≥ 1,500 paid $1 / ¥9.9 deposits)**. Allocation: Team 36%, R&D 10%, tooling/cert 4%, deposit/crowdfunding 10%, legal/rebrand/cloud 9%, cash reserve 31%. Reaches **default-alive** profitability on one round (modeled cash trough **~$50k / ¥355k** in Oct 2029; founder all-in pay capped at ~$1,690/mo [¥12k]).

**8-Week Validation Plan (Nov 18, 2026 – Jan 12, 2027)**

| Weeks | Milestone | Pass Bar |
|---|---|---|
| **1–2** | Live Claude Code & Codex hook replies on Win + macOS; RFQ 3 Shenzhen factories; recruit beta | 0 mis-approvals over 5d; p95 < 300 ms; 100% offline fallback |
| **3** | Hook tests & recordings on Qwen Code, CodeBuddy, Kimi, Trae; 3D-printed hand-built unit | Direct hook approval on ≥ 2 additional coding CLIs |
| **4–5** | 30–50 power users on existing Stream Decks/macro pads; $1 / ¥9.9 VIP deposit page live | D14 retention ≥ 40%; ≥ 20 key actions/user/day |
| **6** | Lock BOM from written quotes; shoot uncut 90s hands-off-keyboard live demo | 10k bare BOM ≤ **$24.8 / ¥176** (≤ $28.5 / ¥202 w/ 15% buffer) |
| **7–8** | Freeze demo, update deck with live cohort & BOM data, close round / accelerator batch | ≥ 300 paid deposits at CAC ≤ **$8.50 / ¥60** |

**Team.** *[Founders to fill: 3 technical co-founders, backgrounds & roles]*. 4–5 people pre-crowdfunding; #1 hire is a Shenzhen mechanical/supply-chain engineer. **Contact.** *[Name · Email · GitHub / X · WeChat]*
