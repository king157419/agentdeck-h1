# AgentDeck Hub v1.1

Hub answers Claude Code and Codex `PermissionRequest` hooks directly. Approval
does not send Enter or Esc to a terminal. All implementation files are new;
`deck.py`, `daemon.py`, existing LCD hooks, and firmware retain their behavior.
No additional dependencies are required beyond the project's installed packages.

## Start and configure

From the project root, using `D:/conda/miniconda3/python.exe` as `python`:

```text
python pc/hub.py --backend none
python pc/hub.py --backend usb -v
python pc/hub.py doctor
python pc/hub_install.py install --dry-run
python pc/hub_install.py install
python pc/hub_install.py uninstall --dry-run
python pc/hub_install.py uninstall
```

The install/uninstall commands above are for the user to execute. Development
tests use temporary homes and never install into the real Claude/Codex settings.
Use `install cc` or `install cx` to select one agent. Existing hooks, including
`agent_lcd.py`, are retained. Existing configuration is backed up as
`*.bak-agentdeck-<timestamp>` before replacement. Repeating an unchanged install
creates neither duplicate entries nor extra backups.

Hub defaults to HTTP input only. USB mode reuses `deck_usb.USBInput` and requires
the existing WinUSB interface 0 setup; it does not change drivers or keymaps.
Run one AgentDeck keyboard reader at a time: use Hub's USB mode in place of
`deck.py run` / `daemon.py --deck` when testing Hub controls.

The address is always `127.0.0.1`. `--port` changes the default port 47800.
`--approve-timeout` changes the default 110-second permission wait. Use the same
options with `hub_install.py install` (or `hub_relay.py` for manual hook setup).
Installed permission hooks have a 120-second timeout, so keep the hub wait plus
the relay's five-second margin below that limit. Codex receives only supported
events; Claude additionally receives `Notification` and `PostToolUseFailure`.

On first startup Hub creates `%USERPROFILE%/.agentdeck/token`; relay reads this
file without creating it. Requests other than `GET /health` require the exact
`X-AgentDeck-Token` header. A missing hub/token, transport error, or timeout
causes relay to print nothing and exit 0, preserving the native approval flow.
Relay uses a 0.5-second connect timeout and permission read timeout of
`approve-timeout + 5` seconds (ordinary events: five seconds).

## HTTP

| Method and route | Behavior |
| --- | --- |
| `GET /health` | Public liveness check, returning `{"ok":true}`. |
| `POST /event?agent=cc` / `?agent=cx` | Accepts a hook JSON object; ordinary events return `{}` immediately, while permission requests wait for a decision or timeout. |
| `GET /state` | Returns sessions, pending requests, selected slot, and `displayed_request_id`. |
| `GET /audit?limit=50` | Returns the most recent audit records, oldest first (limit 1..1000; token required). |
| `POST /action` | Runs the same action path used by the USB keyboard. |

Permission input example:

```json
{
  "session_id": "12345678-abcd-1234-abcd-123456789abc",
  "cwd": "D:/work/my-project",
  "hook_event_name": "PermissionRequest",
  "tool_name": "Bash",
  "tool_input": {"command": "python -m unittest"}
}
```

Action examples:

```json
{"action": "slot 2"}
{"action": "cycle -1"}
{"action": "approve", "request_id": "<id from /state>"}
{"action": "deny"}
{"action": "interrupt"}
{"action": "voice"}
{"action": "screenshot"}
{"action": "prompt tests"}
{"action": "prompt 跑测试"}
```

`slot` also accepts `{"action":"slot","slot":2}`; `cycle` accepts a `delta`
integer; `prompt` accepts a template `name`. Unknown templates or actions are
rejected. `request_id` is optional; supplying it rejects stale decisions with
HTTP 409. Approve/deny responses always include `request_id` (null if no request
is displayed). A first high-risk approve returns `status: "confirm"`; a second
within 1.5 seconds returns `status: "allowed"`. Deny returns `status: "denied"`.
Critical requests immediately return `{}` to the hook, requiring the agent's
native terminal confirmation. Their retained records have `status: "locked"`;
approve, deny, and interrupt return `status: "locked"` without deciding or
injecting keys. Responses retain `action` and `request_id` for stale-id checks.

The permission hook response is:

```json
{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}
```

Deny uses `{"behavior":"deny","message":"Denied from AgentDeck"}`. Timeout,
session end, stop/interrupt events, and hub shutdown release pending hooks with
`{}`, allowing the agent's normal flow. Codex responses never contain
`updatedInput`, `updatedPermissions`, or `interrupt`.

## Selection, display, and actions

Sessions are keyed by the full `(agent, session_id)` pair. The lowest free slot
1..6 is assigned once and released on `SessionEnd`; other slots never move.
A seventh new session receives HTTP 409 and its relay falls back to native
handling. Sessions are not silently evicted. `/state` includes each session's
cwd, project/name, state, last update, LCD key, slot and full pending details.

The first waiting request is displayed automatically. Further arrivals preserve
that request. After a decision or timeout the next request is displayed in
arrival order. Slot/cycle explicitly selects a session and its oldest pending
request, if present. Approval always targets the displayed request, even when
another window is foreground. Interrupt denies a pending request; if none is
displayed but the queue is nonempty, it denies the oldest. With no pending
request it focuses the selected session and sends one Esc.

