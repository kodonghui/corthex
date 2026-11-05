"""Cold metadata preservation only; no header/C2 effects or resume authority.

The original maintenance owner still proves the whole interval. File/directory
barriers assume documented OS/storage behavior, not arbitrary offline rollback.
Failed attempts preserve partial auxiliary data instead of guessing a rollback.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
import stat

from . import files, locks, maintenance_identity, migration_intent, migration_inventory


def _hash(raw):return hashlib.sha256(raw).hexdigest()


def _bytes(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode('ascii')


def _check(owned):
    if owned.check() is not None:raise TypeError('maintenance check must return None')


class _Guard:
    def __init__(self,owned,binding):
        self.owned,self.binding = owned,binding
        self.inventory = owned.inventory
        observer = self.inventory._observer
        self.fence,self.deadline = observer.fence,observer.deadline
        self.root = self.inventory.folder
        self.original_dirs = dict(observer.dirs)
        self.original_files,self.original_records = dict(observer.files),dict(observer.records)
        self.source_dirs = {name:maintenance_identity.bind(self.root/name) for name in self.original_dirs}
        self.source_records = {name:maintenance_identity.bind(self.root/name,entry='file') for name in self.original_records}
        self.root_names = set(self.original_dirs['.'][1])
        self.parents,self.nodes = {},{}
        self.revoked,self.cleanup_pending = False,False
        self.writer_check = self.cold

    def _node(self,path,binding,directory=False):
        info = self.fence.check(path)
        expected = stat.S_ISDIR if directory else stat.S_ISREG
        if info is None or not expected(info.st_mode) or not directory and info.st_nlink != 1:
            raise locks.LostLock()
        binding.check()
        return info

    def artifact_facts(self):
        """Callback-free final facts; this never checks or grants ownership."""
        if self.revoked or self.cleanup_pending:raise locks.LostLock()
        self.binding.check()
        for path,(binding,names) in self.parents.items():
            self._node(path,binding,directory=True)
            if {p.name for p in path.iterdir()} != names:raise locks.LostLock()
            self._node(path,binding,directory=True)
        for path,node in self.nodes.items():
            self._node(path,node['binding'])
            if self.fence.read(path,self.deadline) != node['data'][:node['written']]:
                raise locks.LostLock()
            self._node(path,node['binding'])

    def artifacts(self):
        """Original owner plus auxiliary artifacts only; no effect authority."""
        try:
            _check(self.owned);self.artifact_facts()
            _check(self.owned);self.binding.check()
        except BaseException:
            self.revoked = True
            raise

    def cold(self):
        """The original cold catalog remains unchanged except our auxiliary names."""
        try:
            self.artifacts()
            for relative,(identity,names) in self.original_dirs.items():
                path = self.root/relative;info = self.fence.check(path)
                if info is None or (info.st_dev,info.st_ino) != identity:raise locks.LostLock()
                self.source_dirs[relative].check()
                expected = self.root_names if relative == '.' else set(names)
                if {p.name for p in path.iterdir()} != expected:raise locks.LostLock()
            for relative,pin in self.original_files.items():
                info = self.fence.check(self.root/relative)
                if info is None or migration_inventory._stamp(info) != pin:raise locks.LostLock()
            for relative,raw in self.original_records.items():
                self.source_records[relative].check()
                if self.fence.read(self.root/relative,self.deadline) != raw:raise locks.LostLock()
            self.artifacts()
        except BaseException:
            self.revoked = True
            raise

    def directory_barrier(self,path):
        self.writer_check()
        if os.name == 'nt':
            # Windows file _commit also flushes associated file metadata. The
            # completed seal is not returned until all file barriers succeed.
            return
        binding = self.binding if path == self.root else self.parents[path][0]
        self._node(path,binding,directory=True)
        descriptor = os.open(str(path),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        failed = False
        try:
            opened,current = os.fstat(descriptor),self.fence.check(path)
            if current is None or (opened.st_dev,opened.st_ino) != (current.st_dev,current.st_ino):
                raise locks.LostLock()
            self.writer_check();files._sync(descriptor);self.writer_check()
        except BaseException:
            failed = True
            raise
        finally:
            try:os.close(descriptor)
            except OSError:
                self.cleanup_pending = True
                if not failed:raise

    def directory(self,path,*,new=False):
        self.cold()
        info = self.fence.check(path)
        if info is not None:
            if new or not stat.S_ISDIR(info.st_mode):raise locks.LostLock()
            binding = maintenance_identity.bind(path)
            self.parents[path] = binding,{p.name for p in path.iterdir()}
            self.cold();return
        os.mkdir(str(path),0o700)
        created = self.fence.check(path)
        if created is None or not stat.S_ISDIR(created.st_mode):raise locks.LostLock()
        if os.name != 'nt':os.chmod(str(path),0o700)
        current = self.fence.check(path)
        if current is None or (created.st_dev,created.st_ino) != (current.st_dev,current.st_ino):
            raise locks.LostLock()
        # Only a successful create is registered; a preexisting nonce is never adopted.
        binding = maintenance_identity.bind(path)
        self.parents[path] = binding,set()
        if path.parent == self.root:self.root_names.add(path.name)
        else:self.parents[path.parent][1].add(path.name)
        self.cold();self.directory_barrier(path.parent)

    def write(self,path,data):
        self.writer_check()
        if not isinstance(data,bytes) or path.parent not in self.parents or self.fence.check(path) is not None:
            raise locks.LostLock()
        flags = os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)
        descriptor = os.open(str(path),flags,0o600)
        failed = False
        try:
            opened,current = os.fstat(descriptor),self.fence.check(path)
            if (current is None or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
                    (opened.st_dev,opened.st_ino) != (current.st_dev,current.st_ino)):
                raise locks.LostLock()
            if os.name != 'nt':os.fchmod(descriptor,0o600)
            self.parents[path.parent][1].add(path.name)
            node = dict(binding=maintenance_identity.bind(path,entry='file'),data=data,written=0)
            self.nodes[path] = node
            for offset in range(0,len(data),65536):
                self.writer_check()
                current = os.fstat(descriptor)
                if (current.st_dev,current.st_ino) != (opened.st_dev,opened.st_ino) or current.st_nlink != 1:
                    raise locks.LostLock()
                chunk = data[offset:offset+65536]
                if os.write(descriptor,chunk) != len(chunk):raise OSError('short maintenance write')
                node['written'] += len(chunk)
                self.writer_check()
            self.writer_check();files._sync(descriptor);self.writer_check()
        except BaseException:
            failed = True
            self.revoked = True
            raise
        finally:
            try:os.close(descriptor)
            except OSError:
                self.cleanup_pending = True
                if not failed:raise
        self.writer_check();self.directory_barrier(path.parent)


@dataclass(frozen=True)
class Prepared:
    nonce: str
    seal_sha256: str
    _guard: object = field(repr=False,compare=False)

    def check(self):
        self._guard.cold()

    def check_artifacts(self):
        """Auxiliary evidence only; caller must verify its own publication prefix."""
        self._guard.artifacts()


def _match(owned,binding,intent):
    _check(owned);owned.inventory.check();binding.check()
    if owned.inventory.folder != binding.path or binding.identity.document()['entry'] != 'directory':
        raise migration_intent.InvalidIntent()
    parsed = migration_intent.parse(intent.encoded,intent.originals)
    value = json.loads(parsed.encoded)
    if value['root'] != dict(path_sha256=binding.path_sha256(),identity=binding.identity.document()):
        raise migration_intent.InvalidIntent()
    catalog = [('header',None,name,raw) for name,raw in owned.inventory.headers.originals]
    catalog += [('configuration',None,name,raw) for name,raw in owned.inventory.configuration]
    for project in owned.inventory.projects:
        if not project.exists:raise migration_intent.InvalidIntent()
        catalog += [('progress',project.name,name,raw) for name,raw in project.progress]
    catalog.sort(key=lambda item:(item[0],item[1] or '',item[2]))
    sources = [dict(family=f,project=p,name=n,sha256=_hash(raw)) for f,p,n,raw in catalog]
    if (sources != value['sources'] or tuple((i,raw) for i,(*_,raw) in enumerate(catalog)) != parsed.originals or
            parsed.headers != owned.inventory.headers):
        raise migration_intent.InvalidIntent()
    _check(owned);owned.inventory.check();binding.check()
    return parsed,value


def preserve(owned,intent,binding):
    """Preserve cold originals before any header fence; never resume or initialize.

    File failures keep partial auxiliary artifacts. No backup/temp recovery,
    deletion, replacement or cleanup of a foreign/preexisting nonce is attempted.
    """
    parsed,value = _match(owned,binding,intent)
    guard = _Guard(owned,binding)
    try:
        parent = binding.path/'.maintenance'
        guard.directory(parent)
        parent /= 'format-1-to-2';guard.directory(parent)
        folder = parent/value['nonce'];guard.directory(folder,new=True)
        for slot,raw in parsed.originals:guard.write(folder/('original-%06d.bin'%slot),raw)
        guard.write(folder/'plan.json',parsed.encoded)
        seal = dict(version=1,nonce=value['nonce'],plan_sha256=_hash(parsed.encoded),
            source_directories={name:native.identity.document() for name,native in guard.source_dirs.items()},
            source_records={name:native.identity.document() for name,native in guard.source_records.items()},
            directories={path.relative_to(binding.path).as_posix():native.identity.document()
                         for path,(native,_) in guard.parents.items()},
            files={path.name:dict(identity=node['binding'].identity.document(),sha256=_hash(node['data']))
                   for path,node in guard.nodes.items()})
        sealed = _bytes(seal);guard.write(folder/'prepared.json',sealed)
        guard.cold()
        return Prepared(value['nonce'],_hash(sealed),guard)
    except BaseException:
        guard.revoked = True
        raise
