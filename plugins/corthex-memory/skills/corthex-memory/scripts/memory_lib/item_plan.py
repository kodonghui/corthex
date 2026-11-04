"""Pure normal item/status/pin publication plan. Undo integration is separate."""
import copy

from . import curation, format2, item_types, store


def plan(items, pins, additions, transitions, at, device):
    format2._time(at)
    format2._id(device, store.DEVICE)
    checked = [item_types.parse_item(item_types.item_bytes(value)) for value in items]
    before = {value['id']: value for value in checked}
    if len(before) != len(checked):
        raise ValueError('duplicate stored item')
    final = copy.deepcopy(before)
    pins = item_types.parse_pins(item_types.pins_bytes(pins))
    pin_map = {value['item']: value for value in pins['pins']}
    records, notices, targets = [], [], set()
    for record in additions:
        value = item_types.parse_item(item_types.item_bytes(record))
        if value['id'] in final or value['status'] != 'current':
            raise ValueError('new current item required')
        final[value['id']] = value
        records.append(value)
        targets.add('item:' + value['id'])
    seen, ordered = set(), []
    for transition in transitions:
        curation._shape(transition, 'id status', 'superseded_by')
        item = transition['id']
        format2._id(item, item_types.ITEM)
        curation._choice(transition['status'], {'superseded', 'withdrawn'})
        if item in seen or item not in before or before[item]['status'] != 'current':
            raise ValueError('existing current item required')
        seen.add(item)
        ordered.append(item)
        value = copy.deepcopy(before[item])
        value.update(transition, changed=at)
        if value['status'] == 'superseded':
            format2._id(transition.get('superseded_by'), item_types.ITEM)
        elif 'superseded_by' in transition:
            raise ValueError('withdrawal does not supply a replacement')
        value = item_types.parse_item(item_types.item_bytes(value))
        final[item] = value
        records.append(value)
        targets.add('item:' + item)
    for item in ordered:
        value = final[item]
        replacement = value.get('superseded_by') if value['status'] == 'superseded' else None
        if replacement is not None and (replacement == item or replacement not in final or final[replacement]['status'] != 'current'):
            raise ValueError('current replacement required')
        pin = pin_map.get(item)
        if pin is None or not pin['on']:
            continue
        pin_map[item] = {'item': item, 'on': False, 'at': at, 'device': device}
        targets.add('pin:' + item)
        notice = {'at': at, 'kind': 'pin-dropped', 'item': item}
        if replacement is not None:
            pin_map[replacement] = {'item': replacement, 'on': True, 'at': at, 'device': device}
            targets.add('pin:' + replacement)
            notice.update(kind='pin-moved', to=replacement)
        notices.append((item, item_types.notice_bytes(notice)))
    if not records:
        raise ValueError('item change required')
    return {'records': [(v['id'], item_types.item_bytes(v)) for v in records],
            'pins': item_types.pins_bytes({'pins': list(pin_map.values())}) if notices else None,
            'list': item_types.item_list_bytes(list(final.values())),
            'notices': sorted(notices), 'targets': sorted(targets)}
