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


def read_catalog(limit=12, *, root=None):
    """Return (recent sessions, hidden CLI IDs) from one directory scan.

    ``root`` can replace the ``claude-code-sessions`` directory for offline tests.
    Account selection uses the newest file mtime, including archived sessions.
    Both results share the JSON cache and active account; hidden IDs include
    all archived/scheduled records regardless of the visible session limit.
    Any read failure yields ([], set()) so keyboard controls keep working.
    """
    try:
        if limit <= 0:
            return [], set()
        if root is None:
            appdata = os.environ.get("APPDATA")
            if not appdata:
                return [], set()
            root = Path(appdata) / "Claude" / "claude-code-sessions"
        root = Path(root).resolve()
        files = []
        for path in root.glob("*/*/local_*.json"):
            info = path.stat()
            if stat.S_ISREG(info.st_mode):
                files.append((path, (info.st_mtime_ns, info.st_size)))
        if not files:
            return [], set()
        active = max(files, key=lambda entry: entry[1][0])[0].parent
        with _cache_lock:
            refreshed = {}
            sessions = []
            hidden_ids = set()
            for path, signature in files:
                if path.parent != active:
                    continue
                cached = _cache.get(path)
                if cached is not None and cached[0] == signature:
                    session, hidden_id = cached[1:]
                else:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    session = _session(record)
                    hidden_id = (record.get("cliSessionId") if record.get("isArchived")
                                 or record.get("scheduledTaskId") else None)
                refreshed[path] = (signature, session, hidden_id)
                if session is not None:
                    sessions.append(dict(session))
                if hidden_id:
                    hidden_ids.add(hidden_id)
            sessions.sort(key=lambda session: session["last_activity"], reverse=True)
            result = sessions[:limit]
            _cache.clear()
            _cache.update(refreshed)
            return result, hidden_ids
    except Exception:
        return [], set()


def recent_sessions(limit=12, *, root=None):
    """Return the active account's newest sessions; ``last_activity`` is in ms."""
    return read_catalog(limit, root=root)[0]
