"""TASK-043: the setup command (API-031; SPEC-011) and the script that it prints.

TC-241 to TC-244 at the direct boundary. The runner parses `setup --at` but
hands it to no handler before the 0.3.0 activation, which a test checks, so
these tests call the handler as the runner will, after its gates. The script is
a POSIX shell script: on Linux and macOS the tests run it with a `python3` that
is the Python running them, so that the CI job of Python 3.8 runs it with 3.8,
in made-up homes; no key is real, no worker process starts and nothing leaves
the machine.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (base, clock, commands, configuration, curation_triggers, enablement, files, format2,
                        migration_initialize, migration_plan, projects, setup_command, store, worker_launch)
from memory_lib.c2_store import C2Store

AT = '2026-11-04T13:00:00.000Z'
NOW = datetime(2026, 11, 11, 9, 0, 0, tzinfo=timezone.utc)
MARKERS = {'CORTHEX_MEMORY_ANTHROPIC_API_KEY': 'anthropic-marker-' + secrets.token_hex(8),
           'CORTHEX_MEMORY_OPENAI_API_KEY': 'openai-marker-' + secrets.token_hex(8)}
LEFT_OUT = {'kinds': ['answer'], 'folders': ['private notes']}
TIME = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z\Z')


def device_document(left_out=LEFT_OUT):
    """A printing device's configuration: another project, its own retention and triggers, not temporary."""
    entry = {'enabled': True, 'since': AT}
    if left_out is not None:
        entry['left_out'] = left_out
    return {'consent': {'at': AT, 'version': 1}, 'retention': {'days': 30}, 'triggers': {'minutes': 20},
            'projects': {'sample': entry, 'other': {'enabled': True, 'since': AT}}, 'temporary': False}
POSIX = unittest.skipIf(os.name == 'nt', 'the setup script is a POSIX shell script')


def settings(consent=1, left_out=None):
    document = device_document(left_out)
    if consent is None:
        del document['consent']
    else:
        document['consent']['version'] = consent
    return configuration.prepare(document)


def setup(at, config):
    context = commands.Context('setup', {'folder': '/', 'at': at}, None, None)
    context.project = types.SimpleNamespace(name='sample')
    context.configuration = config
    value = setup_command.setup(context)
    commands.validate_result(value, 'setup')
    return value


def tree(folder):
    """Each file under a folder with its bytes, each link with its target and each folder, by relative POSIX path."""
    found = {}
    for path in sorted(Path(folder).rglob('*')):
        relative = path.relative_to(folder).as_posix()
        if path.is_symlink():
            found[relative] = ('link', os.readlink(str(path)))
        else:
            found[relative] = None if path.is_dir() else path.read_bytes()
    return found


