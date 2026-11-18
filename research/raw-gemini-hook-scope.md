### 1. Claude Code 项目级 Hooks、合并规则、`PermissionRequest` 规范与桌面版行为

#### 1.1 项目级 `.claude/settings.json` / `.claude/settings.local.json` 里的 `hooks` 是否生效？
* **结论**：**生效**。Claude Code 支持在项目共享配置 `<project>/.claude/settings.json` 与项目本机私有配置 `<project>/.claude/settings.local.json` 中定义 `hooks`，且仅对该项目目录生效。
  * 官方文档：[Claude Code Settings](https://code.claude.com/docs/en/settings) ｜ [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
* **细节**：
  * `~/.claude/settings.json`：用户级全局配置，作用于本机所有项目。
  * `.claude/settings.json`：项目级共享配置，面向团队纳入 Git 管理。
  * `.claude/settings.local.json`：项目级个人本机配置，Claude Code 会自动将其排除在 Git 之外（gitignore），非常适合在 `D:/agentdeck-test` 做本机隔离验证。

#### 1.2 项目级 `hooks` 和用户级 `hooks` 如何合并（叠加还是覆盖）？
* **结论**：**叠加合并（合并并去重，不会覆盖清空）**。如果在 `~/.claude/settings.json` 保留了全局钩子，即便在项目目录配置了 `.claude/settings.local.json`，全局钩子依然会在所有项目和本项目中同时触发。
  * 官方文档：[Claude Code Settings — Settings precedence](https://code.claude.com/docs/en/settings) ｜ [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
* **细节**：
  * 标量配置按优先级覆盖（托管策略 > 命令行参数 > `.claude/settings.local.json` > `.claude/settings.json` > `~/.claude/settings.json`）。
  * 数组型配置（如 `permissions.allow`、`hooks` 下的匹配器与处理器列表）会跨所有适用层级**拼接并去重（concatenated and deduplicated）**，所有匹配的钩子都会执行。因此要做单目录隔离测试，**必须先把全局 `~/.claude/settings.json` 里的 AgentDeck 钩子删掉**。

#### 1.3 项目级 `hooks` 是否需要信任确认？
* **结论**：**需要目录级工作区信任确认（Workspace Trust Dialog）**。在交互式会话中，在你接受该文件夹的工作区信任弹窗前，Claude Code 会暂缓执行所有钩子。
  * 官方文档：[Claude Code Settings](https://code.claude.com/docs/en/settings) ｜ [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks) ｜ [Claude Code Security](https://code.claude.com/docs/en/security)
* **细节**：
  * 区分权限规则与钩子：`.claude/settings.local.json` 中的 `allow` 权限规则（未被 Git 追踪时）可免工作区信任直接生效；但针对 **`hooks`**，官方文档明确说明交互式会话在用户接受该目录的 Workspace Trust 弹窗前会拦截所有钩子（*"Interactive sessions hold back every hook, including yours, until you accept the workspace trust dialog"*）。
  * 会话启动快照（Snapshot）：Claude Code 在会话启动时对 `hooks` 配置做快照，运行中途修改 `settings*.json` 不会实时生效，需重启会话（可用 `/hooks` 查看当前已加载钩子）。

#### 1.4 `PermissionRequest` 钩子的输入输出格式和超时后的行为
* **结论**：通过 `stdin` 接收含 `tool_name`、`tool_input` 和可选 `permission_suggestions` 的 JSON；必须以**退出码 `0` + `stdout` JSON（`hookSpecificOutput.decision.behavior`: `"allow"` 或 `"deny"`）**返回决策（**退出码 `2` 在 `PermissionRequest` 上无效**）；默认未设 `onFailure: "block"` 时，超时属于非阻塞错误，会终止钩子并**回退到原有的交互式权限确认流程**（不会自动批准）。
  * 官方文档：[Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
* **细节**：
  * **输入格式（`stdin` JSON）**：
    ```json
    {
      "session_id": "abc123",
      "transcript_path": "/path/to/transcript.jsonl",
      "cwd": "D:/agentdeck-test",
      "permission_mode": "default",
      "hook_event_name": "PermissionRequest",
      "tool_name": "Bash",
      "tool_input": {
        "command": "rm -rf ./tmp",
        "description": "Remove tmp directory"
      },
      "permission_suggestions": [
        {
          "type": "addRules",
          "rules": [{ "toolName": "Bash", "ruleContent": "rm -rf ./tmp" }],
          "behavior": "allow",
          "destination": "localSettings"
        }
      ]
    }
    ```
  * **输出格式（退出码 `0` + `stdout` JSON）**：
    * 批准（可选附带 `updatedInput` 改写参数或 `updatedPermissions` 更新会话权限规则）：
      ```json
      {
        "hookSpecificOutput": {
          "hookEventName": "PermissionRequest",
          "decision": {
            "behavior": "allow"
          }
        }
      }
      ```
    * 拒绝（可选附带 `message` 告知模型原因、`interrupt: true` 直接中止当前轮次）：
      ```json
      {
        "hookSpecificOutput": {
          "hookEventName": "PermissionRequest",
          "decision": {
            "behavior": "deny",
            "message": "物理按键已拒绝本次操作",
            "interrupt": false
          }
        }
      }
      ```
  * **退出码差异警告**：与 `PreToolUse`（退出码 `2` 会直接阻断工具）不同，官方参考表对 `PermissionRequest` 的规定为：*`Not honored: the permission flow proceeds unchanged and stderr is discarded. Deny through the JSON decision object`*。因此拒绝必须输出上述 JSON。
  * **超时行为**：`command` 钩子默认 `timeout` 为 `600` 秒（可在配置中按秒指定，如 `120`）。达到超时后进程被取消并标记为 `timed out`：
    * 默认情况（未设置 `onFailure`）：视为非阻塞失败，丢弃输出，**继续走原有的交互式权限弹窗**。
    * 若显式配置 `"onFailure": "block"`：在 `PermissionRequest` 超时或执行失败时，Claude Code 会**直接拒绝（deny）该权限请求**。

#### 1.5 Claude 桌面版的 Code 标签页是否也读这些设置文件？
* **结论**：**是，完全读取同一套设置文件**。终端 CLI、IDE 扩展与 Claude Desktop 桌面版（Code 标签页本地会话）共用 `~/.claude/settings.json`、`<project>/.claude/settings.json` 和 `<project>/.claude/settings.local.json`。
  * 官方文档：[Claude Code Settings](https://code.claude.com/docs/en/settings) ｜ [Claude Code on Desktop](https://code.claude.com/docs/en/desktop)
* **细节**：
  * 官方 Settings 文档明确写明：*"the terminal, the VS Code and JetBrains extensions, and the desktop app, which all read the same settings files."* 这正是写进 `~/.claude/settings.json` 会影响桌面版所有会话的原因。
  * 在桌面版本地会话的文件面板中，`.claude/settings.json` 为只读（view-only），需用外部编辑器修改；且修改后同样需新开/重启会话才生效。
  * 注：关于桌面版 Code 标签页原生权限 UI 与 `PermissionRequest` 钩子同时等待时的更底层竞争细节，`/docs/en/desktop` 页面未单列说明——**未查到官方说明**。

---

### 2. Codex CLI（0.144 以上）项目级 Hooks、`/hooks` 信任机制与单目录隔离

#### 2.1 `hooks` 是否支持项目级配置（如 `.codex/hooks.json` 或 `config.toml`）？
* **结论**：**支持**。Codex CLI 支持在仓库根目录下的 `<repo>/.codex/hooks.json` 或 `<repo>/.codex/config.toml`（内联 `[hooks]` 表）定义项目级钩子；多层钩子同样是**叠加执行而非覆盖**。
  * 官方文档：[OpenAI Codex Hooks](https://developers.openai.com/codex/hooks) ｜ [OpenAI Codex Configuration Reference](https://developers.openai.com/codex/config-reference) ｜ [openai/codex `docs/config.md`](https://github.com/openai/codex/blob/main/docs/config.md)
* **细节**：
  * 0.144+ 中功能开关规范键名为 `[features] hooks = true`（默认启用，旧名 `codex_hooks` 为兼容别名）。
  * 四个主要发现位置：`~/.codex/hooks.json`、`~/.codex/config.toml`、`<repo>/.codex/hooks.json`、`<repo>/.codex/config.toml`。同一配置层若同时存在 `hooks.json` 与 `config.toml` 内联 `[hooks]`，Codex 会合并它们并打印启动警告，官方建议每层只用一种写法。
  * 合并规则：用户级与项目级钩子**全部加载并匹配执行**（高优先级不会替换低优先级钩子）。
  * 项目根判定：Codex 默认从当前工作目录 `cwd` 向上查找 `.git`（可通过 `config.toml` 的 `project_root_markers` 自定义）来定位 `<repo>` 根并读取 `<repo>/.codex/hooks.json`。
  * Schema 对齐：Codex CLI 的 `PermissionRequest` 输出同样使用 `hookSpecificOutput.decision.behavior`（`"allow"` | `"deny"`），`PreToolUse` 输出使用 `hookSpecificOutput.permissionDecision`（`"allow"` | `"deny"` | `"ask"`）或退出码 `2` 阻断；注意 Codex 内部修改文件的规范 `tool_name` 为 **`apply_patch`**（Shell 为 `Bash`）。

#### 2.2 `/hooks` 信任机制怎么工作？
* **结论**：采用**“项目目录信任（`trust_level`）+ 钩子定义哈希审批（`/hooks` -> `trusted_hash`）”双重信任机制**；未审批或被改动过的非托管命令钩子会被静默跳过。
  * 官方文档：[OpenAI Codex Hooks](https://developers.openai.com/codex/hooks) ｜ [OpenAI Codex Security](https://developers.openai.com/codex/security/) ｜ [openai/codex `docs/config.md`](https://github.com/openai/codex/blob/main/docs/config.md)
* **细节**：
  1. **第一重（项目目录信任）**：若项目目录未被信任，Codex 会忽略整个 `<repo>/.codex/` 层（含 `config.toml` 与 `hooks.json`）。可在首次进入目录的 TUI 提示中选择信任，或在全局 `~/.codex/config.toml` 写入 `[projects."<绝对路径>"] trust_level = "trusted"`。
  2. **第二重（`/hooks` 内容指纹信任）**：官方规定 *"Non-managed hooks must be reviewed and trusted before they run"*。对所有非系统托管（用户级或项目级）的 `command` 钩子，Codex 会计算钩子定义的内容哈希。首次添加或修改 `hooks.json`（包括命令字符串、参数、数组顺序变化）后，必须在 Codex CLI 交互界面输入 **`/hooks`** 打开 Hook Browser 审阅并批准；批准后 Codex 在 `~/.codex/config.toml` 的 `[hooks.state."<source>:<event>:<group_idx>:<handler_idx>"]` 下持久化 `trusted_hash`。哈希不匹配时钩子不执行。

#### 2.3 能否只对某个目录生效？
* **结论**：**能**。只需清空全局 `~/.codex/hooks.json` 中的对应钩子，确保目标目录具备项目根标记（如 `.git`），把钩子仅写入 `D:/agentdeck-test/.codex/hooks.json`，并在该目录内完成信任与 `/hooks` 批准即可。
  * 官方文档：[OpenAI Codex Hooks](https://developers.openai.com/codex/hooks) ｜ [OpenAI Codex Configuration Reference](https://developers.openai.com/codex/config-reference)
* **细节**：由于 Codex 只从当前 `cwd` 所属的 `<repo>/.codex/` 加载项目层钩子，其他任何目录下的 Codex 会话都不会读取 `D:/agentdeck-test/.codex/hooks.json`。

---

### 3. 只在 `D:/agentdeck-test` 验证且不影响其他会话的具体步骤与 `--project` 方案

* **结论**：先摘除全局 `~/.claude/settings.json` 与 `~/.codex/hooks.json` 中的 AgentDeck 钩子防止跨层叠加；将 `D:/agentdeck-test` 初始化为含 `.git` 的独立根目录；分别写入 `D:/agentdeck-test/.claude/settings.local.json` 和 `D:/agentdeck-test/.codex/hooks.json`（使用 `hub_relay.py` 的绝对路径）；首次进入时完成目录信任与 `/hooks` 审批。
  * 官方文档依据：[Claude Code Settings](https://code.claude.com/docs/en/settings) ｜ [Claude Code Hooks](https://code.claude.com/docs/en/hooks) ｜ [OpenAI Codex Hooks](https://developers.openai.com/codex/hooks)

#### 3.1 具体操作步骤与文件内容
> 注：下文中 `<ABS_PATH_TO_HUB_RELAY>` 请替换为 `hub_relay.py` 的真实绝对路径（如 `D:/agentdeck/hub_relay.py`）；题目仅给出了 `PreToolUse` 的完整命令 `python hub_relay.py --agent cc --gate`，`PermissionRequest` 的子参数及 Codex 的 `--agent` 名称（官方无此脚本参数定义——**未查到官方说明**）请按你们 `hub_relay.py` 实际 CLI 参数替换。

1. **清理全局配置（关键，防止影响桌面版和其他终端会话）**
   * 编辑 `C:/Users/<用户名>/.claude/settings.json`：删除 `hooks` 下指向 `hub_relay.py` 的 `PreToolUse` 和 `PermissionRequest` 条目（保留其他个人设置）。
   * 编辑 `C:/Users/<用户名>/.codex/hooks.json`：删除指向 `hub_relay.py` 的条目（若无其他钩子，可改为 `{"hooks": {}}` 或删除该文件）。
   * 重启已打开的 Claude Desktop 会话或其他终端会话（刷新启动快照）。

2. **初始化测试目录根标记**
   * 创建 `D:/agentdeck-test/`，并在其中初始化空的 `.git` 目录（执行 `git init`），确保 Codex CLI 默认的 `.git` 根目录查找能识别 `D:/agentdeck-test/.codex/hooks.json`。

3. **新建 `D:/agentdeck-test/.claude/settings.local.json`**（仅本机当前用户在该目录生效，自动 gitignore）：
   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Bash|Edit|Write|mcp__.*",
           "hooks": [
             {
               "type": "command",
               "command": "python \"<ABS_PATH_TO_HUB_RELAY>/hub_relay.py\" --agent cc --gate",
               "timeout": 120
             }
           ]
         }
       ],
       "PermissionRequest": [
         {
           "matcher": "",
           "hooks": [
             {
               "type": "command",
               "command": "python \"<ABS_PATH_TO_HUB_RELAY>/hub_relay.py\" --agent cc",
               "timeout": 120
             }
           ]
         }
       ]
     }
   }
   ```

4. **新建 `D:/agentdeck-test/.codex/hooks.json`**（注意在 `PreToolUse` 的 `matcher` 中补上 Codex 文件补丁工具名 `apply_patch`）：
   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Bash|apply_patch|Edit|Write|mcp__.*",
           "hooks": [
             {
               "type": "command",
               "command": "python \"<ABS_PATH_TO_HUB_RELAY>/hub_relay.py\" --agent codex --gate",
               "timeout": 120
             }
           ]
         }
       ],
       "PermissionRequest": [
         {
           "matcher": ".*",
           "hooks": [
             {
               "type": "command",
               "command": "python \"<ABS_PATH_TO_HUB_RELAY>/hub_relay.py\" --agent codex",
               "timeout": 120
             }
           ]
         }
       ]
     }
   }
   ```

5. **首次进入测试目录激活信任**
   * **Claude Code**：进入 `D:/agentdeck-test` 启动 `claude` -> 在弹出的 Workspace Trust 对话框选择信任该文件夹 -> 输入 `/hooks` 核对两个钩子均已加载。
   * **Codex CLI**：进入 `D:/agentdeck-test` 启动 `codex` -> 确认信任该目录 -> 输入 `/hooks` 打开管理面板，逐一审阅并批准（Trust）这两个项目钩子，使 `trusted_hash` 落盘。

6. **回滚步骤**
   * 删除 `D:/agentdeck-test/.claude/settings.local.json` 与 `D:/agentdeck-test/.codex/hooks.json`；
   * （可选清理台账）编辑 `~/.codex/config.toml`，删掉指向 `D:/agentdeck-test` 的 `[projects."..."]` 与 `[hooks.state."..."]` 表项；
   * 退出并重开曾在该目录运行的 `claude` / `codex` 会话。

#### 3.2 安装脚本新增 `--project <DIR>` 参数的写入方案（设计方案）
1. **CLI 参数设计**：
   * `install.py`（默认无 `--project`）：维持全局安装（写 `~/.claude/settings.json` 和 `~/.codex/hooks.json`）。
   * `install.py --project <DIR>`：仅针对 `<DIR>` 写入项目级配置，**绝不触碰全局钩子写入**；建议增加可选标志 `--purge-global`（或检测到全局已有 `hub_relay.py` 时告警提示用户清理，否则全局仍会污染所有会话）。
   * `install.py --uninstall [--project <DIR>]`：按相同作用域精准卸载。
2. **路径规范化与根目录检查**：
   * 用 `Path(project_dir).resolve()` 转为绝对路径；将 `sys.executable`（Python 路径）与 `hub_relay.py` 路径均转为**绝对路径**拼入 `command`，防止在 `<DIR>` 下运行时找不到脚本。
   * 检测 `<DIR>/.git` 是否存在：若不存在，打印提示告知用户需 `git init`（或在 `~/.codex/config.toml` 配置 `project_root_markers`），否则 Codex CLI 可能忽略 `.codex/hooks.json`。
3. **目标文件选择与非破坏式 JSON 幂等合并**：
   * Claude Code 目标：`<DIR>/.claude/settings.local.json`（优先用 `settings.local.json` 避免污染目标项目 Git 工作区；可提供 `--shared` 参数切换为 `.claude/settings.json`）。
   * Codex CLI 目标：`<DIR>/.codex/hooks.json`。
   * 合并算法：读取已有 JSON（文件不存在则建 `{}`；JSON 语法损坏则中止报错并保留原文件，绝不静默覆盖）-> 确保顶层 `"hooks"` 字典存在 -> 在 `"PreToolUse"` 与 `"PermissionRequest"` 列表中过滤掉 `command` 包含 `"hub_relay.py"` 的旧条目（实现重复运行幂等更新，同时完整保留用户已有的其他钩子）-> 追加新的 AgentDeck 钩子对象 -> 写入同目录临时文件 `*.tmp` 后 `os.replace` 原子替换。
4. **安装完成后的交互引导输出**：
   * 输出目标写入文件路径与回滚命令（`install.py --uninstall --project <DIR>`）；
   * 明确提示用户：① 重启 `<DIR>` 中已打开的会话；② 在 `<DIR>` 启动 `claude` 接受目录信任；③ 在 `<DIR>` 启动 `codex` 后**必须执行一次 `/hooks` 批准钩子哈希**（任何参数变动都会使旧 `trusted_hash` 失效）。

---

### 4. 验证清单（触发方式与预期现象）

* **结论**：5 类场景由 `PreToolUse`（前置闸门）与 `PermissionRequest`（权限弹窗拦截）两阶段串联完成；钩子协议行为由 Claude Code / Codex 官方规范决定，而高危/极危的具体命令词表由 `hub_relay.py` 内部规则决定（官方无内置高危/极危分级词表——该分级词表部分**未查到官方说明**）。
  * 官方文档依据：[Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks) ｜ [OpenAI Codex Hooks](https://developers.openai.com/codex/hooks)

| 验证项 | 怎么触发（在 `D:/agentdeck-test` 默认 `default` 权限模式下） | 预期现象与底层钩子流转 |
| :--- | :--- | :--- |
| **1. 批准（单次按键）** | 让 Agent 执行一个未加免审白名单的普通写文件或简单命令（如：「新建 `ok.txt` 写入 `123`」或「执行 `echo hello`」）；同时在 `D:/agentdeck-test` **以外**的目录（及 Claude Desktop 其他目录会话）做同样操作做隔离对照。 | 1. 测试目录内：`PreToolUse --gate` 判定非高危直接 `exit 0` 放过 -> 触发 `PermissionRequest` -> 硬件提示待批，按 **1 次【批准】** -> 钩子返回 `decision.behavior: "allow"` -> 工具立即执行成功。<br>2. 其他目录/桌面版其他会话：硬件无任何反应，走原生界面弹窗。 |
| **2. 拒绝（单次按键）** | 让 Agent 执行普通需授权操作（如：「新建 `deny.txt`」），硬件提示审批时按 **1 次【拒绝】**。 | `PreToolUse --gate` 放过 -> `PermissionRequest` 收到物理拒绝 -> 以 `exit 0` 输出 `{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"deny","message":"..."}}}`（注意不能只靠 `exit 2`）-> 工具**不执行**，`deny.txt` 不存在，Agent 收到拒绝反馈。 |
| **3. 高危命令要按两次** | 让 Agent 对测试子目录执行命中 `hub_relay.py` 高危规则但非极危的操作（如：「删除子目录 `rm -rf ./test_sub`」或 `git reset --hard`，按你们的高危正则在沙盒目录内构造）。 | **第 1 次按键（`PreToolUse --gate`）**：硬件报高危闸门告警；按第 1 次【批准】后，`--gate` 返回 `"permissionDecision": "ask"`（或无阻塞空输出 `exit 0`；**不能返回 `"allow"`**，否则官方机制会跳过后续权限请求！）。<br>**第 2 次按键（`PermissionRequest`）**：紧接着进入常规权限拦截，硬件再次提示确认，按第 2 次【批准】返回 `decision.behavior: "allow"` 后，命令才真正执行。（若第 1 关按【拒绝】，`PreToolUse` 直接 `deny`/`exit 2` 阻断，不会弹第 2 次。） |
| **4. 极危命令锁死** | 让 Agent 尝试调用命中 `hub_relay.py` 极危黑名单的命令模式（如模拟系统级破坏命令串，按你们的极危正则构造）。 | 在 `PreToolUse --gate` 阶段即被判定为极危，硬件显示锁死/禁止（按物理【批准】键无效或不可批），脚本直接输出 `permissionDecision: "deny"`（或 `exit 2` + `stderr` 原因）-> 工具被**硬阻断**，根本不会进入 `PermissionRequest` 阶段，Agent 收到锁死拦截原因。 |
| **5. Hub 没开时的降级** | 先关闭/停止本机 AgentDeck Hub 进程，再在 `D:/agentdeck-test` 让 Agent 执行一次需授权命令和一次高危命令。 | `hub_relay.py` 连接 Hub 失败后快速退出（未配 `onFailure: "block"` 时，以 `exit 0` 空输出或非 `2` 错误码如 `exit 1` 退出，避免卡满 120s 超时）-> Claude Code 与 Codex CLI 均将其视为非阻塞直通：**既不卡死会话，也绝不自动静默批准**，而是平滑回退弹出终端/桌面原生的键盘权限确认框。 |

---

### 总结
1. Claude Code（含桌面版 Code 标签页）与 Codex CLI（0.144+）均支持项目级钩子（`.claude/settings.local.json`、`<repo>/.codex/hooks.json`），但都会与全局钩子**叠加合并**。
2. 要实现仅在 `D:/agentdeck-test` 验证，必须先移除 `~/.claude/settings.json` 和 `~/.codex/hooks.json` 中的全局钩子，且为测试目录执行 `git init` 以满足 Codex 根目录发现。
3. 首次进入测试目录需分别通过 Claude Code 的目录信任弹窗，以及 Codex CLI 的目录信任与 `/hooks` 哈希审批（任何配置改动都需重跑 `/hooks`）。
4. `PermissionRequest` 必须用 `exit 0` + JSON `decision.behavior`（`"allow"`/`"deny"`）返回（Claude Code 对该事件忽略 `exit 2`）；超时或 Hub 关闭非阻塞退出时会自动降级回原生权限弹窗。
5. 安装脚本新增 `--project` 时应使用绝对路径、幂等合并写入 `.claude/settings.local.json` 与 `.codex/hooks.json`，切勿触碰全局配置文件。
