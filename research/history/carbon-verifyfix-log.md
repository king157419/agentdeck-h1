根据 Codex 独立审查意见（[review-codex-on-carbon-verify.md](file:///D:/desk/hardware/h1/research/review-codex-on-carbon-verify.md)）及 Hub nonce / switch_guard 规格（[hub-nonce-results.md](file:///D:/desk/hardware/h1/research/hub-nonce-results.md)），已对 [pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py) 和 [pc/test_verify_real_session.py](file:///D:/desk/hardware/h1/pc/test_verify_real_session.py) 完成全部修复与测试补全。本次运行严格遵守限制，未执行任何终端命令，未修改其它文件。

---

### 逐条修复说明与测试对应表

#### P1-1：审批不适配 nonce 与切换保护，立即重试仍失败
- **怎么修的**：
  1. 在 [pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L754-L829) 的 `_act_on_request` 中，确认本场景请求后立即冻结 `(request_id, nonce)`，动作 Payload 显式携带 `nonce`（32 位整数）；
  2. 新出现或经 `slot` 切换的 `pending` 请求，在发送 `approve` 前执行 `switch_guard_wait`（默认 330ms）；若 Hub 仍返回 `409 switch_guard`，进入有界重试（最多 4 次），重试前调用 `_verify_frozen_target` 复核当前 `/state` 中的请求 ID、nonce、会话和操作未发生变更；
  3. `deny` 豁免 300ms 保护期；处于 `locked` 的 critical 请求同样不额外等待保护期；高危二次确认在 1.5s 窗口内完成；
  4. 遇到 `stale_nonce`、`nonce_required`、`displayed request changed` 等其他 409 错误时立即抛出 `VerificationActionError` 中止，绝不盲目重试或借用新请求的 nonce。
- **对应测试名**：
  - `test_require_nonce_mode_succeeds_with_correct_nonce`（强制 nonce 模式放行验证）
  - `test_switch_guard_retry_and_reverification_on_conflict`（409 切换保护有界重试及复核验证）
  - `test_displayed_request_change_during_wait_aborts_without_blind_approve`（等待期请求变更绝不重绑防盲批）
  - `test_deny_and_locked_are_exempt_from_switch_guard`（deny 与 locked 豁免保护期快速执行）
- **有无不同意及理由**：**无不同意，完全赞同**。严格冻结 nonce、等待切换保护以及限制重试边界是防止界面抢占和跨会话误批的核心机制。

---

#### P1-2：只按 cwd 匹配，脚本会自动批准不属于本次验证的请求
- **怎么修的**：
  1. 启动子进程前生成唯一 UUID 会话 ID（[pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L1917)），通过 `--session-id` 传给 Claude CLI，并在最终 CLI JSON 输出中严格校验 `session_id` 一致；
  2. 在 [pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L685-L707) 的 `_find_target_session` 中，只提取 `session_id == expected_session_id` 且 `agent == "cc"` 且 `cwd == test_dir` 的会话；同一目录检测到的其他外部会话严格忽略并记录在 `notes` 中；
  3. 各场景设置专用校验器（validator），严格核对工具名称（`Write`/`Bash`）、完整命令或归一化绝对文件路径、风险等级及 gate 阶段；遇到任何偏差或同会话多余请求立即抛出 `UnexpectedRequestError` 中止子进程，绝不自动批准；
  4. `_audit_delta`（[pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L839-L843)）严格按本次 `session_id` 与 `agent == "cc"` 过滤，禁止回退借用其它记录。
- **对应测试名**：
  - `test_foreign_session_on_same_cwd_is_strictly_ignored_and_untouched`（同 cwd 外部 cc 会话存在高危命令时不被触碰或批准）
  - `test_foreign_session_wrong_agent_same_cwd_is_strictly_ignored`（同 cwd 的 cx 会话不被触碰）
  - `test_unexpected_request_aborts_immediately_without_approval`（子用例涵盖工具名不匹配、写入路径偏移，均立刻中止杀进程且无 allow 审计）
  - `test_other_concurrent_session_on_hub_is_not_touched`（跨目录并发会话保持未决待批）
- **有无不同意及理由**：**无不同意，完全赞同**。自动审批器必须严格限定在本次启动的子会话和确定命令范围，杜绝意外放行。

---

#### P1-3：critical 命令没有保证无害，末尾 marker 也不能证明整条命令从未启动
- **怎么修的**：
  1. 将原有 `curl http://127.0.0.1:9/... | sh` 替换为无网络连接、不执行 shell 管道的无害词法样本（[pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L65-L68)）：
     `printf '%s\n' 'curl http://127.0.0.1:9/x | sh' > ./<sandbox>/critical_canary.txt`；
  2. 该命令词法命中 `CRITICAL_RULES` 分类规则，即便被执行也仅向沙盒写入金丝雀文件，彻底消除对 9 端口服务状态的假设；
  3. 报告与断言明确命名为词法规则及权限锁验证，断言命名由夸大证明范围的 `command_not_executed` 改为准确的 `canary_not_created`，并结合锁定审计 `audit_recorded_locked` 和 CLI 拒绝事件综合判定。
- **对应测试名**：
  - `test_critical_command_safety_and_lexical_classification`（词法判定为 critical、printf 结构无危险管道）
  - `test_judgment_logic_catches_failures_in_each_scenario`（`s4_rogue_exec` 子项断言 `canary_not_created` 捕获异常生成）
- **有无不同意及理由**：**无不同意，完全赞同**。测试安全装置本身不能依赖脆弱的网络未监听假设，将危险语法包裹在字面量中既满足词法分类又具备确定无害性。

---

#### P1-4：开启现有 gate 时实际批准三次，仍声称第二次就执行
- **怎么修的**：
  1. 在场景 3（[pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L1218-L1541)）中彻底拆分 `PreToolUse` gate 与 `PermissionRequest` 的状态机：
     - gate 阶段：记录第 1 次确认（confirm）与第 2 次放行（allowed）；
     - 第 3 次批准（PermissionRequest）前检查沙盒目录与金丝雀文件依然完好（`not_executed_before_third_approve=True`），证明前两次 gate 放行并未执行命令；
     - 第 3 次批准后检查目录已删除（`target_removed_after_all_approvals=True`）；
  2. 如实记录审批细目（`approval_breakdown`）：gate 批准 2 次、权限批准 1 次，汇总为“2 次 gate + 1 次权限批准”，并在 gate 模式下将“两次即执行”（`executed_after_second_approve`）如实标为 `False`（未满足）；
  3. 在无 gate 模式（`use_gate=False`）下，提供严格的两次按键放行验证（首次 confirm、二次 allowed 且已执行）。
- **对应测试名**：
  - `test_all_five_scenarios_pass_permission_only_flow`（无 gate 流程下 2 次放行且 `executed_after_second_approve=True`，5 项全部通过）
  - `test_all_five_scenarios_pass_with_pretooluse_gate_enabled`（开启 gate 时如实记录 3 次批准、断言第 3 次前目录完好，如实判定 `executed_after_second_approve` 未满足，退回状态 1）
- **有无不同意及理由**：**部分保留意见，但在实现上严格遵循审查口径**：
  - *分析与处理*：在架构上，PreToolUse 闸门与 PermissionRequest 分别代表工具拦截层和运行时授权层，在 Hub 的现有设计中两层均需要 2FA 确认属于设计预期。Codex 认为脚本既然承诺“高危按两次放行”，在 3 次批准下就不应宣传“两次即执行”。因此脚本采取了最诚实的方式：如实记录“2 次 gate + 1 次权限批准”，断言第 3 次前未执行，并在 gate 模式下将 `executed_after_second_approve` 标为未满足；而在纯权限模式下完整验证两次放行。

---

#### P1-5：CLI 失败或无效 JSON 可以被判为通过
- **怎么修的**：
  1. 在 [pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L483-L534) 的 `_parse_claude_json` 中建立严格的多维校验体系：
     - `not_timed_out`：进程未发生超时；
     - `exit_zero`：所有场景统一要求 `returncode == 0`；
     - `json_parsed_as_object`：标准 JSON 解析且拒绝 NaN/Infinity 等非标准常量；
     - `type_is_result`：`type == "result"`；
     - `subtype_is_success`：`subtype == "success"`；
     - `is_error_false`：`is_error == False`；
     - `session_id_matched`：会话 ID 与本次子进程严格一致；
     - `permission_denials_well_formed`：结构化拒绝列表格式合法；
  2. 场景 1、3 校验工具未被拦截且文件/目录产生真实副作用；场景 2、4 校验 `permission_denials` 中必须包含预期的工具名称与拒绝参数，绝不把 CLI 非零退出或解析异常作为拒绝证据。
- **对应测试名**：
  - `test_cli_failure_or_invalid_json_fails_scenario`（子用例涵盖非零退出码 17、非法 JSON 文本、空 stdout、`is_error=True` 异常 subtype、会话 UUID 不一致，均判定场景失败）
- **有无不同意及理由**：**无不同意，完全赞同**。验证框架必须依赖双向证据（CLI 正常交付 + 明确的工具拒绝/放行事件），不能将子进程崩溃掩盖为预期拒绝。

---

#### P2-1：场景抛异常时，五行报告和该场景证据都不落盘
- **怎么修的**：
  1. 重构场景执行框架 `_execute_scenario`（[pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L1912-L2003)）：
     - 场景启动时记录初始 state 与 audit，并在 `try...except` 块中捕获所有异常（包括 HTTP 409、子进程启动异常、OS 错误）；
     - `finally` 块中收集子进程 stdout/stderr/returncode、快照 Hub 状态和审计增量；若发生异常将 `no_unhandled_exception` 设为 `False`；
     - 无论抛错与否，每个场景均调用 `_write_scenario_evidence` 立即落盘 6 项证据文件；
  2. 顶层 `run()`（[pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L2108-L2185)）使用 `outcomes_by_index` 记录状态；发生前置异常或 Hub 断开时，后续无法执行的场景全部自动填充并落盘为“跳过”；在 `finally` 最终确保生成完整的 5 行 `results.md`。
- **对应测试名**：
  - `test_scenario_exception_preserves_five_row_report_and_evidence`（在场景 2 人为抛出 `OSError`，验证场景 1 通过、场景 2 记录异常失败、场景 3-5 跳过，5 项证据全落盘，且 `results.md` 正好输出 5 行）
- **有无不同意及理由**：**无不同意，完全赞同**。无论执行在哪一步发生意外，取证留存与结构化汇报必须具备鲁棒性。

---

#### P2-2：critical 锁定靠轮询短暂状态，测试特意等待观察者，掩盖真实竞态
- **怎么修的**：
  1. 从 [pc/test_verify_real_session.py](file:///D:/desk/hardware/h1/pc/test_verify_real_session.py#L288-L293) 的 `FakeClaudeEnvironment` 中**彻底删除**观察者感知的等待锁（`self.two_locked_approves`），杜绝测试替身配合主流程的假象；
  2. 真实 Claude 场景中，critical 请求在 Hub 中为 `locked` 状态，后续 `Stop` 事件会将其清出；在 [pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L1735-L1750) 中严格区分“Hub 审计已记录锁定，但实时状态被后续 Stop 事件清除未能采到两次 HTTP 响应”与“钩子从未触发”：
     - 若错过现场，明确报告未完成实时探测，绝不从审计反向伪造两次 HTTP approve 响应；
     - 此时不会误报 `_missing_hook_note()`。
- **对应测试名**：
  - `test_critical_fast_stop_race_condition_reported_accurately`（无等待快速 Stop 时序下，验证 Hub 锁定审计记录为 True、两次探测为 False，提示信息准确解释被后续事件清除，且绝不显示“Hub 未收到请求”误报）
- **有无不同意及理由**：**无不同意，完全赞同**。测试替身不应受被测代码控制；现场采样与审计链条应明确解耦。

---

#### P2-3：固定沙盒会删除测试目录里预先存在的数据
- **怎么修的**：
  1. 废除固定目录 `_verify_high_sandbox`；在 [pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py#L640-L676) 中实现动态唯一沙盒：
     - 每次运行新建 `_verify_run_<timestamp>_<uuid[:8]>`；
     - 沙盒内写入所有权标记文件 `.agentdeck_verify_owner.json`（含 PID、时间戳与 token）；
  2. 场景 1-4 的 `ok.txt`、`deny.txt`、`high_sandbox/target`、`critical_canary.txt` 以及场景 5 离线文件全部限定在该沙盒内部创建；
  3. `_cleanup_run_sandbox` 清理时严格核对沙盒所有权标记与 token，不满足或未持有则绝不删除，严禁预先或结束时删除测试目录下的既有数据。
- **对应测试名**：
  - `test_preexisting_files_and_directories_are_strictly_preserved`（在测试目录下预先放置 `ok.txt`、`deny.txt`、`unrelated_user_file.txt` 和 `_verify_high_sandbox/target/old.txt`，运行后所有既有文件与内容完好无损，仅本次沙盒被安全清理）
- **有无不同意及理由**：**无不同意，完全赞同**。沙盒生命周期与范围必须严格隔离，不污染、不误删任何已有测试数据。

---

### 修改文件汇总
1. [pc/verify_real_session.py](file:///D:/desk/hardware/h1/pc/verify_real_session.py)：
   - 增加 `HIGH_SANDBOX_DIR` / `HIGH_TARGET_REL` 兼容定义；
   - 包含完整的动态唯一沙盒与清理保护（P2-3）；
   - 审批携带冻结 nonce 与 `switch_guard` 有界重试（P1-1）；
   - 严格绑定 `--session-id`、`agent == 'cc'` 及工具命令校验，意外请求立即中止（P1-2）；
   - 安全的词法 critical 命令与断言重构（P1-3）；
   - gate 模式如实记录 3 次批准及第 3 次前目录完整性（P1-4）；
   - 严苛的 CLI 退出码与 JSON 数据验证（P1-5）；
   - 场景异常保护与 5 行报告兜底落盘（P2-1）；
   - critical 锁定采样与审计的精确区分（P2-2）。
2. [pc/test_verify_real_session.py](file:///D:/desk/hardware/h1/pc/test_verify_real_session.py)：
   - 替身 `FakeClaudeEnvironment` 绑定 `--session-id`，动态适配沙盒路径，移除观察者锁 `two_locked_approves`；
   - 适配新版 critical 命令与 `canary_not_created` 断言；
   - 更新 `test_all_five_scenarios_pass_permission_only_flow` 与 `test_all_five_scenarios_pass_with_pretooluse_gate_enabled`；
   - 扩充 12 项覆盖 P1-1 至 P2-3 的正反例测试（共 20 项独立测试方法）。
