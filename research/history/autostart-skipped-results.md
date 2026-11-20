# AgentDeck 登录自启动未执行：只读调研结果

调研日期：2026-11-19。本机取证时间为当日 22 时段，时区 `Eastern Standard Time`（UTC−05:00）；下文登录事件均为本地时间。任务依据：[调研简报](brief-autostart-skipped.md)。

## 结论

**未能从现存只读证据确定具体根因。最合理的排查方向是 Shell 对该 Run 项的枚举、解析或执行前筛选，而非 AgentDeck 启动后的业务逻辑；这仍是低置信度的工作假设，不能写成“已证实 Windows 26300 的某项新规则/回归”。**

证据链是：Run 项在重启前已写入、exe 在登录前已存在；同次登录其它 HKCU Run 项有完整的执行记录，AgentDeck 没有；AgentDeck 当前文件没有下载区域标识，不要求提权，也未发现对应的兼容性强制提权或显式启动禁用记录。简报中的“同命令手动运行后健康检查正常”进一步削弱了程序本身无法启动的解释，本次没有再次启动应用验证。

没有找到微软官方资料支持以下普遍规则：**24H2 以后普通 HKCU Run 新项必须先到设置确认、未签名 exe 一律不运行、新项首次登录一律跳过、缺 StartupApproved 项就不运行，或无空格路径一律必须加引号。** “没有找到”不等于证明不存在未公开实现。下文给出各项的来源和本机反例。

建议后续实现优先采用**明确限定当前用户的 Task Scheduler 登录任务，使用现有交互令牌和最低权限**。其后是用户启动文件夹 `.lnk`，最后是仅规范引用的 HKCU Run。这个排序针对本次 Shell Run 异常的规避能力和可诊断性，不是实测成功率。**本次没有创建任何任务或快捷方式，也没有验证替代方案在下次登录时成功。**

## 1. 本机证据

### 1.1 系统、注册时间与命令内容

| 项目 | 实际读取结果 | 意义 |
|---|---|---|
| 操作系统 | CIM：Windows 11 专业版，`10.0.26300`；注册表 `DisplayVersion=26H2`、`UBR=9974` | 本机完整构建号为 `26300.9974` |
| 构建信息 | `BuildLabEx=26100.1.amd64fre.ge_release.240331-1435` | 基础构建字符串不能单独代替当前构建号 |
| Insider 信息 | `WindowsSelfHost\Applicability` 存在，但本次读取的 `BranchName/ContentType/Ring` 无值 | 不能据此确定当前 Insider 通道 |
| 当前令牌 | `WindowsPrincipal.IsInRole(Administrator)=False` | 取证进程未提权 |
| 最近开机 | `2026-11-19T07:07:47.5000000-05:00` | 与简报一致 |
| HKCU Run 键最后写入 | `2026-11-19T03:06:06.433201-05:00`，UTC 为 `08:06:06.433201Z` | 早于本次开机；这是整个键的时间，不是单个值的创建时间 |
| AgentDeck 值 | `REG_SZ`，`D:\desk\hardware\h1\dist\AgentDeck\AgentDeck.exe --background` | 61 字符、纯 ASCII、无嵌入 NUL；exe 路径无空格 |
| 注册表视图 | 64 位 Python 读取；另查 HKCU WOW6432Node Run，没有另一份 AgentDeck 注册 | 没有发现因只写另一视图造成的冲突 |

