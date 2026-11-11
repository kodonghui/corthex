"""The migrate command (API-154): the TASK-074 maintenance-interval coordinator.

The command runner accepts it from release 0.3.0 (the activation, TASK-117);
below it an installed plugin keeps C1 behaviour. The coordinator never infers from
processes or locks that other sessions are closed. Its facts are the user's
yes to a preview bound to this exact store, the named header bytes that
preview hashed with the supported C1 release they carry, and the configuration
bytes the user reviewed. The driver migrates only those header bytes; a later
change to any of them stops the migration, which then resumes from its
durable records.
"""
import hashlib
import os
from pathlib import Path
import stat

from . import activation, base, clock, commands, configuration, locks, maintenance_identity, migration_driver
from . import migration_finalize, migration_header_resume, migration_initialize, migration_intent
from . import migration_inventory, store

SUPPORTED_C1 = frozenset(('0.2.0', '0.2.1'))
# The running release; tests replace this name.
release = activation.release
# One operation deadline that answers within a ten-minute host command limit.
SECONDS = 540.0
_LIMIT = 1 << 20
_RESUMED = ('headers', 'initialization', 'finalization', 'final-headers')
# What the components raise when the store or a confirmed fact changed.
_CHANGED = (locks.LostLock, maintenance_identity.IdentityUnavailable, migration_inventory.InvalidInventory,
            migration_intent.InvalidIntent, migration_initialize.InvalidInitialization,
            migration_finalize.InvalidFinalization, migration_header_resume.InvalidResume)
SAY = {
    'fresh': ('Migration moves this memory store to format 2 for curation and recall. Before you confirm, '
              'update the CORTHEX memory plugin to this release in both Claude Code and Codex on this device '
              'and close every other session that uses it; older versions cannot record into the moved store.'),
    'resume': ('An earlier migration of this memory store stopped part way. Before you confirm, close every '
               'other Claude Code and Codex session on this device; confirming finishes it from where it stopped.'),
    'nothing': 'This memory store already uses format 2. Nothing was changed.',
    'done': 'The memory store now uses format 2. Sessions with this release record into it.',
    'blocked': 'This memory store cannot be migrated now; data.reason names why. Nothing was changed.',
    'stopped': ('The migration stopped part way and kept what it had written; data.reason says why when known. '
                'Older plugin versions cannot record into this store until it finishes. Run migrate again to '
                'resume it; if the store changed, undo that change first.'),
}


def _supported(source, target):
    """Whether a fresh migration accepts a format-1 header made by release `source` while `target` runs.

    A supported C1 release made the store; or, from release 0.3.0, a repair of
    a release no later than the running one wrote a new format-1 record over a
    store whose projects only C1 code paths wrote (TASK-117).
    """
    if source in SUPPORTED_C1:
        return True
    numbers = activation.version(source)
    return activation.c2(source) and numbers is not None and numbers <= activation.version(target)


def _bytes(path, error):
    """A small regular file's bytes, None when absent; error() otherwise."""
    try:
        info = os.lstat(str(path))
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > _LIMIT:
        raise error()
    with open(str(path), 'rb') as handle:
        data = handle.read(_LIMIT + 1)
    if len(data) > _LIMIT:
        raise error()
    return data


def _invalid():
    return configuration.ConfigurationInvalid('$')


def _configuration(root):
    """Every configuration copy's SHA-256 by name; the reviewed privacy facts."""
    names = sorted(name for name in os.listdir(str(root)) if name.startswith('configuration.json'))
    return {name: hashlib.sha256(_bytes(root / name, _invalid) or b'').hexdigest() for name in names}


def _projects(raw):
    """The configured project names; strict, so an invalid file refuses."""
    if raw is None:
        return []
    try:
        value = store._configuration(raw)
    except configuration.ConfigurationInvalid:
        raise
    except Exception:
        raise _invalid() from None
    return sorted(value.get('projects', {}))


def _blocked(reason):
    return commands.result('migrate', dict(reason=reason), SAY['blocked'], 'refused', 'migration-blocked')


def _refusal(code):
    if code in ('no-store', 'store-damaged', 'store-newer'):
        return commands.common_result('migrate', code)
    return _blocked(code)


def _source_release(raw):
    """The release in a format-1 store record; a header that is not one is damaged."""
    try:
        return store._record(raw)['release']
    except Exception:
        raise migration_driver.MigrationRefused('store-damaged') from None


