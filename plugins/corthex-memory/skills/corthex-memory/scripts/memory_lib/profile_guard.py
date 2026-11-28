"""Private last-seen settings copies, shared protocol with CORTHEX Memory."""
import json
import base64
import hashlib
import datetime
import shutil
import re
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, urlunsplit

NAMES = ('profile.json', 'projects.json')
DEFAULT_ASK_BEFORE = ('external messages', 'deploys', 'payments', 'deletions', 'publishing')
MISSING = object()


def decode(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('nonstandard JSON value: ' + value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def read(path):
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {'missing': True}
    except OSError:
        return {'inaccessible': True}
    try:
        obj = decode(raw.decode('utf-8-sig'))
        if isinstance(obj, dict): return {'value': obj}
    except (ValueError, UnicodeError):
        pass
    return {'unreadable_sha256': hashlib.sha256(raw).hexdigest(), 'raw_base64': base64.b64encode(raw).decode('ascii')}


def write(path, state):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.guard-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(state, out, ensure_ascii=True, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def field(data, *keys):
    for key in keys:
        if not isinstance(data, dict): return None
        data = data.get(key)
    return data


def reduction(old, new):
    if not isinstance(old, list): return False
    if not isinstance(new, list): return True
    remaining = list(new)
    for item in old:
        if item not in remaining: return True
        remaining.remove(item)
    return False


def contains_saved(old, new):
    if isinstance(old, dict):
        return isinstance(new, dict) and all(key in new and contains_saved(value, new[key]) for key, value in old.items())
    if isinstance(old, list):
        if not isinstance(new, list): return False
        remaining = list(new)
        for value in old:
            index = next ( (i for i, item in enumerate(remaining) if contains_saved(value, item)), None )
            if index is None: return False
            remaining.pop(index)
        return True
    return old == new


def project_reduced(old, new):
    if isinstance(old, list): return not contains_saved(old, new)
    return old is not None and old != new


def approval_reduced(old, new):
    defaults = list(DEFAULT_ASK_BEFORE)
    before = old if isinstance(old, list) else defaults
    after = new if isinstance(new, list) else defaults
    return (reduction(before, after) or
            (old is not None and not isinstance(old, list) and old != new) or
            (new is not None and not isinstance(new, list) and old != new))


def changes(old, new, prefix=''):
    if isinstance(old, dict) and isinstance(new, dict):
        result = []
        for k in sorted(set(old) | set(new)):
            key = prefix + '.' + k if prefix else k
            if k not in old: result.append((key, MISSING, new[k]))
            elif k not in new: result.append((key, old[k], MISSING))
            else: result.extend(changes(old[k], new[k], key))
        return result
    return [(prefix, old, new)] if old != new else []


def valid_baseline(state):
    if not isinstance(state, dict): return False
    if set(state) == {'value'}: return isinstance(state['value'], dict)
    if set(state) == {'missing'}: return state['missing'] is True
    if set(state) in ({'unreadable_sha256'}, {'unreadable_sha256', 'raw_base64'}):
        digest = state['unreadable_sha256']
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest): return False
        if 'raw_base64' not in state: return True  # Older guard copies stored a digest alone.
        try:
            raw = base64.b64decode(state['raw_base64'], validate=True)
            return hashlib.sha256(raw).hexdigest() == digest
        except (ValueError, TypeError):
            return False
    return False


def differences(folder):
    folder = Path(folder)
    state_dir = folder / 'profile-guard'
    marker = state_dir / '.established'
    result = []
    # Empty directories can be left by an interrupted first observation.
    # A marker, any surviving baseline, or a guard archive is evidence of
    # history; compact UTC names also cover a deleted guard directory.
    established = (marker.exists() or marker.is_symlink() or
                   any((state_dir / name).exists() for name in NAMES) or
                   (state_dir.is_dir() and any(state_dir.glob('*.bak'))) or any(
        re.fullmatch(r'(?:profile|projects)\.json\.\d{8}T\d{12}Z(?:\.pending-[A-Za-z0-9_-]+)?\.bak', path.name)
        for path in folder.glob('*.bak')))
    for name in NAMES:
        path, backup = folder / name, state_dir / name
        current = read(path)
        if 'inaccessible' in current:
            result.append((name, backup, [('file inaccessible', None, None)], True))
            continue
        if not backup.exists() and not established:
            state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.guard-', dir=str(state_dir))
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(current, stream, ensure_ascii=True, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    # A link publishes the completed bytes only if absent.
                    os.link(temporary, str(backup))
                    continue
                except FileExistsError:
                    pass
                except OSError:
                    # Some filesystems cannot link. Never replace a competing
                    # baseline; an incomplete copy is treated as invalid.
                    try:
                        target_fd = os.open(str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    except FileExistsError:
                        pass
                    else:
                        try:
                            with open(temporary, 'rb') as source, os.fdopen(target_fd, 'wb') as target:
                                shutil.copyfileobj(source, target)
                                target.flush()
                                os.fsync(target.fileno())
                        except BaseException:
                            # Keep any incomplete file rather than unlink a
                            # newer baseline another process may have installed.
                            raise
                        continue
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
        try:
            previous = json.loads(backup.read_text(encoding='utf-8'))
            if not valid_baseline(previous):
                raise ValueError('invalid baseline')
        except (ValueError, UnicodeError, OSError):
            previous = {'invalid_baseline': True}
        if previous != current:
            old, new = previous.get('value', {}), current.get('value', {})
            diff = changes(old, new)
            for keys, label in ((('ask_before',), 'removed ask_before'), (('nexus', 'push'), 'removed nexus.push')):
                before_list, after_list = field(old, *keys), field(new, *keys)
                if isinstance(before_list, list):
                    remaining = list(after_list) if isinstance(after_list, list) else []
                    removed = []
                    for item in before_list:
                        if item in remaining: remaining.remove(item)
                        else: removed.append(item)
                    if removed: diff.insert(0, (label, removed, []))
            if isinstance(old.get('projects'), list) and isinstance(new.get('projects'), list):
                remaining = [item.get('name') for item in new['projects'] if isinstance(item, dict)]
                removed = [item.get('name') for item in old['projects'] if isinstance(item, dict) and item.get('name') not in remaining]
                if removed: diff.insert(0, ('removed projects', removed, []))
            for keys in (('nexus', 'url'), ('nexus', 'push'), ('ask_before',), ('projects',), ('checkpoints', 'user'), ('checkpoints', 'delegate', 'role')):
                key = '.'.join(keys)
                before, after = field(old, *keys), field(new, *keys)
                if before != after and not any(item[0] == key for item in diff):
                    diff.append((key, before, after))
            if not diff: diff = [('file', previous, current)]
            old_projects, new_projects = field(old, 'projects'), field(new, 'projects')
            def names(entries):
                if not isinstance(entries, list): return entries
                return [entry.get('name') if isinstance(entry, dict) else entry for entry in entries]
            warn = (any(after is MISSING for _, _, after in diff) or
                    'invalid_baseline' in previous or 'unreadable_sha256' in current or
                    ('missing' in current and ('value' in previous or 'unreadable_sha256' in previous)) or
                    field(old, 'nexus', 'url') != field(new, 'nexus', 'url') or
                    field(old, 'checkpoints') != field(new, 'checkpoints') or
                    field(old, 'nexus', 'push') != field(new, 'nexus', 'push') or
                    approval_reduced(field(old, 'ask_before'), field(new, 'ask_before')) or
                    project_reduced(old_projects, new_projects))
            result.append((name, backup, diff, warn))
    if all((state_dir / name).is_file() for name in NAMES):
        try:
            fd = os.open(str(marker), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        except OSError:
            # Do not lose already computed changes when the marker cannot be
            # saved; without it a later loss of both baselines can go unseen.
            result.append(('.established', marker, [('history marker unavailable', None, None)], True))
        else:
            os.close(fd)
    return result


def observe(folder, own_lock=False):
    if not Path(folder).is_dir(): return ''
    locked = not own_lock and (Path(folder) / 'profile-guard.lock').exists()
    # Compare fingerprints around the read so the digest cannot describe a
    # different state from the notice. The first read may create baselines.
    for _ in range(3):
        before = digest(folder)
        diffs = differences(folder)
        stable_digest = digest(folder)
        if before == stable_digest:
            break
    else:
        return 'External settings are changing; run settings.py check again before acting.'
    if not diffs:
        return 'Settings update may be in progress; inspect profile-guard.lock and check again.' if locked else ''
    parts = []
    for name, backup, diff, warn in diffs:
        details = []
        priority = {'removed ask_before': 0, 'removed nexus.push': 1, 'removed projects': 2, 'ask_before': 3, 'nexus.url': 4, 'nexus.push': 5, 'projects': 6, 'checkpoints.user': 7, 'checkpoints.delegate.role': 8}
        for key, before, after in sorted(diff, key=lambda item: priority.get(item[0], 100)):
            # Do not echo possible credentials from unknown fields into host context.
            safe = key in ('nexus.url', 'nexus.push', 'ask_before', 'projects', 'removed projects', 'removed ask_before', 'removed nexus.push', 'checkpoints.user', 'checkpoints.delegate.role')
            def shown(value):
                if value is MISSING: return '<missing>'
                if key == 'checkpoints.delegate.role' and value is not None:
                    return value if isinstance(value, str) else '<invalid role>'
                if key in ('removed projects', 'removed ask_before', 'removed nexus.push') and isinstance(value, list):
                    return [item if isinstance(item, str) else '<invalid>' for item in value]
                if key == 'projects' and value is not None and not isinstance(value, list): return '<invalid list>'
                if key == 'projects' and isinstance(value, list):
                    return [{'name': item.get('name', '<unnamed>'), 'path': item.get('path'),
                             'repo_aliases': sorted(item.get('repos', {})) if isinstance(item.get('repos'), dict) else []}
                            if isinstance(item, dict) else '<invalid>' for item in value]
                if key == 'nexus.url' and value is not None and not isinstance(value, str): return '<invalid URL>'
                if key in ('nexus.push', 'ask_before', 'checkpoints.user') and value is not None:
                    if not isinstance(value, list): return '<invalid list>'
                    return [item if isinstance(item, str) else '<invalid item>' for item in value]
                if key == 'nexus.url' and isinstance(value, str):
                    try:
                        url = urlsplit(value)
                        if url.scheme and url.netloc:
                            safe_path = url.path if re.fullmatch(r'/(?:v[0-9]+/?)?', url.path) else '/<path>' if url.path else ''
                            return urlunsplit((url.scheme, url.netloc.rsplit('@', 1)[-1], safe_path, '', ''))
                    except ValueError:
                        return '<invalid URL>'
                    return '<invalid URL>'
                return value
            def val(value):
                text = json.dumps(shown(value), ensure_ascii=True, separators=(',', ':'))
                return text if len(text) <= 100 else text[:96] + '...'
            name_key = json.dumps(key, ensure_ascii=True)[1:-1][:120]
            action = ': removed' if after is MISSING else ': added' if before is MISSING else ': changed'
            details.append(name_key + (': ' + val(before) + ' -> ' + val(after) if safe else action))
        detail_text = '; '.join(details)
        if len(detail_text) > 220: detail_text = detail_text[:180] + '... (more changes; inspect backup)'
        parts.append(('WARNING protected change, reduction or unreadable file; ' if warn else '') + name + ' ' + detail_text + ('; backup: ' if backup.exists() else '; backup unavailable: ') + '~/.corthex/profile-guard/' + name)
    line = ('Settings update may be in progress; recheck. ' if locked else '') + 'External settings change: ' + ' | '.join(parts)
    if len(line.encode('utf-8')) > 3400:
        line = line[:3000] + '... (more changes; inspect backups)'
    return line + '; digest: ' + stable_digest


def digest(folder, states=None):
    folder = Path(folder)
    states = states or {name: read(folder / name) for name in NAMES}
    baselines = {}
    for name in NAMES:
        try: baselines[name] = hashlib.sha256((folder / 'profile-guard' / name).read_bytes()).hexdigest()
        except FileNotFoundError: baselines[name] = None
        except OSError: baselines[name] = '<inaccessible>'
    data = json.dumps({'current': states, 'baselines': baselines}, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(data).hexdigest()


def accept(folder, expected, validate=None):
    folder = Path(folder)
    states = {name: read(folder / name) for name in NAMES}
    if digest(folder, states) != expected:
        raise ValueError('settings changed since review; run check and review again')
    if any('unreadable_sha256' in state or 'inaccessible' in state for state in states.values()):
        raise ValueError('cannot accept unreadable settings')
    if validate is not None: validate(states)
    if digest(folder) != expected:
        raise ValueError('settings changed during review; run check and review again')
    for name in NAMES:
        backup = folder / 'profile-guard' / name
        if backup.exists():
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            archive = backup.with_name(name + '.' + stamp + '.bak')
            fd = os.open(str(archive), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with backup.open('rb') as source, os.fdopen(fd, 'wb') as target:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
        write(backup, states[name])


def update(folder, name, expected):
    folder = Path(folder)
    current = read(folder / name)
    if current != {'value': expected}:
        raise ValueError('settings were written but changed again; previous baseline retained')
    write(folder / 'profile-guard' / name, current)
