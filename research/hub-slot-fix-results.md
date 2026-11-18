# Hub 会话槽位回收修复结果

日期：2026-11-18。项目：`D:\desk\hardware\h1`。

## 改动

- `pc/hub.py`：六槽占满时，从没有任何 `pending` / `locked` 请求且不是 `voice_target` 的会话中，按 `last_updated` 淘汰最旧会话，新会话复用该槽，其他槽号不变。没有合法候选时保留 HTTP 409。
- `pc/hub.py`：新增 `SESSION_IDLE_SECONDS = 21600`；`_expire()` 在处理请求超时后，撤下最后更新时间超过六小时的可回收会话。维护、状态查询、事件和动作入口都会经过该检查；恰好六小时仍保留。
- `pc/hub.py`：将原 `SessionEnd` 清理集中到 `_remove_session()`，由结束、淘汰和过期共用，包括清理请求和 gate 确认记录、向 LCD 发送 `end <key>`、转移 `selected` 及当前显示请求。选中会话被移除时，优先转到现存请求；没有请求时按原 `SessionEnd` 行为选择剩余会话。
- `pc/test_hub.py`：新增 10 个离线回归测试，更新原先“空闲六槽满后必须拒绝”的旧断言。
- `pc/test_hub_overlay.py`：为直接构造的会话测试夹具补上 `last_updated`，符合真实会话字段。
- `research/hub-slot-fix-results.md`：记录本次改动、验证和打包结果。

候选保护的边界：六个会话都有请求时返回 409；五个有请求、另一个是当前语音目标时同样返回 409，因为没有合法淘汰候选。

## 离线验证

Python：`D:\conda\miniconda3\python.exe`。运行测试使用 `-B`，避免历史实现的差分测试产生缓存文件。

修复前已复现：创建六个空闲会话后，第七个抛出 `HubError 409 all six session slots are occupied`。新增槽满测试在修复前为 `Ran 5 tests ... FAILED (errors=3)`，修复后定向测试 10/10 通过。

新增覆盖包括：按最后更新时间淘汰、复用槽位及保留其他槽号、第七个会话获批、pending 和 locked 保护、全 pending / 全 locked 时仍 409、语音目标保护、选中状态及显示请求转移、六小时边界、最近更新续期、状态查询触发回收、语音释放后回收，以及 LCD `end` / 焦点和 gate 记录清理。

全量收集使用 `unittest.TestLoader().discover('pc', pattern='test_hub*.py')`，覆盖全部 **19 个文件**。最终实际输出：

```text
FILES=19 EXECUTED=476 UNIQUE=404 FAILURES=0 ERRORS=0 SKIPPED=0
Ran 476 tests in 20.859s
OK
Executed: 476; failures: 0; errors: 0; skipped: 0
```

476 为执行次数，按 `test.id()` 去重为 404 个独立用例；差异来自 `test_hub.py` 原有的测试类导入。完整输出保存在 `build/hub-slot-fix-tests.log`。可从项目根目录复跑：

```powershell
& 'D:\conda\miniconda3\python.exe' -B -m unittest discover -s pc -p 'test_hub*.py' -v
```

项目要求的其他检查均退出 0，实际汇总输出：

| 命令（均使用上述 Python，附加 `-B`） | 实际输出 |
| --- | --- |
| `pc/test_ui.py` | `UI: 7 groups passed` |
| `pc/test_daemon.py` | `daemon offline tests: 10 groups passed` |
| `pc/test_pc.py` | `PC and firmware loop: 4 groups passed` |
| `pc/sim.py` | `Rendered 42 scenarios -> D:\desk\hardware\h1\lcd1602\preview-sim.png` |

三个修改过的 Python 文件通过语法编译、`tabnanny` 缩进检查和限定改动文件的 `git diff --check`。环境未安装 Ruff、Pyflakes 或 mypy，未新增依赖，未运行独立类型检查器。

## 打包

重新执行 `cmd.exe /d /c build_exe.bat`，使用脚本指定的 Python 和 PyInstaller 6.11.1，**退出码 0，打包成功**。实际结束输出：

```text
Building COLLECT COLLECT-00.toc completed successfully.
Built: D:\desk\hardware\h1\dist\AgentDeck\AgentDeck.exe
Relay: D:\desk\hardware\h1\dist\AgentDeck\AgentDeck-relay.exe
```

| 产物 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `dist/AgentDeck/AgentDeck.exe` | 5710556 | `add77abf7c5672e35bee7695d21125b564fca0b8b928d173d5de1dd305d67fe4` |
| `dist/AgentDeck/AgentDeck-relay.exe` | 1754575 | `1ec391b9b02482fc36a1caeb693ee31a7e3bf3281bc379087c3c51765415faaa` |

使用 PyInstaller 归档读取器静态提取主 EXE 中的 `hub`，递归比对代码字节码、常量和名称，确认与当前 `pc/hub.py` 一致，且含 21600 秒 TTL。打包日志和静态核验元数据分别保存在 `build/hub-slot-fix-build.log`、`build/hub-slot-fix-package.json`。

## 验证范围

未启动常驻进程或打包后的应用；HTTP 测试仅使用自动关闭的临时 loopback 服务，设备和桌面输入使用替身。未打开 COM4、未上传或修改固件，未修改真实 `~/.claude` / `~/.codex` 配置，也未修改 `wokwi/`、`backup/`、`_rollback/`。实际 LCD 和已打包应用的交互未做硬件验证。

工作区原有的 `research/app-exe-package-check.json` 修改保持原样，本次未更新该文件；本次包核验数据见上述独立记录。
