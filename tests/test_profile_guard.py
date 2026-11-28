"""BUG-251: local settings updates preserve unrelated data and require evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/corthex/skills/corthex/scripts/settings.py'

class GuardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / '.corthex').mkdir()
        self.profile = self.home / '.corthex/profile.json'
        self.projects = self.home / '.corthex/projects.json'
        self.profile.write_text(json.dumps({'nexus': {'url': 'v3', 'push': ['a', 'b']}, 'ask_before': ['deploys', 'merges'], 'unknown': {'x': 1}}))
        self.projects.write_text(json.dumps({'projects': [{'name': 'a', 'path': '/a'}, {'name': 'b', 'path': '/b'}], 'unknown': 1}))

    def run_guard(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home)), capture_output=True, text=True)

    def test_merge_and_backup(self):
        before = self.profile.read_text()
        self.assertEqual(self.run_guard('set', 'language', '"ko"').returncode, 0)
        data = json.loads(self.profile.read_text())
        self.assertEqual(data['unknown'], {'x': 1})
        self.assertEqual(data['nexus']['push'], ['a', 'b'])
        self.assertIn(before, [p.read_text() for p in self.profile.parent.glob('profile.json.*.bak')])

    def test_protected_reductions(self):
        for args in [('set', 'nexus.push', '["a"]'), ('set', 'ask_before', '["deploys"]'), ('set', 'nexus.url', '"v2"'), ('project', 'remove', 'a')]:
            self.assertNotEqual(self.run_guard(*args).returncode, 0, args)
        self.assertEqual(len(json.loads(self.projects.read_text())['projects']), 2)

    def test_ancestor_cannot_discard_unknown_fields(self):
        self.assertNotEqual(self.run_guard('set', 'nexus', 'null').returncode, 0)
        self.assertEqual(json.loads(self.profile.read_text())['nexus']['url'], 'v3')

    def test_authorized_reduction_and_separate_approval(self):
        args = ('--words', 'remove merges', '--place', 'chat', '--time', 'today')
        self.assertNotEqual(self.run_guard(*args, 'set', 'ask_before', '["deploys"]').returncode, 0)
        self.assertEqual(self.run_guard(*args, '--ask-before-words', 'yes, change approval rules', 'set', 'ask_before', '["deploys"]').returncode, 0)

    def test_init_only_creates_missing_profile(self):
        self.profile.unlink()
        self.assertEqual(self.run_guard('init', '{"language":"ko"}').returncode, 0)
        self.assertNotEqual(self.run_guard('init', '{}').returncode, 0)
        self.assertEqual(json.loads(self.profile.read_text())['language'], 'ko')

    def test_init_empty_profile(self):
        self.profile.unlink()
        self.assertEqual(self.run_guard('init', '{}').returncode, 0)
        self.assertEqual(json.loads(self.profile.read_text()), {})

    def test_project_update_preserves_unknown_fields(self):
        self.assertEqual(self.run_guard('--words', 'move', '--place', 'chat', '--time', 'today', '--reduction-words', 'move path', 'project', 'update', '{"name":"a","path":"/new"}').returncode, 0)
        self.assertEqual(json.loads(self.projects.read_text())['projects'][1]['name'], 'b')

    def test_delegation_and_push_changes_require_evidence(self):
        self.assertNotEqual(self.run_guard('set', 'checkpoints', '{"user": []}').returncode, 0)
        self.assertNotEqual(self.run_guard('set', 'nexus.push', '["a", "b", "c"]').returncode, 0)

    def test_removing_fields_requires_evidence(self):
        self.assertNotEqual(self.run_guard('unset', 'nexus').returncode, 0)
        args = ('--words', 'remove it', '--place', 'chat', '--time', 'today')
        self.assertEqual(self.run_guard(*args, '--reduction-words', 'remove push entries', 'unset', 'nexus').returncode, 0)
        self.assertNotIn('nexus', json.loads(self.profile.read_text()))
        self.assertEqual(self.run_guard(*args, '--reduction-words', 'remove project path', 'project-unset', 'a', 'path').returncode, 0)
        self.assertNotIn('path', json.loads(self.projects.read_text())['projects'][0])

    def test_symlinked_profile_is_left_unchanged(self):
        target = self.home / 'profile-target.json'
        self.profile.replace(target)
        try:
            self.profile.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links unavailable')
        before = target.read_bytes()
        self.assertNotEqual(self.run_guard('set', 'language', '"ko"').returncode, 0)
        self.assertTrue(self.profile.is_symlink())
        self.assertEqual(target.read_bytes(), before)

    def test_push_append_and_explicit_reduction(self):
        args = ('--words', 'add c', '--place', 'chat', '--time', 'today')
        self.assertEqual(self.run_guard(*args, 'append', 'nexus.push', '"c"').returncode, 0)
        self.assertEqual(json.loads(self.profile.read_text())['nexus']['push'], ['a', 'b', 'c'])
        self.assertNotEqual(self.run_guard(*args, 'set', 'nexus.push', '["c"]').returncode, 0)
        self.assertEqual(self.run_guard(*args, '--reduction-words', 'remove a and b', 'set', 'nexus.push', '["c"]').returncode, 0)

    def test_unset_approval_defaults_cannot_be_removed_without_separate_evidence(self):
        data = json.loads(self.profile.read_text())
        del data['ask_before']
        self.profile.write_text(json.dumps(data))
        self.assertNotEqual(self.run_guard('set', 'ask_before', '[]').returncode, 0)
        result = self.run_guard('--words', 'remove default approvals', '--place', 'chat', '--time', 'today', '--ask-before-words', 'yes', 'set', 'ask_before', '[]')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_adding_project_repo_needs_no_reduction_words(self):
        result = self.run_guard('--words', 'add checkout', '--place', 'chat', '--time', 'today', 'project', 'update', '{"name":"a","repos":{"api":"/api"}}')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(self.projects.read_text())
        self.assertEqual(data['projects'][0]['repos']['api'], '/api')

    def test_invalid_approval_value_is_refused(self):
        args = ('--words', 'change', '--place', 'chat', '--time', 'today', '--ask-before-words', 'yes')
        self.assertNotEqual(self.run_guard(*args, 'set', 'ask_before', 'false').returncode, 0)

    def test_append_approval_preserves_implicit_defaults(self):
        data = json.loads(self.profile.read_text())
        del data['ask_before']
        self.profile.write_text(json.dumps(data))
        result = self.run_guard('append', 'ask_before', '"migrations"')
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(self.profile.read_text())['ask_before']
        self.assertIn('deploys', values)
        self.assertIn('payments', values)
        self.assertIn('migrations', values)

    def test_duplicate_keys_in_new_value_are_refused(self):
        before = self.profile.read_bytes()
        result = self.run_guard('set', 'unknown', '{"x": 2, "x": 3}')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.profile.read_bytes(), before)

    def test_registering_already_pushed_name_needs_evidence(self):
        result = self.run_guard('project', 'add', '{"name":"c","path":"/c"}')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(self.profile.read_text())
        data['nexus']['push'].append('d')
        self.profile.write_text(json.dumps(data))
        args = ('--words', 'allow d', '--place', 'chat', '--time', 'today')
        # A fresh machine with a previously permitted name must not bind it silently.
        baseline = self.home / '.corthex/profile-guard/profile.json'
        baseline.write_text(json.dumps({'value': data}))
        result = self.run_guard('project', 'add', '{"name":"d","path":"/d"}')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.run_guard(*args, 'project', 'add', '{"name":"d","path":"/d"}').returncode, 0)

    def test_composite_report_shows_safe_fields(self):
        args = ('--words', 'change', '--place', 'chat', '--time', 'today')
        result = self.run_guard(*args, 'set', 'nexus', '{"url":"https://example.invalid/v3","token":"secret-value"}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('example.invalid', result.stdout)
        self.assertNotIn('secret-value', result.stdout)

    def test_project_add_preserves(self):
        self.assertEqual(self.run_guard('project', 'add', '{"name":"c","path":"/c"}').returncode, 0)
        data = json.loads(self.projects.read_text())
        self.assertEqual(len(data['projects']), 3)
        self.assertEqual(data['unknown'], 1)
        self.assertTrue(list(self.projects.parent.glob('projects.json.*.bak')))


class ExternalChangeTest(GuardTest):
    def hook(self):
        import importlib.util
        file = SCRIPT.parents[4] / 'corthex-memory/skills/corthex-memory/scripts/memory_lib/profile_guard.py'
        spec = importlib.util.spec_from_file_location('guard_test', file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.observe(self.home / '.corthex')

    def test_protocol_copies_match(self):
        core = SCRIPT.with_name('profile_guard.py')
        memory = SCRIPT.parents[4] / 'corthex-memory/skills/corthex-memory/scripts/memory_lib/profile_guard.py'
        self.assertEqual(core.read_bytes(), memory.read_bytes())

    def test_external_reduction_remains_visible(self):
        self.assertEqual(self.hook(), '')
        self.profile.write_text(json.dumps({'nexus': {'url': 'v2', 'push': ['a']}, 'ask_before': ['deploys']}))
        self.projects.write_text('{"projects": []}')
        warning = self.hook()
        for expected in ('WARNING', 'nexus.url', 'nexus.push', 'ask_before', 'projects', 'profile-guard'):
            self.assertIn(expected, warning)
        self.assertEqual(self.hook(), warning)

    def test_accept_requires_separate_approval_and_keeps_backup(self):
        self.hook()
        self.profile.write_text(json.dumps({'ask_before': ['deploys']}))
        args = ('--words', 'accept changes', '--place', 'chat', '--time', 'today')
        digest = self.hook().rsplit('digest: ', 1)[1]
        self.assertNotEqual(self.run_guard(*args, 'accept-external', digest).returncode, 0)
        self.assertEqual(self.run_guard(*args, '--ask-before-words', 'yes', '--reduction-words', 'remove push entries', 'accept-external', digest).returncode, 0)
        self.assertEqual(self.hook(), '')
        self.assertTrue(list((self.home / '.corthex/profile-guard').glob('profile.json.*.bak')))

    def test_removed_parent_reports_protected_fields(self):
        self.hook()
        self.profile.write_text('{}')
        warning = self.hook()
        self.assertIn('nexus.url: "<invalid URL>" -> null', warning)
        self.assertIn('nexus.push:', warning)
        self.assertIn('WARNING', warning)

    def test_project_path_change_is_not_a_reduction(self):
        self.hook()
        data = json.loads(self.projects.read_text())
        data['projects'][0]['path'] = '/new'
        self.projects.write_text(json.dumps(data))
        warning = self.hook()
        self.assertIn('WARNING', warning)
        self.assertIn('/new', warning)
        self.assertIn('/a', warning)

    def test_accept_rejects_a_change_since_review(self):
        self.hook()
        self.profile.write_text('{"ask_before": []}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        self.projects.write_text('{"projects": []}')
        result = self.run_guard('--words', 'yes', '--place', 'chat', '--time', 'today', '--ask-before-words', 'yes', 'accept-external', digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('projects', self.hook())

    def test_corrupt_baseline_and_bom(self):
        self.hook()
        guard = self.home / '.corthex/profile-guard/profile.json'
        guard.write_text('[]')
        warning = self.hook()
        self.assertIn('WARNING', warning)
        digest = warning.rsplit('digest: ', 1)[1]
        self.profile.write_text('\ufeff' + self.profile.read_text(), encoding='utf-8')
        self.assertEqual(self.run_guard('--words', 'yes', '--place', 'chat', '--time', 'today', '--ask-before-words', 'yes', '--reduction-words', 'remove push entries', 'accept-external', digest).returncode, 0)
        self.assertEqual(self.run_guard('set', 'language', '"ko"').returncode, 0)

    def test_accept_rejects_changed_baseline(self):
        self.hook()
        self.profile.write_text('{}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        (self.home / '.corthex/profile-guard/profile.json').write_text('{"value":{}}')
        result = self.run_guard('--words', 'yes', '--place', 'chat', '--time', 'today', '--ask-before-words', 'yes', 'accept-external', digest)
        self.assertNotEqual(result.returncode, 0)

    def test_restore_preserves_current_in_backup(self):
        self.hook()
        self.profile.write_text('{}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'restore', '--place', 'chat', '--time', 'today', '--ask-before-words', 'restore original approval categories', 'restore', 'profile', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.profile.read_text())['nexus']['url'], 'v3')
        self.assertIn('{}', [path.read_text() for path in self.profile.parent.glob('profile.json.*.bak')])
        self.assertEqual(self.hook(), '')

    def test_missing_one_baseline_is_warned(self):
        self.hook()
        (self.home / '.corthex/profile-guard/projects.json').unlink()
        self.assertIn('WARNING', self.hook())

    def test_concurrent_writer_lock_refuses(self):
        lock = self.home / '.corthex/profile-guard.lock'
        lock.mkdir()
        self.assertNotEqual(self.run_guard('set', 'language', '"ko"').returncode, 0)
        self.assertTrue(lock.exists())

    def test_invalid_baseline_requires_separate_approval(self):
        self.hook()
        (self.home / '.corthex/profile-guard/profile.json').write_text('{"missing": false}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'yes', '--place', 'chat', '--time', 'today', 'accept-external', digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ask-before-words', result.stderr)

    def test_restore_to_missing_keeps_a_backup(self):
        self.projects.unlink()
        self.hook()
        self.projects.write_text('{"projects": [{"name": "a"}]}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'remove the new file', '--place', 'chat', '--time', 'today', '--reduction-words', 'remove the new project', 'restore', 'projects', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.projects.exists())
        self.assertTrue(list(self.projects.parent.glob('projects.json.*.bak')))
        self.assertEqual(self.hook(), '')

    def test_stale_lock_does_not_hide_external_reduction(self):
        self.hook()
        (self.home / '.corthex/profile-guard.lock').mkdir()
        self.profile.write_text('{}')
        self.assertIn('WARNING', self.hook())

    def test_restore_keeps_new_unknown_fields(self):
        self.hook()
        current = json.loads(self.profile.read_text())
        current['new_unknown'] = {'keep': True}
        current['nexus']['url'] = 'v2'
        self.profile.write_text(json.dumps(current))
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'restore', '--place', 'chat', '--time', 'today', 'restore', 'profile', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.profile.read_text())['new_unknown'], {'keep': True})

    def test_restore_replaces_invalid_contents_even_if_baseline_empty(self):
        self.profile.write_text('{}')
        self.hook()
        self.profile.write_bytes(b'not-json')
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'restore', '--place', 'chat', '--time', 'today', '--ask-before-words', 'yes', '--reduction-words', 'restore unreadable settings', 'restore', 'profile', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.profile.read_text()), {})

    def test_restore_removes_externally_added_protected_fields(self):
        self.profile.write_text('{"language":"ko"}')
        self.hook()
        self.profile.write_text('{"language":"ko","nexus":{"url":"v2","push":["a"],"unknown":1},"checkpoints":{"user":[]}}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'restore', '--place', 'chat', '--time', 'today', '--reduction-words', 'remove outside push entry', 'restore', 'profile', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(self.profile.read_text())
        self.assertEqual(data['nexus'], {'unknown': 1})
        self.assertNotIn('checkpoints', data)

    def test_notice_distinguishes_removed_protected_fields(self):
        self.hook()
        self.profile.write_text('{"nexus": {"push": ["a", "b"]}}')
        warning = self.hook()
        self.assertIn('nexus.url:', warning)
        self.assertIn('-> "<missing>"', warning)

    def test_deleted_file_and_removed_project_are_warned(self):
        self.hook()
        self.profile.unlink()
        self.projects.write_text('{"projects": [{"name": "a", "path": "/a"}]}')
        warning = self.hook()
        self.assertIn('WARNING', warning)
        self.assertIn('removed projects: ["b"]', warning)

    def test_invalid_project_value_is_not_exposed(self):
        self.hook()
        self.projects.write_text('{"projects": {"token": "private-value"}}')
        warning = self.hook()
        self.assertNotIn('private-value', warning)
        self.assertIn('<invalid list>', warning)

    def test_unprotected_field_removal_is_flagged(self):
        self.hook()
        data = json.loads(self.profile.read_text())
        del data['unknown']
        self.profile.write_text(json.dumps(data))
        warning = self.hook()
        self.assertIn('WARNING', warning)
        self.assertIn('unknown: removed', warning)

    def test_restore_projects_keeps_new_entries(self):
        self.hook()
        self.projects.write_text('{"projects": [{"name":"a","path":"/wrong"},{"name":"c","path":"/c"}]}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'restore', '--place', 'chat', '--time', 'today', '--reduction-words', 'restore the old path', 'restore', 'projects', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(self.projects.read_text())
        self.assertEqual(sorted(item['name'] for item in data['projects']), ['a', 'b', 'c'])
        self.assertIn('\"name\": \"c\"', result.stdout)
        self.assertEqual(next(item['path'] for item in data['projects'] if item['name'] == 'a'), '/a')

    def test_invalid_approval_setting_still_requires_separate_approval(self):
        data = json.loads(self.profile.read_text())
        data['ask_before'] = 'everything'
        self.profile.write_text(json.dumps(data))
        self.assertNotEqual(self.run_guard('set', 'ask_before', '[]').returncode, 0)

    def test_external_invalid_approval_reduction_requires_separate_approval(self):
        data = json.loads(self.profile.read_text())
        data['ask_before'] = 'everything'
        self.profile.write_text(json.dumps(data))
        self.hook()
        data['ask_before'] = []
        self.profile.write_text(json.dumps(data))
        warning = self.hook()
        self.assertIn('WARNING', warning)
        digest = warning.rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'accept', '--place', 'chat', '--time', 'today', 'accept-external', digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ask-before-words', result.stderr)

    def test_restore_repairs_changed_field_type(self):
        self.hook()
        data = json.loads(self.profile.read_text())
        data['language'] = {'unexpected': True}
        data['unknown'] = {'x': {'unexpected': True}}
        self.profile.write_text(json.dumps(data))
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'restore', '--place', 'chat', '--time', 'today', 'restore', 'profile', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.profile.read_text())['unknown'], {'x': 1})

    def test_external_push_addition_is_a_warning(self):
        self.hook()
        data = json.loads(self.profile.read_text())
        data['nexus']['push'].append('c')
        self.profile.write_text(json.dumps(data))
        self.assertIn('WARNING', self.hook())

    def test_project_reduction_acceptance_requires_explicit_words(self):
        self.hook()
        self.projects.write_text('{"projects": [{"name": "a", "path": "/a"}]}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        args = ('--words', 'accept', '--place', 'chat', '--time', 'today')
        self.assertNotEqual(self.run_guard(*args, 'accept-external', digest).returncode, 0)
        self.assertEqual(self.run_guard(*args, '--reduction-words', 'remove project b', 'accept-external', digest).returncode, 0)

    def test_restore_ambiguous_projects_requires_explicit_reduction(self):
        self.hook()
        self.projects.write_text('{"projects": [{"path": "/unknown"}]}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        args = ('--words', 'restore', '--place', 'chat', '--time', 'today')
        self.assertNotEqual(self.run_guard(*args, 'restore', 'projects', digest).returncode, 0)
        result = self.run_guard(*args, '--reduction-words', 'replace unnamed entry', 'restore', 'projects', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({item['name'] for item in json.loads(self.projects.read_text())['projects']}, {'a', 'b'})

    def test_invalid_project_baseline_needs_explicit_reduction(self):
        self.hook()
        (self.home / '.corthex/profile-guard/projects.json').write_text('[]')
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'accept', '--place', 'chat', '--time', 'today', 'accept-external', digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('reduction-words', result.stderr)

    def test_accept_unreadable_previous_project_requires_reduction_evidence(self):
        self.projects.write_text('bad json')
        self.hook()
        self.projects.write_text('{"projects": []}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'accept', '--place', 'chat', '--time', 'today', 'accept-external', digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('reduction-words', result.stderr)

    def test_restore_report_does_not_expose_unknown_secret(self):
        data = json.loads(self.profile.read_text())
        data['unknown']['token'] = 'private-secret-value'
        self.profile.write_text(json.dumps(data))
        self.hook()
        data['nexus']['url'] = 'v2'
        self.profile.write_text(json.dumps(data))
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'restore', '--place', 'chat', '--time', 'today', 'restore', 'profile', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('private-secret-value', result.stdout)

    def test_restore_ambiguous_current_keeps_unambiguous_new_project(self):
        self.hook()
        self.projects.write_text('{"projects":[{"name":"a"},{"name":"a"},{"name":"c","path":"/c"}]}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        result = self.run_guard('--words', 'restore', '--place', 'chat', '--time', 'today', '--reduction-words', 'remove duplicate a', 'restore', 'projects', digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(item['name'] for item in json.loads(self.projects.read_text())['projects']), ['a', 'b', 'c'])

    def test_external_invalid_approval_setting_is_warned(self):
        self.hook()
        data = json.loads(self.profile.read_text())
        data['ask_before'] = False
        self.profile.write_text(json.dumps(data))
        self.assertIn('WARNING', self.hook())

    def test_unreadable_project_restore_requires_reduction_words(self):
        self.hook()
        self.projects.write_text('not-json')
        digest = self.hook().rsplit('digest: ', 1)[1]
        args = ('--words', 'restore', '--place', 'chat', '--time', 'today')
        self.assertNotEqual(self.run_guard(*args, 'restore', 'projects', digest).returncode, 0)
        result = self.run_guard(*args, '--reduction-words', 'replace unreadable contents', 'restore', 'projects', digest)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_restore_missing_preserves_a_racing_external_write(self):
        self.projects.unlink()
        self.hook()
        self.projects.write_text('{"projects": [{"name": "old"}]}')
        digest = self.hook().rsplit('digest: ', 1)[1]
        shim = """import os, pathlib, runpy, sys
