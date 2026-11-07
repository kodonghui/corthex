"""Finalization-only header effects; never replay current project data.

Completion records bind fixed effects, not supported lineage or history access.
Both actual current-lineage and privacy coordinators remain mandatory.
"""
import hashlib
import json
import re
import stat
import uuid
from . import base, clock, format2, locks, maintenance_identity, maintenance_journal as journal
from . import migration_header_resume as header_resume, migration_headers as headers
from . import migration_initialize_resume as initialize_resume, migration_finalize as finalize
InvalidResume = header_resume.InvalidResume
_keys = header_resume._keys
_identity = header_resume._identity

def _hash(raw):
    return hashlib.sha256(raw).hexdigest()

class _Reader(initialize_resume._Reader):

    def initialized(self, intent, seal, sources, sealed):
        header_ops, manifest = self.operations(intent, seal, sources, sealed)
        count, _, header_final = header_resume._Reader.checkpoints(self, header_ops, len(header_ops), manifest)
        if count != len(header_ops) or header_final is None:
            raise InvalidResume()
        init_ops, init_manifest = self.manifest(intent, seal, sources, header_final)
        count, previous = initialize_resume._Reader.checkpoints(self, init_ops, len(init_ops), init_manifest)
        if count != len(init_ops):
            raise InvalidResume()
        for _, path, data, identity, temporary in header_ops:
            if temporary:
                self.same(path, identity, data)
            elif self.exists(path):
                raise InvalidResume()
        for kind, _, path, data, identity in init_ops:
            if kind == 'temporary':
                self.same(path, identity, data)
            elif self.exists(path):
                raise InvalidResume()
        _, raw = self.document(self.folder / 'initialization-complete.json')
        plan = json.loads(intent.encoded)
        projects = [dict(name=name, identity=seal['source_directories']['projects/' + base.project_folder_name(name)], epoch=format2.parse_curation(data)['fence']['epoch']) for name, data in intent.progress]
        expected = dict(version=1, nonce=self.nonce, previous=previous, initialized=True, writer_protocol=1, lifecycle_protocol=1, publications_sha256=init_manifest, root=plan['root'], context=plan['context'], projects=projects)
        if raw != journal._bytes(expected):
            raise InvalidResume()
        return (header_ops, init_ops, _hash(raw))

    def final_effects(self, intent, header_ops, initialized):
        value, raw = self.document(self.folder / 'final-header-publications.json')
        _keys(value, 'version nonce previous effects plan_sha256 initialization_sha256')
        if (type(value['version']) is not int or value['version'] != 1 or value['nonce'] != self.nonce
                or value['previous'] != initialized or value['initialization_sha256'] != initialized
                or value['plan_sha256'] != _hash(intent.encoded)
                or not isinstance(value['effects'], list) or len(value['effects']) != 2):
            raise InvalidResume()
        original = {name: identity for name, _, _, identity, temporary in header_ops if not temporary}
        operations = []
        native = []
        for index, ((name, migrating), effect) in enumerate(zip(intent.headers.publications, value['effects'])):
            _keys(effect, 'target stage identity original sha256')
            completed = format2.parse_store(migrating, allow_migrating=True)
            completed.pop('migrating')
            data = format2.store_bytes(completed)
            stage = self.folder / ('final-header-stage-%06d.bin' % index)
            if effect['target'] != name or effect['stage'] != stage.name or effect['original'] != original[name] or (effect['sha256'] != _hash(data)):
                raise InvalidResume()
            identity = _identity(effect['identity'])
            native.append(identity)
            if identity.document()['entry'] != 'file' or identity in [_identity(v) for v in original.values()]:
                raise InvalidResume()
            operations.append((name, stage, data, effect['identity'], migrating, effect['original']))
        if len(set((item.encoded for item in native))) != 2:
            raise InvalidResume()
        if set(dict(self.inventory.headers.originals)) != {'store.json', 'store.json.bak'}:
            raise InvalidResume()
        published = 0
        gap = False
        for name, stage, data, identity, migrating, original in operations:
            path = self.root / name
            done = self.exists(path) and maintenance_identity.capture(path, entry='file') == _identity(identity)
            if done:
                if gap or self.exists(stage):
                    raise InvalidResume()
                self.same(path, identity, data)
                published += 1
            else:
                gap = True
                self.same(path, original, migrating)
                self.same(stage, identity, data)
        if published and getattr(self.owned.original, 'mode', None) != 'finalization-only':
            raise InvalidResume()
        if not published and getattr(self.owned.original, 'mode', None) != 'migration':
            raise InvalidResume()
        return (operations, published, _hash(raw))

    def final_checkpoints(self, operations, published, previous, initialized, intent):
        count = 0
        gap = False
        for index, (name, _, data, identity, _, _) in enumerate(operations):
            path = self.folder / ('final-header-%06d.done.json' % index)
            if not self.exists(path):
                gap = True
                continue
            if gap or index >= published:
                raise InvalidResume()
            _, raw = self.document(path)
            expected = dict(version=1, nonce=self.nonce, previous=previous, step=index, target=name, identity=identity, sha256=_hash(data))
            if raw != journal._bytes(expected):
                raise InvalidResume()
            previous = _hash(raw)
            count += 1
        if published not in {count, count + 1}:
            raise InvalidResume()
        final = None
        if self.exists(self.folder / 'migration-complete.json'):
            _, raw = self.document(self.folder / 'migration-complete.json')
            expected = dict(version=1, nonce=self.nonce, previous=previous, **_complete(initialized, intent))
            if count != 2 or published != 2 or raw != journal._bytes(expected):
                raise InvalidResume()
            final = _hash(raw)
        return (count, previous, final)

    def current_prefix(self, intent, sealed, header_ops, init_ops, published, previous):
        guard = journal._Guard(self.owned, self.binding)
        for path in (self.root / '.maintenance', self.root / '.maintenance/format-1-to-2', self.folder):
            guard.directory(path)
        self.verify_auxiliary_directories(guard)
        allowed = {'plan.json', 'prepared.json', 'header-publications.json', 'headers-complete.json', 'initialization-publications.json', 'initialization-complete.json', 'final-header-publications.json', 'migration-complete.json'}
        allowed.update(('original-%06d.bin' % i for i in range(len(intent.originals))))
        allowed.update(('header-%06d.done.json' % i for i in range(len(header_ops))))
        allowed.update((path.name for _, path, _, _, _ in header_ops))
        allowed.update(('initialize-%06d.done.json' % i for i in range(len(init_ops))))
        allowed.update((path.name for _, _, path, _, _ in init_ops))
        allowed.update(('final-header-stage-%06d.bin' % i for i in range(2)))
        allowed.update(('final-header-%06d.done.json' % i for i in range(2)))
        for path in self.folder.iterdir():
            staged = re.fullmatch('initialize-[0-9a-f]{32}-[0-9]{6}', path.name) is not None
            orphan = re.fullmatch('final-header-orphan-[0-9a-f]{32}-[01]\\.bin', path.name) is not None
            if path.name not in allowed and (not staged) and (not orphan) and (re.fullmatch('checkpoint-[0-9a-f]{32}\\.tmp', path.name) is None):
                raise InvalidResume()
            info = self.fence.check(path)
            if info is None:
                raise locks.LostLock()
            if stat.S_ISDIR(info.st_mode):
                if not staged:
                    raise InvalidResume()
                self.directory(path, empty=True)
                guard.directory(path)
            elif path not in self.nodes:
                self.read(path)
        guard.nodes = {path: node for path, node in self.nodes.items() if path.parent == self.folder}
        prefix = headers._Prefix.__new__(headers._Prefix)
        prefix.prepared, prefix.guard, prefix.intent = (journal.Prepared(self.nonce, sealed, guard), guard, intent)
        prefix.root, prefix.fence, prefix.folder = (self.root, self.fence, self.folder)
        prefix.dirs = {name: set(names) for name, (_, names) in guard.original_dirs.items()}
        prefix.files = {name: dict(stamp=pin, native=maintenance_identity.bind(self.root / name, entry='file'), data=guard.original_records.get(name)) for name, pin in guard.original_files.items()}
        for name, node in prefix.files.items():
            original = self.nodes.get(self.root / name)
            if original is not None and node['native'].identity != original['binding'].identity:
                raise locks.LostLock()
        for path, node in self.nodes.items():
            node['binding'].check()
            if self.fence.read(path, self.deadline) != node['data']:
                raise locks.LostLock()
            node['binding'].check()
        for path, (native, names) in self.directory_nodes.items():
            native.check()
            if {p.name for p in path.iterdir()} != names:
                raise locks.LostLock()
            native.check()
        prefix.published = [name for name, _, _, _, _, _ in published]
        prefix.previous, prefix.uncertain, prefix.revoked = (previous, None, False)
        guard.writer_check = prefix.check
        self.inventory.check()
        prefix.check()
        return prefix

    def handoff(self, prefix):
        self.verify_auxiliary_directories(prefix.guard)
        for path, node in self.nodes.items():
            node['binding'].check()
            if self.fence.read(path, self.deadline) != node['data']:
                raise locks.LostLock()
            current = prefix.guard.nodes.get(path) if path.parent == self.folder else prefix.files.get(path.relative_to(self.root).as_posix())
            if current is None:
                raise locks.LostLock()
            binding = current['binding'] if path.parent == self.folder else current['native']
            if binding.identity != node['binding'].identity or current['data'] != node['data']:
                raise locks.LostLock()
            node['binding'].check()
            binding.check()
        prefix.check()