class SetupHandlerTest(unittest.TestCase):
    def test_tc242_a_device_without_consent_at_this_version_gets_no_script(self):
        for consent in (None, 2):
            with self.subTest(consent=consent):
                value = setup('/workspace/sample', settings(consent))
                self.assertEqual(value, dict(command='setup', outcome='refused', code='no-consent',
                                             say=setup_command.SAY['no-consent'], data={'project': 'sample'}))

    def test_tc243_the_script_holds_no_key_and_carries_the_consent_and_what_is_left_out(self):
        with mock.patch.dict(os.environ, MARKERS):
            value = setup('/workspace/sample', settings(left_out=LEFT_OUT))
        self.assertEqual((value['outcome'], value['code'], value['say']), ('done', 'ok', setup_command.SAY['ok']))
        self.assertEqual(sorted(value['data']), ['at', 'project', 'script'])
        self.assertEqual(value['data']['at'], '/workspace/sample')
        text = value['data']['script']
        for marker in MARKERS.values():
            self.assertNotIn(marker, text)
        self.assertTrue(text.startswith('#!/bin/sh\n'))
        self.assertTrue(text.endswith("\n%s\n" % setup_command.DELIMITER))
        self.assertTrue(text.isascii())
        program = text.split("<<'%s'\n" % setup_command.DELIMITER, 1)[1]
        self.assertEqual(program.splitlines().count(setup_command.DELIMITER), 1)
        # The program uses Python's standard library alone.
        self.assertEqual(set(re.findall(r'^(?:import|from) (\w+)', program, re.M)),
                         {'sys', 'json', 'os', 're', 'secrets', 'stat', 'datetime'})
        values = json.loads(eval(re.search(r'^VALUES = json\.loads\((.*)\)$', program, re.M).group(1)))
        self.assertEqual(sorted(values), ['at', 'configuration', 'curation', 'files', 'folder', 'folders',
                                          'holding', 'letters', 'project', 'store', 'temporary'])
        self.assertEqual((values['project'], values['folder'], values['at']), ('sample', 'sample', '/workspace/sample'))
        carried = values['configuration']
        self.assertEqual(carried, {'consent': {'at': AT, 'version': 1}, 'projects': {'sample': {
            'enabled': True, 'since': setup_command.TIME, 'left_out': {'folders': ['private notes'], 'kinds': ['answer']}}},
            'retention': {'days': 30}, 'triggers': {'minutes': 20}, 'temporary': True})
        self.assertEqual(list(carried), ['consent', 'projects', 'retention', 'triggers', 'temporary'])
        self.assertEqual(list(carried['projects']['sample']['left_out']), ['folders', 'kinds'])
        # The records come from the plugin's encoders; the folders are those of `on` and `runs`.
        self.assertEqual(values['store'], {'format': 2, 'device': setup_command.DEVICE, 'made': setup_command.TIME,
                                           'release': setup_command.migration_command.release()})
        self.assertEqual(values['curation']['fence'], {'epoch': setup_command.EPOCH, 'generation': 0, 'revisions': {}})
        self.assertEqual(values['folders'], list(enablement.PROJECT_FOLDERS) + ['runs'])
        self.assertEqual(values['letters'], base.CROCKFORD)
        self.assertEqual(values['temporary'], migration_plan._TEMP.pattern)
        # Every folder that holds a project's memory counts as such; a new folder of `on` needs a decision here.
        self.assertEqual(set(values['folders']) - set(values['holding']), {'notices', 'injections', 'layer'})
        self.assertLessEqual(set(values['holding']), set(values['folders']))
        # Sync settings stay on this device until C3, and so does every other project.
        text = setup_command.script('sample', '/w', '0.3.0', dict(device_document(), sync={'address': 'https://example.invalid/m.git'}))
        self.assertNotIn('example.invalid', text)
        self.assertNotIn('other', text.split('VALUES = ', 1)[1].split('\n', 1)[0])
        # A reserved name keeps its folder name on every system.
        self.assertIn('"folder":"con_"', setup_command.script('con', '/w', '0.3.0', {'consent': {'at': AT, 'version': 1}}))

    def test_the_shell_part_runs_no_command_substitution_and_the_api_example_shows_it(self):
        text = setup_command.script('corthex', '/workspace/corthex', '0.3.0', {'consent': {'at': AT, 'version': 1}})
        mark = "<<'%s'\n" % setup_command.DELIMITER
        shell = text.split(mark, 1)[0]
        # macOS's /bin/sh is bash 3.2, which misreads some text inside a command substitution.
        self.assertNotIn('$(', shell)
        self.assertNotIn('`', shell)
        example = json.loads((ROOT / 'docs/06-api/memory-examples.json').read_text(encoding='utf-8'))
        example = example['result']['valid']['setup']['data']
        self.assertEqual((example['project'], example['at']), ('corthex', '/workspace/corthex'))
        self.assertEqual(example['script'].split(mark, 1)[0], shell)

    def test_the_runner_takes_only_an_absolute_posix_folder(self):
        for at in ('workspace/sample', '~/sample', 'C:\\work', '', '/a\nb', '/a\tb', '/' + 'a' * 1000,
                   '/a\udcff'):
            with self.subTest(at=at):
                with self.assertRaises(commands.UsageError):
                    commands.parser().parse_args(['setup', '--at', at])
        for at in ('/', '/workspace/sample', '/작업/샘플 폴더', '/' + 'a' * 999):
            with self.subTest(at=at):
                self.assertEqual(vars(commands.parser().parse_args(['setup', '--at', at]))['at'], at)
        self.assertNotIn('setup', commands.CHANGES)
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_HOME': str(Path(temporary).resolve() / 'memory')}):
                value, status = commands.run(['setup', '--at', 'relative'])
        self.assertEqual((value['code'], status), ('usage', 2))


