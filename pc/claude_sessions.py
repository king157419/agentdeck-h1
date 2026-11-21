"""Read Claude Desktop's recent session catalog without modifying its files."""
import json
import os
from pathlib import Path
import stat
import threading

from session_titles import clean_title


_cache = {}
_cache_lock = threading.Lock()


def _session(record):
    title = clean_title(record.get("title"))
    if record.get("isArchived") or record.get("scheduledTaskId") or not title:
        return None
    return {"session_id": record.get("sessionId", ""),
            "cli_session_id": record.get("cliSessionId", ""),
            "title": title, "cwd": record.get("cwd", ""),
            "last_activity": record.get("lastActivityAt", 0) or 0}


def recent_sessions(limit=12, *, root=None):
    """Return the active account's newest sessions; ``last_activity`` is in ms.

    ``root`` can replace the ``claude-code-sessions`` directory for offline tests.
    Account selection uses the newest file mtime, including archived sessions.
    JSON is only reread when its (mtime, size) changes. Any read failure yields
    an empty list so a missing or temporarily incomplete catalog cannot break
    keyboard controls.
    """
    try:
        if limit <= 0:
            return []
        if root is None:
            appdata = os.environ.get("APPDATA")
            if not appdata:
                return []
            root = Path(appdata) / "Claude" / "claude-code-sessions"
        root = Path(root).resolve()
        files = []
        for path in root.glob("*/*/local_*.json"):
            info = path.stat()
            if stat.S_ISREG(info.st_mode):
                files.append((path, (info.st_mtime_ns, info.st_size)))
        if not files:
            return []
        active = max(files, key=lambda entry: entry[1][0])[0].parent
        with _cache_lock:
            refreshed = {}
            sessions = []
            for path, signature in files:
                if path.parent != active:
                    continue
                cached = _cache.get(path)
                if cached is not None and cached[0] == signature:
                    session = cached[1]
                else:
                    session = _session(json.loads(path.read_text(encoding="utf-8")))
                refreshed[path] = (signature, session)
                if session is not None:
                    sessions.append(dict(session))
            sessions.sort(key=lambda session: session["last_activity"], reverse=True)
            result = sessions[:limit]
            _cache.clear()
            _cache.update(refreshed)
            return result
    except Exception:
        return []