path = pathlib.Path(os.environ['HOME']) / '.corthex/projects.json'
original = os.replace
def raced(source, destination):
    if str(source) == str(path):
        path.write_text('{"projects": [{"name": "racing"}]}')
    return original(source, destination)
os.replace = raced
sys.argv = [sys.argv[1], '--words', 'restore', '--place', 'chat', '--time', 'today', '--reduction-words', 'remove old', 'restore', 'projects', sys.argv[2]]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        result = subprocess.run([sys.executable, '-c', shim, str(SCRIPT), digest], env=dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home)), capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('moved copy kept', result.stderr)
        self.assertTrue(any('racing' in path.read_text() for path in self.projects.parent.glob('projects.json.*.bak')))
        self.assertIn('racing', self.projects.read_text())
        kept = [path for path in self.projects.parent.glob('projects.json.*.bak') if 'racing' in path.read_text()]
        self.projects.write_text('{}')
        self.assertTrue(any('racing' in path.read_text() for path in kept))

    def test_duplicate_json_keys_are_preserved_without_rewrite(self):
        original = b'{"unknown": 1, "unknown": 2}'
        self.profile.write_bytes(original)
        result = self.run_guard('set', 'language', '"ko"')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.profile.read_bytes(), original)

    def test_unreadable_file_deleted_is_warned(self):
        self.profile.write_bytes(b'not-json')
        self.hook()
        self.profile.unlink()
        self.assertIn('WARNING', self.hook())

    def test_default_approval_list_matches_example(self):
        import importlib.util
        module_path = SCRIPT.with_name('profile_guard.py')
        spec = importlib.util.spec_from_file_location('guard_defaults_test', module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        example = json.loads((SCRIPT.parents[1] / 'assets/profile.example.json').read_text())
        self.assertEqual(list(module.DEFAULT_ASK_BEFORE), example['ask_before'])

    def test_inaccessible_settings_are_warned_without_losing_backup(self):
        self.hook()
        self.profile.unlink()
        self.profile.mkdir()
        warning = self.hook()
        self.assertIn('WARNING', warning)
        self.assertIn('inaccessible', warning)
        self.assertTrue((self.home / '.corthex/profile-guard/profile.json').is_file())

    def test_delegate_role_change_is_visible(self):
        data = json.loads(self.profile.read_text())
        data['checkpoints'] = {'user': ['01-domain'], 'delegate': {'role': 'reviewer'}}
        self.profile.write_text(json.dumps(data))
        self.hook()
        data['checkpoints']['delegate']['role'] = 'owner'
        self.profile.write_text(json.dumps(data))
        warning = self.hook()
        self.assertIn('WARNING', warning)
        self.assertIn('reviewer', warning)
        self.assertIn('owner', warning)

    def test_late_removed_approval_is_named_before_truncation(self):
        data = json.loads(self.profile.read_text())
        data['ask_before'] = ['category-' + str(i) for i in range(15)] + ['critical-last']
        self.profile.write_text(json.dumps(data))
        self.hook()
        data['ask_before'].pop()
        self.profile.write_text(json.dumps(data))
        warning = self.hook()
        self.assertIn('removed ask_before', warning)
        self.assertIn('critical-last', warning)

    def test_accept_checks_reviewed_profile_even_if_diff_list_changes(self):
        self.hook()
        data = json.loads(self.profile.read_text())
        data['ask_before'] = ['deploys']
        self.profile.write_text(json.dumps(data))
        digest = self.hook().rsplit('digest: ', 1)[1]
        shim = """import os, pathlib, runpy, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).parent))
import profile_guard
profile_guard.differences = lambda folder: [('projects.json', pathlib.Path(folder) / 'profile-guard/projects.json', [], False)]
sys.argv = [sys.argv[1], '--words', 'accept', '--place', 'chat', '--time', 'today', 'accept-external', sys.argv[2]]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        result = subprocess.run([sys.executable, '-c', shim, str(SCRIPT), digest], env=dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home)), capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ask-before-words', result.stderr)

    def test_malformed_project_container_reduction_needs_evidence(self):
        self.projects.write_text('{"projects": {"a": {"path": "/a"}}}')
        self.hook()
        self.projects.write_text('{"projects": []}')
        warning = self.hook()
        self.assertIn('WARNING', warning)
        digest = warning.rsplit('digest: ', 1)[1]
        args = ('--words', 'accept', '--place', 'chat', '--time', 'today')
        self.assertNotEqual(self.run_guard(*args, 'accept-external', digest).returncode, 0)
        result = self.run_guard(*args, '--reduction-words', 'replace malformed project container', 'accept-external', digest)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_guarded_write_updates_baseline(self):
        self.hook()
        self.assertEqual(self.run_guard('set', 'language', '"ko"').returncode, 0)
        self.assertEqual(self.hook(), '')

    def test_guarded_write_does_not_hide_external_change(self):
        self.hook()
        self.profile.write_text('{}')
        self.assertNotEqual(self.run_guard('set', 'language', '"ko"').returncode, 0)
        self.assertIn('WARNING', self.hook())

if __name__ == '__main__': unittest.main()
