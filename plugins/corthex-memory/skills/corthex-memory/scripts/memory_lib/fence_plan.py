"""Pure TASK-075 revision plans; the lease/durability owner must publish them.

This module neither authorizes a mutation nor writes a record. A caller must
read fresh progress under the layer lease, durably publish a reservation and
revalidate ownership before effects. Recovery publication is a separate step.
"""
import copy
import json
import uuid

from . import format2


class Stale(RuntimeError):
    """A request's local control snapshot is no longer current."""


def _checked(progress):
    return format2.parse_curation(json.dumps(progress, ensure_ascii=False, allow_nan=False).encode('utf-8'))


def snapshot(progress):
    """Return only detached control proof, without progress/attempt details."""
    value = _checked(progress)
    return {'applies': value['applies'], 'fence': copy.deepcopy(value['fence'])}


def matches(progress, expected):
    """Validate both counters and the fence; absent revisions stay unknown."""
    if not isinstance(expected, dict) or set(expected) != {'applies', 'fence'}:
        return False
    try:
        proof = _checked({'logs': {}, 'applies': expected['applies'], 'recent': [],
                          'consolidation': {'failures': 0}, 'fence': expected['fence']})
    except (TypeError, ValueError, OverflowError):
        return False
    return snapshot(progress) == {'applies': proof['applies'], 'fence': proof['fence']}


def advance(progress, expected, targets, run_id=None):
    """Plan one generation for affected objects and an optional run, preserving others.

    A missing prior object revision is not manufactured as zero. The returned
    value is only a proposal; failed publication forbids the actual effect.
    """
    value = _checked(progress)
    if not matches(value, expected):
        raise Stale()
    keys = set(targets)
    if run_id is not None:
        format2._id(run_id, format2._RUN)
        keys.add('run:' + run_id)
    if not keys:
        raise ValueError('a mutation requires affected revisions')
    for key in keys:
        format2._id(key, format2._OBJECT)
    generation = value['fence']['generation'] + 1
    value['fence']['generation'] = generation
    for key in keys:
        value['fence']['revisions'][key] = generation
    return _checked(value)


def rotate(progress):
    """Choose a fresh code-owned nonce, retaining no old identity authorization.

    Recovery never accepts a restored or caller-supplied historical epoch.
    Tests may patch UUID generation; operational callers cannot choose it.
    """
    value = _checked(progress)
    epoch = uuid.uuid4().hex
    format2._id(epoch, format2._EPOCH)
    if epoch.lower() == value['fence']['epoch'].lower():
        raise ValueError('recovery requires a new epoch')
    value['fence'] = {'epoch': epoch, 'generation': 0, 'revisions': {}}
    return _checked(value)
