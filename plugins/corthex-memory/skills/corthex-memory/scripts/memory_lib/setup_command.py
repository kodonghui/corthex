"""The setup command (API-031; SPEC-011; TASK-043): a script for a temporary device.

The command runner parses `setup --at <folder>`, an absolute POSIX path of at
most 1,000 characters without a control character, but hands it to no handler
before the 0.3.0 activation, so it answers it as not implemented, as in C1;
until then the tests call this handler as the runner will, after its gates. It
reads only the gated configuration and writes nothing. A device without
consent at this release's version has none to carry: `no-consent`. Otherwise
the answer holds a POSIX shell script for the environment setup of a temporary
device, such as a cloud container, whose project is at that folder there.

The script takes `python3` from an absolute folder on PATH and runs the program
below with it in isolated mode, on Python 3.8 or later and its standard library
alone. The program carries the project's name and folder, and this device's
memory configuration with its consent but with this project alone, `temporary`
true and no sync settings (C3), and no key: the keys go into the environment's
secret settings (SPEC-031). The records that it writes come from the plugin's
own encoders here, so that only the device ID, the times and the epoch are
made there. It finds the store and the folders above it as the plugin does,
following a link there, and stops before it writes anything when the store
holds files besides the temporary files of a run that stopped while its store
records show no format 2, or when a folder that it needs cannot be one, a link
in the store included. Otherwise it writes each file only when the file and its
backup are missing, private and whole, never through a link inside the store:

- the project list `~/.corthex/projects.json`, naming the project at the folder;
- the format-2 store record, with a new device ID;
- the memory configuration, with the project enabled since the run;
- the folders that `on` makes, and the folder `runs`, then, while the project
  holds no memory, its first records as a migration writes them (TASK-074), the
  curation record last with a new epoch, so that the next run finishes a run
  that stopped part way.

A project list or configuration that it keeps, as when the device sets up a
second project or memory was turned off there, may not name the project at its
folder or turn memory on for it with that consent. The program then says so in
a note and still ends without an error, so that the environment starts.
"""
import json

from . import base, commands, enablement, format2, migration_command, migration_initialize, migration_plan