def _complete(initialized, intent):
    return dict(completed=True, initialization_sha256=initialized, writer_protocol=1, lifecycle_protocol=1, effects=2, plan_sha256=_hash(intent.encoded))

def _bind(prefix, lineage, privacy):
    guard = prefix.guard
    context = json.loads(prefix.intent.encoded)['context']
    projects = tuple(sorted({name for name, _ in prefix.intent.progress} | {p.name for p in guard.owned.inventory.projects}))

    def check():
        try:
            if prefix.revoked:
                raise locks.LostLock()
            journal._check(guard.owned)
            guard.binding.check()
            lineage(prefix.root, dict(context), projects)
            privacy(prefix.root, dict(context), projects)
            journal._check(guard.owned)
            guard.artifact_facts()
            prefix.facts()
            guard.binding.check()
            if clock.now() >= guard.deadline:
                raise locks.LockBusy()
        except BaseException:
            prefix.revoke()
            raise
    prefix.check = check
    guard.writer_check = check
    check()
    return check

def _preserve_unpublished(initialized):
    prefix = initialized._prefix
    guard = prefix.guard
    for index in range(2):
        source = prefix.folder / ('final-header-stage-%06d.bin' % index)
        if source not in guard.nodes:
            continue
        prefix.check()
        node = guard.nodes[source]
        target = prefix.folder / ('final-header-orphan-' + uuid.uuid4().hex + '-' + str(index) + '.bin')
        if prefix.fence.check(target) is not None:
            raise locks.LostLock()
        headers._checkpoint_rename(str(source), str(target))
        fresh = prefix._new_native(target, node['binding'].identity, node['data'])
        del guard.nodes[source]
        guard.parents[prefix.folder][1].remove(source.name)
        guard.parents[prefix.folder][1].add(target.name)
        guard.nodes[target] = dict(binding=fresh['native'], data=node['data'], written=len(node['data']))
        prefix.check()
        guard.directory_barrier(prefix.folder)

