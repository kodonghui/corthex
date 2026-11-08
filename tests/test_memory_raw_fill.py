"""TASK-098: the forget's raw fill (TBL-007; SPEC-035; SPEC-007) and TC-238's direct evidence.

`raw_fill.fill` fills a forgotten item's quoted ranges in one raw log under the
project's layer lease. The confirmed forget calls it for each raw log among its
effects (`forget_effects`); these tests call it as the forget does, holding the
layer lease. TC-238 runs the actual prompt hook every 10 ms in one process while
another fills ranges and this one runs retention on the same raw log.
"""
import contextlib
from datetime import timedelta
import io
import json
import multiprocessing
import os
from pathlib import Path
import time
from unittest import mock

from test_memory_retention import NOW
import test_memory_cleanup as cleanup_tests
import test_memory_hooks as hook_tests
import test_memory_store as store_tests
from memory_lib import (base, clock, commands, curator_document, files, hooks, locks, raw_fill, raw_log,
                        raw_rewrite, redaction, request_inputs, retention, worker_support)

SESSION = 'fill-fixture'
SAID = 'Keep the secret plan out of the notes, and keep the hooks in one script.'


def fill_loop(connection, folder):
    """Fill each requested log's ranges under the layer lease, waiting for it as a forget will.

    A slow fill keeps the raw lock for 200 ms, as a slow disk can while it
    copies the backup, so that recording waits past its 50 ms.
    """
    memory = worker_support.WorkerStore(Path(folder))
    root = memory.folder / 'projects' / 'sample'
    backup = files._backup

    def slow_backup(*args, **kwargs):
        time.sleep(.2)
        return backup(*args, **kwargs)
    connection.send(True)
    while True:
        request = connection.recv()
        if request == 'stop':
            break
        log, ranges, hold, slow = request
        deadline = clock.now() + 60
        contended = False
        with contextlib.ExitStack() as stack:
            try:
                stack.enter_context(memory.lease(root / 'layer.lock', 'layer', deadline))
            except locks.LockBusy:
                contended = True
                connection.send('waiting')
                stack.enter_context(memory.lease(root / 'layer.lock', 'layer', deadline,
                                                 acquire_deadline=clock.now() + 10))
            if hold:
                connection.send('holding')
                connection.recv()
            with mock.patch.object(files, '_backup', slow_backup if slow else backup):
                result = raw_fill.fill(memory, root, log, ranges, deadline, wait=10.0)
        connection.send((sorted(result.entries), result.ranges, contended))
    connection.close()


def hook_loop(connection, repo):
    """The actual prompt hook every 10 ms in this process; each recording result is kept."""
    os.environ.update(PLUGIN_ROOT='', CLAUDECODE='1')
    results, append = [], raw_log.RawLog.append

    def observed(self, *args, **kwargs):
        result = append(self, *args, **kwargs)
        results.append(result)
        return result
    raw_log.RawLog.append = observed
    connection.send(True)
    number = 0
    while not (connection.poll() and connection.recv() == 'stop'):
        number += 1
        event = {'hook_event_name': hooks.EVENTS['prompt'], 'session_id': SESSION, 'cwd': repo,
                 'prompt': 'ack-%d 가나다' % number}
        hooks.run('prompt', clock.now(), io.BytesIO(json.dumps(event).encode('utf-8')), io.BytesIO())
        time.sleep(.01)
    connection.send(([result.entry for result in results if result.outcome == 'ok'],
                     sum(result.outcome == 'lock-busy' for result in results),
                     sorted({result.outcome for result in results})))
    connection.close()


def child(test, target, *args):
    context = multiprocessing.get_context('spawn')
    parent, end = context.Pipe()
    process = context.Process(target=target, args=(end,) + args)
    process.start()
    end.close()
    test.assertTrue(parent.poll(30))
    test.assertIs(parent.recv(), True)
    return parent, process


def finish(test, connection, process):
    with contextlib.suppress(OSError):
        connection.send('stop')
    process.join(30)
    if process.is_alive():
        process.terminate()
        process.join(10)
    connection.close()
    test.assertEqual(process.exitcode, 0)


