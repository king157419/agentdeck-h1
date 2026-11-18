"""安装 / 卸载状态屏的上报钩子。

  python install.py install [cc] [codex]     不写名字 = 全部
  python install.py uninstall [cc] [codex]
  python install.py status

只追加自己的条目，不动别人的；每次改动前把原文件备份成 *.bak-agentlcd-<时间>。
自己的条目靠命令里出现 agent_lcd.py 来识别，所以重复安装不会装出两份。
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
PY = sys.executable.replace("\\", "/")
SCRIPT = HERE + "/agent_lcd.py"
MARK = "agent_lcd.py"
HOME = os.path.expanduser("~")

TARGETS = {
    "cc": {
        "path": os.path.join(HOME, ".claude", "settings.json"),
        "events": ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                   "PostToolUseFailure", "Notification", "Stop", "SessionEnd"],
        # Claude Code 支持 command + args（不经过 shell）和 async（后台跑，不拖慢会话）
        "entry": lambda: {"type": "command", "command": PY, "args": [SCRIPT, "hook", "cc"],
                          "timeout": 10, "async": True},
    },
    "codex": {
        "path": os.path.join(HOME, ".codex", "hooks.json"),
        "events": ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                   "PermissionRequest", "Stop", "Interrupt", "SessionEnd"],
        "entry": lambda: {"type": "command", "command": "%s %s hook cx" % (PY, SCRIPT),
                          "timeout": 10},
    },
}


def is_ours(group):
    return any(MARK in json.dumps(h) for h in group.get("hooks", []))


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save(path, data):
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak-agentlcd-" + time.strftime("%Y%m%d-%H%M%S"))
    tmp = path + ".tmp-agentlcd"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def strip(data):
    hooks = data.get("hooks", {})
    n = 0
    for ev in list(hooks):
        kept = [g for g in hooks[ev] if not is_ours(g)]
        n += len(hooks[ev]) - len(kept)
        if kept:
            hooks[ev] = kept
        else:
            del hooks[ev]
    return n


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    names = [a for a in sys.argv[2:] if a in TARGETS] or list(TARGETS)
    for name in names:
        t = TARGETS[name]
        data = load(t["path"])
        if action == "status":
            evs = [ev for ev, gs in data.get("hooks", {}).items() if any(is_ours(g) for g in gs)]
            print("%-6s %s -> %s" % (name, t["path"], ", ".join(evs) or "not installed"))
            continue
        strip(data)
        if action == "install":
            hooks = data.setdefault("hooks", {})
            for ev in t["events"]:
                hooks.setdefault(ev, []).append({"hooks": [t["entry"]()]})
        if not data.get("hooks"):
            data.pop("hooks", None)
        save(t["path"], data)
        print("%s: %s done (%s)" % (name, action, t["path"]))


if __name__ == "__main__":
    main()