def reopen(owned, nonce, *, verify_supported_lineage, verify_current_privacy):
    """Finish only verified final headers, never current project publications.

    The actual coordinator must verify supported current C1/C2 non-deletion
    lineage and current privacy facts across the interval. Callbacks take root,
    immutable original context and the complete original/current project union.
    They return only None; receipts never replace those authorities.
    """
    if not callable(verify_supported_lineage) or not callable(verify_current_privacy):
        raise TypeError('original supported lineage and privacy checks required')
    watched = header_resume._Owner(owned)
    prefix = None
    failure = [None]

    def tracked(function, label):

        def call(*args):
            try:
                value = function(*args)
                if value is not None:
                    raise TypeError(label + ' check must return only None')
                return value
            except BaseException as error:
                failure[0] = error
                raise
        return call
    lineage = tracked(verify_supported_lineage, 'supported lineage')
    privacy = tracked(verify_current_privacy, 'current privacy')
    try:
        reader = _Reader(watched, nonce)
        intent, seal, sources, sealed = reader.archive()
        header_ops, init_ops, initialized = reader.initialized(intent, seal, sources, sealed)
        if not reader.exists(reader.folder / 'final-header-publications.json'):
            if owned.mode != 'migration' or reader.exists(reader.folder / 'migration-complete.json'):
                raise InvalidResume()
            value = initialize_resume.reopen(owned, nonce, verify_c1_lineage=lineage)
            prefix = value._prefix
            reader.handoff(prefix)
            _bind(prefix, lineage, privacy)
            _preserve_unpublished(value)
            return finalize.publish(value, verify_c1_lineage=lineage, verify_current_privacy=privacy)
        operations, published, manifest = reader.final_effects(intent, header_ops, initialized)
        recorded, previous, final = reader.final_checkpoints(operations, published, manifest, initialized, intent)
        if published:
            prefix = reader.current_prefix(intent, sealed, header_ops, init_ops, operations[:published], previous)
        else:
            value = initialize_resume.reopen(owned, nonce, verify_c1_lineage=lineage)
            if value.checkpoint_sha256 != initialized:
                raise InvalidResume()
            prefix = value._prefix
            reader.handoff(prefix)
            prefix.previous = previous
        check = _bind(prefix, lineage, privacy)
        # A visible header rename may still be missing its directory barriers.
        prefix.guard.directory_barrier(prefix.root, binding=prefix.guard.source_dirs['.'])
        prefix.guard.directory_barrier(prefix.folder)
        check()
        if final is not None:
            prefix.previous = final
            return finalize.Finalized(nonce, final, prefix)
        for index in range(recorded, published):
            name, _, data, identity, _, _ = operations[index]
            prefix._checkpoint('final-header-%06d.done.json' % index, dict(step=index, target=name, identity=identity, sha256=_hash(data)))
        for index in range(published, len(operations)):
            name, stage, data, _, _, _ = operations[index]
            prefix._replace(index, stage, name, data, record='final-header')
        check()
        final = prefix._checkpoint('migration-complete.json', _complete(initialized, intent))
        return finalize.Finalized(nonce, final, prefix)
    except BaseException as error:
        owned.inventory._observer.revoked = True
        if prefix is not None:
            prefix.revoke()
            for name, value in [('migration_published', tuple(prefix.published)), ('migration_uncertain', prefix.uncertain), ('cleanup_pending', bool(prefix.guard.cleanup_pending or prefix.uncertain))]:
                try:
                    setattr(error, name, value)
                except Exception:
                    pass
        if error is watched.failure or error is failure[0]:
            raise
        if isinstance(error, (ValueError, KeyError, TypeError, AttributeError, FileNotFoundError)):
            raise InvalidResume() from None
        raise