@POSIX
class SetupScriptTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / 'home'
        self.home.mkdir()
        self.work = self.base / 'workspace' / 'sample'
        self.work.mkdir(parents=True)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        (self.bin / 'python3').symlink_to(sys.executable)
        self.store = self.home / '.corthex' / 'corthex-memory'
        self.root = self.store / 'projects' / 'sample'
        self.text = setup_command.script('sample', str(self.work), '0.3.0', device_document())
        self.path = self.base / 'setup.sh'
        self.path.write_text(self.text, encoding='utf-8')

    def run_script(self, path=None, home=None, **environment):
        values = dict(HOME=str(home or self.home), PATH=str(self.bin) + os.pathsep + '/usr/bin:/bin')
        values.update(MARKERS)
        values.update(environment)
        return subprocess.run([shutil.which('sh') or '/bin/sh', str(path or self.path)], env=values,
                              cwd=str(self.base), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=60)

    def read_store(self, folder=None):
        folder = folder or self.store
        device = json.loads((folder / 'store.json').read_text(encoding='utf-8'))['device']
        memory = C2Store(folder, expected_device=device)
        return memory, memory.record(deadline=clock.now() + 10), memory.configuration(deadline=clock.now() + 10)

    def test_tc241_a_fresh_device_gets_a_format_2_store_with_this_consent_and_the_project_enabled(self):
        done = self.run_script()
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        registry = self.home / '.corthex' / 'projects.json'
        self.assertEqual(json.loads(registry.read_text(encoding='utf-8')),
                         {'projects': [{'name': 'sample', 'path': str(self.work)}]})
        (self.work / 'src').mkdir()
        found = projects.locate(self.work / 'src', registry)
        self.assertEqual((found.name, found.folder), ('sample', self.work))
        memory, record, config = self.read_store()
        self.assertEqual((record['format'], record['release']), (2, '0.3.0'))
        self.assertRegex(record['device'], store.DEVICE)
        self.assertTrue(config.consented())
        self.assertTrue(config.enabled('sample'))
        self.assertIs(config.values['temporary'], True)
        since = config.document['projects']['sample']['since']
        self.assertRegex(since, TIME)
        self.assertEqual(config.document, {'consent': {'at': AT, 'version': 1}, 'retention': {'days': 30},
                                           'triggers': {'minutes': 20}, 'temporary': True,
                                           'projects': {'sample': {'enabled': True, 'since': since, 'left_out': LEFT_OUT}}})
        self.assertEqual((config.values['retention']['days'], config.values['triggers']['minutes']), (30, 20))
        self.assertEqual(record['made'][:10], since[:10])
        progress = format2.parse_curation((self.root / 'curation.json').read_bytes())
        self.assertEqual((progress['logs'], progress['applies'], progress['recent']), ({}, 0, []))
        self.assertEqual((progress['fence']['generation'], progress['fence']['revisions']), (0, {}))
        # The bytes are those that the plugin writes for the same records.
        raw = (self.store / 'store.json').read_bytes()
        self.assertEqual(format2.store_bytes(format2.parse_store(raw)), raw)
        raw = (self.store / 'configuration.json').read_bytes()
        self.assertEqual(base.json_bytes(json.loads(raw.decode('utf-8')), 'TBL-002'), raw)
        raw = (self.root / 'curation.json').read_bytes()
        self.assertEqual(format2.curation_bytes(format2.parse_curation(raw)), raw)
        # The project's first records are those of a migration (TASK-074), and the folders those of `on`.
        intent = types.SimpleNamespace(encoded=json.dumps({'sources': []}), progress=(('sample', b''),))
        made = {path[len('projects/sample/'):]: data for kind, path, data in
                migration_initialize.recipes(intent, {}) if kind == 'file'}
        made.pop('curation.json'), made.pop('curation.json.bak')
        self.assertEqual({name: (self.root / name).read_bytes() for name in made}, made)
        folders = {path.relative_to(self.store).as_posix() for path in self.store.rglob('*') if path.is_dir()}
        self.assertEqual(folders, {'logs', 'projects', 'projects/sample'} | {
            'projects/sample/' + name for name in ('raw', 'unprocessed', 'notices', 'injections', 'layer',
                                                   'layer/items', 'layer/tombstones', 'runs')})
        for path in [self.home / '.corthex', *self.store.rglob('*'), self.store, registry]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600, path)
        # Another fresh device gets its own device ID and epoch.
        other = self.base / 'other'
        other.mkdir()
        self.assertEqual(self.run_script(home=other).returncode, 0)
        _, again, _ = self.read_store(other / '.corthex' / 'corthex-memory')
        self.assertNotEqual(again['device'], record['device'])
        epoch = format2.parse_curation((other / '.corthex/corthex-memory/projects/sample/curation.json')
                                       .read_bytes())['fence']['epoch']
        self.assertNotEqual(epoch, progress['fence']['epoch'])

    def test_tc243_run_twice_each_file_is_written_only_when_it_is_missing_and_no_key_reaches_it(self):
        registry = self.home / '.corthex' / 'projects.json'
        registry.parent.mkdir()
        listed = '{"projects": [{"name": "other", "path": "/elsewhere"}, {"name": "sample", "path": "%s"}]}' % self.work
        registry.write_text(listed, encoding='utf-8')
        done = self.run_script()
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertIn('kept ' + str(registry), done.stdout.splitlines())
        self.assertEqual(registry.read_text(encoding='utf-8'), listed)
        first = tree(self.store)
        (self.store / 'configuration.json').unlink()
        (self.root / 'layer' / 'pins.json').unlink()
        done = self.run_script()
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        wrote = sorted(line for line in done.stdout.splitlines() if line.startswith('wrote '))
        self.assertEqual(wrote, ['wrote ' + str(self.store / 'configuration.json'),
                                 'wrote ' + str(self.root / 'layer' / 'pins.json')])
        second = tree(self.store)
        self.assertEqual({key: value for key, value in second.items() if key != 'configuration.json'},
                         {key: value for key, value in first.items() if key != 'configuration.json'})
        self.assertNotEqual(second['configuration.json'], b'')
        stamps = {path: path.stat().st_mtime_ns for path in self.store.rglob('*')}
        done = self.run_script()
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertFalse([line for line in done.stdout.splitlines() if not line.startswith('kept ')])
        self.assertEqual(tree(self.store), second)
        self.assertEqual({path: path.stat().st_mtime_ns for path in self.store.rglob('*')}, stamps)
        for path in [registry, *self.store.rglob('*')]:
            if path.is_file():
                for marker in MARKERS.values():
                    self.assertNotIn(marker.encode(), path.read_bytes())
        self.assertFalse([path for path in self.home.rglob('*.tmp')])

    def test_tc244_one_unprocessed_turn_on_the_set_up_device_starts_the_worker(self):
        self.assertEqual(self.run_script().returncode, 0)
        memory, record, config = self.read_store()
        marker = '%s.claude-code-0123456789abcdef.1' % NOW.strftime('%Y%m%dT%H%M%SZ')
        (self.root / 'unprocessed' / marker).write_bytes(b'')
        failures = []
        logger = mock.Mock(failure=lambda *args, **options: failures.append((args, options)))
        with mock.patch.object(worker_launch.subprocess, 'Popen') as popen:
            outcome = curation_triggers.start(memory, config, 'sample', 'end-of-turn', clock.now() + 10, logger,
                                              host='claude-code', now=NOW,
                                              environment={'CORTHEX_MEMORY_ANTHROPIC_API_KEY': 'fixture-key'})
        self.assertEqual((outcome, failures), ('started', []))
        self.assertEqual(popen.call_args.args[0][-6:], ['--reason', 'end-of-turn', '--project', 'sample',
                                                         '--expect-device', record['device']])

    def test_a_store_without_a_format_2_record_stops_the_script_before_it_writes_anything(self):
        cases = (('holds files without a store record', {'logs/failures.jsonl': b''}),
                 ('format 1', {'store.json': base.json_bytes(store.new_record('0.2.1'), 'TBL-001')}),
                 ('damaged', {'store.json': b'{"format": 2'}),
                 ('migrating', {'store.json': format2.store_bytes(dict(
                     format=2, device='d_0123456789ab', made=AT, release='0.3.0',
                     migrating={'from': 1, 'to': 2, 'started': AT}), allow_migrating=True)}),
                 ('a format-1 backup', {'store.json': format2.store_bytes(dict(
                     format=2, device='d_0123456789ab', made=AT, release='0.3.0')),
                     'store.json.bak': base.json_bytes(store.new_record('0.2.1'), 'TBL-001')}),
                 ('a link in the record\'s place', {'store.json.bak': b''}))
        for name, contents in cases:
            with self.subTest(name):
                # Each case starts from an empty store, also after the one before it failed.
                if self.store.exists():
                    shutil.rmtree(str(self.store))
                self.store.mkdir(parents=True)
                for relative, data in contents.items():
                    (self.store / relative).parent.mkdir(parents=True, exist_ok=True)
                    (self.store / relative).write_bytes(data)
                if name == "a link in the record's place":
                    (self.store / 'store.json.bak').unlink()
                    good = self.base / 'record.json'
                    good.write_bytes(format2.store_bytes(dict(format=2, device='d_0123456789ab', made=AT,
                                                              release='0.3.0')))
                    (self.store / 'store.json').symlink_to(good)
                before = tree(self.home)
                done = self.run_script()
                self.assertEqual(done.returncode, 1)
                self.assertEqual(done.stdout, '')
                self.assertIn('CORTHEX memory setup stopped: the memory store %s holds files without a format-2 '
                              'store record; nothing was written' % self.store, done.stderr)
                self.assertEqual(tree(self.home), before)

    def test_an_existing_format_2_store_keeps_its_records_and_gains_the_project(self):
        device = 'd_0123456789ab'
        self.store.mkdir(parents=True)
        files.write_json(self.store / 'store.json', dict(format=2, device=device, made=AT, release='0.3.0'), 'TBL-001')
        kept = {'consent': {'at': AT, 'version': 1}, 'projects': {'other': {'enabled': True, 'since': AT},
                                                                   'sample': {'enabled': True, 'since': AT}}}
        files.write_json(self.store / 'configuration.json', kept, 'TBL-002')
        before = {name: (self.store / name).read_bytes() for name in ('store.json', 'configuration.json')}
        done = self.run_script(CORTHEX_MEMORY_HOME='')
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertEqual({name: (self.store / name).read_bytes() for name in before}, before)
        self.assertTrue((self.root / 'curation.json').is_file())
        # Its own memory home, when CORTHEX_MEMORY_HOME names one, as the plugin finds it.
        elsewhere = self.base / 'elsewhere' / 'memory'
        done = self.run_script(CORTHEX_MEMORY_HOME=str(elsewhere))
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertEqual(self.read_store(elsewhere)[1]['format'], 2)
        self.assertTrue((elsewhere / 'projects' / 'sample' / 'curation.json').is_file())
        before = tree(self.home)
        done = self.run_script(CORTHEX_MEMORY_HOME='relative/memory')
        self.assertEqual(done.returncode, 1)
        self.assertIn('CORTHEX_MEMORY_HOME must be an absolute path; nothing was written', done.stderr)
        self.assertEqual(tree(self.home), before)

    def test_a_kept_list_or_configuration_without_the_project_gets_a_note_and_the_setup_still_ends(self):
        registry = self.home / '.corthex' / 'projects.json'
        configuration = self.store / 'configuration.json'
        list_note = ('note: %s does not name the project sample; the corthex skill can add it in a session.'
                     % registry)
        settings_note = ('note: %s does not turn memory on for sample with the consent that this script '
                         'carries; the memory skill can in a session.' % configuration)
        others = {'consent': {'at': AT, 'version': 1}, 'projects': {'other': {'enabled': True, 'since': AT}}}
        off = {'consent': {'at': AT, 'version': 1}, 'projects': {'sample': {'enabled': False, 'since': AT}}}
        unconsented = {'projects': {'sample': {'enabled': True, 'since': AT}}}
        lasting = {'consent': {'at': AT, 'version': 1}, 'projects': {'sample': {'enabled': True, 'since': AT}},
                   'temporary': False}
        lasting_note = ('note: %s says that this device is not temporary, so it curates on its usual triggers '
                        'rather than after every turn.' % configuration)
        named = {'projects': [{'name': 'sample', 'path': str(self.work)}]}
        cases = (('another project', {'name': 'other', 'path': '/elsewhere'}, others, [list_note, settings_note]),
                 ('memory turned off', named, off, [settings_note]),
                 ('no consent', named, unconsented, [settings_note]),
                 ('not temporary', named, lasting, [lasting_note]),
                 ('a damaged list', b'{"projects": [', None, [list_note]))
        for name, listed, kept, expected in cases:
            with self.subTest(name):
                # Each case starts from an empty home, also after the one before it failed.
                if registry.parent.exists():
                    shutil.rmtree(str(registry.parent))
                registry.parent.mkdir()
                if isinstance(listed, bytes):
                    registry.write_bytes(listed)
                else:
                    registry.write_text(json.dumps(listed if 'projects' in listed else {'projects': [listed]}),
                                        encoding='utf-8')
                if kept is not None:
                    self.store.mkdir(parents=True, exist_ok=True)
                    files.write_json(self.store / 'store.json', dict(format=2, device='d_0123456789ab', made=AT,
                                                                     release='0.3.0'), 'TBL-001')
                    files.write_json(configuration, kept, 'TBL-002')
                before = {path: path.read_bytes() for path in (registry, configuration) if path.exists()}
                done = self.run_script()
                self.assertEqual(done.returncode, 0)
                self.assertEqual(done.stderr.splitlines(), expected)
                self.assertEqual({path: path.read_bytes() for path in before}, before)
                self.assertTrue((self.root / 'curation.json').is_file())
        # A list that a link names, as the plugin reads it, and a configuration that only its backup
        # holds, as the plugin restores it, carry the project: no note.
        shutil.rmtree(str(registry.parent))
        registry.parent.mkdir()
        elsewhere = self.base / 'projects.json'
        elsewhere.write_text(json.dumps(named), encoding='utf-8')
        registry.symlink_to(elsewhere)
        self.store.mkdir(parents=True)
        files.write_json(self.store / 'store.json', dict(format=2, device='d_0123456789ab', made=AT,
                                                         release='0.3.0'), 'TBL-001')
        (self.store / 'configuration.json.bak').write_bytes(base.json_bytes(
            {'consent': {'at': AT, 'version': 1}, 'projects': {'sample': {'enabled': True, 'since': AT}}}, 'TBL-002'))
        done = self.run_script()
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertIn('kept ' + str(configuration), done.stdout.splitlines())
        self.assertFalse(configuration.exists())
        linked = self.base / 'linked-sample'
        linked.symlink_to(self.work, target_is_directory=True)
        for name, entry, expected in (
                ('another folder', {'name': 'sample', 'path': '/old/checkout'},
                 ['note: %s names the project sample at another folder than %s; the corthex skill can change it '
                  'in a session.' % (registry, self.work)]),
                ('an alias', {'name': 'sample', 'path': '/old/checkout', 'repos': {'app': str(self.work)}}, []),
                ('a link to the folder', {'name': 'sample', 'path': str(linked)}, []),
                ('the folder with a final slash', {'name': 'sample', 'path': str(self.work) + '/'}, [])):
            with self.subTest(name):
                elsewhere.write_text(json.dumps({'projects': [entry]}), encoding='utf-8')
                done = self.run_script()
                self.assertEqual((done.returncode, done.stderr.splitlines()), (0, expected))

    def test_a_torn_store_record_or_backup_beside_a_format_2_one_is_left_to_the_plugin(self):
        good = format2.store_bytes(dict(format=2, device='d_0123456789ab', made=AT, release='0.3.0'))
        for name, contents in (('torn backup', {'store.json': good, 'store.json.bak': b'{"format": 2'}),
                               ('torn record', {'store.json': b'{"format": 2', 'store.json.bak': good})):
            with self.subTest(name):
                # Each case starts from an empty home, also after the one before it failed.
                if (self.home / '.corthex').exists():
                    shutil.rmtree(str(self.home / '.corthex'))
                self.store.mkdir(parents=True)
                for relative, data in contents.items():
                    (self.store / relative).write_bytes(data)
                done = self.run_script()
                self.assertEqual((done.returncode, done.stderr), (0, ''))
                self.assertIn('kept ' + str(self.store / 'store.json'), done.stdout.splitlines())
                self.assertEqual({relative: (self.store / relative).read_bytes() for relative in contents}, contents)
                self.assertTrue((self.store / 'configuration.json').is_file())
                self.assertTrue((self.root / 'curation.json').is_file())

    def test_temporary_files_that_a_stopped_run_left_are_not_files_of_a_store(self):
        self.store.mkdir(parents=True)
        left = ['store.json.0a1b2c3d.tmp', 'store.json.bak.k_9x2m4p.tmp']
        for name in left:
            (self.store / name).write_bytes(b'{"format": 2')
        done = self.run_script()
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertEqual(self.read_store()[1]['format'], 2)
        self.assertEqual(sorted(path.name for path in self.store.glob('*.tmp')), sorted(left))
        # Another temporary file is a file of a store that the plugin would not take as empty.
        shutil.rmtree(str(self.home / '.corthex'))
        self.store.mkdir(parents=True)
        (self.store / 'configuration.json.0a1b2c3d.tmp').write_bytes(b'{"consent": ')
        done = self.run_script()
        self.assertEqual((done.returncode, done.stdout), (1, ''))
        self.assertIn('holds files without a format-2 store record; nothing was written', done.stderr)
        self.assertEqual(os.listdir(str(self.store)), ['configuration.json.0a1b2c3d.tmp'])

    def test_a_file_system_without_hard_links_still_gets_whole_private_files(self):
        folder = self.base / 'no-links'
        folder.mkdir()
        program = ('import os, sys\n'
                   'def refuse(*arguments, **options):\n'
                   '    raise PermissionError(1, "Operation not permitted")\n'
                   'os.link = refuse\n'
                   'exec(compile(sys.stdin.read(), "<setup>", "exec"), {"__name__": "__main__"})\n')
        (folder / 'python3').write_text('#!/bin/sh\nexec %s -I -c %s\n' % (shlex.quote(sys.executable),
                                                                         shlex.quote(program)), encoding='utf-8')
        (folder / 'python3').chmod(0o755)
        done = self.run_script(PATH=str(folder) + os.pathsep + '/usr/bin:/bin')
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        written = [line[len('wrote '):] for line in done.stdout.splitlines() if line.startswith('wrote ')]
        self.assertEqual(len(written), 10)
        for path in map(Path, written):
            self.assertEqual(stat.S_IMODE(path.lstat().st_mode), 0o600, path)
        memory, record, config = self.read_store()
        self.assertTrue(config.enabled('sample'))
        self.assertEqual(format2.parse_curation((self.root / 'curation.json').read_bytes())['applies'], 0)
        self.assertFalse([path for path in self.home.rglob('*.tmp')])

    def test_a_link_to_the_store_folder_is_followed_as_the_plugin_follows_it(self):
        real = self.base / 'disk' / 'memory'
        real.mkdir(parents=True)
        self.store.parent.mkdir()
        self.store.symlink_to(real, target_is_directory=True)
        done = self.run_script()
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertTrue((real / 'projects' / 'sample' / 'curation.json').is_file())
        memory, record, config = self.read_store()
        self.assertTrue(config.enabled('sample'))

    def test_a_run_that_stopped_part_way_is_finished_and_curated_memory_is_never_given_new_records(self):
        self.assertEqual(self.run_script().returncode, 0)
        for name in ('curation.json', 'state-history.jsonl', 'layer/state.json'):
            (self.root / name).unlink()
        self.assertEqual(self.run_script().returncode, 0)
        for name in ('curation.json', 'state-history.jsonl', 'layer/state.json'):
            self.assertTrue((self.root / name).is_file(), name)
        for name in ('curation.json', 'state-history.jsonl'):
            (self.root / name).unlink()
        (self.root / 'layer' / 'items' / 'i_0123456789ab.json').write_bytes(b'{}')
        before = tree(self.store)
        done = self.run_script()
        missing = ('note: %s holds memory without a curation record; the memory status says what it needs.\n'
                   % self.root)
        self.assertEqual((done.returncode, done.stderr), (0, missing))
        self.assertIn('kept %s, which holds memory' % self.root, done.stdout.splitlines())
        self.assertEqual(tree(self.store), before)
        # A first record that is no longer empty, or its backup, or a raw log is memory as well.
        (self.root / 'layer' / 'items' / 'i_0123456789ab.json').unlink()
        for name, data in (('layer/state.json', b'{"lines": [{"text": "kept"}]}\n'),
                           ('layer/pins.json.bak', b'{"pins": [{"item": "i_0123456789ab"}]}\n'),
                           ('raw/claude-code-0123456789abcdef.jsonl', b'{}\n')):
            with self.subTest(name):
                path = self.root / name
                original = path.read_bytes() if path.exists() else None
                path.write_bytes(data)
                before = tree(self.store)
                done = self.run_script()
                self.assertEqual((done.returncode, done.stderr), (0, missing))
                self.assertIn('kept %s, which holds memory' % self.root, done.stdout.splitlines())
                self.assertEqual(tree(self.store), before)
                self.assertFalse((self.root / 'curation.json').exists())
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)
        done = self.run_script()
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertIn('wrote ' + str(self.root / 'curation.json'), done.stdout.splitlines())

    def test_a_link_or_a_file_where_a_folder_goes_stops_the_script_before_it_writes_anything(self):
        outside = self.base / 'outside'
        outside.mkdir()
        self.store.mkdir(parents=True)
        files.write_json(self.store / 'store.json', dict(format=2, device='d_0123456789ab', made=AT,
                                                         release='0.3.0'), 'TBL-001')
        for place in ('projects', 'projects/sample', 'projects/sample/layer', 'logs', 'projects/sample/runs'):
            with self.subTest(place):
                path = self.store / place
                path.parent.mkdir(parents=True, exist_ok=True)
                if place.endswith('runs'):
                    path.write_bytes(b'')
                else:
                    path.symlink_to(outside, target_is_directory=True)
                before = tree(self.home)
                done = self.run_script()
                self.assertEqual((done.returncode, done.stdout), (1, ''))
                self.assertEqual(done.stderr, 'CORTHEX memory setup stopped: %s is not a folder; nothing was '
                                 'written.\n' % path)
                self.assertEqual((list(outside.iterdir()), tree(self.home)), ([], before))
                path.unlink()
        # A file above the store stops it as well.
        (self.base / 'a-file').write_bytes(b'')
        done = self.run_script(CORTHEX_MEMORY_HOME=str(self.base / 'a-file' / 'memory'))
        self.assertEqual((done.returncode, done.stdout), (1, ''))
        self.assertEqual(done.stderr, 'CORTHEX memory setup stopped: %s is not a folder; nothing was written.\n'
                         % (self.base / 'a-file'))
        self.assertFalse((self.home / '.corthex' / 'projects.json').exists())
        # A link in a file's place is kept, never written through.
        target = self.base / 'target.json'
        (self.store / 'projects' / 'sample' / 'curation.json').symlink_to(target)
        done = self.run_script()
        self.assertEqual(done.returncode, 0)
        self.assertIn('kept ' + str(self.root / 'curation.json'), done.stdout.splitlines())
        self.assertFalse(target.exists())

    def test_python3_only_in_the_current_folder_is_never_run(self):
        planted = self.base / 'python3'
        planted.write_text('#!/bin/sh\ntouch "%s"\n' % (self.base / 'planted-ran'), encoding='utf-8')
        planted.chmod(0o755)
        before = tree(self.home)
        done = self.run_script(PATH='.')
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stderr, 'CORTHEX memory setup needs python3, Python 3.8 or later, '
                                      'in an absolute folder on PATH.\n')
        self.assertFalse((self.base / 'planted-ran').exists())
        self.assertEqual(tree(self.home), before)
        for path in ('.:' + str(self.bin) + ':/usr/bin:/bin', ':bin:' + str(self.bin)):
            with self.subTest(path):
                done = self.run_script(PATH=path)
                self.assertEqual((done.returncode, done.stderr), (0, ''))
                self.assertFalse((self.base / 'planted-ran').exists())


if __name__ == '__main__':
    unittest.main()