SAY = {
    'ok': "Put this script in the environment's setup, and the two memory keys in its secret settings.",
    'no-consent': ('This device has no memory consent to carry. Turn memory on here first, with the '
                   "user's yes; the script then carries that consent."),
}
DELIMITER = 'CORTHEX_MEMORY_SETUP'
# What the program replaces when it runs: the device ID, the times and the epoch.
DEVICE, TIME, EPOCH = 'd_000000000000', '1970-01-01T00:00:00.000Z', '0' * 32
# The folders of a project whose files are its memory, besides its first records: all that `on` and the
# setup make but `notices`, `injections` and `layer`, as a test keeps them.
HOLDING = ('raw', 'unprocessed', 'layer/items', 'layer/tombstones', 'runs')
SHELL = """#!/bin/sh
# CORTHEX memory setup for a temporary device: the project {project}, from corthex-memory {release}.
# It writes the project list, the memory store record, the memory configuration with the consent
# given on the device that printed it, and the project's folder, each only where it is missing.
# It holds no key: put CORTHEX_MEMORY_ANTHROPIC_API_KEY and CORTHEX_MEMORY_OPENAI_API_KEY
# in the environment's secret settings.
set -eu
python=$(
  IFS=:
  set -f
  for folder in ${{PATH-}}; do
    case "$folder" in
    /*) if [ -f "$folder/python3" ] && [ -x "$folder/python3" ]; then printf '%s\\n' "$folder/python3"; break; fi ;;
    esac
  done
)
if [ -z "$python" ]; then
  echo 'CORTHEX memory setup needs python3, Python 3.8 or later, in an absolute folder on PATH.' >&2
  exit 1
fi
"$python" -I - <<'{delimiter}'
{program}{delimiter}
"""
# Run with `python3 -I -` from the heredoc above. Text, not code of this module: ASCII only, and its
# values come in one ASCII line, so that no line of it can end the heredoc.
PROGRAM = r'''import sys
if sys.version_info < (3, 8):
    sys.exit('CORTHEX memory setup needs Python 3.8 or later; nothing was written.')
import json
import os
import re
import secrets
import stat
from datetime import datetime, timezone

VALUES = json.loads(@VALUES@)
# The folders whose files are a project's memory besides its first records, and the temporary files that a
# run that stopped leaves beside a store record, as the plugin names them.
HOLDING = tuple(VALUES['holding'])
TEMPORARY = re.compile(VALUES['temporary'])


class Stop(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def device():
    bits = secrets.randbits(60)
    return 'd_' + ''.join(VALUES['letters'][(bits >> shift) & 31] for shift in range(55, -1, -5))


def document(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def kind(path):
    """What is at a path, without following a link: None, 'folder', 'file' or 'other'."""
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return None
    return 'folder' if stat.S_ISDIR(mode) else 'file' if stat.S_ISREG(mode) else 'other'


def read(path, follow=False):
    """A file's JSON document; None when it is missing or does not read, or is a link not followed."""
    if not follow and kind(path) != 'file':
        return None
    try:
        with open(path, 'rb') as stream:
            return json.loads(stream.read().decode('utf-8-sig'))
    except (OSError, ValueError):
        return None


def places(store, root):
    """The folders that the setup makes in the store, each after the folder that holds it."""
    return ([os.path.join(store, 'logs'), os.path.dirname(root), root] +
            [os.path.join(root, *name.split('/')) for name in VALUES['folders']])


def reachable(path):
    """Stop unless the nearest place on a path that is there is a folder, following a link as the plugin does."""
    while not os.path.lexists(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        raise Stop(path + ' is not a folder; nothing was written')


def formatted(path):
    """Whether the store records show format 2: one reads so, and none that reads shows another format."""
    shown = [value for value in (read(path), read(path + '.bak')) if value is not None]
    return bool(shown) and all(isinstance(value, dict) and value.get('format') == 2 and
                               'migrating' not in value for value in shown)


def check(store, listing, root):
    """Stop before anything is written when the store or a folder that the setup needs is not fit."""
    reachable(os.path.dirname(listing))
    reachable(store)
    names = os.listdir(store) if os.path.isdir(store) else []
    if any(not TEMPORARY.match(name) for name in names) and not formatted(os.path.join(store, 'store.json')):
        raise Stop('the memory store ' + store + ' holds files without a format-2 store record; '
                   'nothing was written, and the memory status says what it needs')
    for path in places(store, root):
        if kind(path) not in (None, 'folder'):
            raise Stop(path + ' is not a folder; nothing was written')


def parents(path):
    """A missing folder and its missing parents, made private as the plugin makes them."""
    missing = []
    while not os.path.lexists(path):
        missing.append(path)
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        raise Stop(path + ' is not a folder')
    for path in reversed(missing):
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)


def folder(path):
    """A missing folder in the store, made private; anything else in its place, a link too, stops."""
    found = kind(path)
    if found is None:
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)
    elif found != 'folder':
        raise Stop(path + ' is not a folder')


def synced(path):
    """The folder that holds a file, flushed where the file system allows it."""
    try:
        handle = os.open(os.path.dirname(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)


def write(path, data):
    """A missing file, written whole and private; a file, a backup or a link in its place is kept."""
    if kind(path) is not None or kind(path + '.bak') is not None:
        print('kept ' + path)
        return
    temporary = path + '.' + secrets.token_hex(4) + '.tmp'
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    placed = False
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            placed = True
        except FileExistsError:
            pass
        except OSError:
            # A file system without hard links: the whole file moves into the place still empty,
            # since the setup runs before any host that could write there.
            if kind(path) is None:
                os.rename(temporary, path)
                placed = True
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    synced(path)
    print(('wrote ' if placed else 'kept ') + path)


def holds(root):
    """Whether a project's folder holds memory: a file in a folder that keeps it, or a first record or
    its backup that is no longer as a migration first writes it."""
    if any(os.listdir(os.path.join(root, *name.split('/'))) for name in HOLDING):
        return True
    for name, text in VALUES['files']:
        path = os.path.join(root, *name.split('/'))
        for candidate in (path, path + '.bak'):
            if kind(candidate) == 'file':
                with open(candidate, 'rb') as stream:
                    if stream.read() != text.encode('utf-8'):
                        return True
    return False


def same(raw):
    """Whether a folder that the project list names is the project's folder, by identity when both are there."""
    if not isinstance(raw, str) or not raw.strip():
        return False
    path = os.path.expanduser(raw)
    try:
        return os.path.samefile(path, VALUES['at'])
    except OSError:
        return os.path.normpath(path) == os.path.normpath(VALUES['at'])


def notes(listing, configuration, root, held):
    """What a kept project list, configuration or project folder lacks, read as the plugin reads them."""
    found = []
    value = read(listing, follow=True)
    entries = value.get('projects') if isinstance(value, dict) else None
    named = [entry for entry in entries if isinstance(entry, dict) and
             entry.get('name') == VALUES['project']] if isinstance(entries, list) else []
    folders = [entry.get('path') for entry in named]
    for entry in named:
        if isinstance(entry.get('repos'), dict):
            folders.extend(entry['repos'].values())
    if not named:
        found.append(listing + ' does not name the project ' + VALUES['project'] +
                     '; the corthex skill can add it in a session')
    elif not any(same(raw) for raw in folders):
        found.append(listing + ' names the project ' + VALUES['project'] + ' at another folder than ' +
                     VALUES['at'] + '; the corthex skill can change it in a session')
    value = read(configuration)
    if value is None:
        value = read(configuration + '.bak')
    settings = value if isinstance(value, dict) else {}
    projects = settings.get('projects')
    entry = projects.get(VALUES['project']) if isinstance(projects, dict) else None
    consent = settings.get('consent')
    if not (isinstance(entry, dict) and entry.get('enabled') is True and isinstance(consent, dict) and
            consent.get('version') == VALUES['configuration']['consent']['version']):
        found.append(configuration + ' does not turn memory on for ' + VALUES['project'] +
                     ' with the consent that this script carries; the memory skill can in a session')
    if settings.get('temporary') is False:
        found.append(configuration + ' says that this device is not temporary, so it curates on its usual '
                     'triggers rather than after every turn')
    curation = os.path.join(root, 'curation.json')
    if held and kind(curation) is None and kind(curation + '.bak') is None:
        found.append(root + ' holds memory without a curation record; the memory status says what it needs')
    return found


def main():
    try:
        sys.stdout.reconfigure(errors='backslashreplace')
    except (AttributeError, ValueError):
        pass
    home = os.path.expanduser('~')
    if not os.path.isabs(home):
        raise Stop('the home folder is not known; nothing was written')
    override = os.environ.get('CORTHEX_MEMORY_HOME')
    store = os.path.expanduser(override) if override else os.path.join(home, '.corthex', 'corthex-memory')
    if not os.path.isabs(store):
        raise Stop('CORTHEX_MEMORY_HOME must be an absolute path; nothing was written')
    listing = os.path.join(home, '.corthex', 'projects.json')
    root = os.path.join(store, 'projects', VALUES['folder'])
    check(store, listing, root)
    parents(os.path.dirname(listing))
    write(listing, document({'projects': [{'name': VALUES['project'], 'path': VALUES['at']}]}))
    parents(store)
    record = VALUES['store']
    record.update(device=device(), made=now())
    write(os.path.join(store, 'store.json'), document(record))
    settings = VALUES['configuration']
    settings['projects'][VALUES['project']]['since'] = now()
    configuration = os.path.join(store, 'configuration.json')
    write(configuration, document(settings))
    for path in places(store, root):
        folder(path)
    held = holds(root)
    if held:
        print('kept ' + root + ', which holds memory')
    else:
        for name, text in VALUES['files']:
            write(os.path.join(root, *name.split('/')), text.encode('utf-8'))
        progress = VALUES['curation']
        progress['fence']['epoch'] = secrets.token_hex(16)
        write(os.path.join(root, 'curation.json'), document(progress))
    for note in notes(listing, configuration, root, held):
        print('note: ' + note + '.', file=sys.stderr)


try:
    main()
except Stop as reason:
    sys.exit('CORTHEX memory setup stopped: ' + str(reason) + '.')
except OSError as error:
    sys.exit('CORTHEX memory setup stopped: ' + (error.strerror or type(error).__name__) +
             (' at ' + str(error.filename) if error.filename else '') + '.')
'''


