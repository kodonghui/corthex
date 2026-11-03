"""The test-only outer clock preserves the real hook's bytes and failures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from _common import ROOT


class OuterHookClockTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copyfile(ROOT / ".github/hook-check/measure_hook.py", self.root / "measure_hook.py")
        self.environment = dict(os.environ, HOOKCHECK_MEASURE_DIR=str(self.root / "measurements"))

    def invoke(self, script):
        (self.root / "hook.py").write_text(script, encoding="utf-8")
        result = subprocess.run([sys.executable, "-I", str(self.root / "measure_hook.py"), "prompt"],
                                env=self.environment, input="한국어 입력".encode(), capture_output=True, timeout=10)
        files = list((self.root / "measurements").glob("*.json"))
        self.assertEqual(len(files), 1)
        return result, json.loads(files[0].read_bytes())

    def test_keeps_the_actual_input_output_and_whole_child_duration(self):
        result, record = self.invoke("import sys,time\ntime.sleep(0.05)\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "한국어 입력".encode())
        self.assertEqual(result.stderr, b"")
        self.assertGreaterEqual(record["milliseconds"], 50)
        self.assertTrue(record["interpreter_startup_included"])
        self.assertFalse(record["wrapper_startup_included"])
        self.assertFalse(record["host_launch_overhead_included"])

    def test_keeps_the_actual_failure_instead_of_calling_it_a_pass(self):
        result, record = self.invoke("import sys\nsys.stderr.buffer.write(b'fixture failure')\nsys.exit(7)\n")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(record["exit"], 7)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"fixture failure")

    def test_memory_child_proxy_is_separate_from_the_hosts_proxy(self):
        self.environment.update(HTTP_PROXY="host-proxy-fixture", HOOKCHECK_MEMORY_PROXY="memory-proxy-fixture")
        result, record = self.invoke("import os,sys\nsys.stdout.write(os.environ['HTTP_PROXY'])\n")
        self.assertEqual(result.stdout, b"memory-proxy-fixture")
        self.assertEqual(self.environment["HTTP_PROXY"], "host-proxy-fixture")
        self.assertTrue(record["dedicated_memory_proxy"])
