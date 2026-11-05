"""Regressions for the original hub screen criteria; DOM doubles, not a browser."""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HubPageRenderTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_empty_checks_trace_groups_reference_places_and_missing_reason(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests/fixtures/hub_page_assertions.js"),
             str(ROOT / "plugins/corthex-nexus/skills/corthex-hub/assets/hub.html")],
            capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b'"passed":true', result.stdout)
