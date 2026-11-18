"""Append-only Hub decision records with a verifiable SHA-256 chain."""
from collections import deque
import hashlib
import hmac
import json
from pathlib import Path
import threading


GENESIS = "0" * 64


class AuditError(ValueError):
    """The existing log is damaged; never silently start a new chain."""


def _encode(record):
    return json.dumps(record, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


class AuditLog:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _read(self, limit=0):
        previous = GENESIS
        records = deque(maxlen=limit)
        try:
            stream = self.path.open("rb")
        except FileNotFoundError:
            return records, previous
        with stream:
            for number, line in enumerate(stream, 1):
                try:
                    if not line.endswith(b"\n"):
                        raise ValueError("incomplete line")
                    raw = line[:-1]
                    record = json.loads(raw)
                    digest = record.pop("sha256")
                    if record["prev_sha256"] != previous or not hmac.compare_digest(
                            digest, hashlib.sha256(_encode(record)).hexdigest()):
                        raise ValueError("hash mismatch")
                    record["sha256"] = digest
                except (ValueError, KeyError, TypeError, AttributeError) as error:
                    raise AuditError("audit chain invalid at line %d" % number) from error
                previous = hashlib.sha256(raw).hexdigest()
                records.append(record)
        return records, previous

    def append(self, record):
        with self.lock:
            _, previous = self._read()
            entry = dict(record, prev_sha256=previous)
            entry.pop("sha256", None)
            entry["sha256"] = hashlib.sha256(_encode(entry)).hexdigest()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab") as stream:
                stream.write(_encode(entry) + b"\n")
            return entry

    def recent(self, limit=50):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("audit limit must be between 1 and 1000")
        with self.lock:
            records, _ = self._read(limit)
            return list(records)

    def verify(self):
        with self.lock:
            self._read()
        return True
