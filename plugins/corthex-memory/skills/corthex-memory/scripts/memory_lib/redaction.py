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
    ("private-key", r"-{5}BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY[A-Z ]{0,40}-{5}[\s\S]*?(?:-{5}END [A-Z0-9 ]{0,40}PRIVATE KEY[A-Z ]{0,40}-{5}|\Z)"),
    ("anthropic-key", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    ("openai-key", r"sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"),
    ("github-token", r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}"),
    ("gitlab-token", r"glpat-[A-Za-z0-9_-]{20,}"),
    ("slack-token", r"xox[abposr]-[A-Za-z0-9-]{10,}|https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{8,}"),
    ("aws-key", r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    ("google-key", r"AIza[0-9A-Za-z_-]{35}|ya29\.[0-9A-Za-z_-]{20,}"),
    ("jwt", r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
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


def _adjust(boundary, start, end, emitted):
    """Shift an incoming cutoff, keeping a marker that starts before it."""
    return emitted - (min(end, boundary) - start) if boundary is not None and start < boundary else 0


def _replace(text, pattern, kind, boundary):
    mark = "[redacted:" + kind + "]"
    if boundary is None:
        return pattern.sub(lambda m: (m.group(1) if pattern.groups else "") + mark, text), None
    delta = 0
    def emit(match):
        nonlocal delta
        prefix = match.group(1) if pattern.groups else ""
        start = match.end(1) if pattern.groups else match.start()
        delta += _adjust(boundary, start, match.end(), len(mark))
        return prefix + mark
    return pattern.sub(emit, text), boundary + delta


def _environment(text, environment, boundary):
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
        mark = "[redacted:" + values[value] + "]"
        if boundary is None:
            text = text.replace(value, mark)
            continue
        pieces, used, delta = [], 0, 0
        while True:
            start = text.find(value, used)
            if start < 0:
                break
            end = start + len(value)
            pieces.extend((text[used:start], mark))
            delta += _adjust(boundary, start, end, len(mark))
            used = end
        text = "".join(pieces) + text[used:]
        boundary += delta
    return text, boundary


def redact(text, environment=None):
    """Return redacted text and optional original bytes; never catch an error."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    # 1. Normalize lone surrogates before byte counts and the guard window.
    text = _unicode(text)
    text, original = _clip(text, WINDOW_BYTES)
    cut = original > WINDOW_BYTES
    boundary = None
    if cut:
        prefix = text.encode("utf-8")[:ENTRY_BYTES].decode("utf-8", "ignore")
        boundary = len(prefix)
        # A source character/marker starting before the byte point belongs to
        # its prefix even if that scalar straddles it. The final cut is safe.
        if len(prefix.encode("utf-8")) < ENTRY_BYTES:
            boundary += 1
    # 2–3. Private spans and key blocks precede all exact-value/pattern passes.
    text, boundary = _replace(text, PRIVATE, "private", boundary)
    text, boundary = _replace(text, COMPILED[0][1], "private-key", boundary)
    # 4. All environment values are used only for redaction, never API auth.
    text, boundary = _environment(text, dict(os.environ) if environment is None else environment, boundary)
    # 5. Keep each pattern's name/header group, as the contract requires.
    for kind, pattern in COMPILED[1:]:
        text, boundary = _replace(text, pattern, kind, boundary)
    # 6. A cut in either step reports the size before any transformation.
    if boundary is not None:
        text = text[:boundary]
    text, size = _clip(text, ENTRY_BYTES)
    return Redacted(text, original if cut or size > ENTRY_BYTES else None)
