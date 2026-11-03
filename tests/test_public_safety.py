"""Checks that nothing private or secret is published with the repository."""

import io
import re
import unittest
from pathlib import Path
from unittest import mock

from _common import ROOT

# Ignored by git: installed packages and Wrangler's local state.
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".wrangler"}
SKIP_FILES = {Path(__file__).resolve()}
PATTERNS = {
    "honorific reserved for one person": re.compile("대표님"),
    "OpenAI-style key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"),
    "Slack token": re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    "AWS key id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "personal home path": re.compile(r"/home/[a-z][a-z0-9_-]*/|/Users/[A-Za-z][^/\s]*/|[A-Za-z]:\\Users\\[^\\\s%]+"),
}


def text_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.resolve() in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


class PublicSafetyTest(unittest.TestCase):
    def test_no_private_or_secret_text(self):
        for path, text in text_files():
            for label, pattern in PATTERNS.items():
                with self.subTest(file=str(path.relative_to(ROOT)), check=label):
                    self.assertFalse(
                        bool(pattern.search(text)),
                        "Private or secret text detected; value withheld.",
                    )


class PublicSafetyReportingTest(unittest.TestCase):
    def test_failure_report_omits_detected_value(self):
        synthetic_key = "sk-" + "x" * 24
        output = io.StringIO()
        case = PublicSafetyTest("test_no_private_or_secret_text")
        with mock.patch(__name__ + ".text_files", return_value=[
            (ROOT / "synthetic-secret.txt", synthetic_key),
        ]):
            result = unittest.TextTestRunner(stream=output).run(case)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.errors, [])
        self.assertIn("OpenAI-style key", output.getvalue())
        self.assertIn("synthetic-secret.txt", output.getvalue())
        self.assertNotIn(synthetic_key, output.getvalue())


if __name__ == "__main__":
    unittest.main()
