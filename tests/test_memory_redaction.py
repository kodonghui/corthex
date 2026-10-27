"""TC-022–028: generated secrets never become fixtures, output or raw files."""

import ast
import contextlib
import io
import os
import re
import secrets
import string
from pathlib import Path
from unittest import mock

from test_memory_store import API, SCRIPTS, StoreCase
from test_memory_api import section
from memory_lib import files, redaction


def random_text(length, alphabet=string.ascii_letters + string.digits):
    return "".join(secrets.choice(alphabet) for _ in range(length))


def secret_examples():
    values = [("anthropic-key", "sk-ant-" + random_text(24))]
    values += [("openai-key", prefix + random_text(24)) for prefix in ("sk-", "sk-proj-", "sk-svcacct-", "sk-admin-")]
    values += [("github-token", "gh" + letter + "_" + random_text(36)) for letter in "pousr"]
    values += [("github-token", "github_pat_" + random_text(24)), ("gitlab-token", "glpat-" + random_text(24))]
    values += [("slack-token", "xox" + letter + "-" + random_text(12)) for letter in "abposr"]
    values += [("slack-token", "https://hooks.slack.com/services/" + random_text(24))]
    values += [("aws-key", prefix + random_text(16, string.ascii_uppercase + string.digits)) for prefix in ("AKIA", "ASIA")]
    values += [("google-key", "AIza" + random_text(35)), ("google-key", "ya29." + random_text(24))]
    values += [("jwt", "eyJ" + random_text(12) + ".eyJ" + random_text(12) + "." + random_text(12))]
    return values


def key_block(name, body, closed=True):
    marker = "-" * 5
    start = marker + "BEGIN " + name + marker + "\n"
    end = "\n" + marker + "END " + name + marker if closed else ""
    return start + body + end


