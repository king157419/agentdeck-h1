# 简报：Hub v1.4 —— PreToolUse 高危闸门（auto mode 开着也能拦）

**为什么要做：** auto mode 开着时，agent 不会发 `PermissionRequest`，现在的 hub 拦不住高危命令。设计写在 `agentdeck/07-技术方案.md` 第 6.4 节（第 330–363 行），先读那一节，**以它为准**。

## 要做的
1. relay 支持闸门模式：`hub_relay.py --agent cc|cx --gate`。闸门模式下 POST 到 `/event?agent=..&gate=1`，读超时和 PermissionRequest 一样（approve-timeout + 5 秒）。
2. hub 处理 `PreToolUse` + `gate=1`：
   - 风险分级复用 `classify`。闸门的默认拦截范围是 high 和 critical，规则列表补齐 07 §6.4 表里的这些：
     - `git push` 到受保护分支（main / master / release/*）或带 `--force`；
     - `gh pr merge`；
     - `kubectl apply|delete|exec`；`terraform apply|destroy`；`helm upgrade`；
     - 数据库写操作：`DROP`、`DELETE FROM`、`UPDATE … SET`、`ALTER`、迁移命令；
     - 写 `.env`、密钥文件、`~/.ssh`；
     - 生产主机 `ssh`：读配置里的 `production_hosts` 列表。
   - low：立即返回 `{}`（不干预）。
   - high 和 critical：登记成待确认的闸门请求，在 LCD / 浮窗上显示为 `GATE`，然后阻塞等待：
     - 按 ✓ 两次（1.5 秒内）：返回 `{}`，**不返回 allow**。语义是"只加不减"，agent 自己的规则照常生效。
     - 按 ✗ 或超时：返回 `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Blocked by AgentDeck gate: <原因>"}}`。
     - critical 在闸门里也必须按两次 ✓ 才放过闸门，之后还会走 agent 自己的确认。闸门不做 L3 锁死，因为闸门本来就不会替 agent 放行。
   - 叠加去重：记住 `(session, tool_input 的 sha256)` 在 30 秒内已经通过闸门的命令。之后同一命令的 `PermissionRequest` 到来时，在请求上标 `gate_confirmed=true` 并显示"已在闸门确认"，但仍然要按 ✓，不自动放行。
   - 闸门的每个决定写进审计日志，`source` 记为 `gate`。
   - 配置 `gate_mode`：`high`（默认）/ `low`（L1 起都拦）/ `off`。
3. `hub_install.py` 支持 `--gate`：额外安装一个 PreToolUse 钩子。
   - Claude 用 matcher `Bash|Edit|Write|mcp__.*`，timeout 120 秒；Codex 照 hooks.json 现有格式写。
   - 默认不装，`install --gate` 才装。卸载能删干净。
4. 浮窗（v1.3）显示闸门请求，标题写 `GATE`，按钮和普通请求一样。

## 测试（离线）
- low 立即返回 `{}`，耗时 < 50 ms。
- high 按一次不放，按两次返回 `{}`；按 ✗ 返回 deny 和原因；超时返回 deny。
- 去重标记正确，并且 PermissionRequest 仍然要按键。
- 安装 / 卸载闸门钩子幂等。
- 现有全部测试通过；`research/selftest_hub_replay.py` 仍然全部 PASS。不碰 COM4，不装真实钩子。

改动前备份到 `_rollback/hub-v1_3/`。汇报：改动文件、测试输出。
