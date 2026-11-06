"""Renewed original ownership for fixed initialization effects, never repair.

Decode private evidence, independently verify the actual prefix, then bind the
real lineage coordinator. No recorded phase, new lease or empty file grants it.
Completed headers never enter this path; published rounds are never replaced.
"""
import hashlib
import json
from pathlib import PurePosixPath
import re
import stat

from . import base, locks, maintenance_identity, maintenance_journal as journal
from . import migration_header_resume as header_resume, migration_headers as headers
from . import migration_initialize as initialize

InvalidResume=header_resume.InvalidResume
_identity=header_resume._identity
_keys=header_resume._keys
def _hash(raw):return hashlib.sha256(raw).hexdigest()


class _Reader(header_resume._Reader):
    def __init__(self,*args):
        super().__init__(*args);self.directory_nodes={}

    def directory(self,path,identity=None,empty=False):
        self.owned.check();self.binding.check();self.fence.check(path)
        native=maintenance_identity.bind(path)
        if identity is not None and native.identity!=_identity(identity):raise InvalidResume()
        names={p.name for p in path.iterdir()};native.check();self.fence.check(path)
        if empty and names:raise InvalidResume()
        original=self.directory_nodes.get(path)
        if original is not None and (original[0].identity!=native.identity or original[1]!=names):raise locks.LostLock()
        self.directory_nodes.setdefault(path,(native,names))
        return native,names

    def manifest(self,intent,seal,sources,previous):
        value,raw=self.document(self.folder/'initialization-publications.json')
        _keys(value,'version nonce previous round effects plan_sha256')
        round_id=value['round']
        if (type(value['version']) is not int or value['version']!=1 or value['nonce']!=self.nonce or
                value['previous']!=previous or value['plan_sha256']!=_hash(intent.encoded) or
                not isinstance(round_id,str) or re.fullmatch('[0-9a-f]{32}',round_id) is None):raise InvalidResume()
        recipes=initialize.recipes(intent,seal['source_directories'])
        if not isinstance(value['effects'],list) or len(value['effects'])!=len(recipes):raise InvalidResume()
        operations=[];identities=[]
        # Named C1 headers were replaced before these stages were allocated.
        # Their dead node IDs may legitimately be reused; reserve live headers.
        reserved=[_identity(v) for name,v in seal['source_records'].items() if name not in {'store.json','store.json.bak'}]
        header_record=json.loads(self.nodes[self.folder/'header-publications.json']['data'])
        reserved += [_identity(effect['identity']) for effect in header_record['effects'] if 'target' in effect]
        reserved += [_identity(v) for v in seal['source_directories'].values()]
        reserved += [_identity(v['identity']) for v in seal['files'].values()]
        for index,((kind,target,data),effect) in enumerate(zip(recipes,value['effects'])):
            stage=self.folder/('initialize-'+round_id+'-%06d'%index)
            if kind=='temporary':
                _keys(effect,'temporary identity sha256');data=sources[target]
                if effect['temporary']!=target or effect['identity']!=seal['source_records'][target] or effect['sha256']!=_hash(data):raise InvalidResume()
                stage=self.folder/('initialize-original-%06d.bin'%index)
            else:
                keys='directory stage identity' if kind=='directory' else 'target stage identity sha256 original'
                _keys(effect,keys)
                if effect['directory' if kind=='directory' else 'target']!=target or effect['stage']!=stage.name:raise InvalidResume()
                identity=_identity(effect['identity']);identities.append(identity)
                if identity in reserved or identity.document()['entry']!=('directory' if kind=='directory' else 'file'):raise InvalidResume()
                if kind=='file' and (effect['sha256']!=_hash(data) or effect['original']!=seal['source_records'].get(target)):raise InvalidResume()
            operations.append((kind,target,stage,data,effect['identity']))
        if len({v.encoded for v in identities})!=len(identities):raise InvalidResume()
        return operations,_hash(raw)

    def effect_prefix(self,operations,seal,sources):
        published=0;gap=False
        for kind,target,stage,data,identity in operations:
            source,destination=(self.root/target,stage) if kind=='temporary' else (stage,self.root/target)
            entry='directory' if kind=='directory' else 'file'
            done=self.exists(destination) and maintenance_identity.capture(destination,entry=entry)==_identity(identity)
            if done:
                if gap or self.exists(source):raise InvalidResume()
                if kind=='directory':self.directory(destination,identity)
                else:self.same(destination,identity,data)
                published+=1
            else:
                gap=True
                if kind=='directory':
                    self.directory(source,identity,empty=True)
                    if self.exists(destination):raise InvalidResume()
                else:
                    self.same(source,identity,data)
                    if kind=='file':
                        if target in sources:self.same(destination,seal['source_records'][target],sources[target])
                        elif self.exists(destination):raise InvalidResume()
        return published

    def namespace(self,intent,seal,sources,operations,published):
        done=operations[:published];original=set(seal['source_directories'])
        added={target:identity for kind,target,_,_,identity in done if kind=='directory'}
        actual=self.inventory._observer.dirs
        if set(actual)!=original|set(added):raise InvalidResume()
        for name in original:self.directory(self.root/name,seal['source_directories'][name])
        for name,identity in added.items():self.directory(self.root/name,identity)
        targets={target for kind,target,_,_,_ in operations if kind!='directory'}
        for name,data in sources.items():
            if not name.startswith('store.json') and name not in targets:self.same(self.root/name,seal['source_records'][name],data)
        metadata={name for name in sources if not name.startswith('store.json')}
        for kind,target,_,_,_ in done:
            if kind=='temporary':metadata.remove(target)
            elif kind=='file' and PurePosixPath(target).name in {'curation.json','curation.json.bak'}:metadata.add(target)
        current={name for name in self.inventory._observer.records if not name.startswith('store.json')}
        if current!=metadata:raise InvalidResume()
        for project,_ in intent.progress:
            root='projects/'+base.project_folder_name(project)
            for relative in ('layer','layer/items','layer/tombstones','runs','notices'):
                name=root+'/'+relative
                if name not in actual:continue
                if relative=='notices' and name in original:continue
                expected={PurePosixPath(n).name for n in original if PurePosixPath(n).parent.as_posix()==name}
                expected.update(PurePosixPath(target).name for _,target,_,_,_ in done if PurePosixPath(target).parent.as_posix()==name)
                if set(actual[name][1])!=expected:raise InvalidResume()
            for name in self.inventory._observer.files:
                exclusive=(name.startswith((root+'/layer/',root+'/runs/',root+'/state-history.jsonl',root+'/notices/conflict-')))
                if exclusive and name not in targets:raise InvalidResume()

    def checkpoints(self,operations,published,previous):
        count=0;gap=False
        for index,(kind,target,_,data,identity) in enumerate(operations):
            path=self.folder/('initialize-%06d.done.json'%index)
            if not self.exists(path):gap=True;continue
            if gap or index>=published:raise InvalidResume()
            _,raw=self.document(path)
            value=dict(version=1,nonce=self.nonce,previous=previous,step=index,identity=identity)
            value[{'directory':'directory','temporary':'temporary','file':'target'}[kind]]=target
            if kind!='directory':value['sha256']=_hash(data)
            if raw!=journal._bytes(value):raise InvalidResume()
            count+=1;previous=_hash(raw)
        if published not in {count,count+1}:raise InvalidResume()
        return count,previous

    def prefix(self,intent,sealed,header_ops,operations,published,previous):
        guard=journal._Guard(self.owned,self.binding)
        for path in (self.root/'.maintenance',self.root/'.maintenance/format-1-to-2',self.folder):guard.directory(path)
        self.verify_auxiliary_directories(guard)
        allowed={'plan.json','prepared.json','header-publications.json','headers-complete.json',
                 'initialization-publications.json','initialization-complete.json'}
        allowed.update('original-%06d.bin'%i for i in range(len(intent.originals)))
        allowed.update('header-%06d.done.json'%i for i in range(len(header_ops)))
        allowed.update(path.name for _,path,_,_,_ in header_ops)
        allowed.update('initialize-%06d.done.json'%i for i in range(len(operations)))
        allowed.update(path.name for _,_,path,_,_ in operations)
        for path in self.folder.iterdir():
            staged=re.fullmatch('initialize-[0-9a-f]{32}-[0-9]{6}',path.name) is not None
            if path.name not in allowed and not staged and re.fullmatch(r'checkpoint-[0-9a-f]{32}\.tmp',path.name) is None:raise InvalidResume()
            info=self.fence.check(path)
            if info is None:raise locks.LostLock()
            if stat.S_ISDIR(info.st_mode):
                if not staged:raise InvalidResume()
                self.directory(path,empty=True);guard.directory(path)
                if guard.parents[path][0].identity!=self.directory_nodes[path][0].identity:raise locks.LostLock()
            elif path not in self.nodes:self.read(path)
        guard.nodes={path:node for path,node in self.nodes.items() if path.parent==self.folder}
        prepared=journal.Prepared(self.nonce,sealed,guard)
        prefix=headers._Prefix.__new__(headers._Prefix)
        prefix.prepared,prefix.guard,prefix.intent=prepared,guard,intent
        prefix.root,prefix.fence,prefix.folder=self.root,self.fence,self.folder
        prefix.dirs={name:set(names) for name,(_,names) in guard.original_dirs.items()};prefix.dirs['.']=set(guard.root_names)
        prefix.files={name:dict(stamp=pin,native=maintenance_identity.bind(self.root/name,entry='file'),
            data=(self.nodes[self.root/name]['data'] if self.root/name in self.nodes else guard.original_records.get(name)))
            for name,pin in guard.original_files.items()}
        for name,native in guard.source_dirs.items():
            observed=self.directory_nodes.get(self.root/name)
            if observed is not None and native.identity!=observed[0].identity:raise locks.LostLock()
        for name,node in prefix.files.items():
            observed=self.nodes.get(self.root/name)
            if observed is not None and node['native'].identity!=observed['binding'].identity:raise locks.LostLock()
        for path,node in self.nodes.items():
            node['binding'].check()
            if self.fence.read(path,self.deadline)!=node['data']:raise locks.LostLock()
            node['binding'].check()
        for path,(native,names) in self.directory_nodes.items():
            native.check()
            if {p.name for p in path.iterdir()}!=names:raise locks.LostLock()
            native.check()
        prefix.published=[name for name,_,_,_,_ in header_ops]+[target for _,target,_,_,_ in operations[:published]]
        prefix.previous,prefix.uncertain,prefix.revoked=previous,None,False
        guard.writer_check=prefix.check;self.inventory.check();prefix.check()
        return prefix


