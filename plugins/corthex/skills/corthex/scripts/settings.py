#!/usr/bin/env python3
"""Update local CORTHEX settings without replacing unrelated fields."""
import sys
sys.dont_write_bytecode = True
import argparse
import re
import copy
from contextlib import contextmanager
import datetime
import json
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlsplit, urlunsplit
sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_guard


def merge(old, new):
    if isinstance(old, dict) and isinstance(new, dict):
        result = copy.deepcopy(old)
        for key, value in new.items():
            result[key] = merge(result[key], value) if key in result else value
        return result
    if isinstance(old, dict):
        raise ValueError('cannot replace an object; set its fields instead')
    return new


def restore_merge(current, saved):
    if isinstance(current, dict) and isinstance(saved, dict):
        result = copy.deepcopy(current)
        for key, value in saved.items():
            result[key] = restore_merge(result[key], value) if key in result else copy.deepcopy(value)
        return result
    if isinstance(current, list) and isinstance(saved, list):
        result = copy.deepcopy(saved)
        for value in current:
            if value not in result: result.append(copy.deepcopy(value))
        return result
    return copy.deepcopy(saved)


def get(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def lost(old, new):
    return profile_guard.reduction(old, new)


def report_value(field, value):
    """Report useful changes without echoing unknown fields or URL credentials."""
    if value is None: return None
    if field in ('language', 'address_as'):
        return value if isinstance(value, str) else '<invalid>'
    if field in ('ask_before', 'nexus.push', 'checkpoints.user'):
        return [item if isinstance(item, str) else '<invalid>' for item in value] if isinstance(value, list) else '<invalid>'
    if field == 'nexus.url':
        if not isinstance(value, str): return '<invalid URL>'
        try:
            url = urlsplit(value)
            if not url.scheme or not url.netloc: return '<invalid URL>'
            path = url.path if re.fullmatch(r'/(?:v[0-9]+/?)?', url.path) else '/<path>' if url.path else ''
            return urlunsplit((url.scheme, url.netloc.rsplit('@', 1)[-1], path, '', ''))
        except ValueError:
            return '<invalid URL>'
    if field == 'nexus' and isinstance(value, dict):
        return {key: report_value('nexus.' + key, item) for key, item in value.items() if key in ('url', 'push')}
    if field == 'checkpoints.delegate' and isinstance(value, dict):
        return {'role': value.get('role') if isinstance(value.get('role'), str) else '<invalid>'}
    if field == 'checkpoints' and isinstance(value, dict):
        return {key: report_value('checkpoints.' + key, item) for key, item in value.items() if key in ('user', 'delegate')}
    if field == 'projects' and isinstance(value, list):
        return [{'name': item.get('name'), 'path': item.get('path'),
                 'repo_aliases': sorted(item.get('repos', {})) if isinstance(item.get('repos'), dict) else []}
                if isinstance(item, dict) else '<invalid>' for item in value]
    if field == 'profile' and isinstance(value, dict):
        result = {key: report_value(key, item) for key, item in value.items() if key in ('language', 'address_as', 'ask_before')}
        nexus = value.get('nexus')
        if isinstance(nexus, dict):
            result['nexus'] = {key: report_value('nexus.' + key, item) for key, item in nexus.items() if key in ('url', 'push')}
        result['other_fields'] = sorted(key for key in value if key not in ('language', 'address_as', 'ask_before', 'nexus'))
        return result
    return '<hidden>'


def publish_exclusive(source, destination):
    """Publish without replacing another writer's file, even on filesystems without links."""
    try:
        os.link(str(source), str(destination))
        return
    except FileExistsError:
        raise
    except OSError:
        fd = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        # If copying fails, leave the partial file for review; never unlink a
        # path that another writer might have replaced in the meantime.
        with open(source, 'rb') as src, os.fdopen(fd, 'wb') as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())


def restore_independent(source, destination, folder):
    """Restore without sharing the saved backup's inode with the live file."""
    fd, name = tempfile.mkstemp(prefix='.restore-', dir=str(folder))
    try:
        with open(source, 'rb') as src, os.fdopen(fd, 'wb') as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        shutil.copymode(source, name)
        publish_exclusive(Path(name), destination)
    finally:
        if os.path.exists(name): os.unlink(name)


