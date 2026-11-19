"""One visual language for every AgentDeck window.

Flat dark surfaces, one hairline border colour, one primary action per window.
Tk has no rounded corners, so hierarchy comes from surface steps and spacing.
Importing this module never creates a window; tkinter is imported lazily.
"""
import sys

# Surfaces, darkest to lightest.
BG = "#13151a"
SURFACE = "#1b1e25"
RAISED = "#262a34"
BORDER = "#2b303a"

# Text.
TEXT = "#e9ebef"
MUTED = "#9aa1ad"
FAINT = "#636a77"

# State colours keep their meaning: run green, ask amber, done blue, error red, idle grey.
STATUS = {"RUN": "#48b879", "ASK": "#e5ad46", "DONE": "#609ce3",
          "ERR": "#ed6969", "IDLE": "#9299a5"}

# Spacing scale (px). Use these instead of ad-hoc numbers.
S1, S2, S3, S4, S5 = 4, 8, 12, 16, 24

CJK = "Microsoft YaHei UI"
LATIN = "Segoe UI"
MONO = "Cascadia Mono"


def font(size=10, bold=False, mono=False, latin=False):
    family = MONO if mono else LATIN if latin else CJK
    return (family, size, "bold") if bold else (family, size)


def _dark_titlebar(window):
    """Best effort: dark native title bar on Windows 10/11. Silently skipped elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window.update_idletasks()
        child = window.winfo_id()
        if type(child) is not int:
            return
        hwnd = ctypes.windll.user32.GetParent(child)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
    except Exception:
        pass


def style_window(window, title, *, resizable=False):
    window.title(title)
    window.configure(bg=BG)
    window.resizable(resizable, resizable)
    try:
        from pathlib import Path
        window.iconbitmap(str(Path(__file__).with_name("agentdeck.ico")))
    except Exception:
        pass  # missing icon or non-Windows Tk: keep the default
    _dark_titlebar(window)
    return window


def center(window):
    """Centre on the screen; runs after the layout is final so the size is known."""
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    if type(width) is not int or type(height) is not int:
        return
    x = max(0, (window.winfo_screenwidth() - width) // 2)
    y = max(0, (window.winfo_screenheight() - height) // 3)
    window.geometry("+%d+%d" % (x, y))


def label(parent, text="", *, color=TEXT, size=10, bold=False, mono=False, latin=False,
          bg=None, **kwargs):
    import tkinter as tk
    return tk.Label(parent, text=text, fg=color, bg=BG if bg is None else bg,
                    font=font(size, bold, mono, latin), anchor=kwargs.pop("anchor", "w"),
                    takefocus=False, **kwargs)


_KINDS = {  # kind -> (bg, hover, fg)
    "primary": (TEXT, "#ffffff", BG),
    "quiet": (RAISED, "#2f3440", TEXT),
    "plain": (BG, RAISED, MUTED),
}


def button(parent, text, command, kind="primary", **kwargs):
    """Flat button. One 'primary' per window; everything else 'quiet' or 'plain'."""
    import tkinter as tk
    bg, hover, fg = _KINDS[kind]
    widget = tk.Label(parent, text=text, bg=bg, fg=fg, font=font(10, kind == "primary"),
                      padx=kwargs.pop("padx", S4), pady=kwargs.pop("pady", S2 - 1),
                      cursor="hand2", takefocus=True, highlightthickness=1,
                      highlightbackground=bg, highlightcolor=TEXT, **kwargs)

    def run(event=None):
        command()

    widget.bind("<Enter>", lambda event: widget.configure(bg=hover, highlightbackground=hover))
    widget.bind("<Leave>", lambda event: widget.configure(bg=bg, highlightbackground=bg))
    widget.bind("<ButtonRelease-1>", run)
    widget.bind("<Return>", run)
    widget.bind("<space>", run)
    return widget


def checkbox(parent, text, variable):
    """Quiet check row: a small square that fills when set."""
    import tkinter as tk
    row = tk.Frame(parent, bg=BG, cursor="hand2")
    box = tk.Label(row, text="", width=2, bg=RAISED, font=font(8), takefocus=False)
    caption = label(row, text, color=MUTED, size=9)
    box.pack(side="left")
    caption.pack(side="left", padx=(S2, 0))

    def refresh(*_):
        on = variable.get()
        box.configure(text="✓" if on else "", bg=TEXT if on else RAISED, fg=BG)

    def toggle(event=None):
        variable.set(not variable.get())
        refresh()

    for widget in (row, box, caption):
        widget.bind("<ButtonRelease-1>", toggle)
    refresh()
    return row


def _dialog(parent, title, text, buttons, *, accent=None):
    """Modal dialog; returns the value of the pressed button (Esc / close = last 'cancel')."""
    import tkinter as tk
    window = tk.Toplevel(parent)
    style_window(window, title)
    result = {"value": None}

    def finish(value):
        result["value"] = value
        window.destroy()

    body = tk.Frame(window, bg=BG, padx=S5, pady=S5)
    body.pack(fill="both", expand=True)
    if accent:
        tk.Frame(body, bg=accent, width=3).pack(side="left", fill="y", padx=(0, S3))
    column = tk.Frame(body, bg=BG)
    column.pack(side="left", fill="both", expand=True)
    label(column, text, size=10, justify="left", wraplength=380).pack(anchor="w")
    row = tk.Frame(column, bg=BG)
    row.pack(anchor="e", pady=(S5, 0))
    for caption, value, kind in buttons:
        button(row, caption, lambda v=value: finish(v), kind).pack(side="left", padx=(S2, 0))
    window.bind("<Escape>", lambda event: finish(buttons[0][1] if len(buttons) == 1 else False))
    window.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    center(window)
    try:
        if parent.winfo_viewable():  # a transient of a withdrawn parent is never shown
            window.transient(parent)
        window.attributes("-topmost", True)  # the overlay is topmost; stay above it
        window.grab_set()
        window.focus_force()
        row.winfo_children()[-1].focus_set()
    except Exception:
        pass
    window.wait_window()
    return result["value"]


def confirm(parent, title, text, ok="确定", cancel="取消"):
    return bool(_dialog(parent, title, text, ((cancel, False, "quiet"), (ok, True, "primary"))))


def notice(parent, title, text, *, error=False):
    _dialog(parent, title, text, (("好", True, "primary"),), accent=STATUS["ERR"] if error else None)
