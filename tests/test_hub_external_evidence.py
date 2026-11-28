"""External decision evidence uses synthetic content and no network."""
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/corthex-nexus/skills/corthex-hub/scripts/commands.py'
spec = importlib.util.spec_from_file_location('evidence_commands', SCRIPT)
commands = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commands)

class EvidenceTest(unittest.TestCase):
    def request(self, **changes):
        args = dict(command='decide', entry='c_123', link='https://example.invalid/decision', text=None,
                    text_file=None, evidence_source_kind=None, evidence_location=None,
                    evidence_text=None, evidence_text_file=None, evidence_at=None)
        args.update(changes)
        h = SimpleNamespace(SECRET_TEXT=re.compile(r'secret-marker'))
        return commands.write_request(SimpleNamespace(**args), 'example', '/synthetic-home', {}, h)

    def test_exact_file_and_legacy(self):
        self.assertNotIn('external_evidence', self.request()[2])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'answer.txt'
            original = 'Yes, "agreed".\r\nSecond line.\n'
            path.write_bytes(original.encode('utf8'))
            body = self.request(evidence_source_kind='chat', evidence_location='item 123',
                                evidence_text_file=str(path), evidence_at='2026-01-01T00:00:00.000Z')[2]
            self.assertEqual(body['external_evidence'], dict(source_kind='chat', location='item 123',
                                                              text=original, at='2026-01-01T00:00:00.000Z'))

    def test_seconds_are_sent_as_milliseconds(self):
        body = self.request(evidence_source_kind='chat', evidence_location='item 123',
                            evidence_text='Yes', evidence_at='2026-01-01T00:00:00Z')[2]
        self.assertEqual(body['external_evidence']['at'], '2026-01-01T00:00:00.000Z')

    def test_session_help_and_missing_session(self):
        import sys
        sys.path.insert(0, str(SCRIPT.parent))
        import hub
        parser = hub.parser()
        args = parser.parse_args(['decide', 'example', 'nc_' + 'a' * 12, '--link', 'https://example.invalid'])
        with self.assertRaisesRegex(commands.CommandLine, r'--session <session-name>.*CORTHEX_NEXUS_SESSION'):
            commands.validate(args, {}, None)
        help_text = parser._subparsers._group_actions[0].choices['decide'].format_help()
        self.assertIn('CORTHEX_NEXUS_SESSION', help_text)

    def test_partial_and_redacted_are_refused(self):
        with self.assertRaises(commands.CommandLine):
            self.request(evidence_source_kind='chat')
        with self.assertRaises(commands.CommandLine):
            self.request(evidence_source_kind='chat', evidence_location='item 123',
                         evidence_text='secret-marker', evidence_at='2026-01-01T00:00:00.000Z')

    def test_invalid_values_are_refused(self):
        base = dict(evidence_source_kind='chat', evidence_location='item 123',
                    evidence_text='Yes', evidence_at='2026-01-01T00:00:00.000Z')
        for field, invalid in [('evidence_source_kind', 'x' * 101), ('evidence_text', '\ufeffYes'),
                               ('evidence_at', '2026-01-01'), ('evidence_at', '2026-01-01T00:00:00'),
                               ('evidence_at', '2999-01-01T00:00:00Z'), ('evidence_at', '2999-01-01T00:00:00.000Z')]:
            with self.subTest(field=field, invalid=invalid):
                with self.assertRaises(commands.CommandLine):
                    self.request(**dict(base, **{field: invalid}))
        with self.assertRaises(commands.CommandLine):
            self.request(**dict(base, text_file='-', evidence_text=None, evidence_text_file='-'))
