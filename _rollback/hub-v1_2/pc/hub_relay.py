"""Forward command hooks to the local hub; failures leave native approval intact."""
import argparse
import http.client
import json
import math
from pathlib import Path
import sys


def relay(event, agent, *, port=47800, approve_timeout=110, home=None,
          connection_factory=http.client.HTTPConnection):
    """Return the original response bytes, or None without exposing errors."""
    connection = None
    try:
        if agent not in ("cc", "cx") or not isinstance(event, dict):
            return None
        approve_timeout = float(approve_timeout)
        if not math.isfinite(approve_timeout) or approve_timeout <= 0:
            return None
        token = ((Path.home() if home is None else Path(home)) /
                 ".agentdeck" / "token").read_text(encoding="utf-8").strip()
        if not token:
            return None
        body = json.dumps(event, ensure_ascii=False).encode("utf-8")
        connection = connection_factory("127.0.0.1", port, timeout=0.5)
        connection.connect()
        connection.sock.settimeout(approve_timeout + 5 if
                                   event.get("hook_event_name") == "PermissionRequest" else 5)
        connection.request("POST", "/event?agent=" + agent, body=body,
                           headers={"Content-Type": "application/json",
                                    "X-AgentDeck-Token": token})
        response = connection.getresponse()
        raw = response.read()
        if response.status != 200 or not isinstance(json.loads(raw), dict):
            return None
        return raw
    except Exception as error:
        try:  # Best-effort diagnostics only; never change the hook's output.
            with open(Path.home() / ".agentdeck" / "relay.log", "a", encoding="utf-8") as log:
                log.write("%s %s %r\n" % (agent, event.get("hook_event_name") if isinstance(event, dict) else None, error))
        except Exception:
            pass
        return None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def main(argv=None, *, stdin=None, stdout=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("cc", "cx"), required=True)
    parser.add_argument("--port", type=int, default=47800)
    parser.add_argument("--approve-timeout", type=float, default=110)
    parser.add_argument("--home", type=Path)
    args = parser.parse_args(argv)
    try:
        event = json.load(sys.stdin if stdin is None else stdin)
        result = relay(event, args.agent, port=args.port,
                       approve_timeout=args.approve_timeout, home=args.home)
        if result is not None:
            output = sys.stdout if stdout is None else stdout
            if hasattr(output, "buffer"):
                output.buffer.write(result)
                output.buffer.flush()
            else:
                output.write(result.decode("utf-8"))
                output.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
