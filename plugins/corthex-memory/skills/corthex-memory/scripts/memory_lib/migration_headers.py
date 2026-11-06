"""Cold-owner header effects only; no initialization, reopening or resume grant.

Exact stage IDs are durable before replacement. Every expected namespace/byte
prefix advances solely through this publisher's own verified effects. A failed
prefix is never rebased; original ownership and its deadline always govern.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
import uuid

from . import clock, locks, maintenance_identity, migration_intent, migration_inventory
from . import maintenance_journal as journal

_rename = os.replace
_checkpoint_rename = os.replace


def _hash(raw):return hashlib.sha256(raw).hexdigest()


class _Prefix:
    def __init__(self,prepared,intent):
        prepared.check()
        self.prepared,self.guard = prepared,prepared._guard
        self.root,self.fence = self.guard.root,self.guard.fence
        self.intent = migration_intent.parse(intent.encoded,intent.originals)
        value = json.loads(self.intent.encoded)
        self.folder = self.root/'.maintenance/format-1-to-2'/prepared.nonce
        if (value['nonce'] != prepared.nonce or
                self.guard.nodes[self.folder/'plan.json']['data'] != self.intent.encoded or
                _hash(self.guard.nodes[self.folder/'prepared.json']['data']) != prepared.seal_sha256):
            raise migration_intent.InvalidIntent()
        self.dirs = {name:set(names) for name,(_,names) in self.guard.original_dirs.items()}
        self.dirs['.'] = set(self.guard.root_names)
        self.files = {name:dict(stamp=pin,native=maintenance_identity.bind(self.root/name,entry='file'),
                               data=self.guard.original_records.get(name))
                      for name,pin in self.guard.original_files.items()}
        self.published,self.uncertain,self.revoked = [],None,False
        self.previous = prepared.seal_sha256
        self.check()

    def check(self):
        try:
            if self.revoked:raise locks.LostLock()
            self.prepared.check_artifacts()
            self.facts()
            self.prepared.check_artifacts()
            # A final owner callback cannot invalidate earlier facts unnoticed.
            self.guard.artifact_facts();self.facts()
            if clock.now() >= self.guard.deadline:raise locks.LockBusy()
        except BaseException:
            self.revoke()
            raise

    def revoke(self):
        self.revoked=self.guard.revoked=True
        self.guard.owned.inventory._observer.revoked=True

    def facts(self):
        for name,names in self.dirs.items():
            self.guard.source_dirs[name].check()
            if {p.name for p in (self.root/name).iterdir()} != names:raise locks.LostLock()
            self.guard.source_dirs[name].check()
        for name,node in self.files.items():
            node['native'].check()
            info = self.fence.check(self.root/name)
            if info is None or migration_inventory._stamp(info) != node['stamp']:
                raise locks.LostLock()
            if node['data'] is not None and self.fence.read(self.root/name,self.guard.deadline) != node['data']:
                raise locks.LostLock()
            node['native'].check()
            current=self.fence.check(self.root/name)
            if current is None or migration_inventory._stamp(current)!=node['stamp']:raise locks.LostLock()

    def _checkpoint(self,name,value):
        self.check()
        raw = journal._bytes(dict(version=1,nonce=self.prepared.nonce,previous=self.previous,**value))
        target = self.folder/name
        if self.fence.check(target) is not None:raise locks.LostLock()
        stage = self.folder/('checkpoint-'+uuid.uuid4().hex+'.tmp')
        self.guard.write(stage,raw)
        self.check()
        native = self.guard.nodes[stage]['binding'].identity
        _checkpoint_rename(str(stage),str(target))
        fresh = self._new_native(target,native,raw)
        del self.guard.nodes[stage]
        self.guard.parents[self.folder][1].remove(stage.name)
        self.guard.parents[self.folder][1].add(target.name)
        self.guard.nodes[target] = dict(binding=fresh['native'],data=raw,written=len(raw))
        self.check();self.guard.directory_barrier(self.folder)
        self.previous = _hash(raw)
        return self.previous

    def _new_native(self,path,expected,data):
        native = maintenance_identity.bind(path,entry='file')
        if native.identity != expected or self.fence.read(path,self.guard.deadline) != data:
            raise locks.LostLock()
        info = self.fence.check(path)
        if info is None or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise locks.LostLock()
        return dict(native=native,data=data,stamp=migration_inventory._stamp(info))

    def _advance_link(self,old):
        if old is None or old['stamp'][-1] == 1:return
        # Only the original named primary/backup pair may lose this one link.
        siblings = [(name,node) for name,node in self.files.items()
                    if node is not old and node['native'].identity == old['native'].identity]
        if old['stamp'][-1] != 2 or len(siblings) != 1:raise locks.LostLock()
        name,node = siblings[0]
        original = next((name for name,node in self.files.items() if node is old),None)
        primary = min(name,original) if original is not None else ''
        if ({name,original} != {primary,primary+'.bak'} or
                not (primary=='store.json' or primary.startswith('projects/') and primary.endswith('/curation.json'))):
            raise locks.LostLock()
        current = self.fence.check(self.root/name)
        if current is None:raise locks.LostLock()
        pin = migration_inventory._stamp(current);before = node['stamp']
        if pin[:4] != before[:4] or pin[5] != before[5] or pin[-1] != 1:
            raise locks.LostLock()
        node['native'].check()
        if self.fence.read(self.root/name,self.guard.deadline) != node['data']:raise locks.LostLock()
        node['stamp'] = pin

    def _replace(self,index,stage,target,data,*,record='header'):
        if record not in {'header','initialize','final-header'}:raise ValueError('invalid checkpoint family')
        self.check()
        staged = self.guard.nodes[stage]
        identity = staged['binding'].identity
        old = self.files.get(target)
        self.uncertain = target
        _rename(str(stage),str(self.root/target))
        # No callback may intervene between replacement and this exact adoption.
        fresh = self._new_native(self.root/target,identity,data)
        del self.guard.nodes[stage]
        self.guard.parents[stage.parent][1].remove(stage.name)
        self._advance_link(old)
        self.files[target] = fresh
        relative=PurePosixPath(target);parent=relative.parent.as_posix()
        self.dirs[parent].add(relative.name)
        self.published.append(target)
        self.check()
        self.guard.directory_barrier((self.root/target).parent,binding=self.guard.source_dirs[parent])
        self.guard.directory_barrier(stage.parent)
        self.uncertain = None
        self._checkpoint(record+'-%06d.done.json'%index,
                         dict(step=index,target=target,identity=identity.document(),sha256=_hash(data)))

    def _move_temp(self,index,name,*,record='header'):
        if record not in {'header','initialize'}:raise ValueError('invalid checkpoint family')
        self.check()
        old = self.files[name]
        target = self.folder/(record+'-original-%06d.bin'%index)
        if self.fence.check(target) is not None:raise locks.LostLock()
        self.uncertain = name
        _rename(str(self.root/name),str(target))
        fresh = self._new_native(target,old['native'].identity,old['data'])
        del self.files[name]
        relative=PurePosixPath(name);parent=relative.parent.as_posix()
        self.dirs[parent].remove(relative.name)
        self.guard.parents[self.folder][1].add(target.name)
        self.guard.nodes[target] = dict(binding=fresh['native'],data=old['data'],written=len(old['data']))
        self.published.append(name)
        self.check()
        self.guard.directory_barrier((self.root/name).parent,binding=self.guard.source_dirs[parent])
        self.guard.directory_barrier(self.folder)
        self.uncertain = None
        self._checkpoint(record+'-%06d.done.json'%index,
                         dict(step=index,temporary=name,identity=fresh['native'].identity.document(),sha256=_hash(old['data'])))

    def _directory(self,index,stage,target):
        self.check()
        if self.guard.parents[stage][1] or self.fence.check(self.root/target) is not None:raise locks.LostLock()
        identity=self.guard.parents[stage][0].identity
        self.uncertain=target;_rename(str(stage),str(self.root/target))
        native=maintenance_identity.bind(self.root/target)
        if native.identity!=identity or any((self.root/target).iterdir()):raise locks.LostLock()
        del self.guard.parents[stage];self.guard.parents[stage.parent][1].remove(stage.name)
        relative=PurePosixPath(target);parent=relative.parent.as_posix()
        self.dirs[parent].add(relative.name);self.dirs[target]=set()
        self.guard.source_dirs[target]=native
        self.published.append(target);self.check()
        self.guard.directory_barrier((self.root/target).parent,binding=self.guard.source_dirs[parent])
        self.guard.directory_barrier(self.root/target,binding=native)
        self.guard.directory_barrier(stage.parent);self.uncertain=None
        self._checkpoint('initialize-%06d.done.json'%index,dict(step=index,directory=target,identity=identity.document()))


@dataclass(frozen=True)
class Fenced:
    nonce: str
    checkpoint_sha256: str
    _prefix: object = field(repr=False,compare=False)

    def check(self):self._prefix.check()


def publish(prepared,intent):
    """Fence every C1 header recovery source before any C2 project publication.

    This accepts only the original cold live owner. A serialized checkpoint or
    a new lease cannot reopen it; a separate strict resume owner is required.
    """
    prefix = _Prefix(prepared,intent)
    guard = prefix.guard
    try:
        stages = []
        for index,(name,raw) in enumerate(prefix.intent.headers.publications):
            path = prefix.folder/('header-stage-%06d.bin'%index)
            guard.write(path,raw)
            stages.append((path,name,raw))
        effects = [dict(temporary=name,identity=prefix.files[name]['native'].identity.document(),
                        sha256=_hash(prefix.files[name]['data'])) for name in prefix.intent.headers.preserve_temps]
        effects += [dict(target=name,stage=path.name,identity=guard.nodes[path]['binding'].identity.document(),
                         sha256=_hash(raw),original=(prefix.files[name]['native'].identity.document() if name in prefix.files else None))
                    for path,name,raw in stages]
        # Immutable, durable native stage IDs precede the first rename.
        prefix._checkpoint('header-publications.json',dict(effects=effects,plan_sha256=_hash(prefix.intent.encoded)))
        guard.writer_check = prefix.check
        for index,name in enumerate(prefix.intent.headers.preserve_temps):prefix._move_temp(index,name)
        start = len(prefix.intent.headers.preserve_temps)
        for index,(path,name,raw) in enumerate(stages,start):prefix._replace(index,path,name,raw)
        prefix.check()
        for name,raw in prefix.intent.headers.publications:
            if prefix.files[name]['data'] != raw:raise locks.LostLock()
        final = prefix._checkpoint('headers-complete.json',dict(headers_complete=True,effects=len(effects)))
        return Fenced(prepared.nonce,final,prefix)
    except BaseException as error:
        prefix.revoked = guard.revoked = True
        # Preserve the caller's exact exception and expose only fixed path names.
        for name,value in [('migration_published',tuple(prefix.published)),('migration_uncertain',prefix.uncertain),
                           ('cleanup_pending',bool(guard.cleanup_pending or prefix.uncertain))]:
            try:setattr(error,name,value)
            except Exception:pass
        raise
