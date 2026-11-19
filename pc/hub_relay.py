"""Forward hooks to the local hub; on gate failure only risky operations are denied."""
import argparse
import json
import math
from pathlib import Path
import sys


def gate_denial(reason="hub unavailable or invalid response"):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "Blocked by AgentDeck gate: " + reason}}).encode("utf-8")


def _log(home, agent, event, error):
    try:  # Best-effort diagnostics only; never change the hook's output.
        with open((Path.home() if home is None else Path(home)) /
                  ".agentdeck" / "relay.log", "a", encoding="utf-8") as log:
            log.write("%s %s %r\n" % (agent, event.get("hook_event_name") if isinstance(event, dict) else None, error))
    except Exception:
        pass


def gate_failure(event, agent, home, reason):
    """Hub unusable: classify locally; deny only high/critical, else None (agent continues)."""
    try:
        if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
            raise ValueError("not a PreToolUse event")
        tool_name = event.get("tool_name")
        if not isinstance(tool_name, str):
            raise ValueError("missing tool_name")
        from hub_risk import PROTECTED_BRANCHES, classify  # lazy: only on the failure path
        options = {}
        try:
            config = json.loads((Path.home() if home is None else Path(home)).joinpath(
                ".agentdeck", "config.json").read_text(encoding="utf-8-sig"))
            if isinstance(config, dict):
                options = {name: config[name] for name in
                           ("production_hosts", "protected_branches", "mcp_write_tools") if name in config}
        except Exception:
            pass  # missing or unreadable config: built-in defaults
        options.setdefault("protected_branches", PROTECTED_BRANCHES)
        risk = classify(tool_name, event.get("tool_input", {}), **options)
    except Exception as error:
        _log(home, agent, event, "gate fallback classification failed: %r (%s)" % (error, reason))
        return None
    if risk in ("high", "critical"):
        return gate_denial("hub unavailable (%s); %s-risk operation blocked" % (reason, risk))
    return None


def relay(event, agent, *, port=47800, approve_timeout=110, home=None,
          connection_factory=None, gate=False):
    """Return the original response bytes, or None without exposing errors."""
    connection = None
    try:
        if agent not in ("cc", "cx") or not isinstance(event, dict):
            return gate_failure(event, agent, home, "invalid gate event") if gate else None
        if gate and event.get("hook_event_name") != "PreToolUse":
            return gate_failure(event, agent, home, "gate requires PreToolUse")
        approve_timeout = float(approve_timeout)
        if not math.isfinite(approve_timeout) or approve_timeout <= 0:
            return gate_failure(event, agent, home, "invalid approval timeout") if gate else None
        token = ((Path.home() if home is None else Path(home)) /
                 ".agentdeck" / "token").read_text(encoding="utf-8").strip()
        if not token:
            return gate_failure(event, agent, home, "missing authentication token") if gate else None
        body = json.dumps(event, ensure_ascii=False).encode("utf-8")
        if connection_factory is None:
            import http.client  # lazy: keeps the hub-down failure path fast
            connection_factory = http.client.HTTPConnection
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
            return gate_failure(event, agent, home, "bad hub response") if gate else None
        if gate and decoded != {}:
            output = decoded.get("hookSpecificOutput")
            if (set(decoded) != {"hookSpecificOutput"} or not isinstance(output, dict)
                    or set(output) != {"hookEventName", "permissionDecision", "permissionDecisionReason"}
                    or output.get("hookEventName") != "PreToolUse"
                    or output.get("permissionDecision") != "deny"
                    or not isinstance(output.get("permissionDecisionReason"), str)):
                return gate_failure(event, agent, home, "bad hub response")
        return raw
    except Exception as error:
        _log(home, agent, event, error)
        return gate_failure(event, agent, home, "hub not reachable") if gate else None
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
        source = sys.stdin if stdin is None else stdin
        # Hooks send UTF-8; the console code page (cp1252/GBK) would corrupt Chinese text.
        data = source.buffer.read() if hasattr(source, "buffer") else source.read()
        event = json.loads(data.decode("utf-8-sig") if isinstance(data, bytes) else data)
        result = relay(event, args.agent, port=args.port,
                       approve_timeout=args.approve_timeout, home=args.home, gate=args.gate)
    except Exception as error:
        result = None  # unparseable input: cannot classify, do not block
        _log(args.home, args.agent, None, "invalid hook input or relay failure: %r" % error)
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