def _flush_verified(prefix,operations,published):
    # A rename may be visible while its original directory barriers were lost.
    # Flush every verified effect before manufacturing any missing evidence.
    canonical={prefix.root}
    for kind,target,_,_,_ in operations[:published]:
        path=prefix.root/target;canonical.add(path.parent)
        if kind=='directory':canonical.add(path)
    for path in sorted(canonical,key=lambda value:(len(value.parts),str(value))):
        name=path.relative_to(prefix.root).as_posix()
        prefix.guard.directory_barrier(path,binding=prefix.guard.source_dirs[name])
    prefix.guard.directory_barrier(prefix.folder)
    prefix.check()


def reopen(owned,nonce,*,verify_c1_lineage):
    """Resume the original round, or preserve an entirely unpublished orphan.

    Actual original coordinator gates remain mandatory; this never clears a
    header marker, restores a sidecar or rewrites unknown current data.
    """
    if not callable(verify_c1_lineage):raise TypeError('original supported C1 lineage check required')
    watched=header_resume._Owner(owned);lineage_failure=[None];prefix=None
    def lineage(*args):
        try:
            value=verify_c1_lineage(*args)
            if value is not None:raise TypeError('C1 lineage check must return only None')
        except BaseException as error:lineage_failure[0]=error;raise
    try:
        reader=_Reader(watched,nonce)
        intent,seal,sources,sealed=reader.archive()
        if reader.inventory.headers.publications!=intent.headers.publications:raise InvalidResume()
        header_ops,header_published,previous=reader.effects(intent,seal,sources,sealed)
        header_count,_,header_final=header_resume._Reader.checkpoints(reader,header_ops,header_published,previous)
        if header_count!=len(header_ops) or header_published!=header_count or header_final is None:raise InvalidResume()
        manifest_path=reader.folder/'initialization-publications.json'
        if not reader.exists(manifest_path):
            if reader.exists(reader.folder/'initialization-complete.json'):raise InvalidResume()
            reader.namespace(intent,seal,sources,(),0)
            prefix=reader.prefix(intent,sealed,header_ops,(),0,header_final)
            _flush_verified(prefix,(),0)
            return initialize.publish(headers.Fenced(nonce,header_final,prefix),verify_c1_lineage=lineage)
        operations,manifest=reader.manifest(intent,seal,sources,header_final)
        published=reader.effect_prefix(operations,seal,sources)
        reader.namespace(intent,seal,sources,operations,published)
        recorded,previous=reader.checkpoints(operations,published,manifest)
        prefix=reader.prefix(intent,sealed,header_ops,operations,published,previous)
        check=initialize.bind_lineage(prefix,lineage)
        _flush_verified(prefix,operations,published)
        complete=reader.folder/'initialization-complete.json'
        if reader.exists(complete):
            _,raw=reader.document(complete)
            expected=dict(version=1,nonce=nonce,previous=previous,**initialize.complete_value(prefix,manifest))
            if recorded!=published or published!=len(operations) or raw!=journal._bytes(expected):raise InvalidResume()
            prefix.previous=_hash(raw);check()
            return initialize.Initialized(nonce,prefix.previous,prefix)
        for index in range(recorded,published):
            kind,target,_,data,identity=operations[index]
            value=dict(step=index,identity=identity)
            value[{'directory':'directory','temporary':'temporary','file':'target'}[kind]]=target
            if kind!='directory':value['sha256']=_hash(data)
            prefix._checkpoint('initialize-%06d.done.json'%index,value)
        for index in range(published,len(operations)):
            kind,target,stage,data,_=operations[index]
            if kind=='directory':prefix._directory(index,stage,target)
            elif kind=='temporary':prefix._move_temp(index,target,record='initialize')
            else:prefix._replace(index,stage,target,data,record='initialize')
        check();final=prefix._checkpoint('initialization-complete.json',initialize.complete_value(prefix,manifest))
        return initialize.Initialized(nonce,final,prefix)
    except BaseException as error:
        owned.inventory._observer.revoked=True
        if prefix is not None:prefix.revoked=prefix.guard.revoked=True
        if error is watched.failure or error is lineage_failure[0]:raise
        if isinstance(error,(ValueError,KeyError,TypeError,AttributeError,FileNotFoundError)):
            raise InvalidResume() from None
        raise
