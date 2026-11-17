"""GitHub CI setup uses fake gh only: no credentials, accounts or network."""
import base64
import json
import os
import re
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock

from test_hub import HubCase, hub

ci = hub.companion("ci")
REAL_EXECUTABLE = ci.executable
ENV = {"CORTHEX_NEXUS_URL": "https://nexus.example.invalid", "CORTHEX_NEXUS_CLIENT_ID": "synthetic-client-unique",
       "CORTHEX_NEXUS_CLIENT_SECRET": "synthetic-secret-unique", "PATH": "/usr/bin",
       "GH_HOST": "enterprise.example.invalid"}
SHA = "a" * 40


class FakeGh:
    def __init__(self, workflow=True, login=True, bad_secret=None, echo=False):
        self.workflow, self.login, self.bad_secret, self.echo = workflow, login, bad_secret, echo
        self.calls, self.branch, self.branch_content, self.pull = [], False, None, None
        self.other_changes = False

    def __call__(self, argv, **options):
        body = options.get("input")
        self.calls.append((argv, body, options))
        args = argv[1:]
        if args[:2] == ["auth", "status"]:
            return subprocess.CompletedProcess(argv, 0 if self.login else 1, ENV["CORTHEX_NEXUS_CLIENT_SECRET"].encode(), b"")
        if args[:2] == ["secret", "set"]:
            bad = args[2] == self.bad_secret
            return subprocess.CompletedProcess(argv, int(bad), body if self.echo else b"", body if self.echo else b"")
        assert args[:2] == ["api", "--method"]
        method, path = args[2:4]
        data = json.loads(body) if body is not None else None
        missing = False
        if path == "repos/example/marong2":
            value = {"full_name": "example/marong2", "default_branch": "main"}
        elif "/contents/" in path and method == "GET":
            content = b"existing user workflow" if path.endswith("ref=main") and self.workflow else self.branch_content if not path.endswith("ref=main") else None
            missing = content is None
            value = {"type": "file", "content": base64.b64encode(content or b"").decode()}
        elif path.endswith("/git/ref/heads/main"):
            value = {"object": {"sha": SHA}}
        elif "/pulls?" in path:
            value = [{"number": self.pull}] if self.pull else []
        elif "/git/ref/heads/" in path:
            missing = not self.branch
            value = {"object": {"sha": "b" * 40 if self.branch_content else SHA}}
        elif path.endswith("/git/refs") and method == "POST":
            self.branch = True; value = {"object": {"sha": SHA}}
        elif "/contents/" in path and method == "PUT":
            assert self.branch_content is None
            self.branch_content = base64.b64decode(data["content"]); value = {"commit": {"sha": "b" * 40}}
        elif "/compare/" in path:
            value = {"files": [{"filename": ci.WORKFLOW}] + ([{"filename": "user.txt"}] if self.other_changes else [])}
        elif path.endswith("/pulls") and method == "POST":
            self.pull = 7; value = {"number": self.pull}
        else:
            raise AssertionError((method, path))
        return subprocess.CompletedProcess(argv, 1 if missing else 0, json.dumps(value).encode(), b"Not Found (HTTP 404)" if missing else b"")


