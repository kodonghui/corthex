"""Strict renewed-owner header resumption; no project initialization or repair.

Named migrating headers must carry pre-recorded native stage identities. A
journal, timestamp, fresh lease or valid-empty file alone grants no authority.
Completed stores are refused by maintenance admission, never reinitialized.
"""
import hashlib
import json
import re

from . import base, locks, maintenance_identity, maintenance_journal as journal
from . import migration_headers as headers, migration_intent, store


class InvalidResume(ValueError):
    def __init__(self):super().__init__('migration header resume unavailable')


def _hash(raw):return hashlib.sha256(raw).hexdigest()
def _keys(value,keys):migration_intent._keys(value,keys)
def _identity(value):return maintenance_identity.parse(journal._bytes(value))


class _Owner:
    def __init__(self,original):
        self.original,self.inventory,self.failure=original,original.inventory,None

    def check(self):
        try:return self.original.check()
        except BaseException as error:
            self.failure=error
            raise


class _Reader:
    def __init__(self,owned,nonce):
        if not isinstance(nonce,str) or re.fullmatch('[0-9a-f]{32}',nonce) is None:raise InvalidResume()
        self.owned,self.inventory = owned,owned.inventory
        self.root,self.fence = self.inventory.folder,self.inventory._observer.fence
        self.deadline = self.inventory._observer.deadline
        self.binding = maintenance_identity.bind(self.root)
        self.folder = self.root/'.maintenance/format-1-to-2'/nonce
        self.nonce,self.nodes = nonce,{}
        owned.check();self.inventory.check()

    def read(self,path,links=1):
        self.owned.check();self.binding.check()
        native = maintenance_identity.bind(path,entry='file')
        info = self.fence.check(path)
        if info is None or links is not None and info.st_nlink != links:raise InvalidResume()
        raw = self.fence.read(path,self.deadline)
        native.check();self.owned.check();self.binding.check()
        self.nodes[path] = dict(binding=native,data=raw,written=len(raw))
        return raw

    def document(self,path):
        raw = self.read(path);value = store.json_document(raw)
        if journal._bytes(value) != raw:raise InvalidResume()
        return value,raw

    def same(self,path,identity,raw):
        # The fresh strict inventory already verifies canonical primary/backup
        # link pairs. Auxiliary evidence always requires one link.
        if self.read(path,links=1 if path.parent==self.folder else None) != raw or self.nodes[path]['binding'].identity != _identity(identity):raise InvalidResume()

    def exists(self,path):
        self.owned.check();return self.fence.check(path) is not None

    def originals(self):
        plan,raw = self.document(self.folder/'plan.json')
        if not isinstance(plan,dict) or not isinstance(plan.get('sources'),list) or not 1<=len(plan['sources'])<=100000:
            raise InvalidResume()
        originals = tuple((i,self.read(self.folder/('original-%06d.bin'%i))) for i in range(len(plan['sources'])))
        intent = migration_intent.parse(raw,originals)
        if intent.encoded != raw or plan['nonce'] != self.nonce:raise InvalidResume()
        if plan['root'] != dict(path_sha256=self.binding.path_sha256(),identity=self.binding.identity.document()):raise InvalidResume()
        seal,sealed = self.document(self.folder/'prepared.json')
        _keys(seal,'version nonce plan_sha256 source_directories source_records directories files')
        if type(seal['version']) is not int or seal['version']!=1 or seal['nonce']!=self.nonce or seal['plan_sha256']!=_hash(raw):raise InvalidResume()
        expected = {'plan.json':raw}
        expected.update(('original-%06d.bin'%i,data) for i,data in originals)
        if not isinstance(seal['files'],dict) or set(seal['files']) != set(expected):raise InvalidResume()
        for name,data in expected.items():
            item=seal['files'][name];_keys(item,'identity sha256')
            if item['sha256']!=_hash(data) or self.nodes[self.folder/name]['binding'].identity!=_identity(item['identity']):raise InvalidResume()
        directories=self.inventory._observer.dirs
        if not isinstance(seal['source_directories'],dict) or set(seal['source_directories'])!=set(directories):raise InvalidResume()
        for name in directories:
            if maintenance_identity.capture(self.root/name)!=_identity(seal['source_directories'][name]):raise InvalidResume()
        parents=[self.root/'.maintenance',self.root/'.maintenance/format-1-to-2',self.folder]
        if not isinstance(seal['directories'],dict) or set(seal['directories'])!={p.relative_to(self.root).as_posix() for p in parents}:raise InvalidResume()
        for path in parents:
            if maintenance_identity.capture(path)!=_identity(seal['directories'][path.relative_to(self.root).as_posix()]):raise InvalidResume()
        sources={}
        for source,(_,data) in zip(plan['sources'],originals):
            name=source['name']
            if source['family']=='progress':name='projects/'+base.project_folder_name(source['project'])+'/'+name
            sources[name]=data
        if not isinstance(seal['source_records'],dict) or set(seal['source_records'])!=set(sources):raise InvalidResume()
        for name,data in sources.items():
            if not name.startswith('store.json'):self.same(self.root/name,seal['source_records'][name],data)
        current={name for name in self.inventory._observer.records if not name.startswith('store.json')}
        if current!={name for name in sources if not name.startswith('store.json')}:raise InvalidResume()
        if self.inventory.headers.publications != intent.headers.publications:raise InvalidResume()
        if not any(name in {'store.json','store.json.bak'} and 'migrating' in store.json_document(data)
                   for name,data in self.inventory.headers.originals):raise InvalidResume()
        return intent,seal,sources,_hash(sealed)

    def effects(self,intent,seal,sources,seal_hash):
        value,raw=self.document(self.folder/'header-publications.json')
        _keys(value,'version nonce previous effects plan_sha256')
        if type(value['version']) is not int or value['version']!=1 or value['nonce']!=self.nonce or value['previous']!=seal_hash or value['plan_sha256']!=_hash(intent.encoded):raise InvalidResume()
        temps=intent.headers.preserve_temps;expected=len(temps)+len(intent.headers.publications)
        if not isinstance(value['effects'],list) or len(value['effects'])!=expected:raise InvalidResume()
        operations=[];stage_ids=[]
        for index,effect in enumerate(value['effects']):
            if index<len(temps):
                name=temps[index];_keys(effect,'temporary identity sha256')
                if effect['temporary']!=name or effect['sha256']!=_hash(sources[name]) or effect['identity']!=seal['source_records'][name]:raise InvalidResume()
                operations.append((name,self.folder/('header-original-%06d.bin'%index),sources[name],effect['identity'],True))
            else:
                slot=index-len(temps);name,data=intent.headers.publications[slot]
                _keys(effect,'target stage identity sha256 original')
                if effect['target']!=name or effect['stage']!='header-stage-%06d.bin'%slot or effect['sha256']!=_hash(data) or effect['original']!=seal['source_records'].get(name):raise InvalidResume()
                identity=_identity(effect['identity']);stage_ids.append(identity)
                if identity in [_identity(v) for v in seal['source_records'].values()]:raise InvalidResume()
                operations.append((name,self.folder/effect['stage'],data,effect['identity'],False))
        if len(set(i.encoded for i in stage_ids))!=len(stage_ids):raise InvalidResume()
        published=0;gap=False;active=False
        for name,artifact,data,identity,temporary in operations:
            source,target=(self.root/name,artifact) if temporary else (artifact,self.root/name)
            done=self.exists(target) and maintenance_identity.capture(target,entry='file')==_identity(identity)
            if done:
                if gap or self.exists(source):raise InvalidResume()
                self.same(target,identity,data);published+=1
                if not temporary:active=True
            else:
                gap=True;self.same(source,identity,data)
                if not temporary:
                    if name in sources:self.same(target,seal['source_records'][name],sources[name])
                    elif self.exists(target):raise InvalidResume()
        if not active:raise InvalidResume()
        actual_names=set(dict(self.inventory.headers.originals));expected_names={n for n in sources if n.startswith('store.json')}
        for name,_,_,_,temporary in operations[:published]:
            if temporary:expected_names.remove(name)
            else:expected_names.add(name)
        if actual_names!=expected_names:raise InvalidResume()
        return operations,published,_hash(raw)

    def checkpoints(self,operations,published,previous):
        count=0;gap=False
        for index,(name,_,data,identity,temporary) in enumerate(operations):
            path=self.folder/('header-%06d.done.json'%index)
            if not self.exists(path):gap=True;continue
            if gap or index>=published:raise InvalidResume()
            value,raw=self.document(path)
            expected=dict(version=1,nonce=self.nonce,previous=previous,step=index,identity=identity,sha256=_hash(data))
            expected['temporary' if temporary else 'target']=name
            if raw!=journal._bytes(expected):raise InvalidResume()
            previous=_hash(raw);count+=1
        if published not in {count,count+1}:raise InvalidResume()
        complete=self.folder/'headers-complete.json';final=None
        if self.exists(complete):
            value,raw=self.document(complete)
            if count!=published or published!=len(operations) or raw!=journal._bytes(dict(version=1,nonce=self.nonce,previous=previous,headers_complete=True,effects=len(operations))):
                raise InvalidResume()
            final=_hash(raw)
        return count,previous,final

    def prefix(self,intent,seal_hash,operations,published,previous):
        guard=journal._Guard(self.owned,self.binding)
        for path in (self.root/'.maintenance',self.root/'.maintenance/format-1-to-2',self.folder):guard.directory(path)
        allowed={'plan.json','prepared.json','header-publications.json','headers-complete.json'}
        allowed.update('original-%06d.bin'%i for i in range(len(intent.originals)))
        allowed.update('header-%06d.done.json'%i for i in range(len(operations)))
        allowed.update(path.name for _,path,_,_,_ in operations)
        for path in self.folder.iterdir():
            if path.name not in allowed and re.fullmatch(r'checkpoint-[0-9a-f]{32}\.tmp',path.name) is None:raise InvalidResume()
            if path not in self.nodes:self.read(path)
        # Only auxiliary paths are admitted; canonical source pins stay in Prefix.
        guard.nodes={p:node for p,node in self.nodes.items() if p.parent==self.folder}
        prepared=journal.Prepared(self.nonce,seal_hash,guard)
        prefix=headers._Prefix.__new__(headers._Prefix)
        prefix.prepared,prefix.guard,prefix.intent=prepared,guard,intent
        prefix.root,prefix.fence,prefix.folder=self.root,self.fence,self.folder
        prefix.dirs={name:set(names) for name,(_,names) in guard.original_dirs.items()}
        prefix.dirs['.']=set(guard.root_names)
        prefix.files={name:dict(stamp=pin,native=maintenance_identity.bind(self.root/name,entry='file'),data=guard.original_records.get(name))
                      for name,pin in guard.original_files.items()}
        for name,node in prefix.files.items():
            observed=self.nodes.get(self.root/name)
            if observed is not None and node['native'].identity!=observed['binding'].identity:raise locks.LostLock()
        for path,node in self.nodes.items():
            node['binding'].check()
            if self.fence.read(path,self.deadline)!=node['data']:raise locks.LostLock()
            node['binding'].check()
        prefix.published=[name for name,_,_,_,_ in operations[:published]]
        prefix.previous,prefix.uncertain,prefix.revoked=previous,None,False
        guard.writer_check=prefix.check
        self.inventory.check();prefix.check()
        return prefix


