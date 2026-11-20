"""Claude transcript titles and bounded labels; no user files read on import."""
import json
from pathlib import Path


TAIL_BYTES = 256 * 1024


def clean_title(value):
    return value.strip() if isinstance(value, str) else ""


def transcript_title(path):
    """Search backwards in chunks, decoding only complete JSONL records."""
    if not isinstance(path, (str, Path)) or not str(path):
        return ""
    try:
        with open(path, "rb") as stream:
            stream.seek(0, 2)
            position = stream.tell()
            partial = b""
            while position:
                size = min(position, TAIL_BYTES)
                position -= size
                stream.seek(position)
                lines = (stream.read(size) + partial).split(b"\n")
                partial = lines[0] if position else b""
                for line in reversed(lines[1:] if position else lines):
                    # Most records are conversation content, not title metadata.
                    if b'"custom-title"' not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if isinstance(record, dict) and record.get("type") == "custom-title":
                        title = clean_title(record.get("customTitle"))
                        if title:
                            return title
    except (OSError, ValueError):
        pass
    return ""


def event_title(event):
    return clean_title(event.get("session_title")) or transcript_title(event.get("transcript_path"))


def session_label(session, limit=60):
    title = (session.get("title") or session.get("name") or session.get("project") or "Unnamed")
    text = " ".join(str(title).split())
    return text if len(text) <= limit else text[:max(0, limit - 1)] + "…"