def move_for_backup(path, raw, folder):
    """Keep the actual file moved, including any last-moment external write."""
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.bak', dir=str(folder))
    os.close(fd)
    moved = Path(name)
    try:
        os.replace(path, moved)
    except OSError:
        moved.unlink()
        raise
    if moved.read_bytes() != raw:
        try:
            restore_independent(moved, path, folder)
        except OSError:
            pass  # Another writer's live file is never replaced.
        raise ValueError('settings changed during the update; moved copy kept at ' + str(moved))
    return moved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--words', help="user's exact words authorizing a protected change")
    parser.add_argument('--place', help='where the user said them')
    parser.add_argument('--time', help='when the user said them')
    parser.add_argument('--ask-before-words', help='separate user approval for reducing ask_before')
    parser.add_argument('--reduction-words', help='user words explicitly approving a push or project reduction')
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='create a missing profile from a JSON object'); init.add_argument('value')
    setting = sub.add_parser('set'); setting.add_argument('key'); setting.add_argument('value', help='JSON value')
    append = sub.add_parser('append', help='add one value to a profile list'); append.add_argument('key'); append.add_argument('value', help='one JSON value')
    unset = sub.add_parser('unset', help='remove a profile field'); unset.add_argument('key')
    pu = sub.add_parser('project-unset', help='remove a field from one project'); pu.add_argument('name'); pu.add_argument('key')
    sub.add_parser('check', help='show external changes and their digest')
    accept = sub.add_parser('accept-external', help='accept reviewed external changes as the new baseline')
    accept.add_argument('digest', help='digest from check or session warning')
    restore = sub.add_parser('restore', help='restore a last-seen settings file'); restore.add_argument('target', choices=['profile', 'projects']); restore.add_argument('digest')
    project = sub.add_parser('project'); project.add_argument('action', choices=['add', 'update', 'remove']); project.add_argument('value', help='JSON object with name for add/update, name for remove')
    args = parser.parse_args()
    folder = Path.home() / '.corthex'
    if args.command == 'check':
        print(profile_guard.observe(folder) or 'No external changes')
        return
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = folder / 'profile-guard.lock'
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise ValueError('another settings command is running; retry, or inspect a stale profile-guard.lock')
    try:
        run(args, folder)
    finally:
        try: lock.rmdir()
        except FileNotFoundError: pass  # Preserve the command's real outcome.