def script(project, at, release, document):
    """The setup script's text for `document`, this device's memory configuration (TBL-002) with its consent."""
    entry = {'enabled': True, 'since': TIME}
    left_out = (document.get('projects') or {}).get(project, {}).get('left_out')
    if left_out is not None:
        entry['left_out'] = left_out
    settings = {key: value for key, value in document.items() if key not in ('projects', 'temporary', 'sync')}
    settings.update(projects={project: entry}, temporary=True)
    values = {
        'project': project, 'folder': base.project_folder_name(project), 'at': at, 'letters': base.CROCKFORD,
        'folders': list(enablement.PROJECT_FOLDERS) + ['runs'], 'holding': list(HOLDING),
        'temporary': migration_plan._TEMP.pattern,
        'store': json.loads(format2.store_bytes(dict(format=2, device=DEVICE, made=TIME, release=release))),
        'configuration': base._ordered(settings, 'TBL-002'),
        'files': [[name, data.decode('utf-8')] for name, data in migration_initialize.first_records()],
        'curation': json.loads(migration_plan.progress(None, epoch=EPOCH)),
    }
    text = json.dumps(values, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
    program = PROGRAM.replace('@VALUES@', repr(text))
    if not program.isascii() or any(line == DELIMITER for line in program.splitlines()):
        raise ValueError('the setup program cannot stay inside its heredoc')
    return SHELL.format(project=project, release=release, delimiter=DELIMITER, program=program)


def setup(context):
    """`setup --at <folder>`: the script, or `no-consent` on a device without consent at this version."""
    project = context.project.name
    if not context.configuration.consented():
        return commands.result('setup', {'project': project}, SAY['no-consent'], 'refused', 'no-consent')
    at = context.arguments['at']
    text = script(project, at, migration_command.release(), context.configuration.document)
    return commands.result('setup', {'project': project, 'at': at, 'script': text}, SAY['ok'])
