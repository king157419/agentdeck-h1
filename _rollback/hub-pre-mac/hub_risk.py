"""Pure risk classification rules shared by hub.py and hub_relay.py (stdlib only)."""
from fnmatch import fnmatchcase
import json
import re
import shlex
from urllib.parse import urlsplit

PROTECTED_BRANCHES = ("main", "master", "release/*")

# High-risk regexes control the double press; critical regexes require native approval.
RISK_RULES = [
    r"\brm\s+(?=[^\n|;&]*(?:-\w*r|--recursive))(?=[^\n|;&]*(?:-\w*f|--force))",
    r"\bRemove-Item\b[^\n|;&]*-Recurse\b",
    r"\b(?:del|rmdir)\b[^\n|;&]*/s\b",
    r"\bgit\b[^\n|;&]*\bpush\b[^\n|;&]*(?:--force(?:-with-lease)?\b|-\w*f\w*\b)",
    r"\bgit\b[^\n|;&]*\bpush\b[^\n|;&]*(?:--all\b|--mirror\b|\s\+\S+|\*)",
    r"\bgit\b[^\n|;&]*\breset\b[^\n|;&]*--hard\b",
    r"\bgit\b[^\n|;&]*\bclean\b[^\n|;&]*(?:-\w*f\w*\b|--force\b)",
    r"\b(?:curl|wget)\b[^\n]*\|\s*(?:(?:sudo|env)\s+)?(?:sh|bash|iex|Invoke-Expression)\b",
    r"\bsudo\b", r"\bformat(?:\.com|\.exe)?\b", r"\bmkfs(?:\.\w+)?\b",
    r"\bdd\s+[^\n|;&]*\bif\s*=",
    r"\bchmod\b(?=[^\n|;&]*-\w*r)(?=[^\n|;&]*\b777\b)",
    r"\bdrop\s+table\b",
    r"\bgh\b[^\n|;&]*\bpr\s+merge\b",
    r"\bkubectl\b[^\n|;&]*\b(?:apply|delete|exec)\b",
    r"\bterraform\b[^\n|;&]*\b(?:apply|destroy)\b",
    r"\bhelm\b[^\n|;&]*\bupgrade\b",
    r"\b(?:(?:DROP|ALTER)\s+\S+|DELETE\s+FROM|UPDATE\s+[^;\n]+?\s+SET)\b",
    r"\b(?:prisma\s+(?:migrate|db\s+push)|alembic\s+(?:upgrade|downgrade)|(?:django-admin|manage\.py|artisan)\s+migrate|(?:rails|rake)\s+db:(?:migrate|rollback|reset)|(?:knex|sequelize)\s+(?:migrate|db:migrate)|(?:flyway|liquibase)\s+(?:migrate|update)|dotnet\s+ef\s+database\s+update)\b",
]
CRITICAL_RULES = [
    r"\b(?:curl|wget)(?:\.exe)?\b[^\n]*\|\s*(?:(?:sudo|env)\s+)?[\"']?(?:[\w/.-]*/)?(?:sh|bash|zsh|iex|Invoke-Expression)\b",
    r"\b(?:iex|Invoke-Expression)\s*\(\s*(?:irm|iwr|Invoke-RestMethod|Invoke-WebRequest)\b",
    r"(?<![\w-])-(?:EncodedCommand|enc)(?=[\s\"']|$)",
    r"\bbase64\b(?=[^\n|;&]*(?:\s-\w*d\w*\b|\s--decode\b))[^\n]*\|\s*(?:(?:sudo|env)\s+)?[\"']?(?:[\w/.-]*/)?(?:sh|bash|zsh)\b",
    r"\brm(?=\s)(?=[^\n|;&]*(?:-\w*r|--recursive))(?=[^\n|;&]*(?:-\w*f|--force))[^\n|;&]*?(?<=\s)[\"']?(?:/\*?|~/?\*?|\$HOME/?\*?|\$\{HOME\}/?\*?)[\"']?(?=\s|[;&|]|$)",
    r"\bRemove-Item\b(?=[^\n|;&]*-Recurse\b)[^\n|;&]*?(?:\s|[\"'])[A-Z]:[/\\]\*?[\"']?(?=\s|[,);&|]|$)",
    r"(?<![\w.-])format(?:\.com|\.exe)?(?=\s|$)", r"\bmkfs(?:\.\w+)?\b",
    r"\bdd\b[^\n|;&]*\bof\s*=\s*[\"']?/dev/",
]
AUTHORIZED_KEYS = re.compile(r"(?:^|[/\\\s\"'=:])\.ssh[/\\]authorized_keys(?=[\s\"'\),;&|<>]|$)", re.I)
SENSITIVE_PATH = re.compile(r"(?:^|[/\\\s\"'=:])(?:\.ssh(?:[/\\\s\"']|$)|\.env(?:[.\s\"'/\\]|$))", re.I)
KEY_PATH = re.compile(r"(?:^|[/\\\s\"'=:])(?:id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|[^/\\\s\"']+\.(?:pem|key|p12|pfx)|(?:credentials|secrets)\.json)(?=[\s\"'\),;&|<>]|$)", re.I)
WRITE_TOOL = re.compile(r"write|edit|patch|save|create|upload", re.I)
SHELL_WRITE = re.compile(
    r">|\b(?:tee|Set-Content|Add-Content|Out-File|Copy-Item|Move-Item|cp|mv|touch|mkdir|install)\b"
    r"|\b(?:sed|perl)\b[^\n|;&]*(?:-\w*i\w*\b|--in-place\b)"
    r"|\bopen\s*\([^)]*,\s*(?:mode\s*=\s*)?[\"'](?:[wax]|rb?\+)"
    r"|\bdd\b[^\n|;&]*\bof\s*="
    r"|\b(?:write_text|write_bytes|writeFile(?:Sync)?|appendFile(?:Sync)?)\s*\(", re.I)