Locked records are separate from the actionable pending queue: `/state` includes
`locked`, and each session includes `locked_requests`. With no actionable queue,
the oldest locked record is displayed; a new actionable request takes priority.
Slot/cycle can select locked sessions. Notification events and LCD heartbeats
retain the warning; the next progress event (for example PreToolUse, Stop, or
SessionEnd) clears that session's locked records. The audit history remains.

LCD keys exactly match `agent_lcd.hook_line`: `cc-` or `cx-` followed by the first
six session-id characters after removing hyphens. Hub sends existing `set`,
`end`, and `focus` commands. Every focus send holds `focus_lock` and touches
`daemon.DECK_HOLD`; a heartbeat renews the hold every 20 seconds. Missing LCD
hardware logs a warning and does not prevent decisions. The first high-risk
press shows `HOLD! press again` using the existing scrolling name field.
Critical requests show `LOCKED: use terminal` in that same scrolling field,
using the firmware's existing `wait` state. Firmware changes are unnecessary.

Window actions reuse the deck's project/title matching and reject ambiguous
matches. Voice focuses the session then sends Win+H. Screenshot captures all
screens to `%USERPROFILE%/.agentdeck/shots/<timestamp>.png` and pastes its path
without Enter. Prompt pastes a named template then sends Enter. Clipboard and
key effects verify the selected foreground window. These actions require a
session window with a title that can be uniquely matched.

`hub_prompts.json` contains four templates in both languages: `continue` / `继续`,
`tests` / `跑测试`, `summary` / `总结进度`, `commit` / `提交`. Use `--prompts FILE`
for another flat JSON mapping. `--keys FILE` selects another USB binding map.
`hub_keys.json` documents every physical key and knob; E/B/Ctrl+Z select slots
1/2/3, G approves, Ctrl+F denies, Space interrupts, H invokes voice, L captures
a screenshot, and knob rotations cycle sessions.

Risk has three levels: `low` allows a single press, `high` requires a double
press, and `critical` always falls back to terminal confirmation. Critical rules
run before high rules. `RISK_RULES` and `CRITICAL_RULES` in `hub.py` are regex
lists; use `--risk-rules FILE` and `--critical-rules FILE` with JSON lists to
replace their defaults independently. Sensitive-file writes add high risk for
`.env`/`.ssh` and critical risk for `.ssh/authorized_keys` (reads stay low).
Default critical patterns include downloaded scripts piped to shells or iex,
iex/Invoke-Expression downloads, PowerShell encoded commands, base64 decoded
scripts piped to shells, recursive forced root/home deletion, recursive drive
root deletion, format/mkfs, and dd writing to `/dev/`. Regex classification does
not parse every shell expression or replace the agent's permission policy.

## Audit and diagnostics

Every final decision appends a UTF-8 JSON line to
`%USERPROFILE%/.agentdeck/audit.jsonl`; `--home` relocates this and the token for
isolated setups. Fields are `timestamp` (Unix seconds), `agent`, `session_id`,
`project`, `tool_name`, `command` (original whitespace, at most 500 characters),
`risk`, `decision` (`allow`/`deny`/`timeout`/`locked`), `source`
(`key`/`http`/`timeout`), and `request_id`. Session end, stop/interrupt hook
events and shutdown use `timeout` to record native fallback. High-risk arming
and repeated actions against a locked record do not add decisions.

`prev_sha256` is the SHA-256 of the previous complete JSON line without its LF;
the first record uses 64 zeroes. Each record also contains `sha256`, computed
over its own sorted, compact UTF-8 JSON excluding that field. This checks even
the last record for content changes. `AuditLog.verify()` validates the chain;
reads and appends validate it too and never overwrite damage. Unavailable or
corrupt audit storage returns HTTP 503 for device decisions and audit reads;
native timeout/critical fallback still returns `{}` and logs the audit error.
The hash chain detects edits without recomputing the chain; it cannot prove
that a whole file was replaced or its tail removed. One Hub process should own
each audit path. Existing history is scanned when reading/appending.

`python pc/hub.py doctor` performs seven read-only checks: `/health`, nonempty
token, relay entries for both agents, cc/cx events in the last ten minutes, and
`claude auth status` (five-second timeout). `/state` supplies `agents_seen`
with each agent's last event time in Unix seconds, or null before any event.
Doctor prints ✓/✗ and repair advice, including Codex `/hooks` trust and Claude
login guidance, and exits 0 only when all checks pass. It never installs hooks,
creates a token, logs in, or opens serial. `--port`/`--home` work with doctor.

## Verification

```text
python pc/test_hub.py
python pc/test_ui.py
python pc/test_daemon.py
python pc/test_pc.py
python pc/test_deck.py
python pc/test_deck_exclusive.py
python pc/test_deck_input.py
python pc/test_deck_keymap.py
python pc/test_deck_probe.py
python pc/test_deck_usb.py
python pc/test_focus_lock.py
python pc/sim.py
```

`test_hub.py` includes the desktop, relay and installer test classes. All native
effects use substitutes; real HTTP tests bind an ephemeral loopback port, and
filesystem tests stay in temporary directories. Complete validation output is
in `hub_test_output.txt`. No real hook installation, COM4 access, firmware
upload, or native keyboard input is part of these checks. Live Claude/Codex and
physical-device end-to-end checks remain for the user's main session.
The acceptance suite also covers the new audit chain, locked native fallback,
event timestamps, and substitute doctor checks in `test_hub_doctor.py`.

Hook schema references: [Codex official hooks](https://learn.chatgpt.com/docs/hooks),
[Claude Code official hooks](https://code.claude.com/docs/en/hooks), and
`agentdeck/research/raw-tech.md` sections 1.2/1.4.
