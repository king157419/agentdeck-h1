**Adapter research — 2026-11-11.** Read-only inspection; the only file written is this report. No GUI was launched or controlled; no credentials or conversation content are included.

**1. Codex CLI 0.166.0**

Verified local installation: `C:/Users/king/AppData/Roaming/npm/node_modules/@openai/codex/package.json` and `bin/codex.js`; native package `node_modules/@openai/codex-win32-x64/package.json` reports `0.166.0-win32-x64`. Its `vendor/x86_64-pc-windows-msvc/bin/codex.exe` contains all 14 event names below. Read `C:/Users/king/.codex/hooks.json`: the five stated OMX events are present. Read `C:/Users/king/.codex/config.toml`: `features.hooks=true`, with five stored hook-state entries.

Exact contracts below come from official tag [`rust-v0.166.0`](https://github.com/openai/codex/tree/rust-v0.166.0), commit `6ff1e1ca3b30fc8b914720681fcf5fe62e95f856`, rather than assuming current docs match the installed version.

**Events and stdin.** These are the complete 14 supported names. Every invocation receives one JSON object on stdin. In the table:

- `B` = `session_id:string`, `transcript_path:string|null`, `cwd:string`, `hook_event_name:string`.
- `M` = `model:string`; `T` = `turn_id:string`; `P` = `permission_mode:string`, one of `default|acceptEdits|plan|dontAsk|bypassPermissions`.
- `A` = `agent_id:string` and `agent_type:string`; optional unless explicitly required. Unmarked fields are required. `tool_input`/`tool_response` are arbitrary JSON.

| Event | Fields in addition to B |
|---|---|
| `SessionStart` | M, P, `source:startup\|resume\|clear\|compact\|fork` |
| `SessionEnd` | `reason:"other"` — **no model, turn_id, or permission_mode** |
| `UserPromptSubmit` | M, T, P, `prompt:string`; optional A |
| `PreToolUse` | M, T, P, `tool_name:string`, `tool_input`, `tool_use_id:string`; optional A |
| `PermissionRequest` | M, T, P, `tool_name:string`, `tool_input`; optional A; **no tool_use_id** |
| `PostToolUse` | M, T, P, `tool_name:string`, `tool_input`, `tool_use_id:string`, `tool_response`; optional A |
| `PreCompact` | M, T, `trigger:manual\|auto`; optional A |
| `PostCompact` | M, T, `trigger:manual\|auto`; optional A |
| `SubagentStart` | M, T, P, required A |
| `SubagentStop` | M, T, P, required A, `agent_transcript_path:string\|null`, `last_assistant_message:string\|null`, `stop_hook_active:boolean` |
| `Stop` | M, T, P, `last_assistant_message:string\|null`, `stop_hook_active:boolean` |
| `Interrupt` | M, T, P |
| `PreModelRequest` | M, T; optional A |
| `PostModelRequest` | M, T, `status:completed\|failed\|cancelled`, `error:string\|null`, `token_usage:object\|null`; optional A |

`token_usage` contains integer `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens` (schema default 0), `output_tokens`, `reasoning_output_tokens`, `total_tokens`. Shell/unified-exec hooks use canonical `tool_name:"Bash"`; shell and `apply_patch` inputs use `tool_input.command`. Other function/MCP inputs retain their argument objects. An approval reason may appear in `tool_input.description`; it is not universal. Subagent hooks use the parent `session_id`, with child identity in A. Sources: [event registry](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/hooks/src/lib.rs#L36), [all 13 input-schema files](https://github.com/openai/codex/tree/rust-v0.166.0/codex-rs/hooks/schema/generated) actually read, including the shared model-request schema.

**Approval and end:** `PermissionRequest` exists and runs before approval handling. Another hook can immediately allow/deny, so it does not prove the UI is waiting. There is no generic waiting-for-user-input, approval-resolved, or `PostToolUseFailure` event. A failed tool need not produce a paired `PostToolUse`. `Stop` is a turn boundary; `SessionEnd` is session teardown, not each completed turn. [Core dispatch](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/core/src/hook_runtime.rs#L272).

**Desktop/app-server:** hooks run in shared core, not only the CLI TUI. The tagged app-server has an integration test that executes `UserPromptSubmit` command hooks and forwards hook lifecycle notifications. A desktop app using that server supports them, subject to its own bundled version, config, and hook trust; the npm CLI version does not establish the desktop's version. [App-server execution test](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/app-server/tests/suite/v2/hooks_list.rs#L1446).

**Stay silent:** plain stdout becomes model/developer context for `SessionStart`, `SubagentStart`, and `UserPromptSubmit`. Structured JSON `additionalContext` can also inject at `PreToolUse` and `PostToolUse`. Model-request hooks only log stdout; other events ignore plain output or reject it, and control JSON can alter execution. **Exit 0, emit nothing on stdout or stderr, omit `statusMessage`, and return no control JSON.** `async:true` does not prevent context injection. [Official output rules](https://learn.chatgpt.com/docs/hooks), [background context delivery](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/core/src/hook_runtime.rs#L809).

**Combining hooks/options:** append a group to the existing event array; do not create a duplicate JSON property. All matching groups and config layers accumulate; higher precedence does not replace earlier hooks. Matching command handlers launch concurrently, so do not rely on execution order. Both JSON and inline TOML load, with a warning if both exist in one layer. New nonmanaged hooks require matching trust; group/handler indices participate in stored keys, so avoid reordering OMX groups. [Discovery](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/hooks/src/engine/discovery.rs#L156), [dispatcher](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/hooks/src/engine/dispatcher.rs#L131).

Command fields: required `type:"command"`, `command`; optional `commandWindows` (alias `command_windows`), `timeout` (integer seconds), `async` (default false), `statusMessage`, `additionalContextLimit`. Most timeouts default to **600 seconds**, minimum 1. `Interrupt` and `SessionEnd` default to **1 second**, clamped to **1–3 seconds**. `SessionEnd` is always synchronous. Background command hooks are capped at eight per session, cannot control the triggering action, and unfinished work is cancelled at shutdown. [Config fields](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/protocol/src/hooks.rs#L148), [timeout normalization](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/hooks/src/engine/discovery.rs#L946), [background runner](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/hooks/src/engine/command_runner.rs#L119).

**2. DeepSeek harness desktop**

Installed executable: `D:/dsh/DeepSeek Harness/DeepSeek Harness.exe`. Read its `resources/app.asar` directly, without extracting or executing it. `/package.json` and the inspected `@deepseek-ai/dsh-*` package manifests report **0.2.2-rc.1**. Below, `A` means `D:/dsh/DeepSeek Harness/resources/app.asar!/dsh/node_modules/@deepseek-ai/`; each `A/package/file` is an actual archive member read.

**An external API exists.** `dsh-api-gateway` exposes authenticated HTTP RPC on `/api` and multiplexed WebSocket subscriptions on `/api/remote.mux`. Session endpoints include `session/state`, `session/observeState`, `session/observeEvent`, `session/observeProjections`, and `session/follow`. State reads take `{sessionId:"..."}` and return `{cursor,active,running,queue,pendingInput}`; `pendingInput` is an array containing `approval`, `question`, and/or `other`. `running` means `agent.status === "running"`. `observeState` streams complete replacements; `follow` supplies an opening snapshot and gap-free durable events. These provide a stronger live signal than checkpoint files.

Desktop binds **127.0.0.1 on an ephemeral port** and passes its authenticated URL privately to the Electron parent over child-process IPC. API clients exchange the launch token through `/connect?token=<secret>&interactions=none`, retain the returned cookie, and attach the WebSocket; there is no tokenless loopback access. That parent-child IPC is not an attachable public named pipe. No public endpoint-discovery file was established; `C:/Users/king/AppData/Roaming/@deepseek-ai/dsh-desktop/logs/` was empty. No API connection or credential extraction was attempted.

API sources: `A/dsh-api-gateway/README.md:31–60`, `A/dsh-client-connection/README.md:30–58`, `A/dsh-desktop-host/lib/index.js:449–454,605–609`, `A/dsh-api-session-controller/lib/index.js:4105–4166`, `A/dsh-api-session-controller/lib/types/state/controller.js:200–239`.

**Files update during turns.**

- `session.v4.jsonl.zstd`: live `session/event` records are buffered for about **200 ms**, then appended as independently compressed zstd batch frames and fsynced. It is not one frame written only at turn end. A reader may see an incomplete physical tail. Source: `A/dsh-session-persistence-jsonl/lib/index.js:187–194,421–431,3276–3333`.
- Projcache JSON: rewritten after **200 events or 5000 ms**, also at creation, turn end, and disposal. The log is flushed before the checkpoint write. Thus cache rows can lag during a turn. Sources: `A/dsh-session-projection-cache/lib/index.js:265–316`; shipped defaults `A/dsh-base/cordis.patch.yml:195–200`.

Actual data read:

- `C:/Users/king/.dsh/sessions/--D-desk-demo-dsh--/session-5f76d107-65f5-4932-b5ca-748f2cf937de/session.v4.jsonl.zstd`
- `C:/Users/king/.dsh/storages/session_projcache/sessions/session-5f76d107-65f5-4932-b5ca-748f2cf937de.json`
- Error example: `C:/Users/king/.dsh/sessions/--C-Users-king-Documents-deepseek-harness-default-workspace--/session-6f359fef-bfd0-44f6-9dbc-0254a94089e6/session.v4.jsonl.zstd`.

Python's already-installed `zstandard` decompressed the first log: **2,561,224 bytes → 10,291,674 bytes, 1,971 JSONL records, 1,177 complete concatenated frames**. Frame boundaries were verified using `eof`/`unused_data`. Five actual event types below show selected fields only; identifiers/content are redacted:

```json
{"type":"turn/start","seq":11,"time":1794394695358,"data":{"turn":1}}
{"type":"step/start","seq":14,"time":1794394695539,"data":{"turn":1,"step":1}}
{"type":"tool/call","seq":26,"time":1794394698094,"data":{"turn":1,"step":1,"callId":"<id>","name":"<tool>","arguments":"<redacted>"}}
{"type":"tool/result","seq":29,"time":1794394699424,"data":{"turn":1,"step":1,"message":{"role":"tool","source":{"kind":"tool","callId":"<id>"},"toolCallId":"<id>","isError":false}},"sourceEventSeqs":[26],"surfaceOp":"append"}
{"type":"turn/end","seq":1969,"time":1794400008004,"data":{"turn":1,"reason":{"kind":"completed"}}}
```

**Exact state mapping.** Cache version is 7; use `record.rows.<projection>.val`, with `.seq` as that projection's replay position.

| Display state | Exact signal |
|---|---|
| Thinking / active | `turnBoundary.val.openTurnStartSeq != null`, no unresolved approval/tool call. `sessionStats.val.openStep` is `{turn,step,startTime,firstTokenTime}` or null; it opens at `step/start`, clears on `assistant/message`/`step/end`. This is an activity inference, not proof of literal reasoning. |
| Tool running/pending | `sessionStats.val.pendingCalls` maps `callId` to dispatch timestamp. Replay adds `tool/call.data.callId`, removes `tool/result.data.message.source.callId` (also equal to `.toolCallId`). Give approval waiting precedence. |
| Waiting approval | Live API: `pendingInput` contains `approval`. Durable fallback: unmatched `approval/asked.data.id` until `approval/decided.data.id`. Asked fields: `id`, `toolName`, optional `callId`, `reason`; decided: `id`, `outcome:allowed-once\|rejected\|cancelled\|unavailable`. |
| Finished | Latest `turn/end.data.reason.kind === "completed"`; turn-open pointer becomes null. |
| Error | `turn/end.data.reason.kind === "error"`, details in `.reason.error`. `tool/result.data.message.isError` is a tool error and may be recovered. |
| Cancelled / limit | `turn/end.data.reason.kind` is `aborted` / `max-tokens`; keep distinct from successful completion. |

`approvalState.val` has only `{policy:null|"ask"|"never",turnOpen:boolean}`: **policy is not a waiting flag**. Pending approvals are process-local and are not restored from checkpoints. Sources: `A/dsh-session-stats/lib/index.js:44–52,83–154`; `A/dsh-user-approval/lib/index.js:47–73,153–167` and `README.md:168`; `A/dsh-agent-loop/lib/index.js:800–821,949–958`.

**Recommended Python watcher:** if authenticated connection details are deliberately supplied, poll `session/state` for authoritative `running`/`pendingInput`, combining event following for tool and terminal status. For a small credential-free polling watcher, scan session directories, replay each transcript once, then poll size/identity every **250–500 ms** and incrementally decode appended bytes with `zstandard`. Buffer incomplete frames/JSON lines; retain compressed offset, partial decoder state, last `seq`, open turn, pending call IDs, and approval IDs. Handle replacement/truncation by replaying. Use cache only as a lagging checkpoint, replaying beyond the relevant row's `.seq`; otherwise replay from the beginning.

Apply precedence: terminal event → finished/error/aborted/limit; otherwise outstanding approval → waiting; outstanding tool → tool; open turn → active. Reset terminal status on each `turn/start`; clear outstanding sets at turn end. Do not infer completion from inactivity, and treat a dead host with an open turn as stale/unknown rather than a surviving approval prompt. Existing logs contained recoverable tool errors and separate terminal errors, confirming that distinction.

Verification limit: all three inspected sessions were closed. Live batching/checkpoint timing is verified from installed writer source, not a newly generated turn. No files outside the current directory were changed. Remaining risk: dsh's internal archive contracts and disk format can change across upgrades.