def classify(tool_name, tool_input, rules=None, critical_rules=None, *,
             production_hosts=(), protected_branches=PROTECTED_BRANCHES, mcp_write_tools=()):
    """Classify the requested operation; callers may supply regex strings."""
    if isinstance(tool_input, dict):
        text = "\n".join(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                         for value in tool_input.values())
    else:
        text = tool_input if isinstance(tool_input, str) else json.dumps(tool_input, ensure_ascii=False)
    # JSON escaping must not hide Windows paths from the sensitive-write rule.
    paths = text.replace("\\\\", "\\")
    if any(re.search(pattern, text, re.I) for pattern in
           (CRITICAL_RULES if critical_rules is None else critical_rules)):
        return "critical"
    if AUTHORIZED_KEYS.search(paths) and (WRITE_TOOL.search(tool_name) or SHELL_WRITE.search(text)):
        return "critical"
    if any(re.search(pattern, text, re.I) for pattern in (RISK_RULES if rules is None else rules)):
        return "high"
    for push in re.finditer(r"\bgit\b[^\n|;&]*?\bpush\b([^\n|;&]*)", text, re.I):
        refs = re.findall(r"(?:^|[\s:])[\"']?(?:refs/heads/)?([^\s\"':]+)", push[1])
        if any(fnmatchcase(ref, pattern) for ref in refs for pattern in protected_branches):
            return "high"
    if _production_ssh(text, production_hosts):
        return "high"
    if tool_name.startswith("mcp__") and any(fnmatchcase(tool_name, pattern) for pattern in mcp_write_tools):
        return "high"
    if (SENSITIVE_PATH.search(paths) or KEY_PATH.search(paths)) and (WRITE_TOOL.search(tool_name) or SHELL_WRITE.search(text)):
        return "high"
    return "low"


def _production_ssh(text, hosts):
    if not hosts:
        return False

    def production(destination):
        if destination.startswith("ssh://"):
            host = urlsplit(destination).hostname or ""
        else:
            host = destination.rsplit("@", 1)[-1]
            host = host[1:host.index("]")] if host.startswith("[") and "]" in host else host
        return any(fnmatchcase(host.casefold(), pattern.strip("[]").casefold()) for pattern in hosts)

    for match in re.finditer(r"\bssh(?:\.exe)?\s+([^\n|;&]+)", text, re.I):
        try:
            args = iter(shlex.split(match[1]))
            for arg in args:
                if arg == "--":
                    arg = next(args, "")
                elif arg.startswith("-"):
                    if arg == "-o" or arg.startswith("-o"):
                        option = next(args, "") if arg == "-o" else arg[2:]
                        parts = re.split(r"[=\s]+", option, maxsplit=1)
                        if len(parts) == 2 and parts[0].casefold() == "hostname" and production(parts[1]):
                            return True
                    elif arg in ("-p", "-l", "-i", "-F", "-J", "-L", "-R", "-D", "-S", "-E", "-b", "-c", "-e", "-m", "-O", "-Q", "-W", "-w"):
                        next(args, None)
                    continue
                if production(arg):
                    return True
                break
        except ValueError:
            continue
    return False
