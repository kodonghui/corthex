"""Pure private migration-intent codec, not a journal or resume authority.

The real driver must preserve originals durably, match named migration headers,
reacquire original ownership and prove initialization/current privacy facts.
No path from a serialized record is ever opened by this module.
"""
from dataclasses import dataclass, field
import hashlib
import json
import re
import uuid

from . import base, curation, format2, maintenance_identity, migration_plan, store

_COPY = re.compile(r'(?:\.bak)?(?:\.[a-z0-9_]{8}\.tmp)?\Z')


class InvalidIntent(ValueError):
    def __init__(self):
        super().__init__('migration intent unavailable')


def _bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode('ascii')


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _hex(value, size):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{'+str(size)+'}', value) is None:
        raise InvalidIntent()


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise InvalidIntent()


def _check(value):
    if value.check() is not None:
        raise TypeError('maintenance check must return None')


@dataclass(frozen=True)
class Intent:
    encoded: bytes = field(repr=False)
    originals: tuple = field(repr=False)
    headers: migration_plan.HeaderPlan = field(repr=False)
    progress: tuple = field(repr=False)


def parse(data, originals):
    """Regenerate proposals from exact originals and fixed epochs, with no I/O.

    Hashes detect inconsistency, not malicious editing or rollback. Validation
    does not establish that a journal belongs to the currently named store.
    """
    try:
        value = store.json_document(data)
        _keys(value, 'version nonce root context sources projects header_sha256')
        if type(value['version']) is not int or value['version'] != 1:
            raise InvalidIntent()
        _hex(value['nonce'], 32)
        root, context = value['root'], value['context']
        _keys(root, 'path_sha256 identity')
        _hex(root['path_sha256'], 64)
        maintenance_identity.parse(_bytes(root['identity']))
        _keys(context, 'device made release started')
        if not isinstance(value['sources'], list) or not isinstance(value['projects'], list):
            raise InvalidIntent()
        originals = tuple(originals)
        if any(type(slot) is not int or not isinstance(raw, (bytes, bytearray)) for slot, raw in originals):
            raise InvalidIntent()
        originals = tuple((slot, bytes(raw)) for slot, raw in originals)
        if tuple(slot for slot, _ in originals) != tuple(range(len(value['sources']))):
            raise InvalidIntent()
        headers, progress, ordered = {}, {}, []
        configured = set()
        for slot, (source, (_, raw)) in enumerate(zip(value['sources'], originals)):
            _keys(source, 'family project name sha256')
            family, project, name = source['family'], source['project'], source['name']
            if family not in {'header', 'configuration', 'progress'} or not isinstance(name, str):
                raise InvalidIntent()
            primary = {'header': 'store.json', 'configuration': 'configuration.json', 'progress': 'curation.json'}[family]
            if not name.startswith(primary) or _COPY.fullmatch(name[len(primary):]) is None:
                raise InvalidIntent()
            if source['sha256'] != _hash(raw):
                raise InvalidIntent()
            if family == 'progress':
                base.project_folder_name(project)
                curation.parse(raw)
                progress.setdefault(project, {})[name] = (slot, raw)
            elif project is not None:
                raise InvalidIntent()
            elif family == 'header':
                store._record(raw)  # A new cold intent never accepts C2 or an existing migration.
                headers[name] = raw
            else:
                configured.update(store._configuration(raw).get('projects', {}))
            ordered.append((family, project or '', name))
        if ordered != sorted(set(ordered)) or configured - set(progress):
            raise InvalidIntent()
        proposal = migration_plan.header_fence(headers, release=context['release'], when=context['started'])
        header = format2.parse_store(proposal.publications[0][1], allow_migrating=True)
        if context != dict(device=header['device'], made=header['made'], release=header['release'],
                           started=header['migrating']['started']) or value['header_sha256'] != _hash(proposal.publications[0][1]):
            raise InvalidIntent()
        outputs = []
        for item in value['projects']:
            _keys(item, 'name epoch source sha256')
            name = item['name']
            candidates = progress[name]
            source = candidates.get('curation.json', candidates.get('curation.json.bak'))
            if source is None or type(item['source']) is not int or item['source'] != source[0]:
                raise InvalidIntent()
            raw = migration_plan.progress(source[1], epoch=item['epoch'])
            if item['sha256'] != _hash(raw):
                raise InvalidIntent()
            outputs.append((name, raw))
        if [name for name, _ in outputs] != sorted(progress):
            raise InvalidIntent()
        if len({item['epoch'] for item in value['projects']}) != len(outputs):
            raise InvalidIntent()
        return Intent(_bytes(value), originals, proposal, tuple(outputs))
    except Exception:
        raise InvalidIntent() from None


def prepare(owned, binding):
    """Bind a cold owner snapshot; never initialize missing state or write files."""
    _check(owned)
    inventory = owned.inventory
    _check(inventory)
    _check(binding)
    if inventory.folder != binding.path or binding.identity.document()['entry'] != 'directory':
        raise InvalidIntent()
    catalog = [('header', None, name, raw) for name, raw in inventory.headers.originals]
    catalog += [('configuration', None, name, raw) for name, raw in inventory.configuration]
    for project in inventory.projects:
        if not project.exists or not project.progress:
            raise InvalidIntent()
        catalog += [('progress', project.name, name, raw) for name, raw in project.progress]
    catalog.sort(key=lambda item: (item[0], item[1] or '', item[2]))
    sources, originals, projects = [], [], []
    for slot, (family, project, name, raw) in enumerate(catalog):
        sources.append(dict(family=family, project=project, name=name, sha256=_hash(raw)))
        originals.append((slot, raw))
    for project in inventory.projects:
        candidates = dict(project.progress)
        name = 'curation.json' if 'curation.json' in candidates else 'curation.json.bak'
        if name not in candidates:
            raise InvalidIntent()
        epoch = uuid.uuid4().hex
        slot = next(i for i, item in enumerate(catalog) if item[:3] == ('progress', project.name, name))
        projects.append(dict(name=project.name, epoch=epoch, source=slot,
                             sha256=_hash(migration_plan.progress(candidates[name], epoch=epoch))))
    header = format2.parse_store(inventory.headers.publications[0][1], allow_migrating=True)
    value = dict(version=1, nonce=uuid.uuid4().hex,
        root=dict(path_sha256=binding.path_sha256(), identity=binding.identity.document()),
        context=dict(device=header['device'], made=header['made'], release=header['release'],
                     started=header['migrating']['started']), sources=sources, projects=projects,
        header_sha256=_hash(inventory.headers.publications[0][1]))
    result = parse(_bytes(value), originals)
    _check(inventory)
    _check(binding)
    _check(owned)
    return result
