"""Private format-1-to-2 migration driver; never a command, hook or host check.

The caller is the actual maintenance-interval coordinator. It supplies the
three original None-only checks; this driver never infers quiescence, supported
C1 lineage or current privacy facts from files, locks or processes. It chooses
the one path that the named headers and the private migration records support:
a fresh migration, or the resume of headers, initialization or finalization.
The classification is a read-only hint. Every effect and every verification
stays with the component that owns it, under the original ordered owner.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from . import configuration, format2, locks, maintenance_identity, maintenance_journal, maintenance_owner, store
from . import migration_finalize, migration_finalize_resume, migration_header_resume, migration_headers
from . import migration_initialize, migration_initialize_resume, migration_intent

_NONCE = re.compile(r'[0-9a-f]{32}\Z')
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
NAMED = ('store.json', 'store.json.bak')
_LIMIT = 1 << 20
_MARKS = ('headers-complete.json', 'initialization-complete.json',
          'final-header-publications.json', 'migration-complete.json')
PHASES = ('fresh', 'headers', 'initialization', 'finalization', 'final-headers', 'complete', 'format-2')


class MigrationRefused(ValueError):
    """Refused before any lease or effect; code names the reason."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Plan:
    phase: str
    nonce: object = None
    # The (device, made) pair of the named headers; a hint, not compared.
    identity: object = field(default=None, compare=False)


@dataclass(frozen=True)
class Outcome:
    phase: str
    nonce: object = None
    resumed: object = None


def _read(path, code):
    """Read one small regular file without following its final link."""
    try:
        info = os.lstat(str(path))
    except FileNotFoundError:
        return None
    except OSError:
        raise MigrationRefused(code) from None
    if not stat.S_ISREG(info.st_mode) or info.st_size > _LIMIT:
        raise MigrationRefused(code)
    try:
        with open(str(path), 'rb') as handle:
            data = handle.read(_LIMIT + 1)
    except OSError:
        raise MigrationRefused(code) from None
    if len(data) > _LIMIT:
        raise MigrationRefused(code)
    return data


def _header(raw):
    try:
        value = store.json_document(raw)
    except Exception:
        raise MigrationRefused('store-damaged') from None
    if not isinstance(value, dict):
        raise MigrationRefused('store-damaged')
    number = value.get('format')
    if configuration.integer(number) and number > 2:
        raise MigrationRefused('store-newer')
    try:
        if number == 1 and 'migrating' not in value:
            store._record(raw)
            return 'c1', value
        value = format2.parse_store(raw, allow_migrating=True)
    except Exception:
        raise MigrationRefused('store-damaged') from None
    return ('migrating' if 'migrating' in value else 'completed'), value


def _records(root):
    """Code-shaped record folders with their plan context and phase files."""
    folder = root / '.maintenance' / 'format-1-to-2'
    for path in (folder.parent, folder):
        try:
            info = os.lstat(str(path))
        except FileNotFoundError:
            return []
        except OSError:
            raise MigrationRefused('migration-record-unavailable') from None
        if not stat.S_ISDIR(info.st_mode):
            raise MigrationRefused('migration-record-unavailable')
    found = []
    try:
        names = sorted(os.listdir(str(folder)))
    except OSError:
        raise MigrationRefused('migration-record-unavailable') from None
    for name in names:
        path = folder / name
        try:
            info = os.lstat(str(path))
        except OSError:
            continue
        if not _NONCE.fullmatch(name) or not stat.S_ISDIR(info.st_mode):
            continue
        try:
            raw = _read(path / 'plan.json', 'migration-record-unavailable')
            value = store.json_document(raw) if raw is not None else None
            context = value['context'] if isinstance(value, dict) and value.get('nonce') == name else None
            if not isinstance(context, dict):
                continue
            marks = frozenset(mark for mark in _MARKS if os.path.lexists(str(path / mark)))
        except Exception:
            continue  # An unreadable record supports no resume; the owner verifies the chosen one.
        found.append((name, context, marks))
    return found