def run(args, folder):
    if args.command == 'accept-external':
        if not all((args.words, args.place, args.time)):
            raise ValueError('accepting external state requires --words, --place and --time')
        if not folder.is_dir(): raise ValueError('no settings to accept')
        diffs = profile_guard.differences(folder)
        if not diffs: raise ValueError('no external changes to accept')
        def validate(states):
            for name in profile_guard.NAMES:
                backup = folder / 'profile-guard' / name
                if name == 'projects.json':
                    try:
                        state = json.loads(backup.read_text(encoding='utf-8'))
                        if not profile_guard.valid_baseline(state): raise ValueError('invalid baseline')
                        if 'unreadable_sha256' in state: raise ValueError('unreadable baseline')
                        previous_projects = state.get('value', {}).get('projects')
                    except (ValueError, UnicodeError, FileNotFoundError, AttributeError):
                        if not args.reduction_words:
                            raise ValueError('damaged project baseline requires explicit --reduction-words')
                        previous_projects = None
                    current_projects = states[name].get('value', {}).get('projects')
                    if profile_guard.project_reduced(previous_projects, current_projects) and not args.reduction_words:
                        raise ValueError('project reduction requires explicit --reduction-words')
                if name == 'profile.json':
                    try:
                        state = json.loads(backup.read_text(encoding='utf-8'))
                        if not profile_guard.valid_baseline(state): raise ValueError('invalid baseline')
                        if 'unreadable_sha256' in state: raise ValueError('unreadable baseline')
                        previous = state.get('value', {})
                        if not isinstance(previous, dict): raise ValueError('invalid baseline')
                    except (ValueError, UnicodeError, FileNotFoundError):
                        if not args.ask_before_words or not args.reduction_words:
                            raise ValueError('damaged profile baseline requires --ask-before-words and --reduction-words')
                        previous = {}
                    current = states[name].get('value', {})
                    if profile_guard.approval_reduced(previous.get('ask_before'), current.get('ask_before')) and not args.ask_before_words:
                        raise ValueError('ask_before reduction requires separate --ask-before-words approval')
                    if lost(get(previous, 'nexus', 'push'), get(current, 'nexus', 'push')) and not args.reduction_words:
                        raise ValueError('NEXUS push reduction requires explicit --reduction-words')
        profile_guard.accept(folder, args.digest, validate)
        print(json.dumps({'accepted': 'external settings', 'words': args.words, 'place': args.place, 'time': args.time, 'ask_before_words': args.ask_before_words, 'reduction_words': args.reduction_words}, ensure_ascii=True))
        return
    warning = profile_guard.observe(folder, own_lock=True)
    if warning and args.command != 'restore':
        raise ValueError(warning + '; review and restore or accept-external first')
    path = folder / ('profile.json' if args.command in ('set', 'append', 'unset', 'init') or (args.command == 'restore' and args.target == 'profile') else 'projects.json')
    if path.is_symlink(): raise ValueError('settings file is a symbolic link; leave it unchanged and ask for its intended location')
    existed = path.exists()
    raw = path.read_bytes() if existed else None
    unreadable_old = False
    try:
        old = profile_guard.decode(raw.decode('utf-8-sig')) if existed else {}
        if not isinstance(old, dict): raise ValueError('settings must be a JSON object')
    except (ValueError, UnicodeError):
        if args.command != 'restore': raise
        if not args.reduction_words:
            raise ValueError('restoring unreadable settings requires explicit --reduction-words')
        if path.name == 'profile.json' and not args.ask_before_words:
            raise ValueError('restoring unreadable profile requires separate --ask-before-words approval')
        old = {}
        unreadable_old = True
    changed = profile_guard.observe(folder, own_lock=True) if args.command != 'restore' else ''
    if changed:
        raise ValueError(changed + '; review before retrying')
    new = copy.deepcopy(old)
    restore_missing = False
    if args.command == 'restore':
        if not all((args.words, args.place, args.time)):
            raise ValueError('restore requires --words, --place and --time')
        if args.digest != profile_guard.digest(folder):
            raise ValueError('settings changed since review; run check and review again')
        backup = folder / 'profile-guard' / path.name
        state = json.loads(backup.read_text(encoding='utf-8'))
        if not profile_guard.valid_baseline(state): raise ValueError('invalid last-seen copy')
        restore_missing = state == {'missing': True}
        new = {} if restore_missing else state.get('value')
        if not isinstance(new, dict): raise ValueError('no usable last-seen copy to restore')
        if not restore_missing:
            if path.name == 'projects.json' and isinstance(old.get('projects'), list) and isinstance(new.get('projects'), list):
                current_projects = old['projects']
                original_projects = new['projects']
                def valid_entries(entries):
                    return (all(isinstance(item, dict) and isinstance(item.get('name'), str) and item['name'] for item in entries)
                            and len({item['name'] for item in entries}) == len(entries))
                if not valid_entries(original_projects):
                    if not args.reduction_words:
                        raise ValueError('ambiguous last-seen projects require explicit --reduction-words')
                    new['projects'] = copy.deepcopy(original_projects)
                else:
                    if not valid_entries(current_projects):
                        if not args.reduction_words:
                            raise ValueError('ambiguous current projects require explicit --reduction-words to restore the last-seen list')
                        # Keep unambiguous new entries. Conflicting or unnamed
                        # entries remain in the timestamped backup for review.
                        saved_names = {item['name'] for item in original_projects}
                        counts = {}
                        for item in current_projects:
                            if isinstance(item, dict) and isinstance(item.get('name'), str):
                                counts[item['name']] = counts.get(item['name'], 0) + 1
                        current_projects = [item for item in current_projects
                                            if isinstance(item, dict) and isinstance(item.get('name'), str)
                                            and item['name'] not in saved_names and counts[item['name']] == 1]
                    restored = copy.deepcopy(current_projects)
                    positions = {item['name']: index for index, item in enumerate(restored)}
                    for item in original_projects:
                        if item['name'] in positions:
                            index = positions[item['name']]
                            restored[index] = restore_merge(restored[index], item)
                        else:
                            restored.append(item)
                    new['projects'] = restored
            # Preserve unrelated fields added since the baseline, but restore
            # protected approval and NEXUS fields exactly to their prior state.
            current = copy.deepcopy(old)
            if path.name == 'projects.json' and 'projects' in new:
                current.pop('projects', None)
            for key in ('ask_before', 'checkpoints'):
                current.pop(key, None)
            if isinstance(current.get('nexus'), dict):
                current['nexus'].pop('url', None)
                current['nexus'].pop('push', None)
                if not current['nexus']: current.pop('nexus')
            new = restore_merge(current, new)
        keys = []
    elif args.command == 'init':
        if existed: raise ValueError('profile already exists')
        new = profile_guard.decode(args.value)
        if not isinstance(new, dict): raise ValueError('profile must be an object')
        keys = []
    elif args.command in ('unset', 'project-unset'):
        if not all((args.words, args.place, args.time)): raise ValueError('removing a field requires --words, --place and --time')
        keys = args.key.split('.')
        if any(not key for key in keys): raise ValueError('empty key')
        node = new
        if args.command == 'project-unset':
            entries = new.get('projects')
            if not isinstance(entries, list): raise ValueError('projects is not a list')
            matches = [item for item in entries if isinstance(item, dict) and item.get('name') == args.name]
            if len(matches) != 1: raise ValueError('project not found or ambiguous')
            if keys[0] == 'name': raise ValueError('cannot remove a project name')
            node = matches[0]
        for key in keys[:-1]:
            if not isinstance(node, dict) or key not in node: raise ValueError('field not found')
            node = node[key]
        if not isinstance(node, dict) or keys[-1] not in node: raise ValueError('field not found')
        del node[keys[-1]]
    elif args.command in ('set', 'append'):
        keys = args.key.split('.')
        if any(not k for k in keys): raise ValueError('empty key')
        value = profile_guard.decode(args.value)
        node = new
        for key in keys[:-1]:
            if key not in node: node[key] = {}
            if not isinstance(node[key], dict): raise ValueError('parent is not an object')
            node = node[key]
        if args.command == 'append':
            if keys[-1] not in node:
                node[keys[-1]] = list(profile_guard.DEFAULT_ASK_BEFORE) if keys == ['ask_before'] else []
            if not isinstance(node[keys[-1]], list): raise ValueError('field is not a list')
            if value not in node[keys[-1]]: node[keys[-1]].append(value)
        else:
            node[keys[-1]] = merge(node[keys[-1]], value) if keys[-1] in node else value
    else:
        entries = new.setdefault('projects', [])
        if not isinstance(entries, list): raise ValueError('projects is not a list')
        if args.action in ('add', 'update'):
            value = profile_guard.decode(args.value)
            if not isinstance(value, dict) or not isinstance(value.get('name'), str) or not value['name']: raise ValueError('project needs a name')
            matches = [i for i, entry in enumerate(entries) if isinstance(entry, dict) and entry.get('name') == value['name']]
            if args.action == 'add':
                if matches: raise ValueError('project already exists')
                profile_state = profile_guard.read(folder / 'profile.json')
                if ('unreadable_sha256' in profile_state or 'inaccessible' in profile_state) and not all((args.words, args.place, args.time)):
                    raise ValueError('registering a project with an unreadable profile requires --words, --place and --time')
                profile = profile_state.get('value', {})
                push = get(profile, 'nexus', 'push')
                if isinstance(push, list) and value['name'] in push and not all((args.words, args.place, args.time)):
                    raise ValueError('registering an already pushed project requires --words, --place and --time')
                entries.append(value)
            else:
                if len(matches) != 1: raise ValueError('project not found or ambiguous')
                entries[matches[0]] = merge(entries[matches[0]], value)
        else:
            if sum(isinstance(e, dict) and e.get('name') == args.value for e in entries) != 1: raise ValueError('project not found or ambiguous')
            new['projects'] = [e for e in entries if not isinstance(e, dict) or e.get('name') != args.value]
    if old.get('ask_before') != new.get('ask_before') and 'ask_before' in new:
        value = new['ask_before']
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError('ask_before must be a list of nonempty strings')
    old_push, new_push = get(old, 'nexus', 'push'), get(new, 'nexus', 'push')
    if old_push != new_push and new_push is not None:
        if not isinstance(new_push, list) or any(not isinstance(item, str) or not item.strip() for item in new_push):
            raise ValueError('nexus.push must be a list of nonempty strings')
    ask_reduced = profile_guard.approval_reduced(old.get('ask_before'), new.get('ask_before'))
    protected = (get(old, 'nexus', 'url') != get(new, 'nexus', 'url')) or (get(old, 'nexus', 'push') != get(new, 'nexus', 'push')) or (get(old, 'checkpoints') != get(new, 'checkpoints')) or ask_reduced or args.command in ('unset', 'project-unset') or (args.command == 'project' and args.action in ('update', 'remove')) or (args.command == 'restore' and path.name == 'projects.json' and profile_guard.project_reduced(old.get('projects'), new.get('projects')))
    if protected and not all((args.words, args.place, args.time)): raise ValueError('protected change requires --words, --place and --time')
    if ask_reduced and not args.ask_before_words: raise ValueError('ask_before reduction requires separate --ask-before-words approval')
    if lost(get(old, 'nexus', 'push'), get(new, 'nexus', 'push')) and not args.reduction_words:
        raise ValueError('NEXUS push reduction requires explicit --reduction-words')
    if path.name == 'projects.json' and profile_guard.project_reduced(old.get('projects'), new.get('projects')) and not args.reduction_words:
        raise ValueError('project reduction or change requires explicit --reduction-words')
    if existed and old == new and not restore_missing and not unreadable_old:
        print('No fields restored; inspect remaining external changes with check' if args.command == 'restore' else 'No change')
        return
    if restore_missing and not existed: print('No change'); return
    folder.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = path.with_name(path.name + '.' + stamp + '.bak')
        fd = os.open(str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with path.open('rb') as source, os.fdopen(fd, 'wb') as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
    if restore_missing:
        if not existed or path.read_bytes() != raw:
            raise ValueError('settings changed during the update; retry after review')
        # Move the actual file instead of deleting a concurrent write.
        move_for_backup(path, raw, folder)
        try:
            if profile_guard.read(path) != {'missing': True}:
                raise ValueError('file was recreated during restore')
            profile_guard.write(folder / 'profile-guard' / path.name, {'missing': True})
        except (OSError, ValueError) as error:
            raise ValueError('settings were removed but the baseline was not updated: ' + str(error))
    else:
        fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=str(folder))
        pending = None
        published = False
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(new, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            pending_fd, pending = tempfile.mkstemp(prefix=path.name + '.' + stamp + '.pending-', suffix='.bak', dir=str(folder))
            with open(temp, 'rb') as source, os.fdopen(pending_fd, 'wb') as target:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            if path.exists(): shutil.copymode(path, temp)
            if path.exists() != existed or (existed and path.read_bytes() != raw):
                raise ValueError('settings changed during the update; retry after review')
            if existed:
                # Atomic replacement keeps readers from seeing a missing or partial file.
                os.replace(temp, path)
            else:
                # A new file must not clobber a concurrent creator.
                publish_exclusive(Path(temp), path)
            published = True
        finally:
            if os.path.exists(temp): os.unlink(temp)
            if not published and pending is not None and os.path.exists(pending): os.unlink(pending)
        try:
            profile_guard.update(folder, path.name, new)
        except (OSError, ValueError) as error:
            raise ValueError('settings were written but the baseline was not updated; approved copy kept at ' + str(pending) + ': ' + str(error))
        else:
            if pending is not None and os.path.exists(pending): os.unlink(pending)
    before = None if args.command == 'init' else old if args.command == 'restore' else get(old, *keys) if args.command in ('set', 'append', 'unset') else old.get('projects')
    after = None if restore_missing else new if args.command in ('init', 'restore') else get(new, *keys) if args.command in ('set', 'append', 'unset') else new.get('projects')
    field = args.key if args.command in ('set', 'append', 'unset') else args.target if args.command == 'restore' else 'profile' if args.command == 'init' else 'projects'
    if args.command == 'restore' and args.target == 'projects':
        before = before.get('projects') if isinstance(before, dict) else before
        after = after.get('projects') if isinstance(after, dict) else after
    report = {'file': path.name, 'field': field, 'before': report_value(field, before), 'after': report_value(field, after)}
    if protected:
        report['approval'] = {'words': args.words, 'place': args.place, 'time': args.time, 'ask_before_words': args.ask_before_words, 'reduction_words': args.reduction_words}
    print(json.dumps(report, ensure_ascii=True))

if __name__ == '__main__':
    try: main()
    except (ValueError, OSError) as error:
        print('profile guard: ' + str(error), file=sys.stderr); sys.exit(1)
