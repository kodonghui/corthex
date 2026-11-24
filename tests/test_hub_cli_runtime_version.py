"""The accepted CLI fixture permits exactly the reviewed release changes."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import hub_cli_fixture as fixture

ROOT = Path(__file__).resolve().parents[1]


class RuntimeVersionPinTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scripts = self.root / fixture.PREFIX
        self.scripts.mkdir(parents=True)
        for name in fixture.RUNTIME:
            shutil.copyfile(ROOT / fixture.PREFIX / name, self.scripts / name)

    def test_actual_version_hashes_are_retained_with_the_old_protocol_anchor(self):
        _, rows = fixture.verify_runtime(self.root)
        changed = {row['file'] for row in rows if row['reviewedNormalization']}
        self.assertEqual(changed, {'hub.py', 'transport.py', 'snapshot02.py', 'commands.py', 'outbox.py', 'records.py'})
        manifest = json.loads((ROOT / 'plugins/corthex-nexus/plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['version'], '0.6.0')
        self.assertIn('VERSION = "0.6.0"', (self.scripts / 'hub.py').read_text(encoding='utf-8'))
        self.assertIn('version="0.6.0", timeout=30', (self.scripts / 'transport.py').read_text(encoding='utf-8'))

    def test_a_wire_schema_change_is_still_refused(self):
        path = self.scripts / 'hub.py'
        source = path.read_text(encoding='utf-8')
        self.assertIn('SCHEMA = "corthex-hub/0.2"', source)
        path.write_text(source.replace('SCHEMA = "corthex-hub/0.2"', 'SCHEMA = "corthex-hub/9.9"', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            fixture.verify_runtime(self.root)

    def test_an_unreviewed_version_field_is_still_refused(self):
        path = self.scripts / 'transport.py'
        path.write_text(path.read_text(encoding='utf-8').replace('version="0.6.0"', 'version="0.6.1"', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            fixture.verify_runtime(self.root)

    def test_another_ask_before_change_is_still_refused(self):
        path = self.scripts / 'snapshot02.py'
        source = path.read_text(encoding='utf-8')
        self.assertIn('if not kept(x)]', source)
        path.write_text(source.replace('in (" ", "(")', 'in (" ", "(", "-")', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            fixture.verify_runtime(self.root)

    def test_another_comment_change_is_still_refused(self):
        path = self.scripts / 'commands.py'
        source = path.read_text(encoding='utf-8')
        self.assertIn('ASKS = ("answer", "recommended", "checkpoint")', source)
        path.write_text(source.replace('"checkpoint")', '"checkpoint", "maybe")', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            fixture.verify_runtime(self.root)

    def test_another_checkpoint_link_change_is_still_refused(self):
        # NEXUS v3: status builds v3's stage address, offline, only for a server recorded as v3.
        path = self.scripts / 'records.py'
        source = path.read_text(encoding='utf-8')
        self.assertIn('("/p/" + place if v3 else', source)
        path.write_text(source.replace('("/p/" + place if v3 else', '("/p/" + place + "#" + checkpoint if v3 else', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            fixture.verify_runtime(self.root)

    def test_another_source_path_change_is_still_refused(self):
        # NEXUS v3: propose sends source_path only with source_text, after its local checks.
        path = self.scripts / 'commands.py'
        source = path.read_text(encoding='utf-8')
        self.assertIn('SOURCE_PATH_CHARS = 300\n', source)
        path.write_text(source.replace('SOURCE_PATH_CHARS = 300\n', 'SOURCE_PATH_CHARS = 3000\n', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            fixture.verify_runtime(self.root)

    def test_another_format_change_is_still_refused(self):
        # 0.6.0 sends 0.3 only to a server that lists it; any other change to that choice is not reviewed.
        path = self.scripts / 'commands.py'
        source = path.read_text(encoding='utf-8')
        self.assertIn('schema=h.companion("snapshot03").choose(held.get("answer"))', source)
        path.write_text(source.replace('choose(held.get("answer"))', 'NEW', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            fixture.verify_runtime(self.root)