def plan(root, *, release):
    """Classify without leases or effects; the chosen path still verifies all."""
    root = Path(root)
    if not root.is_absolute():
        raise MigrationRefused('no-store')
    named = []
    for name in NAMED:
        raw = _read(root / name, 'store-damaged')
        if raw is not None:
            named.append(_header(raw))
    if not named:
        raise MigrationRefused('no-store')
    kinds = {kind for kind, _ in named}
    values = [value for _, value in named]
    if len({(value['device'], value['made']) for value in values}) != 1:
        raise MigrationRefused('store-damaged')
    identity = values[0]['device'], values[0]['made']
    if kinds == {'c1'}:
        return Plan('fresh', identity=identity)
    releases = {value['release'] for kind, value in named if kind != 'c1'}
    markers = [value['migrating'] for value in values if 'migrating' in value]
    if 'c1' in kinds and 'completed' in kinds or len(releases) != 1 or any(m != markers[0] for m in markers):
        raise MigrationRefused('store-damaged')
    expected = dict(device=values[0]['device'], made=values[0]['made'], release=releases.pop())
    if markers:
        expected['started'] = markers[0]['started']
    matches = [(name, marks) for name, context, marks in _records(root)
               if {key: context.get(key) for key in expected} == expected]
    if not markers:
        unfinished = [(name, marks) for name, marks in matches if 'migration-complete.json' not in marks]
        if len(unfinished) > 1:
            raise MigrationRefused('migration-record-ambiguous')
        if not unfinished:
            # A completed store needs nothing from this release, older or newer.
            if not matches:
                return Plan('format-2', identity=identity)
            return Plan('complete', matches[0][0] if len(matches) == 1 else None, identity)
    # Every resume publishes the release that the interrupted migration fixed.
    if expected['release'] != release:
        raise MigrationRefused('release-changed')
    if not markers:
        return Plan('final-headers', unfinished[0][0], identity)
    if not matches:
        raise MigrationRefused('migration-record-unavailable')
    if len(matches) > 1:
        raise MigrationRefused('migration-record-ambiguous')
    nonce, marks = matches[0]
    if 'completed' in kinds:
        return Plan('final-headers', nonce, identity)
    for mark, phase in (('headers-complete.json', 'headers'), ('initialization-complete.json', 'initialization')):
        if mark not in marks:
            return Plan(phase, nonce, identity)
    return Plan('finalization', nonce, identity)


def migrate(root, *, release, when, deadline, headers, verify_quiescence, verify_c1_lineage,
            verify_current_privacy):
    """Run or resume one migration under a fresh original ordered owner.

    `headers` maps each named header that the coordinator's confirmation
    covered to the SHA-256 of its bytes. Once the owner holds every lease, and
    before any effect, the named headers it observed must be exactly those, so
    a header changed after the confirmation is never migrated: LostLock.
    The three checks take what their components pass and return only None.
    An exception keeps the component's published/uncertain attributes; nothing
    is rolled back, and a later call resumes from the durable records.
    """
    for check in (verify_quiescence, verify_c1_lineage, verify_current_privacy):
        if not callable(check):
            raise TypeError('original maintenance-interval checks required')
    if not isinstance(headers, dict) or not headers or any(
            name not in NAMED or not isinstance(digest, str) or not _SHA256.fullmatch(digest)
            for name, digest in headers.items()):
        raise TypeError('confirmed named header digests required')
    confirmed = dict(headers)
    current = plan(root, release=release)
    if current.phase in ('complete', 'format-2'):
        return Outcome(current.phase, current.nonce)
    acquire = maintenance_owner.acquire_finalization if current.phase == 'final-headers' else maintenance_owner.acquire
    nonce, initialized = current.nonce, None
    with acquire(Path(root), release=release, when=when, deadline=deadline,
                 verify_quiescence=verify_quiescence) as owned:
        observed = {name: hashlib.sha256(raw).hexdigest() for name, raw in owned.inventory.headers.originals
                    if name in NAMED}
        if observed != confirmed:
            raise locks.LostLock()
        if current.phase == 'fresh':
            native = maintenance_identity.bind(owned.inventory.folder)
            intent = migration_intent.prepare(owned, native)
            nonce = json.loads(intent.encoded)['nonce']
            fenced = migration_headers.publish(maintenance_journal.preserve(owned, intent, native), intent)
        elif current.phase == 'headers':
            fenced = migration_header_resume.reopen(owned, nonce)
        if current.phase in ('fresh', 'headers'):
            initialized = migration_initialize.publish(fenced, verify_c1_lineage=verify_c1_lineage)
        elif current.phase == 'initialization':
            initialized = migration_initialize_resume.reopen(owned, nonce, verify_c1_lineage=verify_c1_lineage)
        if initialized is None:
            finalized = migration_finalize_resume.reopen(
                owned, nonce, verify_supported_lineage=verify_c1_lineage, verify_current_privacy=verify_current_privacy)
        else:
            finalized = migration_finalize.publish(
                initialized, verify_c1_lineage=verify_c1_lineage, verify_current_privacy=verify_current_privacy)
        finalized.check()
    return Outcome('migrated', nonce, None if current.phase == 'fresh' else current.phase)
