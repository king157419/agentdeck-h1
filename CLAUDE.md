# h1 — Agent 状态屏（ESP32 + 1602 LCD）

硬件、命令、文件说明都在 `lcd1602/README.md`，先读它，不要重新摸索。

## 省额度规则（所有在本目录工作的 Claude 都要遵守，包括子代理）

1. **工程活交给 Codex。** 写代码、改代码、跑测试、查 bug、读大文件，一律用
   `omc ask codex "<任务>"`（走用户的 ChatGPT 账号，不花 Claude 额度）。
   从本目录运行，Codex 会自动读 `AGENTS.md`，所以简报只写"做什么 + 做完的标准"，不必重讲项目背景。
2. **Claude 只做三件事：** 把需求写成简报、审 Codex 的结果（看 diff 和测试输出，不重读整份文件）、向用户汇报。
3. **Codex 做不了或连续两次没做对**，才换 Sonnet 子代理（`executor`）。不要用 Opus 子代理，除非用户点名。
4. **主会话自己不动手写实现。** 例外：三行以内的小改动，直接改比写简报更省。
5. **少读。** 不要通读 `wokwi/.pio/`、`backup/`、`_rollback/`、`research/`、`*.log`、`*.pdf`；找东西用 Grep 定位到行再读。
6. **不要并行开多个子代理**，不要为小任务跑 workflow / 多模型编排。
7. 回复写短：结论、需要用户亲自确认的清单、回滚命令。不写过程复述。

## 固定约定

- Python 用 `D:\conda\miniconda3\python.exe`。
- 简报放 `research/briefs/`，测试记录、日志、评审稿放 `research/history/`，不要堆在 `research/` 或根目录。
- 改固件前先把上一版复制到 `_rollback/<版本号>/`，汇报里给出回滚命令。
- 测试：`python pc/test_ui.py`、`pc/test_daemon.py`、`pc/test_pc.py`；离线预览：`python pc/sim.py`。
- 上板（COM4）和屏幕实际观感只能由用户确认，放进回复的确认清单里，不要写进 README。
- 当前重点是功能，不是美术和动效；用户没提就不要动动画。
