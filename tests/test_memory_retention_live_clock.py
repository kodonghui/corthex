"""Normal concurrent appends are not evidence of a future device clock."""
from datetime import datetime, timedelta, timezone
import json
from unittest import mock

from test_memory_store import StoreCase
from memory_lib import base, clock, raw_log, retention, worker_support


class RetentionLiveClockTest(StoreCase):
    def test_live_append_after_cutoff_snapshot_is_not_a_future_clock(self):
        worker = worker_support.WorkerStore()
        project = self.root / "projects" / "sample"
        base.private_directory(project / "raw")
        base.private_directory(project / "unprocessed")
        log = raw_log.log_name("codex", "retention-fixture")
        path = project / "raw" / (log + ".jsonl")
        now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        entries = [{"id": "e_" + str(seq).zfill(12), "seq": seq, "turn": seq,
                    "at": base.utc_time(at), "host": "codex", "session": "retention-fixture",
                    "kind": "prompt", "speaker": "user", "text": "fixture-%d" % seq}
                   for seq, at in enumerate((now - timedelta(days=101), now + timedelta(days=1)), 1)]
        path.write_bytes(b"".join(base.json_bytes(row, "TBL-007", compact=True) for row in entries))
        (project / "curation.json").write_bytes(base.json_bytes({"logs": {log: 20}, "applies": 4,
            "recent": [], "consolidation": {"failures": 0}}, "TBL-009"))
        inventory = retention._inventory
        later = now + timedelta(seconds=2)

        def append_before_inventory(*args):
            result = raw_log.RawLog(worker, "sample", "codex", "retention-fixture").append(
                "prompt", raw_log.prepare("appended after the cutoff snapshot"),
                diagnostic_deadline=clock.now() + 5, when=now + timedelta(seconds=1))
            self.assertEqual(result.outcome, "ok")
            return inventory(*args)

        with mock.patch.object(retention, "_inventory", side_effect=append_before_inventory), \
                mock.patch.object(retention, "_now", side_effect=[now, later, later]):
            deadline = clock.now() + 30
            with worker.lease(project / "curation.lock", "curation", deadline) as owner:
                result = retention.retain_project(worker, "sample", owner, deadline)
        self.assertEqual((result["removed"], result["kept"], result["future"]), (1, 2, 1))
        self.assertEqual([json.loads(row)["seq"] for row in path.read_bytes().splitlines()], [2, 3])
        notices = [json.loads(line) for path in (self.root / "logs").glob("failures-*.jsonl")
                   for line in path.read_bytes().splitlines()]
        self.assertEqual([(row["error"], row["count"]) for row in notices], [("future-entry", 1)])