class MemoryRedactionTest(StoreCase):
    def test_tc022_private_spans_are_ascii_case_insensitive_and_use_the_next_end(self):
        cases = [("<private>made-up address</private> hi", "[redacted:private] hi"),
                 ("<PRIVATE>a</Private> b", "[redacted:private] b"),
                 ("x<private>a\nb</private>y<private>c</private>", "x[redacted:private]y[redacted:private]"),
                 ("<private>a<private>b</private>c</private>", "[redacted:private]c</private>"),
                 ("<prİvate>a</prİvate>", "<prİvate>a</prİvate>")]
        for text, expected in cases:
            self.assertEqual(redaction.redact(text, {}).text, expected)

    def test_tc023_each_generated_format_is_redacted_before_any_write(self):
        examples = secret_examples()
        source = "\n".join(value for _, value in examples)
        expected = "\n".join("[redacted:" + kind + "]" for kind, _ in examples)
        for speaker in ("user", "agent"):
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                result = redaction.redact(source, {})
                self.assertTrue(result.text == expected, "each known format must retain its kind")
                files.append_jsonl(self.root / (speaker + ".jsonl"),
                                   {"speaker": speaker, "text": result.text}, "TBL-007")
            self.assertEqual(out.getvalue() + err.getvalue(), "")
        stored = b"".join(path.read_bytes() for path in self.root.rglob("*") if path.is_file())
        for kind, value in examples:
            with self.subTest(kind=kind):
                self.assertFalse(value.encode() in stored)

    def test_tc023_private_key_blocks_closed_open_and_multiline(self):
        for name in ("PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "ENCRYPTED PRIVATE KEY"):
            for closed in (False, True):
                body = random_text(96) + "\n" + random_text(96)
                source = "before\n" + key_block(name, body, closed) + ("\nafter" if closed else "")
                expected = "before\n[redacted:private-key]" + ("\nafter" if closed else "")
                self.assertTrue(redaction.redact(source, {}).text == expected)

    def test_tc023_pattern_order_and_macros_match_the_canonical_contract(self):
        text = section((API / "memory.md").read_text(encoding="utf-8"), "## Redaction")
        block = re.search(r"```text\n(.*?)\n```", text, re.S).group(1)
        macros = {}
        for line in block.splitlines():
            if line.startswith("V ") or line.startswith("VS "):
                name, value = line.split(None, 1)
                macros[name] = value
        expected = []
        for line in block.splitlines()[1:]:
            if not line or line.startswith(("V ", "VS ")):
                continue
            kind, pattern = line.split(None, 1)
            for name in ("VS", "V"):
                if pattern.endswith(name):
                    pattern = pattern[:-len(name)] + "(?:" + macros[name] + ")"
                    break
            expected.append((kind, pattern))
        self.assertEqual(list(redaction.PATTERNS), expected)

    def test_tc023_known_pattern_minimum_lengths(self):
        for kind, prefix, minimum in (("anthropic-key", "sk-ant-", 20), ("openai-key", "sk-", 20),
                                      ("gitlab-token", "glpat-", 20), ("github-token", "ghp_", 36)):
            for length in (minimum - 1, minimum, minimum + 1):
                value = prefix + random_text(length)
                output = redaction.redact(value, {}).text
                # The generic OpenAI pattern also recognizes a short Anthropic
                # body when its whole post-sk suffix is already long enough.
                if kind == "anthropic-key" and length == minimum - 1:
                    self.assertTrue(output == "[redacted:openai-key]")
                else:
                    expected = "[redacted:" + kind + "]" if length >= minimum else value
                    self.assertTrue(output == expected)

    def test_tc024_unclosed_private_span_removes_everything_after_it(self):
        self.assertEqual(redaction.redact("a <private> b c", {}).text, "a [redacted:private]")
        generated = random_text(48)
        output = redaction.redact("a <PRIVATE>" + generated, {}).text
        self.assertEqual(output, "a [redacted:private]")

    def test_tc025_memory_and_environment_values_have_their_distinct_marks(self):
        first, second, environment, short = [random_text(n) for n in (32, 32, 16, 8)]
        env = dict(zip(redaction.MEMORY_KEYS, (first, second)))
        env.update({"DEPLOY_TOKEN": environment, "SHORT_KEY": short})
        output = redaction.redact(" ".join((first, second, environment, short)), env).text
        self.assertTrue(output == "[redacted:memory-key] [redacted:memory-key] [redacted:environment] " + short)
        for value in (first, second, environment):
            self.assertFalse(value in output)

    def test_tc025_literal_longest_first_duplicate_priority_and_twelve_character_edge(self):
        shorter = random_text(12)
        longer = shorter + random_text(12)
        punctuation = "[" + random_text(16) + "].*"
        env = {"DEPLOY_TOKEN": shorter, "api_secret": longer, "AuthKey": punctuation,
               redaction.MEMORY_KEYS[0]: longer, "SHORT_KEY": random_text(11), "PUBLIC": random_text(20)}
        source = " ".join((longer, shorter, punctuation, env["SHORT_KEY"], env["PUBLIC"]))
        expected = "[redacted:memory-key] [redacted:environment] [redacted:environment] " + env["SHORT_KEY"] + " " + env["PUBLIC"]
        self.assertTrue(redaction.redact(source, env).text == expected)
        # Default environment use is tested with a completely synthetic mapping.
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(redaction.redact(source).text == expected)

    def test_tc026_lookalikes_stay_but_url_credentials_and_headers_are_removed(self):
        public = "max_tokens: 64000\ntoken = 5\ntoken = 12345678"
        self.assertEqual(redaction.redact(public, {}).text, public)
        user, password = random_text(16), random_text(32)
        source = "https://" + user + ":" + password + "@example.com/path"
        self.assertTrue(redaction.redact(source, {}).text == "https://[redacted:url-credentials]@example.com/path")
        for header in ("Authorization", "proxy-AUTHORIZATION"):
            source = header + ":\tBearer " + random_text(32) + "\r\nX-Trace: public"
            self.assertTrue(redaction.redact(source, {}).text == header + ":\t[redacted:authorization]\r\nX-Trace: public")

    def test_tc026_assigned_values_keep_names_and_respect_value_classes(self):
        for name in ("password", "passwd", "secret", "password.extra", "token", "api_key", "access-key"):
            for quote in ("", "'", '"'):
                value = random_text(24)
                source = name + " = " + quote + value + quote
                self.assertTrue(redaction.redact(source, {}).text == name + " = [redacted:assigned-secret]")
        self.assertEqual(redaction.redact("password=5", {}).text, "password=[redacted:assigned-secret]")
        self.assertEqual(redaction.redact("token=abcd1234", {}).text, "token=[redacted:assigned-secret]")
        self.assertEqual(redaction.redact("token=abc1234", {}).text, "token=abc1234")

    def test_tc027_pattern_failure_propagates_without_returning_or_writing_source(self):
        before = self.snapshot()
        broken = mock.Mock()
        broken.sub.side_effect = ValueError("made-up redaction error")
        with mock.patch.object(redaction, "COMPILED", (("private-key", broken),)):
            with self.assertRaisesRegex(ValueError, "made-up redaction error"):
                redaction.redact(random_text(32), {})
        with self.assertRaises(TypeError):
            redaction.redact(None, {})
        with self.assertRaises(UnicodeEncodeError):
            redaction.redact("\ud800", {})
        self.assertEqual(self.snapshot(), before)

    def test_tc028_utf8_cuts_are_character_boundaries_and_report_original_bytes(self):
        source = "가" * (redaction.ENTRY_BYTES // 3 + 1)
        result = redaction.redact(source, {})
        self.assertEqual(result.cut, len(source.encode("utf-8")))
        self.assertEqual(len(result.text.encode("utf-8")), redaction.ENTRY_BYTES // 3 * 3)
        self.assertNotIn("\ufffd", result.text)
        self.assertIsNone(redaction.redact("hi", {}).cut)
        self.assertIsNone(redaction.redact("x" * redaction.ENTRY_BYTES, {}).cut)
        result = redaction.redact("x" * (redaction.WINDOW_BYTES + 1), {})
        self.assertEqual((len(result.text), result.cut), (redaction.ENTRY_BYTES, redaction.WINDOW_BYTES + 1))
        source = "password=5 " * (redaction.ENTRY_BYTES // len("password=5 "))
        result = redaction.redact(source, {})
        self.assertEqual(result.cut, len(source.encode("utf-8")))
        self.assertEqual(len(result.text.encode("utf-8")), redaction.ENTRY_BYTES)

    def test_tc028_guard_window_prevents_a_split_key_from_reaching_the_entry(self):
        key = "sk-proj-" + random_text(64)
        source = "x" * (redaction.WINDOW_BYTES - 10) + key
        result = redaction.redact(source, {})
        self.assertTrue(result.text == "x" * redaction.ENTRY_BYTES)
        self.assertEqual(result.cut, len(source.encode("utf-8")))
        source = "x" * (redaction.ENTRY_BYTES - 40) + key
        result = redaction.redact(source, {})
        self.assertFalse(key in result.text)
        self.assertIsNone(result.cut)  # Redaction shrank it before either cut.

    def test_tc028_pass_order_and_recording_imports(self):
        key = "sk-proj-" + random_text(32)
        self.assertEqual(redaction.redact("<private>" + key + "</private>", {}).text, "[redacted:private]")
        self.assertEqual(redaction.redact(key, {redaction.MEMORY_KEYS[0]: key}).text, "[redacted:memory-key]")
        for name in ("projects.py", "redaction.py"):
            tree = ast.parse((SCRIPTS / "memory_lib" / name).read_text(encoding="utf-8"))
            imports = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            imports |= {alias.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names}
            self.assertFalse(imports & {"http", "urllib", "socket", "ssl", "sqlite3", "requests"})
