"""Pure TASK-074 migration proposals, never maintenance authority or I/O.

The actual owner verifies old-writer quiescence, a complete inventory, original
leases/identities and non-deletion lineage. It preserves originals outside
automatic recovery, durably fences every header before C2 data, and clears
migrating last. These byte proposals prove none of those conditions.
"""
import copy
from dataclasses import dataclass
import hashlib
import re
import uuid

from . import curation, format2, store

_TEMP = re.compile(r'store\.json(?:\.bak)?\.[a-z0-9_]{8}\.tmp\Z')
_NAMED = ('store.json', 'store.json.bak')


@dataclass(frozen=True)
class HeaderPlan:
    originals: tuple
    original_sha256: tuple
    preserve_temps: tuple
    publications: tuple


def header_fence(headers, *, release, when):
    """Propose backup then primary, binding every supplied original byte.

    Input is an observed catalog, not evidence that a filesystem inventory is
    complete. An absent primary may use a named backup, never a lone temp.
    Damaged/unknown/mixed-device headers are refused, not automatically healed.
    Existing migration markers govern resumes; a new wall time cannot reset one.
    """
    if not isinstance(headers, dict) or not headers or not any(n in headers for n in _NAMED):
        raise ValueError('named header required')
    if any(not isinstance(n, str) for n in headers):
        raise ValueError('invalid header name')
    format2._time(when)
    originals, parsed = [], []
    for name, raw in sorted(headers.items()):
        if name not in _NAMED and not _TEMP.fullmatch(name):
            raise ValueError('unknown header artifact')
        if not isinstance(raw, (bytes, bytearray)):
            raise ValueError('header bytes required')
        raw = bytes(raw)
        value = store.json_document(raw)
        if not isinstance(value, dict):
            raise ValueError('invalid header')
        if value.get('format') == 1 and 'migrating' not in value:
            value = store._record(raw)
        else:
            value = format2.parse_store(raw, allow_migrating=True)
            if 'migrating' not in value:
                raise ValueError('completed format-2 store requires maintenance owner')
        originals.append((name, raw))
        parsed.append(value)
    source = next(value for (name, _), value in zip(originals, parsed) if name in _NAMED)
    identity = source['device'], source['made']
    if any((v['device'], v['made']) != identity for v in parsed):
        raise ValueError('mixed store identity')
    resumed = [v for (name, _), v in zip(originals, parsed) if name in _NAMED and 'migrating' in v]
    observed = [v for v in parsed if 'migrating' in v]
    if observed and not resumed:
        raise ValueError('temporary header cannot establish a migration context')
    if resumed and any(v['migrating'] != resumed[0]['migrating'] or v['release'] != release for v in observed):
        raise ValueError('mixed migration context')
    marker = copy.deepcopy(resumed[0]['migrating']) if resumed else {'from': 1, 'to': 2, 'started': when}
    proposed = dict(format=2, device=identity[0], made=identity[1], release=release, migrating=marker)
    data = format2.store_bytes(proposed, allow_migrating=True)
    return HeaderPlan(tuple(originals),
        tuple((n, hashlib.sha256(b).hexdigest()) for n, b in originals),
        tuple(n for n, _ in originals if n not in _NAMED),
        (('store.json.bak', data), ('store.json', data)))


def progress(data):
    """Propose a fresh format-2 control document from strict C1 or absence.

    This is for the migration owner's proven C1 lineage, not damaged C2 repair.
    Missing data is merely an input; it does not prove supported initialization.
    No historical object/run revision, restoration link or zero revision is made.
    """
    if data is not None and not isinstance(data, (bytes, bytearray)):
        raise ValueError('progress bytes required')
    value = ({'logs': {}, 'applies': 0, 'recent': [], 'consolidation': {'failures': 0}}
             if data is None else curation.parse(bytes(data)))
    value['fence'] = {'epoch': uuid.uuid4().hex, 'generation': 0, 'revisions': {}}
    return format2.curation_bytes(value)
