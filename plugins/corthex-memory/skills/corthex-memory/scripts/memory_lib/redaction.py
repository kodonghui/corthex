"""Stage 06's six redaction steps. Pure text transformation; errors propagate.

Limits use KiB (1024 UTF-8 bytes). The cut value is the original byte size,
not the redacted size. This module performs no I/O except environment access.
"""

import datetime
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
# Korean names, a particle, ":", "=" or white space, then a value of ASCII
# letters, digits and symbols only: a Hangul value is a sentence, not a secret.
KO_PASSWORD = r"(?:비밀[ \t]?번호|비번|패스워드|암호)"
KO_KEY = (r"(?:API[ \t]?키|api[ \t]?키|액세스[ \t]?(?:토큰|키)|비밀[ \t]?키|인증[ \t]?키|시크릿(?:[ \t]?키)?|토큰"
          r"|키(?<![가-힣]키))")
KO_SEPARATOR = r"(?:[은는이가을를][ \t]*(?:[:=][ \t]*)?|[ \t]*[:=][ \t]*|[ \t]+)"
KO_VALUE = r'''"[ !#-~]{1,512}"|'[ -&(-~]{1,512}'|[!#-&(-+\--:<-~]{1,512}'''
KO_SECRET_VALUE = (r'''"(?=[ !#-~]{0,512}[A-Za-z])[ !#-~]{8,512}"|'''
                   r"'(?=[ -&(-~]{0,512}[A-Za-z])[ -&(-~]{8,512}'|"
                   r'''(?=[!#-&(-+\--:<-~]{0,512}[A-Za-z])[!#-&(-+\--:<-~]{8,512}''')
