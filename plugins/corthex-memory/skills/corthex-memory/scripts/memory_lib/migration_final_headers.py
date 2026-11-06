"""Read-only completed-header catalog; never migration or recovery authority."""
from dataclasses import dataclass
import hashlib
from . import format2, migration_plan

@dataclass(frozen=True)
class FinalHeaders:
    originals: tuple
    original_sha256: tuple
    preserve_temps: tuple
    publications: tuple
    started: object

def observe(headers, *, release):
    """Require an actual named completed header without inventing a marker."""
    named = {'store.json', 'store.json.bak'}
    if not isinstance(headers, dict) or not headers or (not any((name in named for name in headers))):
        raise ValueError('named completed header required')
    if any((not isinstance(name, str) for name in headers)):
        raise ValueError('invalid header name')
    originals = []
    values = []
    completed = False
    markers = []
    for name, raw in sorted(headers.items()):
        if name not in named and (not isinstance(name, str) or migration_plan._TEMP.fullmatch(name) is None):
            raise ValueError('unknown header artifact')
        if not isinstance(raw, (bytes, bytearray)):
            raise ValueError('header bytes required')
        raw = bytes(raw)
        value = format2.parse_store(raw, allow_migrating=True)
        if value['release'] != release:
            raise ValueError('different completed release')
        if 'migrating' in value:
            markers.append(value['migrating'])
        elif name in named:
            completed = True
        originals.append((name, raw))
        values.append(value)
    if not completed:
        raise ValueError('named completed header required')
    context = (values[0]['device'], values[0]['made'], values[0]['release'])
    if any(((value['device'], value['made'], value['release']) != context for value in values)):
        raise ValueError('mixed completed context')
    if markers and any((marker != markers[0] for marker in markers)):
        raise ValueError('mixed residual migration marker')
    completed_value = dict(values[0])
    completed_value.pop('migrating', None)
    raw = format2.store_bytes(completed_value)
    return FinalHeaders(tuple(originals), tuple(((name, hashlib.sha256(data).hexdigest()) for name, data in originals)), tuple((name for name, _ in originals if name not in named)), (('store.json.bak', raw), ('store.json', raw)), markers[0]['started'] if markers else None)
