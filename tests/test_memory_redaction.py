"""TC-022–028: generated secrets never become fixtures, output or raw files."""

import ast
import contextlib
import io
import json
import os
import re
import secrets
import string
import subprocess
import sys
import time
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
    values += [("notion-token", "ntn_" + random_text(11, string.digits) + random_text(35)),
               ("notion-token", "secret_" + random_text(43))]
    values += [("supabase-key", "sbp_" + random_text(40, string.ascii_lowercase + string.digits)),
               ("supabase-key", "sb_secret_" + random_text(31) + "_")]
    values += [("atlassian-token", "ATATT3" + random_text(186) + "=" + random_text(8, "0123456789ABCDEF"))]
    values += [("stripe-key", kind + "_" + mode + "_" + random_text(24)) for kind in ("sk", "rk") for mode in ("live", "test")]
    values += [("huggingface-token", "hf_" + random_text(34, string.ascii_letters)),
               ("npm-token", "npm_" + random_text(36))]
    hexadecimal = "0123456789abcdef"
    values += [("langsmith-key", "lsv2_" + kind + "_" + random_text(32, hexadecimal) + "_" + random_text(10, hexadecimal))
               for kind in ("pt", "sk", "tr")]
    values += [("langsmith-key", "ls__" + random_text(32, hexadecimal))]
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
        for filename, heading in (("memory.md", "## Redaction"), ("memory.ko.md", "## 지우기 처리")):
            text = section((API / filename).read_text(encoding="utf-8"), heading)
            block = re.search(r"```text\n(.*?)\n```", text, re.S).group(1)
            macros = {}
            names = ("KVS", "KV", "VS", "V")
            for line in block.splitlines():
                if line.startswith(tuple(name + " " for name in names)):
                    name, value = line.split(None, 1)
                    macros[name] = value
            self.assertEqual(set(macros), set(names))
            expected = []
            for line in block.splitlines()[1:]:
                if not line or line.startswith(tuple(name + " " for name in names)):
                    continue
                kind, pattern = line.split(None, 1)
                for name in names:
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

    def test_tc023_jwt_boundary_and_canonical_substitution_agree(self):
        pattern = dict(redaction.COMPILED)["jwt"]
        token = "eyJ" + random_text(12) + ".eyJ" + random_text(12) + "." + random_text(12)
        for prefix in ("", " ", "(", ".", "\n", "a", "7", "_", "-"):
            source = prefix + token
            expected = prefix + "[redacted:jwt]" if prefix in ("", " ", "(", ".", "\n") else source
            self.assertTrue(redaction.redact(source, {}).text == expected)
            self.assertTrue(pattern.sub("[redacted:jwt]", source) == expected)
        for prefix in ("%3D", "Bearer%20", "%3d", "%41"):
            source = prefix + token
            expected = prefix + "[redacted:jwt]"
            self.assertTrue(redaction.redact(source, {}).text == expected)
            self.assertTrue(pattern.sub("[redacted:jwt]", source) == expected)
        for a in (7, 8, 9):
            for b in (7, 8, 9):
                for c in (7, 8, 9):
                    source = "eyJ" + random_text(a) + ".eyJ" + random_text(b) + "." + random_text(c)
                    expected = pattern.sub("[redacted:jwt]", source)
                    self.assertTrue(redaction.redact(source, {}).text == expected)

    def test_tc023_private_key_name_slots_are_bounded_on_both_headers(self):
        for length, matches in ((40, True), (41, False)):
            source = key_block("A" * length + "PRIVATE KEY", random_text(32))
            expected = "[redacted:private-key]" if matches else source
            self.assertTrue(redaction.redact(source, {}).text == expected)
        source = key_block("PRIVATE KEY", random_text(32), False) + "\n-----END " + "A" * 41 + "PRIVATE KEY-----\nafter"
        self.assertTrue(redaction.redact(source, {}).text == "[redacted:private-key]")

    def test_tc028_four_small_calls_and_one_large_stay_within_growth_limit(self):
        worker = Path(__file__).with_name("bench_memory_redaction.py")
        # About 18 seconds on Linux for 33 inputs; macOS Intel runners took 1.7 times as long.
        run = subprocess.run([sys.executable, str(worker), "--growth", "--samples", "5"],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, "growth worker exit %d; input remains suppressed" % run.returncode)
        marked = [line for line in run.stdout.splitlines() if line.startswith("CORTHEX_REDACTION_BENCH=")]
        self.assertEqual(len(marked), 1)
        data = json.loads(marked[0].split("=", 1)[1])
        self.assertEqual(data["mode"], "growth")
        self.assertEqual(data["statistic"], "minimum")
        self.assertEqual((data["small_repetitions"],data["large_repetitions"]),(4,1))
        self.assertEqual({row["input"] for row in data["rows"]},
                         {"private-openers", "pem-begin-name-repeat", "jwt-no-dots",
                          "jwt-percent-repeat", "anthropic-near-minimum", "openai-near-minimum",
                          "github-near-minimum", "gitlab-near-minimum", "slack-near-minimum", "aws-short-body",
                          "google-short-body", "url-without-at", "authorization-repeat", "passwd-repeat", "token-repeat",
                          "token-quoted-escapes",
                          "notion-near-minimum", "supabase-near-minimum", "atlassian-near-minimum",
                          "stripe-near-minimum", "huggingface-near-minimum", "npm-near-minimum",
                          "langsmith-near-minimum", "bearer-short-token", "korean-password-count",
                          "korean-token-digits", "korean-quote-phrase", "resident-bad-date", "resident-label-short", "phone-near-miss",
                          "card-luhn-fail", "card-security-code", "account-long-digits"})
        for row in data["rows"]:
            self.assertEqual(row["samples"],5)
            self.assertEqual(row["large_bytes"], row["small_bytes"] * 4)
            self.assertGreater(row["small_ms"], 20, json.dumps(row, sort_keys=True))
            self.assertLessEqual(row["ratio"], 2.5, json.dumps(row, sort_keys=True))

    def test_tc028_growth_inputs_hold_the_bytes_that_the_guard_assumes(self):
        # The growth worker sets the byte limits to four times the small size, plus one.
        import bench_memory_redaction as bench
        for name in bench.GROWTH:
            for size in (1024, 32 * 1024 + 1, 128 * 1024):
                with self.subTest(name=name, size=size):
                    self.assertEqual(len(bench.slow_input(name, size).encode("utf-8")), size)

    def test_tc024_unclosed_private_span_removes_everything_after_it(self):
        self.assertEqual(redaction.redact("a <private> b c", {}).text, "a [redacted:private]")
        generated = random_text(48)
        output = redaction.redact("a <PRIVATE>" + generated, {}).text
        self.assertTrue(output == "a [redacted:private]")

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
        self.assertEqual(self.snapshot(), before)

    def test_tc027_environment_and_step_five_errors_propagate(self):
        before = self.snapshot()
        environment = mock.Mock()
        environment.items.side_effect = ValueError("made-up environment read error")
        with self.assertRaises(ValueError):
            redaction.redact(random_text(32), environment)
        broken = mock.Mock()
        broken.sub.side_effect = ValueError("made-up pattern error")
        with mock.patch.object(redaction, "COMPILED", (redaction.COMPILED[0], ("openai-key", broken))):
            with self.assertRaises(ValueError):
                redaction.redact(random_text(32), {})
        self.assertEqual(self.snapshot(), before)

    def test_tc028_lone_surrogates_are_normalized_before_utf8_cuts(self):
        cases = [("\ud800", "\ufffd"), ("\udfff", "\ufffd"),
                 ("a\ud800b\udc00c", "a\ufffdb\ufffdc"),
                 ("\ud800\ud800\udc00", "\ufffd\U00010000"),
                 ("\ud83d\ude42", "\U0001f642"), ("가\U0001f642", "가\U0001f642")]
        before = self.snapshot()
        for source, expected in cases:
            result = redaction.redact(source, {})
            self.assertTrue(result.text == expected)
            self.assertIsNone(result.cut)
            result.text.encode("utf-8")
        for limit in (redaction.ENTRY_BYTES, redaction.WINDOW_BYTES):
            source = "x" * (limit - 1) + "\ud800"
            result = redaction.redact(source, {})
            self.assertEqual(result.cut, limit + 2)
            self.assertLessEqual(len(result.text.encode("utf-8")), redaction.ENTRY_BYTES)
            self.assertNotIn("\ufffd", result.text)
        self.assertEqual(self.snapshot(), before)

    def test_tc025_environment_matching_uses_the_same_surrogate_normalization(self):
        prefix = random_text(24)
        raw, normalized = prefix + "\ud800", prefix + "\ufffd"
        environment = {"DEPLOY_TOKEN": raw}
        before = self.snapshot()
        result = redaction.redact(raw + " " + normalized, environment)
        self.assertTrue(result.text == "[redacted:environment] [redacted:environment]")
        self.assertFalse(prefix in result.text)
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

    def test_tc320_earlier_shrinking_passes_cannot_expose_the_guard_fragment(self):
        first, second = random_text(64), random_text(64)
        prefixes = [("<private>" + "p" * 20000 + "</private>", {}),
                  (key_block("PRIVATE KEY", "p" * 20000), {}),
                  (((first + " " + second + " ") * 200), {"FIRST_SECRET": first, "SECOND_SECRET": second}),
                  ("Authorization: " + "p" * 20000 + "\n", {})]
        for prefix, environment in prefixes:
            for kind in ("environment", "openai-key"):
                value = random_text(64) if kind == "environment" else "sk-proj-" + random_text(64)
                visible = value[:39] if kind == "environment" else value[:20]
                chosen = dict(environment, DEPLOY_TOKEN=value) if kind == "environment" else environment
                padding_bytes = redaction.WINDOW_BYTES - len(prefix.encode("utf-8")) - len(visible)
                padding = "가" * (padding_bytes // 3) + "z" * (padding_bytes % 3)
                source = prefix + padding + value + " tail"
                result = redaction.redact(source, chosen)
                self.assertFalse(visible in result.text, "guard fragments must not enter output")
                self.assertFalse(visible[-12:] in result.text)
                self.assertEqual(result.cut, len(source.encode("utf-8")))
                # Only step 1 cuts: after replacement and provenance filtering
                # the result is already below the final byte limit.
                self.assertLess(len(result.text.encode("utf-8")), redaction.ENTRY_BYTES)
        value = random_text(32) + "가" + random_text(32)
        prefix = prefixes[0][0]
        source = prefix + "z" * (redaction.WINDOW_BYTES - len(prefix) - 33) + value + " tail"
        result = redaction.redact(source, {"DEPLOY_TOKEN": value})
        self.assertFalse(value[:32] in result.text)
        self.assertEqual(result.cut, len(source.encode("utf-8")))

    def test_tc320_cutoff_preserves_only_markers_started_before_the_source_point(self):
        prefix = "<private>" + "p" * 20000 + "</private>"
        value = random_text(64)
        for offset, kept in ((-8, True), (0, False), (8, False)):
            public = prefix + "z" * (redaction.ENTRY_BYTES + offset - len(prefix))
            source = public + value + " q" * 5000
            result = redaction.redact(source, {"DEPLOY_TOKEN": value})
            self.assertEqual("[redacted:environment]" in result.text, kept)
            self.assertFalse(value in result.text)
            self.assertEqual(result.cut, len(source.encode("utf-8")))
        for value_start, kept in ((redaction.ENTRY_BYTES - 4, True), (redaction.ENTRY_BYTES + 8, False)):
            header = "Authorization: "
            public = prefix + "z" * (value_start - len(prefix) - len(header))
            source = public + header + value + "\n" + " q" * 5000
            result = redaction.redact(source, {})
            self.assertEqual("[redacted:authorization]" in result.text, kept)
            self.assertFalse(value in result.text)

    def test_tc320_canonical_fragments_and_jwt_markers_use_the_source_point(self):
        prefix = "<private>" + "p" * 20000 + "</private>"
        values = ["AKIA" + random_text(16, string.ascii_uppercase + string.digits),
                  "eyJ" + random_text(12) + ".eyJ" + random_text(12) + "." + random_text(32)]
        for value in values:
            visible = value[:-10]
            source = prefix + "z" * (redaction.WINDOW_BYTES - len(prefix) - len(visible)) + value
            result = redaction.redact(source, {})
            self.assertFalse(visible in result.text, "canonical fragments must not enter output")
            self.assertEqual(result.cut, len(source.encode("utf-8")))
        value = values[-1]
        for offset, kept in ((-8, True), (0, False), (8, False)):
            source = prefix + "z" * (redaction.ENTRY_BYTES + offset - len(prefix) - 1) + " " + value + " q" * 5000
            result = redaction.redact(source, {})
            self.assertEqual("[redacted:jwt]" in result.text, kept)
            self.assertFalse(value in result.text)

    def test_tc320_unclipped_input_and_character_start_semantics_stay_intact(self):
        prefix = "<private>" + "p" * 20000 + "</private>"
        source = prefix + "z" * (redaction.ENTRY_BYTES + 1000 - len(prefix)) + " ordinary tail"
        result = redaction.redact(source, {})
        self.assertTrue(result.text.endswith(" ordinary tail"))
        self.assertIsNone(result.cut)
        value = "가" + random_text(32)
        source = prefix + "z" * (redaction.ENTRY_BYTES - 1 - len(prefix)) + value + " q" * 5000
        result = redaction.redact(source, {"DEPLOY_TOKEN": value})
        self.assertTrue(result.text.endswith("[redacted:environment]"))
        self.assertFalse(value in result.text)
        self.assertEqual(result.cut, len(source.encode("utf-8")))

    def test_tc028_pass_order_and_recording_imports(self):
        key = "sk-proj-" + random_text(32)
        self.assertTrue(redaction.redact("<private>" + key + "</private>", {}).text == "[redacted:private]")
        self.assertTrue(redaction.redact(key, {redaction.MEMORY_KEYS[0]: key}).text == "[redacted:memory-key]")
        for name in ("projects.py", "redaction.py"):
            tree = ast.parse((SCRIPTS / "memory_lib" / name).read_text(encoding="utf-8"))
            imports = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            imports |= {alias.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names}
            self.assertFalse(imports & {"http", "urllib", "socket", "ssl", "sqlite3", "requests"})


# TASK-109: Korean names, other services' tokens and personal numbers. Every
# value is made up while the test runs; only ordinary sentences are fixed.
KOREAN_PASSWORD_NAMES = ("비밀번호", "비밀 번호", "비번", "패스워드", "암호")
KOREAN_KEY_NAMES = ("API 키", "API키", "api 키", "키", "토큰", "액세스 토큰", "액세스토큰", "액세스 키", "시크릿",
                    "시크릿 키", "비밀 키", "비밀키", "인증 키", "인증키")
SYMBOLS = "!#$%&*+-./:<=>?@^_~"
# Sentences that hold the names, and numbers that look long, stay as they are.
ORDINARY = ("비밀번호는 바꿔야 해", "토큰 수가 너무 많아요", "비밀번호는 8자 이상이어야 합니다.",
            "비밀번호 4자리를 입력하세요.", "비번 5회 틀리면 잠깁니다.", "API 키를 환경 변수에 넣어 주세요.",
            "토큰 4096개까지 보낼 수 있어요.", "암호화된 파일은 이 기기에 남습니다.",
            "액세스 토큰이 만료되면 다시 로그인하세요.", "인증 키가 없으면 검색은 낱말로만 합니다.",
            "시크릿 키는 비밀 저장소에 둡니다.", "비밀번호 (선택)", "비밀번호: ****", "키보드 단축키를 바꿨어요.",
            "쿠키 sessionid12345는 그대로 둡니다.", "터키 Istanbul123 여행", "토큰 abc는 짧아요.",
            "토큰: 12345678", "주민번호 앞자리만 적어 주세요.", "계좌 잔액 1000000000원", "계좌번호를 알려 주세요.")
NUMBERS = ("1794058051195", "20261107135733", "주문 번호 2026110700012345", "run 42378332169",
           "job 128430412035", "991399-1234567", "010229-3123456", "900101-9123456", "01012345678",
           "1234 5678 9012 3456", "4111 1111 1111 1112", "v0.2.1 192.168.0.1", "2026-11-07 13:57:33",
           "메일은 dev@example.com 주소로 보내 주세요.")


def has_final_consonant(name):
    last = name[-1]
    return "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0


def separators(name):
    """Each particle the name takes, then ":", "=" and white space."""
    pairs = ("은", "이", "을") if has_final_consonant(name) else ("는", "가", "를")
    return [pair + " " for pair in pairs] + [pairs[0] + ": ", ": ", " = ", "=", " ", "\t"]


def luhn(body):
    total = 0
    for place, digit in enumerate(reversed(body)):
        value = int(digit) * (2 if place % 2 == 0 else 1)
        total += value - 9 if value > 9 else value
    return body + str((10 - total % 10) % 10)


def card_numbers():
    """Made-up numbers that pass the Luhn check, as written plain and in groups."""
    values = []
    for prefix, length, groups in (("4", 16, (4, 4, 4, 4)), ("51", 16, (4, 4, 4, 4)), ("2221", 16, (4, 4, 4, 4)),
                                   ("37", 15, (4, 6, 5)), ("36", 14, (4, 6, 4)), ("6011", 16, (4, 4, 4, 4)),
                                   ("9410", 16, (4, 4, 4, 4)), ("4", 13, (4, 4, 5)), ("62", 19, (4, 4, 4, 4, 3))):
        digits = luhn(prefix + random_text(length - len(prefix) - 1, string.digits))
        parts, used = [], 0
        for size in groups:
            parts.append(digits[used:used + size])
            used += size
        values += [digits, " ".join(parts), "-".join(parts)]
    return values


def resident_numbers():
    """Made-up numbers whose first six digits are a real date of the century the seventh gives."""
    values = []
    for seventh in "12345678":
        century = 1900 if seventh in "1256" else 2000
        year = century + secrets.randbelow(100 if century == 1900 else 26)
        day = 1 + secrets.randbelow(28)
        values.append("%02d%02d%02d" % (year % 100, 1 + secrets.randbelow(12), day) + seventh +
                      random_text(6, string.digits))
    values.append("000229" + "3" + random_text(6, string.digits))
    return values


def sent_text(text):
    """The text as the pre-send pass gives it, inside a curator request."""
    from html import escape
    import xml.etree.ElementTree as ET
    from memory_lib import model_access, model_request
    credentials = model_access.Credentials.read({redaction.MEMORY_KEYS[0]: "fixture-" + random_text(32)})
    document = ('<request kind="curate" instructions="curate-3"><turns><entry id="e_sample">' + escape(text) +
                '</entry></turns></request>')
    sent = model_request.document(document, instructions="curate-3", environment={}, credentials=credentials)
    return ET.fromstring(sent).find(".//entry").text or ""


def escaped_values(quote):
    """Values in quotes whose letter follows a backslash or that are 8 characters long only
    as written: letters as JSON's \\u escapes, whose hexadecimal digits hold no letter;
    \\n counted as two characters; and an escaped quote after 8 written characters."""
    letters = "".join("\\u%04x" % ord(c) for c in random_text(3, "abcdefghi") + random_text(5, string.digits))
    return (("unicode escapes", letters), ("written length", "k" + random_text(1) + "\\n" + random_text(2) + "\\n"),
            ("escaped quote", "\\n" * 4 + "\\" + quote + random_text(2)))


class KoreanAndPersonalRedactionTest(StoreCase):
    def both(self, text):
        """The recorded text and the sent text, which must agree."""
        recorded, sent = redaction.redact(text, {}).text, sent_text(text)
        self.assertTrue(recorded == sent, "the record and pre-send passes differ")
        return recorded

    def test_tc395_korean_names_keep_the_name_and_separator_and_lose_an_ascii_value(self):
        for names, kind in ((KOREAN_PASSWORD_NAMES, "V"), (KOREAN_KEY_NAMES, "VS")):
            for name in names:
                for separator in separators(name):
                    values = ["k" + random_text(23), random_text(12) + secrets.choice(SYMBOLS) + "x" + random_text(4),
                              '"' + random_text(8) + " " + random_text(8) + '"', "'" + random_text(16) + "'"]
                    if kind == "V":
                        values += [random_text(1, string.ascii_letters), random_text(6, string.digits)]
                    for value in values:
                        with self.subTest(name=name, separator=separator, length=len(value)):
                            text = "앞 문장. " + name + separator + value + " 뒤 문장"
                            output = self.both(text)
                            self.assertTrue(output == "앞 문장. " + name + separator + "[redacted:assigned-secret] 뒤 문장")
                            if len(value) >= 6:  # the equality above already covers a short value
                                self.assertFalse(value.strip("\"'") in output)
        # The earlier check's mixed prompt: both values go, the English one as before.
        value = "k" + random_text(15)
        self.assertTrue(self.both("비밀번호: " + value + " 그리고 password: " + value) ==
                        "비밀번호: [redacted:assigned-secret] 그리고 password: [redacted:assigned-secret]")

    def test_tc395_quoted_names_as_json_keys_lose_their_values(self):
        for name in KOREAN_PASSWORD_NAMES + KOREAN_KEY_NAMES:
            for quote in "\"'":
                for separator in (": ", ":", " = ", "="):
                    value = "k" + random_text(15)
                    for written in (quote + value + quote, value):
                        with self.subTest(name=name, quote=quote, separator=separator, quoted=written != value):
                            key = "{" + quote + name + quote + separator
                            output = self.both(key + written + ", " + quote + "n" + quote + ": 1}")
                            self.assertTrue(output == key + "[redacted:assigned-secret], " + quote + "n" + quote + ": 1}")

    def test_tc395_quoted_values_hold_escapes_and_open_quotes_hide_nothing(self):
        for name in KOREAN_PASSWORD_NAMES + KOREAN_KEY_NAMES:
            for quote in "\"'":
                value = "k" + random_text(7) + "\\" + quote + random_text(8) + "\\\\"
                tail = random_text(15)
                for case, source, expected in (
                        # JSON's escaped quote and backslash stay inside the value.
                        ("escapes", "{" + quote + name + quote + ": " + quote + value + quote + ", " + quote + "n" + quote + ": 1}",
                         "{" + quote + name + quote + ": [redacted:assigned-secret], " + quote + "n" + quote + ": 1}"),
                        # A quote left open runs to the end of the line, or to Hangul when no quote closes it.
                        ("line end", name + ": " + quote + "k" + tail + "\n다음 줄 " + quote,
                         name + ": [redacted:assigned-secret]\n다음 줄 " + quote),
                        ("text end", name + ": " + quote + "k" + tail, name + ": [redacted:assigned-secret]"),
                        ("Hangul", name + ": " + quote + "k" + tail + " 이고 다음", name + ": [redacted:assigned-secret]이고 다음"),
                        # A quote after white space opens another text, and a tab stays inside the value.
                        ("another quote", name + ": " + quote + "k" + tail + " 이고 이름은 " + quote + "b" + quote,
                         name + ": [redacted:assigned-secret]이고 이름은 " + quote + "b" + quote),
                        ("tab", name + ": " + quote + "k" + tail + "\t" + tail + quote + " 다음", name + ": [redacted:assigned-secret] 다음")):
                    with self.subTest(name=name, quote=quote, case=case):
                        output = self.both(source)
                        self.assertTrue(output == expected)
                        self.assertFalse(tail in output)
        # A quote that closes later on its line, after Hangul, holds a phrase.
        for text in ('API 키는 "Settings 메뉴"에서 만듭니다.', "토큰은 'Developer settings 화면'에서 만들어요.",
                     '비밀번호는 "8자 이상"이어야 해요.', '비밀번호는 "8자 이상', '비번: "1234 형식"으로 쓰세요.'):
            with self.subTest(text=text):
                self.assertEqual(self.both(text), text)

    def test_tc395_an_escaped_letter_counts_and_a_backslash_is_never_a_phrase_or_count(self):
        for name in KOREAN_KEY_NAMES:
            for quote in "\"'":
                for case, value in escaped_values(quote):
                    with self.subTest(name=name, quote=quote, case=case):
                        key = "{" + quote + name + quote + ": "
                        self.assertTrue(self.both(key + quote + value + quote + "}") == key + "[redacted:assigned-secret]}")
        for name in KOREAN_PASSWORD_NAMES + KOREAN_KEY_NAMES:
            for quote in "\"'":
                value, digits = "k" + random_text(7), random_text(4, string.digits)
                cases = [("phrase", name + ": " + quote + value + "\\" + quote + "한글" + quote + "에서",
                          name + ": [redacted:assigned-secret]한글" + quote + "에서", value)]
                if name in KOREAN_PASSWORD_NAMES:
                    cases.append(("count", name + ": " + quote + digits + "\\" + quote + "5자 이상",
                                  name + ": [redacted:assigned-secret]자 이상", digits))
                for case, source, expected, hidden in cases:
                    with self.subTest(name=name, quote=quote, case=case):
                        output = self.both(source)
                        self.assertTrue(output == expected)
                        self.assertFalse(hidden in output)

    def test_tc023_english_quoted_values_hold_escapes_and_open_quotes_hide_nothing(self):
        for name in ("password", "passwd", "secret", "token", "api_key", "access-key"):
            for quote in "\"'":
                value = "k" + random_text(7) + "\\" + quote + random_text(8) + "\\\\"
                tail = random_text(15)
                for case, source, expected in (
                        ("escapes", "{" + quote + name + quote + ": " + quote + value + quote + ", " + quote + "n" + quote + ": 1}",
                         "{" + quote + name + quote + ": [redacted:assigned-secret], " + quote + "n" + quote + ": 1}"),
                        ("line end", name + " = " + quote + "k" + tail + " and more\nnext " + quote,
                         name + " = [redacted:assigned-secret]\nnext " + quote),
                        ("text end", name + " = " + quote + "k" + tail, name + " = [redacted:assigned-secret]")):
                    with self.subTest(name=name, quote=quote, case=case):
                        output = self.both(source)
                        self.assertTrue(output == expected)
                        self.assertFalse(tail in output)

    def test_tc023_an_escaped_letter_counts_and_eight_characters_count_as_written(self):
        for name in ("token", "api_key", "access-key"):
            for quote in "\"'":
                for case, value in escaped_values(quote):
                    with self.subTest(name=name, quote=quote, case=case):
                        key = "{" + quote + name + quote + ": "
                        self.assertTrue(self.both(key + quote + value + quote + "}") == key + "[redacted:assigned-secret]}")
        # Without a letter, or shorter than 8 both ways, a value stays.
        for text in ('{"token": "\\1\\2\\3\\4"}', '{"token": "' + random_text(8, string.digits) + '"}',
                     "{'token': 'abc\\'d'}", '{"API 키": "\\1\\2\\3\\4"}'):
            with self.subTest(text=text):
                self.assertEqual(self.both(text), text)

    def test_tc395_key_names_need_eight_characters_with_a_letter_and_password_counts_stay(self):
        for name in KOREAN_KEY_NAMES:
            for value in (random_text(7, string.ascii_letters), random_text(12, string.digits), "한글값입니다"):
                with self.subTest(name=name, value=value):
                    text = name + ": " + value
                    self.assertEqual(self.both(text), text)
        for name in KOREAN_PASSWORD_NAMES:
            for text in (name + "는 8자 이상", name + " 4자리", name + ": 3회", name + "는 바꿨어요", name + ": ****"):
                with self.subTest(text=text):
                    self.assertEqual(self.both(text), text)
            value = random_text(4, string.digits)
            self.assertTrue(self.both(name + ": " + value + " 입니다") == name + ": [redacted:assigned-secret] 입니다")

    def test_tc396_other_service_tokens_and_bare_bearer_values(self):
        examples = secret_examples()[-15:]
        self.assertEqual([kind for kind, _ in examples],
                         ["notion-token"] * 2 + ["supabase-key"] * 2 + ["atlassian-token"] + ["stripe-key"] * 4 +
                         ["huggingface-token", "npm-token"] + ["langsmith-key"] * 4)
        for kind, value in examples:
            with self.subTest(kind=kind):
                self.assertTrue(self.both("값 " + value + " 끝") == "값 [redacted:" + kind + "] 끝")
        for prefix in ("Bearer ", "bearer ", "Bearer\t"):
            value = random_text(16) + secrets.choice("._~+/-") + random_text(8) + "=="
            with self.subTest(prefix=prefix):
                self.assertTrue(self.both("curl -H x " + prefix + value + " y") ==
                                "curl -H x " + prefix + "[redacted:bearer-token] y")
        short = "Bearer " + random_text(15)
        self.assertEqual(self.both(short), short)
        # Shorter than each format's minimum, the look-alikes stay.
        for text in ("ntn_" + random_text(11, string.digits) + random_text(34), "secret_" + random_text(42),
                     "sbp_" + random_text(39, string.ascii_lowercase), "sb_secret_" + random_text(15),
                     "ATATT3" + random_text(185), "sk_live_" + random_text(9), "hf_" + random_text(33, string.ascii_letters),
                     "npm_" + random_text(35), "lsv2_pt_" + random_text(19), "ls__" + random_text(19)):
            with self.subTest(text=text[:12]):
                self.assertEqual(self.both(text + " 끝"), text + " 끝")

    def test_tc397_personal_numbers_lose_their_digits(self):
        cases = [(value[:6] + "-" + value[6:], "", "resident-number") for value in resident_numbers()]
        cases += [(value, label, "resident-number") for value in resident_numbers()[:3]
                  for label in ("주민번호: ", "주민등록번호는 ", "주민번호 ")]
        cases += [(value, "", "card-number") for value in card_numbers()]
        cases += [("01" + middle + separator + random_text(digits, string.digits) + separator + random_text(4, string.digits),
                   "", "phone-number")
                  for middle in "016789" for separator in "- " for digits in (3, 4)]
        cases += [(value, label, "account-number")
                  for label in ("계좌: ", "계좌번호는 ", "계좌 번호: ", "계좌 국민 ", "계좌번호: 카카오뱅크 ")
                  for value in (random_text(3, string.digits) + "-" + random_text(2, string.digits) + "-" +
                                random_text(6, string.digits), random_text(14, string.digits))]
        for value, label, kind in cases:
            with self.subTest(kind=kind, label=label, length=len(value)):
                output = self.both("앞 " + label + value + " 뒤")
                self.assertTrue(output == "앞 " + label + "[redacted:" + kind + "] 뒤")

    def test_tc397_numbers_written_after_a_card_stay_and_the_card_goes(self):
        def passes(digits):
            return 13 <= len(digits) <= 19 and luhn(digits[:-1]) == digits
        for value in card_numbers():
            separator = "-" if "-" in value else " "
            digits = value.replace(separator, "")
            for sizes in ((3,), (4,), (4, 3)):
                # A security code, a date or another number that the groups run on into; made again
                # while the card and its first groups would pass the check together by chance.
                while True:
                    extra = [random_text(size, string.digits) for size in sizes]
                    if not any(passes(digits + "".join(extra[:count])) for count in range(1, len(extra) + 1)):
                        break
                after = "".join(separator + part for part in extra)
                with self.subTest(card=len(value), after=sizes):
                    self.assertTrue(self.both("앞 " + value + after + " 뒤") == "앞 [redacted:card-number]" + after + " 뒤")
        # Two cards of four groups in a row: each goes, since the search goes on after the first.
        cards = [value for value in card_numbers() if len(value) == 19 and " " in value]
        self.assertTrue(self.both(" ".join(cards)) == " ".join(["[redacted:card-number]"] * len(cards)))

    def test_tc397_quoted_labels_keep_their_quotes_and_lose_the_number(self):
        for quote in "\"'":
            for label in ("주민번호", "주민등록번호"):
                value = resident_numbers()[0]
                with self.subTest(label=label, quote=quote):
                    key = "{" + quote + label + quote + ": " + quote
                    self.assertTrue(self.both(key + value + quote + "}") == key + "[redacted:resident-number]" + quote + "}")
            for label, bank in (("계좌번호", ""), ("계좌", "국민 ")):
                value = random_text(3, string.digits) + "-" + random_text(2, string.digits) + "-" + random_text(6, string.digits)
                with self.subTest(label=label, quote=quote):
                    key = "{" + quote + label + quote + ": " + quote + bank
                    self.assertTrue(self.both(key + value + quote + "}") == key + "[redacted:account-number]" + quote + "}")

    def test_tc398_ordinary_sentences_long_numbers_and_mail_addresses_stay(self):
        self.assertGreaterEqual(len(ORDINARY), 10)
        for text in ORDINARY + NUMBERS:
            with self.subTest(text=text):
                self.assertEqual(self.both(text), text)
        # A made-up order number that a payment card's first digits and the Luhn check do not fit.
        for _ in range(20):
            order = random_text(1, "178") + random_text(15, string.digits)
            self.assertEqual(self.both("주문 " + order), "주문 " + order)
        # The instructions sent with every request pass the same patterns and stay whole.
        from memory_lib import model_access, model_prompts, model_request
        credentials = model_access.Credentials.read({redaction.MEMORY_KEYS[0]: "fixture-" + random_text(32)})
        for name, prompt in model_prompts.PROMPTS.items():
            with self.subTest(prompt=name):
                self.assertEqual(model_request._redact(prompt, {}, credentials), prompt)