class RawFillTest(store_tests.StoreCase):
    def setUp(self):
        super().setUp()
        self.worker = worker_support.WorkerStore()
        self.project = self.worker.folder / 'projects' / 'sample'
        for name in ('raw', 'unprocessed', 'layer/items', 'layer/tombstones'):
            base.private_directory(self.project / name)
        self.log = raw_log.log_name('claude-code', SESSION)
        self.path = self.project / 'raw' / (self.log + '.jsonl')

    def entry(self, seq, text=SAID, kind='prompt', turn=None, **extra):
        value = {'id': 'e_' + str(seq).zfill(12), 'seq': seq, 'at': base.utc_time(NOW), 'host': 'claude-code',
                 'session': SESSION, 'kind': kind}
        if kind in ('prompt', 'answer'):
            value.update(turn=turn or seq, speaker='user' if kind == 'prompt' else 'agent', text=text)
        value.update(extra)
        return value

    @staticmethod
    def line(value):
        return base.json_bytes(value, 'TBL-007', compact=True)

    def write(self, *parts):
        self.path.write_bytes(b''.join(part if isinstance(part, bytes) else self.line(part) for part in parts))

    def read(self):
        return [json.loads(line) for line in self.path.read_bytes().splitlines()]

    def span(self, words, text=SAID):
        start = text.index(words)
        return [start, start + len(words)]

    def fill(self, ranges, seconds=30, **options):
        deadline = clock.now() + seconds
        with self.worker.lease(self.project / 'layer.lock', 'layer', deadline):
            return raw_fill.fill(self.worker, self.project, self.log, ranges, deadline, **options)

    def siblings(self):
        return sorted(path.name for path in self.path.parent.iterdir() if path.name != self.path.with_suffix('.lock').name)

    def test_tc238_fill_keeps_length_lists_ranges_and_every_other_byte(self):
        said, answered = self.entry(2), self.entry(3, 'One script now serves the hooks.', 'answer', turn=2)
        before = [self.line(self.entry(1, kind='start', event='start')), self.line(said), self.line(answered),
                  b'{"damaged"\n', self.line(self.entry(4, 'A tab\there, and \x01 too.')), b'{"id":"e_unfinished']
        self.write(*before)
        identity = self.path.stat().st_ino
        secret = self.span('secret plan')
        result = self.fill({said['id']: [secret]})
        self.assertEqual(result, raw_fill.Filled(frozenset([said['id']]), 1))
        filled = dict(said, text=SAID[:secret[0]] + '�' * 11 + SAID[secret[1]:], forgotten=[secret])
        self.assertEqual(self.path.read_bytes(), b''.join(before[:1] + [self.line(filled)] + before[2:]))
        self.assertEqual(len(filled['text']), len(SAID))
        self.assertNotEqual(self.path.stat().st_ino, identity)
        self.assertEqual(self.siblings(), [self.path.name])
        shown = [entry for entry in request_inputs.entries(self.project, self.log) if entry['id'] == said['id']]
        self.assertEqual(curator_document.entry_text(shown[0]),
                         'Keep the [forgotten] out of the notes, and keep the hooks in one script.')

    def test_tc238_later_fills_add_only_new_ranges_and_fill_listed_ones_again(self):
        said = self.entry(2)
        first, second = self.span('secret'), self.span('plan')
        self.write(said)
        self.assertEqual(self.fill({said['id']: [first, first]}).ranges, 1)
        identity = self.path.stat().st_ino
        # A range already listed changes nothing, so the log stays as it is.
        self.assertEqual(self.fill({said['id']: [first]}), raw_fill.Filled(frozenset(), 0))
        self.assertEqual(self.path.stat().st_ino, identity)
        self.assertEqual(self.fill({said['id']: [second, first, [first[0] + 1, second[1]]]}).ranges, 2)
        value = self.read()[0]
        self.assertEqual(value['forgotten'], sorted([first, second, [first[0] + 1, second[1]]]))
        self.assertEqual(value['text'], SAID.replace('secret plan', '�' * 11))
        # A listed range whose text is not U+FFFD, as written by hand, is filled again.
        self.write(dict(said, forgotten=[[float(first[0]), float(first[1])]]))
        self.assertEqual(self.fill({said['id']: [first]}), raw_fill.Filled(frozenset([said['id']]), 0))
        self.assertEqual(self.read()[0], dict(said, text=SAID.replace('secret', '�' * 6), forgotten=[first]))

    def test_tc238_each_filled_character_counts_as_one_byte_of_the_entry_limit(self):
        size = redaction.ENTRY_BYTES
        self.write(self.entry(1, 'a' * size), self.entry(2, '�' * size))
        self.assertEqual(len(self.read()), 2)
        self.assertEqual([entry['seq'] for entry in request_inputs.entries(self.project, self.log)], [1])
        result = self.fill({self.entry(1)['id']: [[0, size // 2], [size // 2 - 10, size]]})
        self.assertEqual(result.ranges, 2)
        filled = self.read()[0]
        self.assertEqual(len(filled['text'].encode('utf-8')), 3 * size)
        self.assertEqual(raw_rewrite._entry(self.line(filled), self.log), filled)
        self.assertEqual([entry['seq'] for entry in request_inputs.entries(self.project, self.log)], [1])
        for ranges, valid in (([[0, size]], True), ([[0, size // 2]], False), ([[0, size // 2], [size // 2, size]], True),
                              ([[0, size - 1], [1, size - 1]], False)):
            with self.subTest(ranges=ranges):
                value = self.entry(2, '�' * size, forgotten=ranges)
                if valid:
                    self.assertEqual(raw_log._parsed_entry(value, 'claude-code', SESSION), value)
                else:
                    with self.assertRaises(ValueError):
                        raw_log._parsed_entry(value, 'claude-code', SESSION)
        # Recording reads the filled entry as the turn that it is: the answer joins it.
        self.write(filled)
        answer = raw_log.RawLog(self.worker, 'sample', 'claude-code', SESSION).append(
            'answer', raw_log.prepare('made-up answer'), diagnostic_deadline=clock.now() + 3, when=NOW)
        self.assertEqual((answer.outcome, answer.entry['seq'], answer.entry['turn']), ('ok', 2, 1))

    def test_tc238_the_fill_needs_the_layer_lease_and_takes_only_the_raw_lock(self):
        said = self.entry(2)
        self.write(said)
        before = self.path.read_bytes()
        deadline = clock.now() + 10
        with self.assertRaises(locks.LostLock):
            raw_fill.fill(self.worker, self.project, self.log, {said['id']: [[0, 4]]}, deadline)
        with self.worker.lease(self.project / 'curation.lock', 'curation', deadline):
            with self.assertRaises(locks.LostLock):
                raw_fill.fill(self.worker, self.project, self.log, {said['id']: [[0, 4]]}, deadline)
        self.assertEqual(self.path.read_bytes(), before)
        taken, lease = [], self.worker.lease

        def recorded(path, kind, *args, **kwargs):
            taken.append(kind)
            return lease(path, kind, *args, **kwargs)
        with mock.patch.object(self.worker, 'lease', recorded):
            self.fill({said['id']: [[0, 4]]})
        self.assertEqual(taken, ['layer', 'raw'])

    def test_tc238_entries_that_the_log_does_not_hold_change_nothing(self):
        said = self.entry(2)
        self.write(said, b'{"damaged"\n')
        before, identity = self.path.read_bytes(), self.path.stat().st_ino
        self.assertEqual(self.fill({'e_' + 'z' * 12: [[0, 4]]}), raw_fill.Filled(frozenset(), 0))
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_ino), (before, identity))
        self.assertEqual(self.siblings(), [self.path.name])
        self.path.unlink()
        self.assertEqual(self.fill({said['id']: [[0, 4]]}), raw_fill.Filled(frozenset(), 0))
        self.assertFalse(self.path.exists())

    def test_tc238_ranges_that_cannot_be_filled_refuse_before_any_change(self):
        said, start = self.entry(2), self.entry(1, kind='start')
        self.write(start, said)
        before, identity = self.path.read_bytes(), self.path.stat().st_ino
        for ranges in ({said['id']: [[0, len(SAID) + 1]]}, {start['id']: [[0, 1]]}, {said['id']: [[3, 3]]},
                       {said['id']: [[-1, 2]]}, {said['id']: [[True, 2]]}, {said['id']: [[0.5, 2]]},
                       {said['id']: [[0, 1, 2]]}, {said['id']: '01'}, {'e_1': [[0, 1]]}, [[0, 1]]):
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                self.fill(ranges)
        for options in ({'wait': -1}, {'wait': float('nan')}, {'wait': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.fill({said['id']: [[0, 4]]}, **options)
        deadline = clock.now() + 10
        with self.worker.lease(self.project / 'layer.lock', 'layer', deadline), self.assertRaises(ValueError):
            raw_fill.fill(self.worker, self.project, '../' + self.log, {said['id']: [[0, 4]]}, deadline)
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_ino), (before, identity))
        self.assertEqual(self.siblings(), [self.path.name])

    def test_tc238_an_append_while_the_new_file_is_built_is_carried_unchanged(self):
        said = self.entry(2)
        self.write(self.entry(1, kind='start'), said, b'{"id":"e_unfinished"')
        appended, temporary = [], files._temporary

        def during(*args, **kwargs):
            if not appended:
                appended.append(raw_log.RawLog(self.worker, 'sample', 'claude-code', SESSION).append(
                    'prompt', raw_log.prepare('Appended meanwhile.'), diagnostic_deadline=clock.now() + 3, when=NOW))
            return temporary(*args, **kwargs)
        with mock.patch.object(files, '_temporary', during):
            self.assertEqual(self.fill({said['id']: [self.span('secret plan')]}).ranges, 1)
        self.assertEqual(appended[0].outcome, 'ok')
        lines = self.path.read_bytes().split(b'\n')
        self.assertEqual(lines[2:], [b'{"id":"e_unfinished"', self.line(appended[0].entry)[:-1], b''])
        self.assertNotIn(b'secret', self.path.read_bytes())

    def test_tc238_backups_and_temporary_files_that_hold_the_text_are_removed(self):
        said = self.entry(2)
        self.write(said)
        stale = [self.path.name + suffix for suffix in ('.bak', '.abcd_123.tmp', '.bak.zyxw9876.tmp')]
        kept = [self.path.name + '.notes', 'claude-code-0000000000000000.jsonl.bak']
        for name in stale + kept:
            (self.path.parent / name).write_bytes(self.line(said))
        self.fill({said['id']: [self.span('secret plan')]})
        self.assertEqual(self.siblings(), sorted([self.path.name] + kept))
        # Every range filled already: the fill still removes what a stopped rewrite left.
        for name in stale:
            (self.path.parent / name).write_bytes(self.line(said))
        self.assertEqual(self.fill({said['id']: [self.span('secret plan')]}), raw_fill.Filled(frozenset(), 0))
        self.assertEqual(self.siblings(), sorted([self.path.name] + kept))

    def test_tc238_a_missing_log_is_restored_from_its_backup_and_filled(self):
        said = self.entry(2)
        backup = self.path.with_name(self.path.name + '.bak')
        backup.write_bytes(self.line(said))
        self.assertEqual(self.fill({said['id']: [self.span('secret plan')]}).ranges, 1)
        self.assertNotIn(b'secret', self.path.read_bytes())
        self.assertEqual(self.siblings(), [self.path.name])

    def test_tc238_every_line_of_one_entry_is_filled(self):
        said = self.entry(2)
        self.write(said, dict(said, seq=3, turn=3))
        self.assertEqual(self.fill({said['id']: [self.span('secret plan')]}), raw_fill.Filled(frozenset([said['id']]), 2))
        self.assertNotIn(b'secret', self.path.read_bytes())

    def test_tc238_a_busy_raw_lock_leaves_the_log_and_no_temporary_file(self):
        said = self.entry(2)
        self.write(said)
        before, identity = self.path.read_bytes(), self.path.stat().st_ino
        connection, process = child(self, cleanup_tests.hold, str(self.path.with_suffix('.lock')), 'raw',
                                    self.worker.device)
        try:
            began = clock.now()
            with self.assertRaises(locks.LockBusy):
                self.fill({said['id']: [self.span('secret plan')]}, wait=0.05)
            self.assertLess(clock.now() - began, 5)
        finally:
            finish(self, connection, process)
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_ino), (before, identity))
        self.assertEqual(self.siblings(), [self.path.name])


class ForgetFillStressTest(hook_tests.HookCase):
    """TC-238: the prompt hook appends every 10 ms while fills and retention rewrite the same raw log."""

    def setUp(self):
        super().setUp()
        self.worker = worker_support.WorkerStore()
        self.project = self.worker.folder / 'projects' / 'sample'
        self.log = raw_log.log_name('claude-code', SESSION)
        self.path = self.project / 'raw' / (self.log + '.jsonl')
        (self.project / 'curation.json').write_bytes(base.json_bytes(
            {'logs': {}, 'applies': 0, 'recent': [], 'consolidation': {'failures': 0}}, 'TBL-009'))

    def seed(self, text, when):
        """Append as recording does; None when the raw lock stayed busy."""
        result = raw_log.RawLog(self.worker, 'sample', 'claude-code', SESSION).append(
            'prompt', raw_log.prepare(text), diagnostic_deadline=clock.now() + 3, when=when)
        if result.outcome == 'lock-busy':
            return None
        self.assertEqual(result.outcome, 'ok')
        return result.entry

    def retain(self):
        deadline = clock.now() + 30
        with self.worker.lease(self.project / 'curation.lock', 'curation', deadline) as owner:
            return retention.retain_project(self.worker, 'sample', owner, deadline, NOW)

    def test_tc238_appends_survive_100_fills_with_retention_on_the_same_log(self):
        hook, appender = child(self, hook_loop, str(self.repo))
        filler, worker = child(self, fill_loop, str(self.root))
        secrets_, counts = [], dict(fills=0, retention_rewrites=0, retention_skips=0, retention_while_held=0,
                                    fill_waits=0, seed_lock_skips=0, iterations=0)
        acknowledged = skipped = outcomes = None
        limit = time.monotonic() + 240
        try:
            while counts['fills'] < 100 and counts['iterations'] < 300 and time.monotonic() < limit:
                counts['iterations'] += 1
                expired = self.seed('expired stress seed', NOW - timedelta(days=101))
                secret = expired and self.seed('Remember secret-%d for later.' % counts['iterations'], NOW)
                if secret is None:
                    counts['seed_lock_skips'] += 1
                    continue
                words = 'secret-%d' % counts['iterations']
                start = secret['text'].index(words)
                secrets_.append((secret, [start, start + len(words)]))
                # In every five rounds a fill holds the layer lease while
                # retention tries the same log; a fill waits while retention
                # holds it; retention runs first; and twice both start at
                # once, once with a slow fill that makes recording skip.
                turn = len(secrets_) % 5
                request = (self.log, {secret['id']: [[start, start + len(words)]]}, turn == 0, turn == 3)
                if turn == 0:
                    filler.send(request)
                    self.assertTrue(filler.poll(30))
                    self.assertEqual(filler.recv(), 'holding')
                    result = self.retain()
                    self.assertEqual((result['files'], result['skipped']), (0, 1))
                    counts['retention_while_held'] += 1
                    filler.send('go')
                elif turn == 1:
                    sent, sync = [], files._sync

                    def during(fd):
                        # Retention holds the layer lease while it builds its file.
                        if not sent:
                            sent.append(True)
                            filler.send(request)
                            self.assertTrue(filler.poll(30))
                            self.assertEqual(filler.recv(), 'waiting')
                        return sync(fd)
                    with mock.patch.object(files, '_sync', during):
                        result = self.retain()
                    self.assertEqual(sent, [True])
                elif turn == 2:
                    result = self.retain()
                    filler.send(request)
                else:
                    filler.send(request)
                    result = self.retain()
                counts['retention_rewrites'] += result['files']
                counts['retention_skips'] += result['skipped']
                while True:
                    self.assertTrue(filler.poll(60))
                    answer = filler.recv()
                    if answer != 'waiting':
                        break
                entries, added, contended = answer
                self.assertEqual((entries, added), ([secret['id']], 1))
                counts['fills'] += 1
                counts['fill_waits'] += contended
        finally:
            with contextlib.suppress(OSError):
                hook.send('stop')
            if hook.poll(30):
                acknowledged, skipped, outcomes = hook.recv()
            finish(self, hook, appender)
            finish(self, filler, worker)
        self.assertIsNotNone(acknowledged)
        data = self.path.read_bytes()
        actual = [json.loads(line) for line in data.splitlines()]
        print('FORGET_FILL_STRESS ' + json.dumps(dict(counts, acknowledged=len(acknowledged),
                                                        append_lock_skips=skipped)))
        self.assertEqual(counts['fills'], 100)
        self.assertGreater(counts['retention_rewrites'], 0)
        self.assertEqual(counts['retention_while_held'], 20)
        self.assertGreaterEqual(counts['fill_waits'], 20)
        self.assertEqual(set(outcomes), {'ok', 'lock-busy'})
        self.assertGreater(len(acknowledged), 0)
        self.assertTrue(all(entry in actual for entry in acknowledged))
        by_id = {entry['id']: entry for entry in actual}
        for secret, span in secrets_:
            self.assertEqual(by_id[secret['id']]['forgotten'], [span])
            self.assertEqual(by_id[secret['id']]['text'][span[0]:span[1]], '�' * (span[1] - span[0]))
        self.assertNotIn(b'secret-', data)
        self.assertEqual(sorted(path.name for path in self.path.parent.iterdir() if path.suffix != '.lock'),
                         [self.path.name])
        value, _ = commands.run(['--folder', str(self.repo), 'status'])
        hooks_ = {(row['hook'], row['host']): row['outcomes'] for row in value['data']['hooks']}
        self.assertEqual(hooks_[('prompt', 'claude-code')].get('ok', 0), len(acknowledged))
        self.assertEqual(hooks_[('prompt', 'claude-code')].get('lock-busy', 0), skipped)
