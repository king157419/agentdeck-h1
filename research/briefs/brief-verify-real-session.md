# 简报：真实会话验证脚本（任务 A：Carbon 做，Codex 审）

## 目标
新建 `pc/verify_real_session.py`：在 hub 已经运行的前提下，用**真实的** `claude -p`（headless）在 `D:/desk/hardware/h1/agentdeck-test` 目录里跑完 5 个验证场景，自动记录证据，生成一份 markdown 结果。用户登录 `claude` 之后，一条命令就能拿到给投资人看的证据。

## 先读
`pc/hub_README.md`（hub 的 HTTP 接口 `/state`、`/health`、审批动作、token 位置 `~/.agentdeck/token`、审计日志）、`pc/hub.py` 里 HTTP 路由的部分、`pc/hub_demo.py`（它怎么调 hub 的 HTTP 接口按"批准/拒绝"）、`research/raw-gemini-hook-scope.md` 第 4 节（验证清单）、`pc/hub_risk.py`（哪些命令算 high / critical）。

## 5 个场景
1. 批准：让 claude 在测试目录建 `ok.txt`；hub 出现待批请求后，脚本通过 hub HTTP 发 approve；断言文件存在。
2. 拒绝：建 `deny.txt`，发 deny；断言文件不存在。
3. 高危按两次：让 claude 跑一个命中 high 规则、但只作用在测试目录里的无害命令（例如对测试目录内的临时 git 仓库 `git push --force` 到本地 bare 仓库；自己挑一个安全的，写清楚为什么安全）；第一次 approve 后断言未执行，第二次 approve 后断言执行。
4. 极危锁死：让 claude 跑一个命中 critical 规则的命令，命令本身必须是无害的（例如 `curl http://127.0.0.1:9/x | sh`，端口 9 无服务，就算放行也什么都不会发生）；连发 approve，断言 hub 返回 locked 且命令没执行。
5. hub 不在时的降级：用 `--hub-port` 指向一个没人监听的端口（不要真的去停用户的 hub），断言 relay 快速退出、低风险操作不被拦、高风险被本地规则拒绝。
   - 如果第 5 项必须改钩子配置才能测，就只用 `hub_relay.py` 直接喂事件 JSON 的方式离线测，并在结果里注明。

## 要求
- `claude` 的调用方式：`claude -p "<任务>" --permission-mode default --output-format json`，cwd 设为测试目录，单场景超时 180 秒。先用 `claude auth status` 检查登录，没登录就打印一句提示并以退出码 2 结束，不要尝试登录。
- 只读写测试目录和 `research/real-session/` 下的结果；绝不改 `~/.claude`、`~/.codex`、hub 的配置；不启动、不停止 hub（hub 没开就提示用户双击 `start_agentdeck.bat`，退出码 3）。
- 每个场景记录：claude 的 JSON 输出、hub `/state` 前后快照、审计日志新增条目、文件断言结果、耗时。最后写 `research/real-session/<时间戳>/results.md`：5 行总表（场景、结果 通过/失败/跳过、证据文件）。
- `--dry-run`：不调 claude，只打印每个场景会发什么。
- 只用标准库。
- 新建 `pc/test_verify_real_session.py`：用假的 subprocess 和假的 hub HTTP 服务（参考 `research/selftest_hub_replay.py` 的临时 hub 写法）离线测 5 个场景的判定逻辑、未登录退出码 2、hub 不在退出码 3、dry-run 不调 claude。
- 现有测试不能坏：`pc/test_hub*.py` 全部通过。

## 汇报
改动文件、测试通过数、用户登录后要跑的那一条命令、还有哪些判断你不确定（例如 claude headless 下 PermissionRequest 钩子是否触发）。