简报把 26300 直接称为“Insider/Canary 级别”需要修正：微软 [Flight Hub](https://learn.microsoft.com/en-us/windows-insider/flight-hub/) 将 26300 列入 Windows 11 26H2 系列。单凭主构建号不能认定 Canary，更不能由此推导启动新规则。

### 1.2 AgentDeck 与已正常启动的 Typeless

| 比较项 | AgentDeck | Typeless |
|---|---|---|
| 注册位置 | HKCU `...\CurrentVersion\Run` | 同一个键 |
| 值名 | `AgentDeck` | `Typeless.exe` |
| 命令 | `D:\desk\hardware\h1\dist\AgentDeck\AgentDeck.exe --background` | `"C:\Users\king\AppData\Local\Programs\Typeless\Typeless.exe" --system-startup-silent-launch` |
| HKCU StartupApproved\Run | 无对应值 | 无对应值 |
| 其它检查到的 StartupApproved 位置 | HKLM Run/Run32/StartupFolder、HKCU StartupFolder 中也无 AgentDeck | 未发现对应禁用值 |
| 文件创建时间 | `2026-11-19 05:58:09.4306009` | `2026-09-16 04:35:40.8177003`（当时 UTC−04:00） |
| 文件最后写入 | `2026-11-19 05:58:09.4348320` | `2026-10-30 09:17:56`（当时 UTC−04:00） |
| 文件大小 | 5,821,049 字节 | 239,515,728 字节 |
| Authenticode | `NotSigned` | `Valid`，Simply LLC |
| 文件属性 | `Archive` | `Archive` |
| NTFS 数据流 | 仅 `:$DATA`，无 `Zone.Identifier` | 同左 |
| exe 内嵌 manifest | `asInvoker`，`uiAccess=false` | 同左 |
| AppCompatFlags\Layers | HKCU/HKLM 未发现匹配该路径的记录 | 未发现匹配记录 |
| 本次登录的 9707/9708 | 无 | 有，见下表 |

实际差异包括：签名、安装位置、文件新旧、命令引用形式、值名是否带 `.exe`，以及 PyInstaller 与 Electron 的打包方式。**这些差异目前没有任何一个具备足够证据可单独解释选择性跳过。** `OneDrive`、`LGHUB` 等值名也不带 `.exe`，因此值名后缀不是普遍门槛。

另外，正常启动的 `EDeviceMonitor` 命令是 `C:\Users\king\AppData\Local\ScreenShare\1.1.2.1218\EDeviceMonitor.exe 1`，同样无引号、带参数，是“无空格路径未引用就一律被跳过”的本机反例。`Steam`、`WallpaperEngine` 和 `vmware-tray.exe` 均从 D 盘正常启动；C、D 当前都是健康的 Fixed/NTFS 卷。因此不能把原因简单归结为“程序位于 D 盘”。这仍不能证明 AgentDeck 所在目录在登录枚举的那一瞬间一定可读。

### 1.3 Shell 日志：能定位范围，不能提供完整排除原因

日志：`Microsoft-Windows-Shell-Core/Operational`。本机 provider 元数据说明：9705/9706 是开始/完成注册表键的命令枚举；9707 是开始执行命令；9708 带命令和 PID。9708 **不表示 AgentDeck 业务健康或应用已正常退出**。

| 本地时间 | Event ID | Record ID | 内容摘要 |
|---|---|---|---|
| 07:08:25.319 | 9705 | 101845 | 开始枚举 `Software\Microsoft\Windows\CurrentVersion\Run` |
| 07:08:25.319 | 9707 | 101846 | OneDrive 开始执行 |
| 07:08:28.467 | 9707 | 101848 | Steam 开始执行 |
| 07:08:32.408 | 9707 | 101850 | WallpaperEngine 开始执行 |
| 07:08:34.574 | 9707 | 101852 | Typeless 开始执行 |
| 07:08:46.671 | 9708 | 101855 | Typeless，PID 19868 |
| 07:08:46.680 | 9707 | 101856 | EDeviceMonitor 开始执行 |
| 07:08:50.707 | 9707 | 101858 | LGHUB 开始执行 |
| 07:08:53.037 | 9707 | 101860 | RazerAppEngine 开始执行 |
| 07:09:02.743 | 9706 | 101862 | 完成这一轮 Run 枚举 |

这些事件的 XML 中 `KeyName` 没有标出 HKCU/HKLM；将这一块对应到 HKCU，是结合连续命令与 HKCU Run 内容进行的归属判断。exe 命令字段会出现仅文件名及尾部引号的形式，不能把日志展示的截短命令当成原始注册表路径损坏。

扩大到当日 06:55 至取证时，对 9707–9712 共读取到 20 条事件，搜索 XML 中 `AgentDeck` 或 `hardware\h1` 均为 0；早晨完整的枚举起止记录仍保留。单纯“稍后才运行”的解释因而缺乏正向证据。

**应修正简报的证据强度：没有 9707，能够说明该日志没有记到 AgentDeck 的这一类执行事件；不能单凭这一点证明 Windows 从未尝试任何启动，也不能反推出具体跳过条件。** 未找到微软公开的“9707 前所有分支”或“任何尝试都必记 9707”的契约。要知道当时到底有没有读该值、解析出哪个路径、在哪个检查失败，需要登录时的进一步跟踪；现存日志没有这些信息。

### 1.4 禁用状态、策略与安全控制

- HKCU `Explorer\StartupApproved` 仅有 `Run` 和 `StartupFolder` 子键。AgentDeck、Typeless、LGHUB、RazerAppEngine 均没有相应 Run 值，但后三者本次确实执行。HKLM 对应 Run/Run32/StartupFolder 及存在性检查到的 WOW6432Node StartupApproved 中也未发现 AgentDeck 禁用记录。**这能排除“这些已检查位置存在显式禁用值”的说法；不等于掌握 Windows 的全部内部状态。**
- 已有明确区别的状态保留原始字节，例如 OneDrive 为 `02-00-00-00-00-00-00-00-00-00-00-00`，Docker Desktop 为 `03-00-00-00-00-00-00-00-00-00-00-00`，Ollama.lnk 以 `03` 开头。本报告不把未公开的二进制格式作为写入接口，也不建议补造“批准”字节。
- HKCU `...\Policies\Explorer` 不存在；HKLM 同位置只有 ActiveDesktop 相关值，未发现 `DisableCurrentUserRun` 等所查 Run 禁用值；所查用户/机器 Windows System/Explorer 策略位置没有相关启动拦截证据。微软确有整类 Run 控制策略，但这也解释不了同一轮其它 HKCU Run 项正常执行。[ADMX_Logon 策略映射](https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-admx-logon)
- HKCU `Explorer` 下未发现 `StartupNotifications`、`StartupApp`、`Serialize` 这些候选键。`Notifications\Settings\Windows.SystemToast.StartupApp` 的 `Enabled=0` 仅是此通知的设置证据，不能解释为“启动项未获批准”。
- `HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState=0`，与简报中的 SAC 关闭一致。Smart App Control 是独立的执行安全机制；它启用时确实可能根据信誉及签名拦截程序，不能据此发明 HKCU Run 一律禁止未签名程序的规则。[微软 SAC FAQ](https://support.microsoft.com/en-gb/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions)

对本次登录附近 06:55–07:30 的安全日志读取结果：

| 日志 | 启用状态 | 时间窗内事件总数 | AgentDeck / hardware\h1 命中 |
|---|---|---|---|
| CodeIntegrity/Operational | 开 | 11 | 0 |
| Windows Defender/Operational | 开 | 11 | 0 |
| AppLocker/EXE and DLL | 开 | 0 | 0 |
| SmartScreen/Debug | **关** | 0 | 0 |

尤其不能用**关闭的 SmartScreen 日志没有记录**来排除 SmartScreen。上述结果只说明所查已保留日志没有关联证据。本次也读取了 `C:\Users\king\.agentdeck\logs\app.log`，未找到当日 07/08 时段的行，但程序没有保证每次正常进入都写启动标记，因此这个负面结果同样不能证明进程从未存在。

## 2. 官方规则与待验证假设

| 假设或条件 | 文献结论 | 对本机的判断 |
|---|---|---|
| 新 Run 项必须先到设置确认 | 未找到适用于普通 HKCU Run 的官方新要求；现行支持文档仍列出 HKCU Run 和用户 Startup 入口 | 不应把“去设置点一次”写成确定修复 |
| 新增启动项通知需要用户批准 | 微软 2020 年就加入新增启动项通知；公告描述的是提醒，不是新增批准门槛 | 本机关闭通知不证明禁止自启；[Build 20221 公告](https://blogs.windows.com/windows-insider/2020/09/23/announcing-windows-10-insider-preview-build-20221/) |
| 必须先手动运行一次 | 官方确有这个要求，但对象为 UWP / Windows app package 的 `StartupTask` | 当前 PyInstaller onedir + Run 不适用；[StartupTask Remarks](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.startuptask?view=winrt-26100) |
| 缺 StartupApproved 默认不允许 | 未找到微软公开、可依赖的缺省状态契约 | Typeless、LGHUB、Razer 是直接反例，不能以缺项解释 AgentDeck |
| 未签名 exe 不允许放 Run | Run 文档未给出这种普遍要求；SAC 等安全策略是另一层 | 确实存在签名差异，但当前 SAC 关闭，无关联拦截记录，证据不足 |
| 路径未引用导致跳过 | Windows 命令行规则允许无空格的首个路径 token；引号用于消除路径空格歧义 | 当前 61 字符命令没有此歧义，EDeviceMonitor 也未引用且成功；[CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw) 仅支持解析层说明，不证明 Explorer 的内部调用路径 |
| 请求管理员权限，登录时被抑制 | 微软有明确的历史设计依据，Run 和 Startup 目录都可能受影响 | 两个 exe 都是 `asInvoker/uiAccess=false`，所查 Layers 无匹配，当前证据不支持；[微软登录应用设计文档](https://learn.microsoft.com/en-us/previous-versions/bb325654%28v%3Dmsdn.10%29)（Vista 文档，不能据此承诺 26300 的事件编号） |
| Safe Mode、Run 策略、错误注册表视图 | 属于需要核查的常规范围 | 同轮大量对应 Run 项成功、视图已比较，缺乏支持本案的证据 |
| 顺序、延迟、枚举期间改键 | 微软不保证顺序/及时性，并警告运行期间改 Run 键会干扰其它项 | Run 键本次读到的最后写入仍在 03:06，没有本次登录期间改键的证据；普通延迟也未被后续日志证实 |
| 登录瞬间路径/依赖暂不可用，或 Shell 针对此项的状态/解析异常 | 现存日志无法恢复逐项检查结果 | 仍值得检查的方向；文件时间不证明登录瞬间所有依赖可读，不能据此断言是 bug |

Run 的长度、Safe Mode、顺序、延迟和改键限制依据同一份 [Run and RunOnce 官方文档](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys)。这些文档描述正常语义，**没有公开 9707 前的完整筛选实现**。

已检索 Windows 11 24H2 以后及 26xxx 官方发布资料，没有发现与“26300.9974 下仅此合法 HKCU Run 项无执行记录”精确对应、可确认适用的微软已知问题。其它启动性能/Explorer 修复不能拿来代替本机根因证据。

## 3. 方案排序及本机权限

这里的“开机自启”实际应为**当前用户登录后启动**。AgentDeck 有托盘、覆盖窗口及输入交互，不适合改成登录前的 SYSTEM 服务或非交互任务。

| 排序 | 方案 | 本机是否需要管理员 | 是否可能遇到同类阻止 | 建议 |
|---|---|---|---|---|
| 1 | Task Scheduler：仅当前用户的 LogonTrigger，InteractiveToken，LeastPrivilege | 官方允许低权限进程创建自己的这类任务；本机服务和目录 ACL 有正向证据。**未实际注册验证** | 不走 Explorer Run/StartupFolder 的逐项枚举，是规避本次疑点的结构性优势（推断）。仍受任务权限、文件可用性和执行安全策略影响 | 首选后续实现方案；可回读定义、运行时间和结果 |
| 2 | 用户 `shell:startup` 的 `AgentDeck.lnk` | 用户目录存在，ACL 给当前用户 FullControl；通常不需管理员 | 仍受 Shell 登录启动机制影响，且本机已有 `StartupApproved\StartupFolder\Ollama.lnk` 状态记录；不能当成完全绕开启动管理 | 最简单的常规后备方案，可独立设置 exe、参数、工作目录 |
| 3 | HKCU Run 对 exe 明确加引号 | 不需管理员；当前实现已能写自己的 HKCU Run | 仍走本次发生疑点的同一路径；没有证据说明加引号就能修复 | 可作为后续最小对照实验，不能单独承诺可靠性提升 |
| 不作为当前方案 | 打包为 MSIX 后使用 StartupTask | 取决于部署与信任策略；本机未验证 | 有自己的启用/用户禁用/策略状态，仍有首次运行或设置启用要求 | 需要改变分发方式，不是本次小范围修复 |
| 不推荐 | RunOnce、HKLM、公共 Startup、SYSTEM/BootTrigger、服务 | 权限和触发语义不同，其中多项需管理员 | RunOnce 只执行一次；服务/非交互桌面不适合现有界面 | 不为当前需求引入这些路径 |

微软的 [启动应用配置说明](https://support.microsoft.com/en-us/windows/experience/startup-boot/configure-startup-applications-in-windows)支持用户 `shell:startup` 和 HKCU Run。此处排名没有声称 `.lnk` 在所有机器上都比 Run 更可靠。

### 3.1 为什么“普通用户也可以创建登录任务”有条件成立

必须同时明确以下四个字段：

| 字段 | 建议值 | 作用 |
|---|---|---|
| `Principal.UserId` | 当前用户 SID | 以谁的身份运行 |
| `Principal.LogonType` | `TASK_LOGON_INTERACTIVE_TOKEN=3` | 使用已登录的交互会话，无需保存密码 |
| `Principal.RunLevel` | `TASK_RUNLEVEL_LUA=0` / XML `LeastPrivilege` | 不请求管理员权限 |
| `LogonTrigger.UserId` | **同一个当前用户 SID** | 只有谁登录才触发；不能省略 |

微软允许低权限进程注册 LUA 任务；非管理员为自己注册 interactive 任务无需提供密码，仍受目标任务目录的权限限制。[Security Contexts for Tasks](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks)

决定性的限制在微软协议：非管理员注册 BootTrigger、针对所有用户/其它用户的 LogonTrigger 或相应会话触发器时，应返回 `E_ACCESSDENIED`。LogonTrigger 省略 UserId 表示任意用户登录。因此**仅设 Principal 或 `/RU` 不够**。[MS-TSCH：SchRpcRegisterTask](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-tsch/849c131a-64e4-46ef-b015-9d4c599c5167)

不建议直接承诺 `schtasks /Create /SC ONLOGON /RU ... /RL LIMITED /IT` 在普通用户下成功：`/RU` 定义为运行身份，不能代替明确的触发用户。应使用 COM/XML 显式设置 `LogonTrigger.UserId`；GUI 也要选具体当前用户。不能把一次未限定触发用户的命令“访问被拒绝”推广成“所有登录任务都要求管理员”。[schtasks create 参数文档](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create)

S4U/“不管用户是否登录都运行”使用非交互执行环境，不适合作为此 UI 应用的替代品；InteractiveToken 才符合需求。[TASK_LOGON_TYPE](https://learn.microsoft.com/en-us/windows/win32/api/taskschd/ne-taskschd-task_logon_type)

### 3.2 本机已有的只读支持证据

- `Schedule` 服务为 Running / Automatic；当前未提权进程可通过 `Schedule.Service.Connect()` 连接。
- 根任务目录 `GetSecurityDescriptor(7)` 含 `(A;CI;FW;;;AU)`，即 Authenticated Users 的写权限 ACE，是正向证据；没有执行完整创建访问检查，不能代替实际注册结果。
- 现有 `OneDrive Startup Task-<当前用户SID>`：所有者为当前用户；Principal 为 `king`，LogonType=3，RunLevel=0；LogonTrigger.UserId 为 `DESKTOP-MFQKJ1U\king`，Delay=`PT10M`；LastRunTime=`2026-11-19 07:18:09`，LastTaskResult=0。
- 现有 `WpsExternal_king_startup` 也为当前用户的 InteractiveToken、RunLevel=0、限定登录用户的任务，本次登录后有 LastRunTime。

这些证据表明本机并非不支持这种任务形态，**不证明这些已有任务最初一定由非管理员创建，也不证明 AgentDeck 新任务已能创建或会健康运行**。本次未调用 RegisterTask、CreateFolder、Run、Enable 或任何删除/更新任务的方法。

## 4. 后续代码修改建议（本次未实施）

范围以 `pc/agentdeck_app.py` 的 `AutoStart` 为主，不需要改固件或增加依赖。

| 当前代码位置 | 当前行为 | 建议 |
|---|---|---|
| `launch_command()`，238–244 行 | 使用 `subprocess.list2cmdline`；路径无空格时不加引号是其正常行为 | 保留正确的 argv 构造。若保留 Run 后端，可规范化为 `"完整exe路径" --background`，但不要把这称为已验证修复；任务/.lnk 将目标、参数分字段设置 |
| `AutoStart.__init__/_value()/enabled()`，247–266 行 | 只比较 Run 值是否等于当前/legacy 命令 | 采用任务后端时，回读限定用户的触发器、运行身份、权限、Enabled、exe 和参数；“已注册/已启用”与“本次登录已运行”分开表达 |
| `AutoStart.upgrade()`，268–273 行 | 把旧的无 background 命令升级为 background | 后端迁移须幂等；新定义成功写入并回读确认后才清理本程序旧入口；尊重用户显式禁用状态，不能自动改用别的入口绕过用户选择 |
| `AutoStart.set_enabled()`，275–284 行 | 写入/删除自己的 HKCU Run 值 | 首选创建/更新只属于当前用户的命名任务；关闭时只处理本程序拥有的入口。无权限应返回具体错误，不能请求最高权限或暗中回退为多重自启 |
| `init_all()`，352–363 行；`status_model()`，919–949 行 | 注册匹配就显示“已开启”并参与完成状态 | 显示准确配置状态；增加可诊断的上次登录运行信息，不能把配置存在当成健康证明 |
| `main()`，1208–1225 行 | 单实例成功后才配置日志并进入 hub | 后续可增加尽早的启动来源/时间/PID/是否 background 日志，便于区分未触发、重复实例退出与运行失败；本次没有改动 |
| `pc/test_agentdeck_app.py`，376–420 行等 | FakeRegistry 覆盖现有注册、升级及命令构造 | 后续后端变更补充替身测试：触发用户必须设置、拒绝访问、注册后回读、禁用状态、迁移失败保留旧入口、避免重复注册；不对真实注册表或任务写测试数据 |

任务动作建议为：

```text
Path:             D:\desk\hardware\h1\dist\AgentDeck\AgentDeck.exe
Arguments:        --background
WorkingDirectory: D:\desk\hardware\h1\dist\AgentDeck
Trigger:          当前用户登录，可设 PT30S 短延迟
Principal:        当前用户 SID / InteractiveToken / LeastPrivilege
```

上面是配置建议，**未执行**。不要把完整的带参数命令填进 `Exec.Path`；源码模式需相应使用 pythonw 和脚本参数。长驻任务还应明确：`DisallowStartIfOnBatteries=False`、`StopIfGoingOnBatteries=False`、`RunOnlyIfIdle=False`、`RunOnlyIfNetworkAvailable=False`、`ExecutionTimeLimit=PT0S`、`MultipleInstancesPolicy=IgnoreNew`，保留已有应用单实例保护。否则默认的供电条件和 72 小时执行上限可能造成新的间歇问题。[供电启动条件](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-disallowstartifonbatteries)、[切换电池时停止](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-stopifgoingonbatteries)、[执行时间上限](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-executiontimelimit)

若任务方案因本机策略拒绝，用户 Startup `.lnk` 是下一候选；仍需按下一次登录的真实证据判断。不要自行写 `StartupApproved` 的私有字节，更不要给多个入口同时兜底；重复后台启动可能触发现有单实例的 SHOW 行为。

## 5. 还缺什么才能确定根因

现有只读证据能缩小范围，无法补回登录时的逐项检查过程。后续若要确认原因，应在另一次获准的实际验证中，先保留当前状态，再单变量比较引用形式或替代入口，并收集该次登录的 Shell/进程创建证据。需要看到是否读取 AgentDeck 值、解析目标及文件打开结果，才能区分 Shell 筛选、路径瞬时不可用或其它状态问题。该步骤可能涉及重登、持久化诊断或设置变更，**不属于本次已执行内容**。

“加引号一定好”“先点设置一次就好”“签名就好”“26300 已知 bug”目前都超出了证据。推荐任务后端是工程上的规避选择，不等于已确认原故障机制。

## 6. 本次变更与验证

仅新增本报告 `research/autostart-skipped-results.md`。没有修改源代码、Run/StartupApproved 或其它注册表值，没有创建/更新任务或启动快捷方式，没有启动 AgentDeck、重登或重启，也没有访问 COM4、上传固件或触碰 `wokwi/`、`backup/`、`_rollback/`。不存在代码简化变更。

使用指定解释器 `D:\conda\miniconda3\python.exe`，加 `-B -X utf8` 避免写入字节码缓存并固定终端编码。三项要求的离线测试退出码均为 0，真实输出如下：

```text
> python -B -X utf8 pc/test_ui.py
test_layout_states: PASS
test_marquee: PASS
test_focus: PASS
test_compatibility: PASS
test_priority_rotation: PASS
test_bad_commands_glyphs: PASS
test_dance: PASS
UI: 7 groups passed

> python -B -X utf8 pc/test_daemon.py
test_mapping: PASS
test_focus: PASS
test_hold_rechecked_before_focus_send: PASS
test_focus_mutex_serializes_delayed_daemon_send_and_manual_hold: PASS
test_focus_mutex_rechecks_hold_after_waiting_for_manual_owner: PASS
test_focus_mutex_timeout_skips_send_and_retries_next_tick: PASS
test_state_machine: PASS
test_log_tick: PASS
test_main_schedule_and_lock: PASS
test_process_snapshot: PASS
daemon offline tests: 10 groups passed

> python -B -X utf8 pc/test_pc.py
test_names_hooks: PASS
test_ensure_daemon: PASS
test_demo: PASS
test_firmware_loop: PASS
PC and firmware loop: 4 groups passed
```

显示内容未改，不运行会生成图片的 `pc/sim.py`。离线测试不证明 Windows 登录启动成功。

全仓 `git diff --check` 退出码为 1，报告了已有源码差异中的 trailing whitespace，例如 `pc/agentdeck_app.py:43` 和 `pc/test_agentdeck_app.py:1236`。没有为清理这些问题而越界修改代码。本报告的 UTF-8 解码、末尾换行、逐行尾随空白与代码围栏配对检查通过。

报告写入前后，既有 tracked diff 的 SHA-256 均为 `249fa38080f82c4a5fc203243c4f8d65d7639dc775ab68d3da0f131b6f3d80e2`；所查 HKCU/HKLM Run 与 StartupApproved Run/Run32/StartupFolder（含不存在的键、值及最后写入时间）序列化快照的 SHA-256 均为 `4569fcda654b472b238202ee32ed5baa05f194940205fe81a99c1c80437dab1c`。`git status` 相比基线只多出本报告；工作区原有改动保留。
