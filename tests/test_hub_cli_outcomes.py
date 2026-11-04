"""TASK-250: 59 remaining CLI outcomes, one CI method per original TC.

The child runs the actual hub entry point and HTTP/outbox code. HTTP peers and
all homes/projects are synthetic. These tests do not prove a live handler,
SQLite persistence, Access policy or the full original multi-OS acceptance.
"""
import json
import tempfile
import unittest
from pathlib import Path

import hub_cli_fixture as fixture

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "fixtures" / "hub_cli"
CASES = json.loads((DATA / "cases.json").read_text(encoding="utf8"))
BUNDLE = json.loads((DATA / "wire.json").read_text(encoding="utf8"))

# Preserve the original outcome IDs. The 16 already-audited CLI candidates
# remain in their existing tests, and build TC-1145-1147 is a separate scope.
PRIOR_CANDIDATES = {1139, 1142, 1144, 1156, 1161, 1163, 1165, 1167,
                    1168, 1169, 1173, 1178, 1183, 1188, 1193, 1198}
LAYOUT = (
    (133, "snapshot", 1139, ("done", "command-line-invalid", "failed")),
    (134, "status", 1142, ("done", "command-line-invalid", "failed")),
    (136, "push", 1148, ("done", "command-line-invalid", "refused", "failed")),
    (137, "remove", 1152, ("done", "command-line-invalid", "refused", "failed")),
    (138, "todo", 1156, ("done", "command-line-invalid", "refused", "failed")),
    (139, "comment", 1160, ("done", "command-line-invalid", "refused", "failed", "kept")),
    (140, "reply", 1165, ("done", "command-line-invalid", "refused", "failed", "kept")),
    (141, "answered", 1170, ("done", "command-line-invalid", "refused", "failed", "kept")),
    (142, "decide", 1175, ("done", "command-line-invalid", "refused", "failed", "kept")),
    (143, "propose", 1180, ("done", "command-line-invalid", "refused", "failed", "kept")),
    (144, "withdraw", 1185, ("done", "command-line-invalid", "refused", "failed", "kept")),
    (145, "reflect", 1190, ("done", "command-line-invalid", "refused", "failed", "kept")),
    (146, "record", 1195, ("done", "command-line-invalid", "refused", "failed", "kept")),
    (147, "show", 1200, ("done", "command-line-invalid", "refused", "failed")),
    (148, "claim", 1204, ("done", "command-line-invalid", "refused", "failed")),
    (149, "release", 1208, ("done", "command-line-invalid", "refused", "failed")),
    (150, "outbox", 1212, ("done", "command-line-invalid", "refused", "failed", "kept")),
)
EXPECTED = {"TC-" + str(first + offset): (api, command, outcome)
            for api, command, first, outcomes in LAYOUT
            for offset, outcome in enumerate(outcomes) if first + offset not in PRIOR_CANDIDATES}
if len(CASES) != 59 or {case["id"] for case in CASES} != set(EXPECTED):
    raise ValueError("TASK-250 fixture must preserve exactly its 59 original TC IDs")
for case in CASES:
    api, command, outcome = EXPECTED[case["id"]]
    if (case["command"], case["outcome"], case["title"]) != (command, outcome, "API-%d %s \u00b7 %s" % (api, command, outcome)):
        raise ValueError("an original TC was remapped to another purpose")
if BUNDLE["runtimePin"] != fixture.PIN or BUNDLE["project"] != "qa-cli-fixture":
    raise ValueError("CLI fixtures must use the audited runtime and synthetic project")


class HubCliOutcomeTest(unittest.TestCase):
    observations = {}

    @classmethod
    def setUpClass(cls):
        cls.git, cls.runtime_before = fixture.verify_runtime(ROOT)
        cls.observations = {}

    @classmethod
    def tearDownClass(cls):
        _, after = fixture.verify_runtime(ROOT)
        if cls.runtime_before != after:
            raise AssertionError("CLI tests changed the audited hub runtime")


def outcome_case(case):
    def test(self):
        with tempfile.TemporaryDirectory(prefix="corthex-cli-") as owned:
            result = fixture.run_case(case, Path(owned), ROOT / fixture.PREFIX / "hub.py", self.git, BUNDLE)
        type(self).observations[case["id"]] = result
        self.assertTrue(result["executed"], json.dumps(result, ensure_ascii=True))
        self.assertTrue(result["passed"], json.dumps(result, ensure_ascii=True))
        self.assertFalse(result["sourceVerdictChanged"])
        self.assertFalse(result["fixtureServerIsProductHandler"])
    test.__name__ = "test_" + case["id"].replace("-", "_") + "_" + case["command"] + "_" + case["outcome"].replace("-", "_")
    return test


for case in CASES:
    method = outcome_case(case)
    setattr(HubCliOutcomeTest, method.__name__, method)


if __name__ == "__main__":
    unittest.main()
