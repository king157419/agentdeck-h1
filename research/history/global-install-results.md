# 全局钩子启用：完成记录

2026-11-18，按 `research/briefs/brief-global-install.md` 完成。

## 实现与修改文件

- `pc/agentdeck_app.py`：托盘新增“所有项目启用”，勾选状态每次读取两份全局配置，只有两者各含对应 agent 的 AgentDeck 钩子才勾选；原入口移入“单个项目”。启用时只确认一次，依次调用旧钩子备份移除和全局安装；停用只卸载 AgentDeck 钩子，不恢复旧钩子。首次引导使用同一全局入口，已全局启用或有已登记项目安装时跳过；取消或安装失败保留引导窗口，失败显示错误。exe 启动时检测移动后的 relay 路径，已全局启用才静默重装并记日志；修复失败仅记录日志，不阻止启动。
- `pc/hub_install.py`：新增只读 `global_status(home=...)`，分别报告启用状态、缺失路径、是否需要修复和配置读取错误。识别当前 exe 旁的 relay 路径，旧文件仍存在也可判断路径已改变。
- `pc/hub_doctor.py`：托盘诊断和命令行诊断均显示“全局钩子：已启用 / 未启用 / 路径失效”。命令行汇总行不改变原有检查计数和退出码。
- `pc/test_agentdeck_app.py`：覆盖菜单层级、真实配置勾选、取消、确认与调用顺序、原始配置备份、停用不恢复旧钩子、备份失败、引导与错误处理、目录移动后一次修复、未安装或单边安装不修复、源码运行不修复、修复失败日志和启动接入。
- `pc/test_hub_app_support.py`：新增全局状态测试，覆盖两份配置、错误 agent、损坏配置、失效路径、目录移动、旧源码命令、Windows 路径大小写与斜杠、中文及空格路径、只读行为。
- `pc/test_hub_doctor.py`：覆盖命令行三种全局状态。
- `pc/test_hub_relay.py`：扩展 Hub 未运行时的子进程测试，覆盖 Claude/Codex 的 `PermissionRequest` 和有/无 token；均断言退出码为 0、stdout/stderr 为空、耗时小于 1.5 秒。原 CLI 测试补齐临时 `--home`。

复用原安装器、旧钩子识别与备份机制；诊断复用全局状态检测，删除重复路径扫描，并共用中文状态文案。未新增依赖。

## 实际验证

在项目根目录使用 `D:\conda\miniconda3\python.exe` 执行，以下命令均退出 0：

| 命令 | 真实输出摘要 |
| --- | --- |
| `D:\conda\miniconda3\python.exe pc/test_agentdeck_app.py` | `Ran 61 tests in 1.118s` / `OK` |
| `D:\conda\miniconda3\python.exe pc/test_hub_app_support.py` | `Ran 24 tests in 0.730s` / `OK` |
| `D:\conda\miniconda3\python.exe pc/test_hub.py` | `Ran 144 tests in 5.446s` / `OK` |
| `D:\conda\miniconda3\python.exe pc/test_hub_install.py` | `Ran 35 tests in 2.289s` / `OK` |
| `D:\conda\miniconda3\python.exe pc/test_hub_doctor.py` | `Ran 14 tests in 0.494s` / `OK` |
| `D:\conda\miniconda3\python.exe pc/test_hub_relay.py` | `Ran 12 tests in 2.074s` / `OK`；最终 Hub 验收亦包含此套件 |
| `D:\conda\miniconda3\python.exe pc/test_ui.py` | `UI: 7 groups passed` |
| `D:\conda\miniconda3\python.exe pc/test_daemon.py` | `daemon offline tests: 10 groups passed` |
| `D:\conda\miniconda3\python.exe pc/test_pc.py` | `PC and firmware loop: 4 groups passed` |

新增测试显式使用临时 home，并对全局状态及应用操作禁止调用 `Path.home()`；没有读取或修改真实 `~/.claude`、`~/.codex`。外部进程、注册表和 GUI 操作用替身，relay 离线测试只启动指定临时 home 的子进程。

另以 Python AST 解析和编译检查全部 7 个修改的 Python 文件；`git diff --check` 无输出、退出 0。仓库无 lint/typecheck 配置，指定 Python 未安装 ruff、mypy、pyright，未安装额外工具，未将语法检查当作类型检查。

## 验证范围

未打包或运行 exe，frozen 启动行为通过替身测试；发布后仍需人工检查真实托盘与 CLI 的集成。relay 测试证明审批事件无输出、无外部审批决定，终端提示的实际展示仍由 agent CLI 处理。

未打开 COM4、上传固件或调整 `hub_overlay.py` 样式；LCD 输出未改变，因此未运行 `pc/sim.py`。未修改 `wokwi/`、`backup/`、`_rollback/`。本次未执行真实全局安装，生效由用户在托盘启用。
