# 浮窗位置修复计划

1. 新增离线回归测试，以工作区包含窗口的数值约束验证负坐标、副屏恢复、任务栏、拓扑变化和展开；先运行并记录失败。
2. 使用 Windows EnumDisplayMonitors/GetMonitorInfoW 的工作区，创建 Tk 前设置线程 DPI 上下文；通过 SetWindowPos 定位负坐标，避免 Tk geometry 的负偏移语义。
3. 统一启动、拖动结束、展开收回与显示拓扑变化后的位置约束；保留偏好格式、透明度及审批逻辑。
4. 跑新增测试及现有浮窗测试；真实多屏混合 DPI 体验仅能由用户设备验收。本任务不创建可见窗口、不连接设备。

官方 API 依据：[EnumDisplayMonitors](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaymonitors)、[GetMonitorInfoW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getmonitorinfow)、[SetThreadDpiAwarenessContext](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setthreaddpiawarenesscontext)。