class CiSetupTest(HubCase):
    def setUp(self):
        super().setUp()
        self.project(); self.register()
        self.project_object = hub.select_projects(self.home, ["acme-shop"])[0][1]
        self.h = SimpleNamespace(**vars(hub))
        self.git = mock.patch.object(self.h, "git", return_value="https://github.com/example/marong2.git")
        self.git.start(); self.addCleanup(self.git.stop)
        self.gh = mock.patch.object(ci, "executable", return_value="/installed/bin/gh")
        self.gh.start(); self.addCleanup(self.gh.stop)

    def setup(self, fake=None, env=None, dry_run=False):
        fake = fake or FakeGh()
        return ci.setup(self.project_object, self.home, self.h, ENV if env is None else env, dry_run, fake), fake

    def test_secrets_use_stdin_only_and_project_id_does_not_become_repository(self):
        result, fake = self.setup(FakeGh(echo=True))
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["repository"], "example/marong2")
        self.assertEqual(result["workflow"], {"state": "present"})
        writes = [c for c in fake.calls if c[0][1:3] == ["secret", "set"]]
        self.assertEqual(len(writes), 3)
        for (argv, body, options), name in zip(writes, ci.SECRET_NAMES):
            self.assertEqual(body, ENV[name].encode())
            self.assertEqual(argv[3:], [name, "--repo", "example/marong2", "--app", "actions"])
            self.assertTrue(all(key not in options["env"] for key in ci.SECRET_NAMES))
            self.assertEqual(options["env"]["GH_HOST"], "github.com")
            self.assertTrue(all(value not in " ".join(argv) for value in ENV.values() if value != "/usr/bin"))
        rendered = json.dumps(result) + ci.line("acme-shop", result)
        for name in ci.SECRET_NAMES:
            self.assertNotIn(ENV[name], rendered)
        self.assertEqual([c for c in fake.calls if c[0][1:3] == ["api", "--method"] and c[0][3] != "GET"], [])

    def test_missing_workflow_opens_one_pr_without_changing_local_files(self):
        (self.repo / "uncommitted.txt").write_text("preserve")
        before = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob("*") if p.is_file()}
        result, fake = self.setup(FakeGh(workflow=False))
        self.assertEqual(result["workflow"], {"state": "pr-open", "url": "https://github.com/example/marong2/pull/7"})
        self.assertEqual(fake.branch_content, ci.workflow_text().encode())
        self.assertEqual(before, {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob("*") if p.is_file()})
        again, _ = self.setup(fake)
        self.assertEqual(again["workflow"], result["workflow"])
        self.assertEqual(sum(c[0][3] == "POST" and c[0][4].endswith("/pulls") for c in fake.calls if c[0][1:3] == ["api", "--method"]), 1)

    def test_interrupted_workflow_branch_is_reused_only_without_other_changes(self):
        for other in (False, True):
            fake = FakeGh(workflow=False); fake.branch = True
            fake.branch_content = ci.workflow_text().encode(); fake.other_changes = other
            result, _ = self.setup(fake)
            self.assertEqual(result["state"], "failed" if other else "done")
            if other:
                self.assertIsNone(fake.pull)

    def test_an_existing_manual_workflow_pr_is_reused_before_creating_a_branch(self):
        class ManualPull(FakeGh):
            def __call__(self, argv, **options):
                if argv[1:4] == ["api", "--method", "GET"] and "per_page=100" in argv[4]:
                    self.calls.append((argv, options.get("input"), options))
                    return subprocess.CompletedProcess(argv, 0, json.dumps([{"number":215,"head":{"sha":"c"*40}}]).encode(), b"")
                return super().__call__(argv, **options)
        fake = ManualPull(workflow=False)
        fake.branch_content = ci.workflow_text().encode()
        result, _ = self.setup(fake)
        self.assertEqual(result["workflow"]["url"], "https://github.com/example/marong2/pull/215")
        self.assertFalse(fake.branch)
        self.assertIsNone(fake.pull)

    def test_existing_different_branch_workflow_is_never_overwritten(self):
        fake = FakeGh(workflow=False); fake.branch = True; fake.branch_content = b"user's own change"
        result, _ = self.setup(fake)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(fake.branch_content, b"user's own change")
        self.assertIsNone(fake.pull)

    def test_auth_failure_and_missing_gh_skip_with_one_line_and_no_writes(self):
        result, fake = self.setup(FakeGh(login=False))
        self.assertEqual(result["state"], "skipped")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(len(ci.line("acme-shop", result).splitlines()), 1)
        with mock.patch.object(ci, "executable", return_value=None):
            result, fake = self.setup()
        self.assertEqual(result["state"], "skipped"); self.assertFalse(fake.calls)

    def test_missing_settings_and_loopback_never_contact_gh(self):
        for values in ({}, dict(ENV, CORTHEX_NEXUS_URL="http://127.0.0.1:8080"), dict(ENV, CORTHEX_NEXUS_URL="https://localhost")):
            result, fake = self.setup(env=values)
            self.assertEqual(result["state"], "skipped"); self.assertFalse(fake.calls)

    def test_failed_secret_and_timeout_never_render_echoed_values(self):
        result, fake = self.setup(FakeGh(bad_secret=ci.SECRET_NAMES[1], echo=True))
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["secrets"], [ci.SECRET_NAMES[0]])
        self.assertNotIn(ENV[ci.SECRET_NAMES[1]], json.dumps(result))
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 45, output=ENV[ci.SECRET_NAMES[2]])
        result = ci.setup(self.project_object, self.home, self.h, ENV, run=timeout)
        self.assertEqual(result["state"], "failed")
        self.assertNotIn(ENV[ci.SECRET_NAMES[2]], json.dumps(result))

    def test_dry_run_never_sets_a_secret_creates_a_branch_or_opens_a_pr(self):
        result, fake = self.setup(FakeGh(workflow=False), dry_run=True)
        self.assertEqual(result["state"], "preview")
        self.assertEqual(result["workflow"]["state"], "would-open-pr")
        self.assertFalse(fake.branch)
        self.assertTrue(all(c[0][1] in ("auth", "api") for c in fake.calls))
        self.assertTrue(all(c[0][3] == "GET" for c in fake.calls if c[0][1] == "api"))

    def test_first_upload_hook_never_runs_for_jobs_dry_runs_failures_or_ordinary_pushes(self):
        for command, first, dry, outcome in [("push",False,False,"done"),("push",True,True,"done"),("push",True,False,"failed"),("todo",False,False,"done")]:
            args = SimpleNamespace(command=command, first=first, dry_run=dry)
            with mock.patch.object(ci, "setup") as setup:
                ci.after_first(args, self.home, [{"project":"acme-shop","outcome":outcome}], self.h)
                setup.assert_not_called()
        args = SimpleNamespace(command="push", first=True, dry_run=False)
        with mock.patch.dict(os.environ, ENV, clear=True), mock.patch.object(ci, "setup", return_value={"state":"skipped","why":"fixture","secrets":[]}) as setup, mock.patch.object(self.h,"say"):
            ci.after_first(args, self.home, [{"project":"acme-shop","outcome":"done"}], self.h)
            setup.assert_called_once()

    def test_first_upload_to_another_server_never_configures_ci_for_the_environment_server(self):
        for address in ("https://other.example.invalid", "http://127.0.0.1:8080"):
            args = SimpleNamespace(command="push", first=True, dry_run=False, url=address)
            with mock.patch.dict(os.environ, ENV, clear=True), mock.patch.object(ci, "setup") as setup, mock.patch.object(self.h, "say") as say:
                ci.after_first(args, self.home, [{"project":"acme-shop","outcome":"done"}], self.h)
                setup.assert_not_called()
                say.assert_called_once()
                message, stream = say.call_args[0]
                self.assertIs(stream, ci.sys.stderr)
                self.assertIn("upload destination differs from CORTHEX_NEXUS_URL", message)
                self.assertEqual(len(message.splitlines()), 1)
                for value in [address] + [ENV[name] for name in ci.SECRET_NAMES]:
                    self.assertNotIn(value, message)
        args = SimpleNamespace(command="push", first=True, dry_run=False, url=ENV["CORTHEX_NEXUS_URL"] + "/")
        with mock.patch.dict(os.environ, ENV, clear=True), mock.patch.object(ci, "setup", return_value={"state":"skipped","why":"fixture","secrets":[]}) as setup, mock.patch.object(self.h, "say"):
            ci.after_first(args, self.home, [{"project":"acme-shop","outcome":"done"}], self.h)
            setup.assert_called_once()

    def test_only_github_origins_are_accepted(self):
        ssh_host = "@".join(("git", "github.com"))
        for remote in [ssh_host + ":example/marong2.git","https://github.com/example/marong2.git","ssh://" + ssh_host + "/example/marong2.git"]:
            self.assertEqual(ci.repository(remote),"example/marong2")
        for remote in ["https://example.invalid/example/marong2","https://" + "@".join(("token", "github.com")) + "/example/marong2","https://github.com/example/marong2?token=synthetic","file:///tmp/repo"]:
            self.assertIsNone(ci.repository(remote))

    def test_workflow_keeps_immutable_pins_read_only_permissions_and_default_branch_trigger(self):
        text = ci.workflow_text()
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("persist-credentials: false", text)
        self.assertEqual(len(re.findall(r"uses: actions/checkout@[0-9a-f]{40}", text)), 2)
        self.assertIn("ref: c6095b40c71bc74d207b13b5b08aeeb078c7d0c5", text)
        self.assertIn("push --job --json", text)
        self.assertNotRegex(text, r"pull_request|workflow_dispatch|schedule")
        branch = ci.workflow_text("release/quarter-2")
        self.assertIn('branches: ["release/quarter-2"]', branch)
        self.assertNotIn("branches: [main]", branch)

    def test_setup_command_requires_an_allowed_project_and_preserves_global_json(self):
        args = hub.parser().parse_args(["--json","setup-ci","acme-shop","--dry-run"])
        self.assertTrue(args.json)
        with self.assertRaisesRegex(ValueError,"not allowed"):
            ci.selected(args,self.home,self.h)

    def test_cwd_is_not_a_source_of_gh_executables(self):
        program = self.repo / ("gh.exe" if os.name == "nt" else "gh")
        program.write_text("fixture"); program.chmod(0o755)
        # Use the real resolver, not this case's injected fake gh path.
        self.assertIsNone(REAL_EXECUTABLE({"PATH": str(self.repo)}, self.repo))
