"""TC-015–021: temporary registries, real directory identities and exclusions."""

import json
import os
import time
from pathlib import Path
from unittest import mock

from test_memory_store import AT, StoreCase
from memory_lib import configuration, diagnostics, files, projects, store


class MemoryProjectsTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.home = Path(os.environ["HOME"])
        self.registry = self.home / ".corthex/projects.json"
        self.registry.parent.mkdir(parents=True)
        self.repo = self.folder / "checkout"
        self.repo.mkdir()
        self.register({"name": "sample", "path": str(self.repo)})
        self.config = self.enabled("sample", "inner", "other")

    def enabled(self, *names):
        return configuration.prepare({"consent": {"at": AT, "version": 1},
                                      "projects": {name: {"enabled": True, "since": AT} for name in names}})

    def register(self, *entries):
        self.registry.write_text(json.dumps({"projects": entries}), encoding="utf-8")

    def test_tc015_deepest_real_ancestor_and_repo_alias_win(self):
        inner = self.repo / "inner"
        child = inner / "child"
        child.mkdir(parents=True)
        self.register({"name": "sample", "path": str(self.repo)}, {"name": "inner", "path": str(inner)})
        self.assertEqual(projects.find(self.config, child).name, "inner")
        self.assertEqual(projects.find(self.config, self.repo).name, "sample")
        external = self.folder / "external"
        external.mkdir()
        self.register({"name": "sample", "path": str(self.repo), "repos": {"design": str(external)}})
        found = projects.find(self.config, external)
        self.assertEqual((found.name, found.alias), ("sample", "design"))
        self.assertTrue(os.path.samefile(found.folder, self.repo))
        self.assertTrue(os.path.samefile(found.matched, external))
        self.register({"name": "sample", "path": str(self.folder / "missing"), "repos": {"design": str(external)}})
        self.assertEqual(projects.find(self.config, external).name, "sample")

    def test_tc015_disabled_deeper_project_never_falls_back_to_enabled_parent(self):
        inner = self.repo / "inner"
        inner.mkdir()
        self.register({"name": "sample", "path": str(self.repo)}, {"name": "inner", "path": str(inner)})
        self.assertIsNone(projects.find(self.enabled("sample"), inner))
        self.assertEqual(projects.locate(inner).name, "inner")
        without_consent = configuration.prepare({"projects": self.config.document["projects"]})
        with mock.patch.object(Path, "read_bytes") as read:
            self.assertIsNone(projects.find(without_consent, self.repo))
            read.assert_not_called()
        newer_consent = dict(self.config.document, consent={"at": AT, "version": 2})
        self.assertIsNone(projects.find(configuration.prepare(newer_consent), self.repo))

    def test_tc016_repository_settings_are_never_opened(self):
        settings = self.repo / ".corthex/project.json"
        settings.parent.mkdir()
        settings.write_text('{"name":"other"}', encoding="utf-8")
        read = Path.read_bytes
        accessed = []
        def registry_only(path):
            self.assertEqual(path, self.registry)
            accessed.append(path)
            return read(path)
        with mock.patch.object(Path, "read_bytes", registry_only):
            self.assertEqual(projects.find(self.config, self.repo).name, "sample")
        self.assertEqual(accessed, [self.registry])

    def test_tc017_unlisted_and_similarly_spelled_sibling_change_no_memory_file(self):
        unlisted = self.folder / "checkout-other"
        unlisted.mkdir()
        before = self.snapshot()
        self.assertIsNone(projects.find(self.config, unlisted))
        self.assertEqual(self.snapshot(), before)
        # Discovery must also leave a store that has not been created absent.
        (self.root / "logs").rmdir()
        (self.root / "store.json").unlink()
        self.root.rmdir()
        self.assertIsNone(projects.find(self.config, unlisted))
        self.assertFalse(self.root.exists())

    def test_tc018_case_ignoring_volume_uses_directory_identity(self):
        upper, lower = self.folder / "Project", self.folder / "project"
        upper.mkdir()
        if not lower.exists():
            self.skipTest("this volume keeps directory case apart")
        self.assertTrue(os.path.samefile(upper, lower))
        child = lower / "child"
        child.mkdir()
        self.register({"name": "sample", "path": str(upper)})
        found = projects.find(self.config, child)
        self.assertEqual(found.name, "sample")
        document = self.config.document
        document["projects"]["sample"]["left_out"] = {"folders": ["CHILD"]}
        self.assertTrue(found.left_out(configuration.prepare(document), "prompt"))

    def test_tc018_case_preserving_volume_keeps_distinct_directories_apart(self):
        upper, lower = self.folder / "Project", self.folder / "project"
        upper.mkdir()
        if lower.exists():
            self.skipTest("this volume ignores directory case")
        lower.mkdir()
        self.assertFalse(os.path.samefile(upper, lower))
        self.register({"name": "sample", "path": str(upper)})
        self.assertIsNone(projects.find(self.config, lower))
        self.assertEqual(projects.find(self.config, upper).name, "sample")

    def test_tc019_missing_unreadable_or_bad_registry_has_only_a_safe_code(self):
        logger = diagnostics.Diagnostics(self.memory)
        self.registry.unlink()
        for content in (None, b"{", b"[]", b'{"projects":{}}', b'{"projects":[],"projects":[]}'):
            if content is not None:
                self.registry.write_bytes(content)
            with self.assertRaises(projects.ProjectError) as caught:
                projects.find(self.config, self.repo)
            self.assertEqual((caught.exception.code, caught.exception.clash), ("no-project-list", ()))
            self.assertEqual(str(caught.exception), "no-project-list")
            self.assertTrue(logger.failure(caught.exception, "record", time.monotonic() + 2))
            records = [line for path in sorted((self.root / "logs").glob("failures-*.jsonl"))
                       for line in files.read_jsonl(path)]
            self.assertEqual(records[-1]["error"], "no-project-list")
        read = Path.read_bytes
        def denied(path):
            if path == self.registry:
                raise PermissionError("made-up private path")
            return read(path)
        with mock.patch.object(Path, "read_bytes", denied):
            with self.assertRaises(projects.ProjectError) as caught:
                projects.find(self.config, self.repo)
        self.assertEqual(caught.exception.code, "no-project-list")

    def test_tc019_registry_bom_compatibility_keeps_memory_records_strict(self):
        original = self.registry.read_bytes()
        for prefix in (b"", b"\xef\xbb\xbf"):
            self.registry.write_bytes(prefix + original)
            self.assertEqual(projects.find(self.config,self.repo).name,"sample")
        self.registry.write_bytes(b"\xef\xbb\xbf"*2 + original)
        with self.assertRaises(projects.ProjectError):
            projects.locate(self.repo)
        record = self.root / "store.json"
        record.write_bytes(b"\xef\xbb\xbf" + record.read_bytes())
        with self.assertRaises(store.StoreUnavailable) as caught:
            self.memory.record(deadline=time.monotonic()+2)
        self.assertEqual(caught.exception.code,"store-damaged")

    def test_tc019_tied_folder_is_a_clash_even_if_one_project_is_disabled(self):
        self.register({"name": "sample", "path": str(self.repo)},
                      {"name": "other", "repos": {"same": str(self.repo)}})
        with self.assertRaises(projects.ProjectError) as caught:
            projects.find(self.enabled("sample"), self.repo)
        self.assertEqual(caught.exception.code, "project-clash")
        self.assertEqual(caught.exception.clash, ("other", "sample"))
        logger = diagnostics.Diagnostics(self.memory)
        self.assertTrue(logger.failure(caught.exception, "record", time.monotonic() + 2))
        records = [line for path in sorted((self.root / "logs").glob("failures-*.jsonl"))
                   for line in files.read_jsonl(path)]
        self.assertEqual(records[-1]["error"], "project-clash")
        # Aliases of the same project are one owner, even with the same folder.
        self.register({"name": "sample", "path": str(self.repo), "repos": {"self": str(self.repo)}})
        found = projects.find(self.config, self.repo)
        self.assertEqual((found.name, found.alias), ("sample", None))

    def test_tc019_registry_filters_unusable_entries_and_missing_roots(self):
        self.register(None, {"name": 12, "path": str(self.repo)},
                      {"name": [], "path": str(self.repo)},
                      {"name": "other", "path": str(self.folder / "missing")},
                      {"name": "sample", "path": str(self.repo), "repos": {"missing": []}})
        self.assertEqual(projects.find(self.config, self.repo).name, "sample")

    def test_tc015_invalid_deeper_name_never_falls_back_to_enabled_parent(self):
        inner = self.repo / "inner"
        inner.mkdir()
        before = self.snapshot()
        for name in ("Inner", "inner_notes", "", "x" * 61):
            self.register({"name": "sample", "path": str(self.repo)},
                          {"name": name, "path": str(inner)})
            self.assertIsNone(projects.locate(inner))
            self.assertIsNone(projects.find(self.enabled("sample"), inner))
            self.assertEqual(projects.find(self.enabled("sample"), self.repo).name, "sample")
            self.assertEqual(self.snapshot(), before)

    def test_tc020_deleted_folder_has_no_project_and_missing_cwd_uses_process_cwd(self):
        deleted = self.repo / "deleted"
        deleted.mkdir()
        deleted.rmdir()
        self.assertIsNone(projects.find(self.config, deleted))
        self.assertIsNone(projects.find(self.config, ""))
        self.assertIsNone(projects.find(self.config, self.registry))
        previous = Path.cwd()
        try:
            os.chdir(str(self.repo))
            self.assertEqual(projects.find(self.config).name, "sample")
        finally:
            os.chdir(str(previous))
        with mock.patch.object(projects.Path, "cwd", side_effect=FileNotFoundError()):
            self.assertIsNone(projects.find(self.config))

    def test_tc020_linked_folder_matches_its_real_project_and_clashes_by_identity(self):
        link = self.folder / "linked"
        try:
            link.symlink_to(self.repo, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable on this volume")
        self.assertEqual(projects.find(self.config, link).name, "sample")
        self.register({"name": "sample", "path": str(self.repo)}, {"name": "other", "path": str(link)})
        with self.assertRaises(projects.ProjectError) as caught:
            projects.find(self.config, link)
        self.assertEqual(caught.exception.code, "project-clash")
        private = self.repo / "private"
        private.mkdir()
        private_link = self.folder / "private-link"
        private_link.symlink_to(private, target_is_directory=True)
        self.register({"name": "sample", "path": str(self.repo)})
        document = self.config.document
        document["projects"]["sample"]["left_out"] = {"folders": ["private"]}
        config = configuration.prepare(document)
        self.assertTrue(projects.find(config, private_link).left_out(config, "answer"))

    def test_tc021_excluded_folder_includes_descendants_but_not_a_sibling(self):
        private = self.repo / "secret-data"
        nested = private / "x/y"
        nested.mkdir(parents=True)
        sibling = self.repo / "secret-data-other"
        sibling.mkdir()
        document = self.config.document
        document["projects"]["sample"]["left_out"] = {"folders": ["secret-data"]}
        config = configuration.prepare(document)
        for folder, excluded in ((private, True), (nested, True), (sibling, False), (self.repo, False)):
            found = projects.find(config, folder)
            for kind in projects.KINDS:
                self.assertEqual(found.left_out(config, kind), excluded)

    def test_tc021_each_kind_is_independent_and_future_exclusion_creates_nothing(self):
        for kind in projects.KINDS:
            document = self.config.document.copy()
            document["projects"] = {"sample": {"enabled": True, "since": AT, "left_out": {"kinds": [kind]}}}
            config = configuration.prepare(document)
            found = projects.find(config, self.repo)
            for candidate in projects.KINDS:
                self.assertEqual(found.left_out(config, candidate), candidate == kind)
        document["projects"]["sample"]["left_out"] = {"folders": ["future"]}
        config = configuration.prepare(document)
        found = projects.find(config, self.repo)
        self.assertFalse(found.left_out(config, "prompt"))
        self.assertFalse((self.repo / "future").exists())
        (self.repo / "future").mkdir()
        self.assertTrue(projects.find(config, self.repo / "future").left_out(config, "answer"))
        with self.assertRaises(ValueError):
            found.left_out(config, "tool")
