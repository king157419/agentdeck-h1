"""Forward hooks to the local hub; gate failures deny the pending operation."""
import argparse
import http.client
import json
import math
from pathlib import Path
import sys


def gate_denial(reason="hub unavailable or invalid response"):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "Blocked by AgentDeck gate: " + reason}}).encode("utf-8")


def relay(event, agent, *, port=47800, approve_timeout=110, home=None,
          connection_factory=http.client.HTTPConnection, gate=False):
    """Return the original response bytes, or None without exposing errors."""
    connection = None
    try:
        if agent not in ("cc", "cx") or not isinstance(event, dict):
            return gate_denial("invalid gate event") if gate else None
        if gate and event.get("hook_event_name") != "PreToolUse":
            return gate_denial("gate requires PreToolUse")
        approve_timeout = float(approve_timeout)
        if not math.isfinite(approve_timeout) or approve_timeout <= 0:
            return gate_denial("invalid approval timeout") if gate else None
        token = ((Path.home() if home is None else Path(home)) /
                 ".agentdeck" / "token").read_text(encoding="utf-8").strip()
        if not token:
            return gate_denial("missing authentication token") if gate else None
        body = json.dumps(event, ensure_ascii=False).encode("utf-8")
        connection = connection_factory("127.0.0.1", port, timeout=0.5)
        connection.connect()
        connection.sock.settimeout(approve_timeout + 5 if
                                   gate or event.get("hook_event_name") == "PermissionRequest" else 5)
        connection.request("POST", "/event?agent=" + agent + ("&gate=1" if gate else ""), body=body,
                           headers={"Content-Type": "application/json",
                                    "X-AgentDeck-Token": token})
        response = connection.getresponse()
        raw = response.read()
        decoded = json.loads(raw)
        if response.status != 200 or not isinstance(decoded, dict):
            return gate_denial() if gate else None
        if gate and decoded != {}:
            output = decoded.get("hookSpecificOutput")
            if (set(decoded) != {"hookSpecificOutput"} or not isinstance(output, dict)
                    or set(output) != {"hookEventName", "permissionDecision", "permissionDecisionReason"}
                    or output.get("hookEventName") != "PreToolUse"
                    or output.get("permissionDecision") != "deny"
                    or not isinstance(output.get("permissionDecisionReason"), str)):
                return gate_denial()
        return raw
    except Exception as error:
        try:  # Best-effort diagnostics only; never change the hook's output.
            with open((Path.home() if home is None else Path(home)) /
                      ".agentdeck" / "relay.log", "a", encoding="utf-8") as log:
                log.write("%s %s %r\n" % (agent, event.get("hook_event_name") if isinstance(event, dict) else None, error))
        except Exception:
            pass
        return gate_denial() if gate else None
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
    parser.add_argument("--gate", action="store_true")
    args = parser.parse_args(argv)
    try:
        event = json.load(sys.stdin if stdin is None else stdin)
        result = relay(event, args.agent, port=args.port,
                       approve_timeout=args.approve_timeout, home=args.home, gate=args.gate)
    except Exception:
        result = gate_denial("invalid gate input or relay failure") if args.gate else None
    if args.gate and result is None:
        result = gate_denial()
    try:
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
