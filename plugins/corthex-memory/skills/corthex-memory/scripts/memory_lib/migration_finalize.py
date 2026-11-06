"""Publish completed headers only from a live exact initialized prefix.

Real original lineage/current-privacy gates are mandatory. Durable receipts
record effects; they never supply their own authority or history recovery.
"""
from dataclasses import dataclass, field
import hashlib
import json

from . import clock, format2, locks
from . import maintenance_journal as journal, migration_initialize as initialize


class InvalidFinalization(ValueError):
    def __init__(self):super().__init__('migration finalization unavailable')


def _hash(raw):return hashlib.sha256(raw).hexdigest()


def _initialized(value):
    if not isinstance(value,initialize.Initialized):raise TypeError('live initialized prefix required')
    value.check();prefix=value._prefix;guard=prefix.guard
    if value.nonce!=prefix.prepared.nonce or value.checkpoint_sha256!=prefix.previous:raise InvalidFinalization()
    folder=prefix.folder
    try:
        manifest=guard.nodes[folder/'initialization-publications.json']['data']
        publications=json.loads(manifest)
        count=len(publications['effects'])
        previous=_hash(guard.nodes[folder/('initialize-%06d.done.json'%(count-1))]['data']) if count else _hash(manifest)
        expected=dict(version=1,nonce=value.nonce,previous=previous,**initialize.complete_value(prefix,_hash(manifest)))
        complete=guard.nodes[folder/'initialization-complete.json']['data']
        if complete!=journal._bytes(expected) or _hash(complete)!=value.checkpoint_sha256:raise InvalidFinalization()
    except (KeyError,TypeError,ValueError):raise InvalidFinalization() from None
    for name,raw in prefix.intent.headers.publications:
        if prefix.files[name]['data']!=raw or 'migrating' not in format2.parse_store(raw,allow_migrating=True):raise InvalidFinalization()
    return prefix


def bind_privacy(prefix,verify_current_privacy):
    if not callable(verify_current_privacy):raise TypeError('original current privacy check required')
    guard=prefix.guard;context=json.loads(prefix.intent.encoded)['context']
    projects=tuple(name for name,_ in prefix.intent.progress)
    lineage=prefix.check
    def check():
        try:
            if prefix.revoked:raise locks.LostLock()
            lineage()
            if verify_current_privacy(prefix.root,dict(context),projects) is not None:
                raise TypeError('current privacy check must return only None')
            # Owner/lineage callbacks finish before the final callback-free facts.
            journal._check(guard.owned);guard.binding.check()
            guard.artifact_facts();prefix.facts();guard.binding.check()
            if clock.now()>=guard.deadline:raise locks.LockBusy()
        except BaseException:
            prefix.revoke()
            raise
    prefix.check=check;guard.writer_check=check;check()
    return check


@dataclass(frozen=True)
class Finalized:
    nonce: str
    checkpoint_sha256: str
    _prefix: object = field(repr=False,compare=False)

    def check(self):self._prefix.check()


def publish(initialized,*,verify_c1_lineage,verify_current_privacy):
    """Clear backup then primary, preserving project bytes and fixed epochs.

    Both original coordinator callbacks take root, immutable store context and
    project names, and return only None. Neither receipt nor fixture callback
    establishes those real-host authorities. Later completed-header resumption
    has its own owner; this path cannot reopen or reinitialize a store.
    """
    if not callable(verify_c1_lineage) or not callable(verify_current_privacy):raise TypeError('original lineage and privacy checks required')
    if not isinstance(initialized,initialize.Initialized):raise TypeError('live initialized prefix required')
    prefix=initialized._prefix;guard=prefix.guard
    try:
        _initialized(initialized)
        initialize.bind_lineage(prefix,verify_c1_lineage)
        check=bind_privacy(prefix,verify_current_privacy)
        stages=[]
        for index,(name,raw) in enumerate(prefix.intent.headers.publications):
            value=format2.parse_store(raw,allow_migrating=True);value.pop('migrating')
            completed=format2.store_bytes(value)
            path=prefix.folder/('final-header-stage-%06d.bin'%index)
            guard.write(path,completed);stages.append((path,name,completed))
        effects=[dict(target=name,stage=path.name,identity=guard.nodes[path]['binding'].identity.document(),
                      original=prefix.files[name]['native'].identity.document(),sha256=_hash(raw)) for path,name,raw in stages]
        prefix._checkpoint('final-header-publications.json',dict(effects=effects,
            plan_sha256=_hash(prefix.intent.encoded),initialization_sha256=initialized.checkpoint_sha256))
        for index,(path,name,raw) in enumerate(stages):prefix._replace(index,path,name,raw,record='final-header')
        check()
        final=prefix._checkpoint('migration-complete.json',dict(completed=True,initialization_sha256=initialized.checkpoint_sha256,
            writer_protocol=1,lifecycle_protocol=1,effects=len(stages),plan_sha256=_hash(prefix.intent.encoded)))
        return Finalized(initialized.nonce,final,prefix)
    except BaseException as error:
        prefix.revoke()
        for name,value in [('migration_published',tuple(prefix.published)),('migration_uncertain',prefix.uncertain),
                           ('cleanup_pending',bool(guard.cleanup_pending or prefix.uncertain))]:
            try:setattr(error,name,value)
            except Exception:pass
        raise
