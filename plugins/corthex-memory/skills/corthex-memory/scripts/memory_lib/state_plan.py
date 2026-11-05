"""Pure complete physical state diff; a plan grants no publication authority.

The caller owns named-edit/provenance/cap/stale policy. This layer derives
every persisted prior version itself and never accepts a supplied history list.
Verified same-ID restorations belong to the inverse owner, not this publisher.
"""
from dataclasses import dataclass, field
import json

from . import curation, format2, item_types, state_types, store


def _placements(lines):
    result = {}
    for part in state_types.PARTS:
        group = sorted((line for line in lines if line['part'] == part), key=lambda line: (line['pos'], line['id']))
        for index, line in enumerate(group):
            result[line['id']] = (part, line['pos'], group[index-1]['id'] if index else '',
                                  group[index+1]['id'] if index+1 < len(group) else '')
    return result


@dataclass(frozen=True)
class Effect:
    line: str
    op: str
    why: str = field(repr=False)
    before: bytes = field(repr=False)
    before_place: tuple
    after_place: tuple


@dataclass(frozen=True)
class Plan:
    state: bytes = field(repr=False)
    removed: bytes = field(repr=False)
    effects: tuple

    @property
    def targets(self):
        return tuple('line:'+effect.line for effect in self.effects)

    def history(self, progress, run, at, device):
        """Materialize exact prior records only after a durable reservation."""
        fence = progress['fence']
        values = []
        for effect in self.effects:
            if effect.before is None:
                continue
            old = json.loads(effect.before.decode('utf-8'))
            value = {'at':at, 'run':run, 'epoch':fence['epoch'], 'generation':fence['generation'],
                     'line':effect.line, 'part':old['part'], 'pos':old['pos'], 'op':effect.op,
                     'text':old['text'], 'cites':old['cites'], 'why':effect.why, 'device':device}
            state_types.history_record_bytes(value)
            values.append(value)
        return tuple(values)


def plan(before_state, before_removed, proposal, at, device):
    """Verify descriptors against all physical differences, including positions.

    Proposal is {state:{lines:[...]}, operations:[{id,op,why},...]}. New rows use
    added with an empty reason. Existing rows need a matching history operation.
    This does not decide source eligibility; the original owner must prove it.
    """
    old = state_types.parse_state(item_types._raw(before_state))
    removed = state_types.parse_removed(item_types._raw(before_removed))
    proposal = item_types._document(item_types._raw(proposal))
    curation._shape(proposal, 'state operations')
    after = state_types.parse_state(item_types._raw(proposal['state']))
    format2._time(at)
    format2._id(device, store.DEVICE)
    if not isinstance(proposal['operations'], list):
        raise ValueError('state operations required')
    operations = {}
    allowed = {'added','changed','removed','cut','stale','recited','undone'}
    for operation in proposal['operations']:
        curation._shape(operation, 'id op why')
        format2._id(operation['id'], state_types.LINE)
        curation._choice(operation['op'], allowed)
        item_types._text(operation['why'], 200)
        if operation['id'] in operations:
            raise ValueError('duplicate state operation')
        operations[operation['id']] = operation
    previous = {line['id']:line for line in old['lines']}
    following = {line['id']:line for line in after['lines']}
    changed = sorted(key for key in set(previous)|set(following) if previous.get(key) != following.get(key))
    if set(operations) != set(changed):
        raise ValueError('state operations do not cover exact physical changes')
    before_places, after_places = _placements(old['lines']), _placements(after['lines'])
    groups = {}
    for marker in removed['removed']:
        groups.setdefault(marker['id'], []).append(marker)
    effects, new_markers = [], {}
    for line_id in changed:
        prior, next_line = previous.get(line_id), following.get(line_id)
        operation, markers = operations[line_id], groups.get(line_id, [])
        if markers and (prior is None or len(markers) != 1 or markers[0].get('kind') != 'edit' or
                        not {'restored_by','restored_at'} <= set(markers[0])):
            raise ValueError('privacy, unknown or unverified removed line')
        op, why = operation['op'], operation['why']
        if prior is None:
            if op != 'added' or why:
                raise ValueError('new line requires added and empty reason')
        elif next_line is None:
            if op not in {'removed','cut','stale','undone'}:
                raise ValueError('missing removal operation')
            new_markers[line_id] = state_types.removal_marker(line_id, at, device, 'edit')
        else:
            if op not in {'changed','recited','undone'}:
                raise ValueError('invalid retained-line operation')
            position_only = (prior['text'],prior['cites']) == (next_line['text'],next_line['cites']) and (
                prior['part'],prior['pos']) != (next_line['part'],next_line['pos'])
            if position_only and ((op != 'undone' and (op != 'changed' or why != 'position')) or
                                  any(prior[key] != next_line[key] for key in ('at','device'))):
                raise ValueError('position-only changes preserve content and time')
        effects.append(Effect(line_id, op, why, None if prior is None else item_types._raw(prior),
                              before_places.get(line_id, ()), after_places.get(line_id, ())))
    if not effects:
        return Plan(None, None, ())
    marker_bytes = None
    if new_markers:
        values = [new_markers.pop(marker['id'], marker) for marker in removed['removed']]
        values.extend(new_markers[key] for key in sorted(new_markers))
        marker_bytes = state_types.removed_bytes({'removed':values})
    return Plan(state_types.state_bytes(after), marker_bytes, tuple(effects))
