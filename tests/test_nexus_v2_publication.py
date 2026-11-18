"""Versioned publishing reads only Git blobs and keeps secrets out of receipts."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from test_hub import hub, SCRIPT

publisher = hub.companion("publication_v2")
h = SimpleNamespace(**vars(hub))


class NexusV2PublicationTest(unittest.TestCase):
    def test_preview_uses_the_approved_canonical_envelope(self):
        source = "# Synthetic preview\n"
        body = {"format": "nexus.publish/1", "commit": "a" * 40, "base_commit": None, "consent_id": "owner-consent",
                "artifacts": [{"part": "rebuild", "stage": "02-prd", "source_files": [{
                    "path": "docs/example.md", "media_type": "text/markdown", "content_utf8": source,
                    "sha256": hashlib.sha256(source.encode("utf8")).hexdigest()}]}]}
        self.assertEqual(publisher.preview_digest("project_demo", body),
                         "c8b7b333ea7987d2574e57bb6bd2e793aa46954de26c3b8d350e45333f3c1cb0")
        self.assertEqual(publisher.preview_digest("project_demo", {**body, "consent_id": "other-consent"}),
                         publisher.preview_digest("project_demo", body))

    def test_prepared_source_comes_from_fetched_default_not_worktree(self):
        git = hub.git_program()
        if not git:
            self.skipTest("Git is required")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            home = Path(temporary) / "profile"
            home.mkdir()
            run = lambda *args: subprocess.check_output([git, *args], cwd=root, stderr=subprocess.STDOUT)
            run("init", "-b", "main")
            run("config", "user.email", "fixture@example.com")
            run("config", "user.name", "Fixture")
            run("config", "core.autocrlf", "false")
            run("remote", "add", "origin", "https://github.com/example/sample.git")
            (root / ".corthex").mkdir()
            (root / ".corthex/project.json").write_text(json.dumps({"name": "demo-project", "language": "en"}), encoding="utf8")
            index = {"format": "nexus.sources/1", "artifacts": [{"part": "main", "stage": "02-prd", "files": ["requirements.md"]}]}
            (root / ".corthex/nexus-v2-sources.json").write_text(json.dumps(index), encoding="utf8")
            source = "요구사항\r\n"
            (root / "requirements.md").write_bytes(source.encode("utf8"))
            run("add", ".")
            run("commit", "-m", "Fixture source")
            held = run("rev-parse", "HEAD").decode("ascii").strip()
            run("update-ref", "refs/remotes/origin/main", held)
            run("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
            (root / "requirements.md").write_bytes(b"An uncommitted file")
            record = publisher.envelope(SimpleNamespace(root=root), "project_demo", None, None, None, h)
            item = record["artifacts"][0]["source_files"][0]
            self.assertEqual(record["commit"], held)
            self.assertEqual(item["content_utf8"], source)
            self.assertEqual(item["sha256"], hashlib.sha256(source.encode("utf8")).hexdigest())
            result = subprocess.run([os.sys.executable, str(SCRIPT), "--home", str(home), "preview-v2", "demo-project",
                                     "--project-id", "project_demo", "--json"], cwd=root,
                                    env={**os.environ, "CORTHEX_NEXUS_PUSH": "demo-project"}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["preview_digest"], publisher.preview_digest("project_demo", record))
            self.assertNotIn("An uncommitted file", result.stdout)

    def test_publication_keeps_its_request_key_across_safe_retries(self):
        seen = []
        pauses = []
        commit = "b" * 40
        body = {"commit": commit, "consent_id": None, "base_commit": "a" * 40}
        synthetic_token = "F" * 43

        class Server:
            def __init__(self, url, _env, *, version, timeout, publisher):
                self.args = url, version, timeout
                if publisher != synthetic_token:
                    raise AssertionError("incorrect fixture credential")

            def call(self, method, path, value, write=None):
                seen.append((method, path, value, write))
                if len(seen) < 3:
                    return {"outcome": "failed", "retry": True, "failure": "timeout"}
                return {"outcome": "done", "answer": {"id": "pub_fixture", "sent": True, "held_commit": commit,
                                                       "revision": 2, "snapshot_digest": "f" * 64, "stray": synthetic_token}}

        receipt = publisher.send("https://example.test", "project_demo", body, {publisher.PUBLISHER_ENV: synthetic_token},
                                 h, client_factory=Server, pause=pauses.append)
        self.assertEqual(pauses, [1, 2])
        self.assertTrue(all(value == seen[0] for value in seen))
        self.assertEqual(receipt["held_commit"], commit)
        self.assertNotIn(synthetic_token, json.dumps(receipt))
        safe = hub.companion("commands").scrub(synthetic_token, Path.home(), {publisher.PUBLISHER_ENV: synthetic_token}, h)
        self.assertEqual(safe, "[redacted]")