def _preview(root, target):
    """The proposal and its data, or None and the final result."""
    current = migration_driver.plan(root, release=target)
    if current.phase in ('complete', 'format-2'):
        return None, commands.result('migrate', dict(phase=current.phase, release=target), SAY['nothing'], 'nothing')
    if not activation.c2(target):
        return None, _blocked('unsupported-release')
    damaged = lambda: migration_driver.MigrationRefused('store-damaged')
    named = {name: _bytes(root / name, damaged) for name in migration_driver.NAMED}
    named = {name: raw for name, raw in named.items() if raw is not None}
    if not named:
        raise migration_driver.MigrationRefused('no-store')
    # The release is read from the very bytes the confirmation binds.
    if current.phase == 'fresh' and any(not _supported(_source_release(raw), target) for raw in named.values()):
        return None, _blocked('unsupported-release')
    headers = {name: hashlib.sha256(raw).hexdigest() for name, raw in named.items()}
    reviewed = _configuration(root)
    binding = hashlib.sha256(commands.canonical(dict(
        root=str(root), phase=current.phase, nonce=current.nonce, headers=headers,
        configuration=reviewed)).encode('ascii')).hexdigest()
    projects = _projects(_bytes(root / 'configuration.json', _invalid))
    data = dict(phase=current.phase, release=target, projects=projects, binding=binding)
    return (current, reviewed, headers), data


def migrate(context):
    """Preview, then on the user's yes run or resume the migration once."""
    root = Path(os.path.abspath(str(context.memory.folder)))
    target = release()
    try:
        prepared, data = _preview(root, target)
    except migration_driver.MigrationRefused as error:
        return _refusal(error.code)
    except configuration.ConfigurationInvalid as error:
        return commands.common_result('migrate', 'configuration-invalid', field=error.field)
    if prepared is None:
        return data
    current, reviewed, headers = prepared
    say = SAY['fresh' if current.phase == 'fresh' else 'resume']
    return context.confirm(data, say, lambda: _apply(root, target, current, reviewed, headers, data['projects']))


def _apply(root, target, current, reviewed, headers, projects):
    canonical, (device, made) = root.resolve(), current.identity

    def same_store(folder, device_now, made_now, release_now, configuration_too):
        if Path(folder) != canonical or (device_now, made_now, release_now) != (device, made, target):
            raise locks.LostLock()
        if configuration_too:
            try:
                unchanged = _configuration(root) == reviewed
            except Exception:
                unchanged = False
            if not unchanged:
                raise locks.LostLock()

    def quiescence(folder, binding):
        same_store(folder, binding[0], binding[1], binding[2], True)

    def lineage(folder, context, names):
        same_store(folder, context.get('device'), context.get('made'), context.get('release'), False)

    def privacy(folder, context, names):
        same_store(folder, context.get('device'), context.get('made'), context.get('release'), True)

    deadline = clock.now() + SECONDS
    try:
        outcome = migration_driver.migrate(
            root, release=target, when=base.utc_time(), deadline=deadline, headers=headers,
            verify_quiescence=quiescence, verify_c1_lineage=lineage, verify_current_privacy=privacy)
    except migration_driver.MigrationRefused as error:
        return _refusal(error.code)
    except Exception as error:
        late = clock.now() >= deadline
        if isinstance(error, locks.LockBusy) and not late:
            # Leases are taken without waiting: a live session still holds one.
            return commands.common_result('migrate', 'lock-busy')
        try:
            after = migration_driver.plan(root, release=target)
        except Exception:
            after = None
        if after is not None and after.phase == current.phase == 'fresh':
            # No named header changed, so there is nothing to resume.
            if isinstance(error, _CHANGED):
                return _blocked('store-contents')
            raise
        data = dict(release=target)
        if after is not None and after.phase in _RESUMED:
            data['phase'] = after.phase
        if isinstance(error, locks.LockBusy):
            data['reason'] = 'deadline'
        elif isinstance(error, _CHANGED):
            data['reason'] = 'store-changed'
        return commands.result('migrate', data, SAY['stopped'], 'failed', 'migration-stopped')
    data = dict(phase='migrated', release=target, projects=projects)
    if outcome.resumed in _RESUMED:
        data['resumed'] = outcome.resumed
    return commands.result('migrate', data, SAY['done'])
