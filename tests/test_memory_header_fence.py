"""TC-327: supported atomic header replacement inside fingerprint I/O."""

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from test_memory_store import SCRIPTS, StoreCase
from memory_lib import base, diagnostics, files, raw_log
from memory_lib import clock


WRITER = r'''
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from memory_lib import base, clock, files, locks
root = Path(sys.argv[2])
lease = locks.Lock(root / "store.lock", "store", sys.argv[3])
with lease.held(clock.now() + 5):
    header = files.read_json(root / "store.json")
    header["device"] = base.new_id("d")
    files.write_json(root / "store.json", header, "TBL-001", check=lease.check)
'''


class HeaderFenceTest(StoreCase):
    def exercise(self, kind, stage):
        path = self.root / "store.json"
        files.write_json(path, self.header, "TBL-001")
        base.private_directory(self.root / "projects/sample/raw")
        base.private_directory(self.root / "projects/sample/unprocessed")
        logger = diagnostics.Diagnostics(self.memory)
        log = raw_log.RawLog(self.memory, "sample", "codex", kind + stage)
        if kind == "late":
            logger.read_gate(clock.now() + 10)
        opened, private_open, write = Path.open, files.private_open, files.os.write
        target, swapped, payloads = [], [], []
        testcase = self

        def replace():
            if swapped:
                return
            env = {key: value for key, value in os.environ.items() if not key.upper().startswith(
                ("CLOUDFLARE", "CF_", "CLAUDE", "ANTHROPIC", "OPENAI", "CORTHEX_MEMORY_"))}
            result = subprocess.run([sys.executable, "-I", "-c", WRITER, str(SCRIPTS),
                                     str(self.root), self.header["device"]], env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=10)
            testcase.assertEqual(result.returncode, 0, "atomic store writer failed")
            testcase.assertEqual(result.stdout + result.stderr, b"")
            swapped.append(True)

        class Incoming:
            def __init__(self, source):
                self.source = source
            def __enter__(self):
                self.source.__enter__()
                return self
            def __exit__(self, *args):
                result = self.source.__exit__(*args)
                if stage == "close":
                    replace()
                return result
            def fileno(self):
                return self.source.fileno()
            def read(self, size=-1):
                if stage == "read":
                    replace()
                return self.source.read(size)

        def opening(candidate, *args, **kwargs):
            source = opened(candidate, *args, **kwargs)
            mode = args[0] if args else kwargs.get("mode", "r")
            if candidate == path and mode == "rb" and target and not swapped:
                return Incoming(source)
            return source

        def target_opening(candidate, *args, **kwargs):
            fd = private_open(candidate, *args, **kwargs)
            if Path(candidate).suffix == ".jsonl":
                info = os.fstat(fd)
                target.append((fd, info.st_dev, info.st_ino))
            return fd

        def writing(fd, data):
            if any(value[0] == fd for value in target):
                info = os.fstat(fd)
                if (fd, info.st_dev, info.st_ino) in target:
                    payloads.append(data)
            return write(fd, data)

        with mock.patch.object(Path, "open", opening), \
                mock.patch.object(files, "private_open", target_opening), \
                mock.patch.object(files.os, "write", writing):
            if kind == "raw":
                result = log.append("prompt", raw_log.prepare("made-up prompt", {}),
                                    diagnostic_deadline=clock.now() + 10, notices=[])
                self.assertEqual(result.outcome, "error")
                self.assertIsNone(result.entry)
            else:
                deadline = clock.now() + (-1 if kind == "late" else 10)
                self.assertFalse(logger.failure("deadline", "record", deadline,
                                                opportunistic=kind == "late"))
        self.assertEqual(swapped, [True])
        self.assertNotEqual(files.read_json(path)["device"], self.header["device"])
        self.assertEqual(payloads, [])
        self.assertEqual(files.read_jsonl(log.path) if log.path.exists() else [], [])
        self.assertEqual(list(log.markers.iterdir()), [])
        self.assertEqual([row for item in (self.root / "logs").glob("failures-*.jsonl")
                          for row in files.read_jsonl(item)], [])

    def test_tc327_atomic_header_replacement_fences_raw_payload_and_marker(self):
        for stage in (["close", "read"] if os.name != "nt" else ["close"]):
            with self.subTest(stage=stage):
                self.exercise("raw", stage)

    def test_tc327_atomic_header_replacement_fences_early_and_late_diagnostics(self):
        for stage in (["close", "read"] if os.name != "nt" else ["close"]):
            for kind in ("early", "late"):
                with self.subTest(stage=stage, kind=kind):
                    self.exercise(kind, stage)
