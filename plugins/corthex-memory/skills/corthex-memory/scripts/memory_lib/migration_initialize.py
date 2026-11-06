"""Migration-owned initial C2 bytes; never infer lineage from valid-empty files.

A real coordinator supplies original supported-C1-lineage verification. This
port preserves partial effects, keeps migrating and grants no history repair or
production activation. Completed headers always defer to their separate owner.
"""
from dataclasses import dataclass, field
import hashlib
import json
import uuid

from . import base, clock, format2, item_types, locks, state_types
from . import maintenance_journal as journal


class InvalidInitialization(ValueError):
    def __init__(self):super().__init__('migration initialization unavailable')


def _hash(raw):return hashlib.sha256(raw).hexdigest()


def _recipes(prefix):
    """Code-owned paths/proposals; no serialized destination is opened."""
    operations=[]
    for project,progress in prefix.intent.progress:
        root='projects/'+base.project_folder_name(project)
        if root not in prefix.dirs or root+'/raw' not in prefix.dirs:raise InvalidInitialization()
        blocked=(root+'/layer/',root+'/runs/')
        if any(name.startswith(blocked) or name.startswith(root+'/state-history.jsonl') or
               name.startswith(root+'/notices/conflict-') for name in prefix.files):raise InvalidInitialization()
        for name in ('layer/items','layer/tombstones','runs'):
            if prefix.dirs.get(root+'/'+name):raise InvalidInitialization()
        for name in ('layer','layer/items','layer/tombstones','notices','runs'):
            path=root+'/'+name
            if path not in prefix.dirs:operations.append(('directory',path,None))
        sources=[source for source in json.loads(prefix.intent.encoded)['sources']
                 if source['family']=='progress' and source['project']==project]
        for source in sources:
            name=source['name']
            if name not in {'curation.json','curation.json.bak'}:operations.append(('temporary',root+'/'+name,None))
        operations += [('file',root+'/'+name,progress) for name in ('curation.json.bak','curation.json')]
        records=[('layer/state.json',state_types.state_bytes({'lines':[]})),
                 ('layer/state-removed.json',state_types.removed_bytes({'removed':[]})),
                 ('layer/pins.json',item_types.pins_bytes({'pins':[]})),
                 ('layer/item-list.txt',item_types.item_list_bytes([])),
                 ('state-history.jsonl',b''),('layer/conflicts.json',journal._bytes({'candidates':[]}))]
        for name,raw in records:
            target=root+'/'+name
            if target in prefix.files:raise InvalidInitialization()
            operations.append(('file',target,raw))
    return tuple(operations)


def _verify_headers(fenced):
    fenced.check();prefix=fenced._prefix
    if prefix.previous!=fenced.checkpoint_sha256:raise InvalidInitialization()
    for name,raw in prefix.intent.headers.publications:
        if prefix.files[name]['data']!=raw or 'migrating' not in format2.parse_store(raw,allow_migrating=True):
            raise InvalidInitialization()
    return prefix


@dataclass(frozen=True)
class Initialized:
    nonce: str
    checkpoint_sha256: str
    _prefix: object = field(repr=False,compare=False)

    def check(self):self._prefix.check()


def publish(fenced,*,verify_c1_lineage):
    """Require the original real coordinator, then publish exactly initial C2.

    The coordinator takes canonical root, immutable store context and project
    names, and returns only None after verifying supported C1/non-deletion
    lineage. A fixture callback is not that production verification.
    """
    if not callable(verify_c1_lineage):raise TypeError('original supported C1 lineage check required')
    prefix=fenced._prefix;guard=prefix.guard
    context=json.loads(prefix.intent.encoded)['context'];projects=tuple(name for name,_ in prefix.intent.progress)
    try:
        _verify_headers(fenced)
        def check():
            try:
                if prefix.revoked:raise locks.LostLock()
                journal._check(guard.owned);guard.binding.check()
                if verify_c1_lineage(prefix.root,dict(context),projects) is not None:
                    raise TypeError('C1 lineage check must return only None')
                journal._check(guard.owned)
                guard.artifact_facts();prefix.facts();guard.binding.check()
                if clock.now()>=guard.deadline:raise locks.LockBusy()
            except BaseException:
                prefix.revoke()
                raise
        prefix.check=check;guard.writer_check=check
        check();recipes=_recipes(prefix);effects=[];stages=[];round_id=uuid.uuid4().hex
        for index,(kind,target,raw) in enumerate(recipes):
            if kind=='temporary':
                node=prefix.files[target]
                effects.append(dict(temporary=target,identity=node['native'].identity.document(),sha256=_hash(node['data'])))
                stages.append(None);continue
            path=prefix.folder/('initialize-'+round_id+'-%06d'%index)
            if kind=='directory':
                guard.directory(path,new=True);guard.directory_barrier(path)
                identity=guard.parents[path][0].identity
                effects.append(dict(directory=target,stage=path.name,identity=identity.document()))
            else:
                guard.write(path,raw);identity=guard.nodes[path]['binding'].identity
                old=prefix.files.get(target)
                effects.append(dict(target=target,stage=path.name,identity=identity.document(),sha256=_hash(raw),
                                    original=None if old is None else old['native'].identity.document()))
            stages.append(path)
        manifest=prefix._checkpoint('initialization-publications.json',dict(round=round_id,effects=effects,plan_sha256=_hash(prefix.intent.encoded)))
        for index,(kind,target,raw) in enumerate(recipes):
            if kind=='temporary':prefix._move_temp(index,target,record='initialize')
            elif kind=='directory':prefix._directory(index,stages[index],target)
            else:prefix._replace(index,stages[index],target,raw,record='initialize')
        check()
        value=dict(initialized=True,writer_protocol=1,lifecycle_protocol=1,publications_sha256=manifest,
            root=dict(path_sha256=guard.binding.path_sha256(),identity=guard.binding.identity.document()),context=context,
            projects=[dict(name=name,identity=guard.source_dirs['projects/'+base.project_folder_name(name)].identity.document(),
                           epoch=format2.parse_curation(raw)['fence']['epoch']) for name,raw in prefix.intent.progress])
        final=prefix._checkpoint('initialization-complete.json',value)
        return Initialized(fenced.nonce,final,prefix)
    except BaseException as error:
        prefix.revoke()
        for name,value in [('migration_published',tuple(prefix.published)),('migration_uncertain',prefix.uncertain),
                           ('cleanup_pending',bool(guard.cleanup_pending or prefix.uncertain))]:
            try:setattr(error,name,value)
            except Exception:pass
        raise
