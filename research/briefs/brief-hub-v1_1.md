# 简报：Hub v1.1（在 v1 基础上的两个小功能）

先读 `pc/hub_README.md` 和 `pc/hub.py`。只改 hub 相关文件，不要动 deck.py、daemon.py。

## 1. 第三档风险 L3：设备上不允许批准
- 把 `classify` 扩成三档：`low`、`high`、`critical`。
- 归为 critical 的情况：
  - 管道直接执行远程脚本：`curl|wget … | sh/bash/zsh/iex`、`iex (irm …)`、`Invoke-Expression (Invoke-WebRequest …)`；
  - PowerShell `-EncodedCommand` / `-enc`；
  - `base64 -d … | sh`；
  - 删根或删家目录：`rm -rf /`、`rm -rf ~`、`Remove-Item -Recurse` 作用于盘符根；
  - `format`、`mkfs`、`dd of=/dev/…`；
  - 写入 `~/.ssh/authorized_keys`。
- 规则写成可配置列表，和 high 一样。
- 收到 critical 的 PermissionRequest 时：**立即返回 `{}`**，让 agent 走自己的原生确认（必须在终端里确认）。同时：
  - 在会话表里把这条记成 `locked`；
  - LCD 显示 `LOCKED: use terminal`；
  - 写一条审计日志。
- `approve` 作用在 locked 记录上时，返回 `{"status":"locked"}`，什么都不做。

## 2. 审计日志
- 每个决定（allow / deny / timeout / locked）追加一行 JSON 到 `%USERPROFILE%\.agentdeck\audit.jsonl`。
- 字段：时间、agent、session_id、项目名、tool_name、命令原文（截断到 500 字）、风险档、决定、决定来源（key / http / timeout）、请求 id。
- 每行带上一行的 sha256，形成哈希链。
- `GET /audit?limit=50` 返回最近记录（需要 token）。

## 3. `python pc/hub.py doctor` 自检命令
逐项打印 ✓ / ✗ 和修复建议：
- hub 是否在跑（/health）；
- token 文件是否存在；
- `~/.claude/settings.json` 和 `~/.codex/hooks.json` 里有没有 hub_relay 条目；
- hub 最近 10 分钟有没有收到 cc / cx 的事件（hub 要在 /state 里提供 `agents_seen: {"cc": 最后时间, "cx": 最后时间}`）。没收到 cx 事件时，提示"在 Codex 里输入 /hooks 信任 AgentDeck 钩子"；
- `claude` 命令是否已登录：运行 `claude auth status` 或等价命令，超时 5 秒；拿不到就提示"运行 claude 登录"。不要真的去登录。

## 测试
- 在 `pc/test_hub.py` 里加离线测试：
  - critical 立即返回 `{}`，approve 不起作用；
  - 审计哈希链连续，篡改一行能检出；
  - doctor 在各种替身状态下输出正确的建议。
- 所有现有测试必须仍然通过。不要碰 COM4，不要装钩子。
- 汇报：改动文件、全部测试输出。