PATTERNS = (
    ("private-key", r"-{5}BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY[A-Z ]{0,40}-{5}[\s\S]*?(?:-{5}END [A-Z0-9 ]{0,40}PRIVATE KEY[A-Z ]{0,40}-{5}|\Z)"),
    ("anthropic-key", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    ("openai-key", r"sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"),
    ("github-token", r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}"),
    ("gitlab-token", r"glpat-[A-Za-z0-9_-]{20,}"),
    ("slack-token", r"xox[abposr]-[A-Za-z0-9-]{10,}|https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{8,}"),
    ("aws-key", r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    ("google-key", r"AIza[0-9A-Za-z_-]{35}|ya29\.[0-9A-Za-z_-]{20,}"),
    ("notion-token", r"ntn_[0-9]{11}[A-Za-z0-9]{35,}|secret_[A-Za-z0-9]{43,}"),
    ("supabase-key", r"sbp_[a-z0-9]{40,}|sb_secret_[A-Za-z0-9_-]{16,}"),
    ("atlassian-token", r"ATATT3[A-Za-z0-9_=-]{186,}"),
    ("stripe-key", r"[rs]k_(?:live|test|prod)_[A-Za-z0-9]{10,}"),
    ("huggingface-token", r"hf_[A-Za-z]{34,}"),
    ("npm-token", r"npm_[A-Za-z0-9]{36,}"),
    ("langsmith-key", r"lsv2_(?:pt|sk|tr)_[A-Za-z0-9_]{20,}|ls__[A-Za-z0-9]{20,}"),
    ("jwt", r"(?:(?<![A-Za-z0-9_-])|(?<=%[0-9A-Fa-f]{2}))eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ("url-credentials", r"(?<=://)[^/\s:@]{1,256}:[^/\s@]{1,256}(?=@)"),
    ("authorization", r"(?i)((?:proxy-)?authorization[ \t]*:[ \t]*)[^\r\n]+"),
    ("bearer-token", r"([Bb]earer[ \t]+)[A-Za-z0-9._~+/-]{16,}=*"),
    ("assigned-secret", r'''(?i)((?:password|passwd|secret)[A-Za-z0-9_.-]{0,40}["']?[ \t]*[:=][ \t]*)(?:''' + VALUE + ")"),
    ("assigned-secret", r'''(?i)((?:token|api[_-]?key|access[_-]?key)[A-Za-z0-9_.-]{0,40}["']?[ \t]*[:=][ \t]*)(?:''' + SECRET_VALUE + ")"),
    ("assigned-secret", "(" + KO_PASSWORD + KO_SEPARATOR + ")(?:" + KO_VALUE + ")"),
    ("assigned-secret", "(" + KO_KEY + KO_SEPARATOR + ")(?:" + KO_SECRET_VALUE + ")"),
    # Stage 06 prints these patterns, so no character class comes right before
    # a parenthesis, which Markdown would read as a link.
    ("resident-number", r"[0-9]{6}(?<![0-9]{7})-[1-8][0-9]{6}(?![0-9])"),
    ("resident-number", "(주민(?:등록)?번호" + KO_SEPARATOR + r")[0-9]{6}[1-8][0-9]{6}(?![0-9])"),
    ("phone-number", r"01(?<![0-9]01)[016789][ -][0-9]{3,4}[ -][0-9]{4}(?![0-9])"),
    ("account-number", r"(계좌(?:[ \t]?번호)?" + KO_SEPARATOR + r"(?:[가-힣A-Za-z]{1,12}[ \t]+)?)(?!-)(?:-?[0-9]){10,16}(?![0-9])"),
    ("card-number", r"[0-9]{4}(?<![0-9]{5})(?:[0-9]{9,15}|(?:[ -][0-9]{3,6}){2,4})(?![0-9])"),
)
COMPILED = tuple((kind, re.compile(pattern)) for kind, pattern in PATTERNS)
# A number directly followed by one of these is a count, as in 비밀번호 8자 이상.
COUNTER = re.compile("자|글자|문자|회|번|개|단계|일|시간|분|초|년|이상|이하|이내|미만|초과")


def _korean_value(match):
    """After a Korean password name: not punctuation alone, nor a count."""
    value = match.string[match.end(1):match.end()]
    if not re.search("[A-Za-z0-9]", value):
        return False
    if value[0] in "\"'" or re.search("[A-Za-z]", value):
        return True
    return not COUNTER.match(match.string, match.end())


def _birth_date(match):
    """YYMMDD is a date of the century that the seventh digit gives (1, 2, 5, 6: 1900s; 3, 4, 7, 8: 2000s)."""
    start = match.end(1) if match.re.groups else match.start()
    digits = match.string[start:match.end()].replace("-", "")
    century = 1900 if digits[6] in "1256" else 2000
    try:
        datetime.date(century + int(digits[:2]), int(digits[2:4]), int(digits[4:6]))
    except ValueError:
        return False
    return True


def _card(match):
    """13 to 19 digits of a payment card's industry (3, 4, 5, 6, 9 or 2221-2720) that pass the Luhn check."""
    digits = re.sub("[^0-9]", "", match.group(0))
    if not 13 <= len(digits) <= 19 or (digits[0] not in "34569" and not 2221 <= int(digits[:4]) <= 2720):
        return False
    total = 0
    for place, digit in enumerate(reversed(digits)):
        value = int(digit) * (2 if place % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def _account(match):
    """An amount of money in won after the name is not an account number."""
    return not match.string.startswith("원", match.end())


def _check(kind, pattern):
    if kind == "assigned-secret" and pattern.startswith("(" + KO_PASSWORD):
        return _korean_value
    return {"resident-number": _birth_date, "card-number": _card, "account-number": _account}.get(kind)


# A pattern with a check replaces only the matches that pass it; others stay as they are.
CHECKS = {compiled: _check(kind, compiled.pattern) for kind, compiled in COMPILED if _check(kind, compiled.pattern)}


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
    check = CHECKS.get(pattern)
    if boundary is None:
        return pattern.sub(lambda m: m.group(0) if check and not check(m) else
                           (m.group(1) if pattern.groups else "") + mark, text), None
    delta = 0
    def emit(match):
        nonlocal delta
        if check and not check(match):
            return match.group(0)
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
