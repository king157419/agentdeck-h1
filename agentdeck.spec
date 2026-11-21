# -*- mode: python ; coding: utf-8 -*-
"""Two entry points, one onedir bundle and one shared _internal directory."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH)
pc = root / "pc"
icon = str(pc / "agentdeck.ico")
data = [(str(pc / name), ".") for name in
        ("hub_keys.json", "hub_prompts.json", "agentdeck.ico", "claude_uia.ps1")]
data.append((str(root / "agentdeck" / "装驱动.md"), "."))  # tray: 装驱动说明
data += [(str(path), "ui") for path in sorted((pc / "ui").glob("*")) if path.is_file()]  # management panel
data += collect_data_files("libusb_package")
binaries = collect_dynamic_libs("libusb_package")
excludes = ["PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "IPython",
            "pystray._appindicator", "pystray._darwin", "pystray._gtk", "pystray._xorg"]

app = Analysis(
    [str(pc / "agentdeck_app.py")],
    pathex=[str(pc)],
    binaries=binaries,
    datas=data,
    hiddenimports=["pystray._win32", "PIL.ImageTk", "tkinter", "tkinter.filedialog",
                   "tkinter.messagebox", "usb.backend.libusb1", "libusb_package",
                   "deck_input", "hub_keyboard", "claude_uia", "claude_sessions", "hub_window_switch", "session_titles",
                   "panel", "panel_launch"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=excludes,
    noarchive=False, optimize=0,
)
relay = Analysis(
    [str(pc / "hub_relay.py")],
    pathex=[str(pc)], binaries=[], datas=[], hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=excludes,
    noarchive=False, optimize=0,
)

app_exe = EXE(
    PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="AgentDeck",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, icon=icon,
)
relay_exe = EXE(
    PYZ(relay.pure), relay.scripts, [], exclude_binaries=True, name="AgentDeck-relay",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, icon=icon,
)
bundle = COLLECT(
    app_exe, relay_exe, app.binaries, app.datas, relay.binaries, relay.datas,
    strip=False, upx=False, name="AgentDeck",
)
