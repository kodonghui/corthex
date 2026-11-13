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
        self.assertEqual(changed, {'hub.py', 'transport.py', 'snapshot02.py', 'commands.py', 'outbox.py'})
        manifest = json.loads((ROOT / 'plugins/corthex-nexus/plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['version'], '0.4.0')
        self.assertIn('VERSION = "0.4.0"', (self.scripts / 'hub.py').read_text(encoding='utf-8'))
        self.assertIn('version="0.4.0", timeout=30', (self.scripts / 'transport.py').read_text(encoding='utf-8'))

    def test_a_wire_schema_change_is_still_refused(self):
        path = self.scripts / 'hub.py'
        source = path.read_text(encoding='utf-8')
        self.assertIn('SCHEMA = "corthex-hub/0.2"', source)
        path.write_text(source.replace('SCHEMA = "corthex-hub/0.2"', 'SCHEMA = "corthex-hub/9.9"', 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            fixture.verify_runtime(self.root)

    def test_an_unreviewed_version_field_is_still_refused(self):
        path = self.scripts / 'transport.py'
        path.write_text(path.read_text(encoding='utf-8').replace('version="0.4.0"', 'version="0.4.1"', 1), encoding='utf-8')
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
