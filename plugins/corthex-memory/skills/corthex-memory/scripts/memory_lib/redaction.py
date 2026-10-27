"""Stage 06's six redaction steps. Pure text transformation; errors propagate.

Limits use KiB (1024 UTF-8 bytes). The cut value is the original byte size,
not the redacted size. This module performs no I/O except environment access.
"""

import os
import re
from dataclasses import dataclass

ENTRY_BYTES = 512 * 1024
WINDOW_BYTES = 520 * 1024
MEMORY_KEYS = ("CORTHEX_MEMORY_ANTHROPIC_API_KEY", "CORTHEX_MEMORY_OPENAI_API_KEY")
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.IGNORECASE | re.ASCII)
SURROGATE = re.compile(r"[\ud800-\udfff]")
PRIVATE = re.compile(r"<private>[\s\S]*?(?:</private>|\Z)", re.IGNORECASE | re.ASCII)
VALUE = r'''"[^"\r\n]{1,512}"|'[^'\r\n]{1,512}'|[^\s"',;]{1,512}'''
SECRET_VALUE = (r'''"(?=[^"\r\n]{0,512}[A-Za-z])[^"\r\n]{8,512}"|'''
                r"'(?=[^'\r\n]{0,512}[A-Za-z])[^'\r\n]{8,512}'|"
                r'''(?=[^\s"',;]{0,512}[A-Za-z])[^\s"',;]{8,512}''')
PATTERNS = (
    ("private-key", r"-{5}BEGIN [A-Z0-9 ]*PRIVATE KEY[A-Z ]*-{5}[\s\S]*?(?:-{5}END [A-Z0-9 ]*PRIVATE KEY[A-Z ]*-{5}|\Z)"),
    ("anthropic-key", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    ("openai-key", r"sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"),
    ("github-token", r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}"),
    ("gitlab-token", r"glpat-[A-Za-z0-9_-]{20,}"),
    ("slack-token", r"xox[abposr]-[A-Za-z0-9-]{10,}|https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{8,}"),
    ("aws-key", r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    ("google-key", r"AIza[0-9A-Za-z_-]{35}|ya29\.[0-9A-Za-z_-]{20,}"),
    ("jwt", r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ("url-credentials", r"(?<=://)[^/\s:@]{1,256}:[^/\s@]{1,256}(?=@)"),
    ("authorization", r"(?i)((?:proxy-)?authorization[ \t]*:[ \t]*)[^\r\n]+"),
    ("assigned-secret", r'''(?i)((?:password|passwd|secret)[A-Za-z0-9_.-]{0,40}["']?[ \t]*[:=][ \t]*)(?:''' + VALUE + ")"),
    ("assigned-secret", r'''(?i)((?:token|api[_-]?key|access[_-]?key)[A-Za-z0-9_.-]{0,40}["']?[ \t]*[:=][ \t]*)(?:''' + SECRET_VALUE + ")"),
)
COMPILED = tuple((kind, re.compile(pattern)) for kind, pattern in PATTERNS)


@dataclass(frozen=True)
class Redacted:
    text: str
    cut: object = None


def _unicode(text):
    # Keep ordinary scalar text fast; preserve pairs and replace lone units.
    if not SURROGATE.search(text):
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _clip(text, limit):
    data = text.encode("utf-8")
    return data[:limit].decode("utf-8", "ignore"), len(data)


def _environment(text, environment):
    values = {}
    for name, value in environment.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if name not in MEMORY_KEYS and not SECRET_NAME.search(name):
            continue
        value = _unicode(value)
        if len(value) < 12:
            continue
        if name in MEMORY_KEYS:
            values[value] = "memory-key"
        elif SECRET_NAME.search(name):
            values.setdefault(value, "environment")
    for value in sorted(values, key=lambda item: (-len(item), item)):
        text = text.replace(value, "[redacted:" + values[value] + "]")
    return text


def redact(text, environment=None):
    """Return redacted text and optional original bytes; never catch an error."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    # 1. Normalize lone surrogates before byte counts and the guard window.
    text = _unicode(text)
    text, original = _clip(text, WINDOW_BYTES)
    cut = original > WINDOW_BYTES
    # 2–3. Private spans and key blocks precede all exact-value/pattern passes.
    text = PRIVATE.sub("[redacted:private]", text)
    text = COMPILED[0][1].sub("[redacted:private-key]", text)
    # 4. All environment values are used only for redaction, never API auth.
    text = _environment(text, dict(os.environ) if environment is None else environment)
    # 5. Keep each pattern's name/header group, as the contract requires.
    for kind, pattern in COMPILED[1:]:
        mark = "[redacted:" + kind + "]"
        text = pattern.sub(lambda match: (match.group(1) if pattern.groups else "") + mark, text)
    # 6. A cut in either step reports the size before any transformation.
    text, size = _clip(text, ENTRY_BYTES)
    return Redacted(text, original if cut or size > ENTRY_BYTES else None)