def reopen(owned,nonce):
    """Finish only proven remaining header effects under a new original owner.

    No private serialized path is opened. This returns a header-only live scope;
    completed headers, initialization and privacy/history recovery are separate.
    """
    watched=_Owner(owned)
    try:
        reader=_Reader(watched,nonce)
        intent,seal,sources,sealed=reader.originals()
        operations,published,previous=reader.effects(intent,seal,sources,sealed)
        recorded,previous,final=reader.checkpoints(operations,published,previous)
        prefix=reader.prefix(intent,sealed,operations,published,previous)
        # A visible verified rename may have stopped before its old barriers.
        # Flush both directories before adding evidence or returning a fence.
        if published:
            prefix.guard.directory_barrier(prefix.root)
            prefix.guard.directory_barrier(prefix.folder)
            prefix.check()
        if final is not None:
            prefix.previous=final
            return headers.Fenced(nonce,final,prefix)
        for index in range(recorded,published):
            name,_,data,identity,temporary=operations[index]
            value=dict(step=index,identity=identity,sha256=_hash(data))
            value['temporary' if temporary else 'target']=name
            prefix._checkpoint('header-%06d.done.json'%index,value)
        for index in range(published,len(operations)):
            name,artifact,data,_,temporary=operations[index]
            if temporary:prefix._move_temp(index,name)
            else:prefix._replace(index,artifact,name,data)
        final=prefix._checkpoint('headers-complete.json',dict(headers_complete=True,effects=len(operations)))
        return headers.Fenced(nonce,final,prefix)
    except (locks.LostLock,locks.LockBusy):
        owned.inventory._observer.revoked=True
        raise
    except Exception as error:
        owned.inventory._observer.revoked=True
        if error is watched.failure:raise
        if isinstance(error,(ValueError,KeyError,TypeError,AttributeError,FileNotFoundError)):
            raise InvalidResume() from None
        raise
