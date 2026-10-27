"""Manual lease-review mutations in temporary copies; emits metadata only."""

import ast
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = Path("plugins/corthex-memory/skills/corthex-memory/scripts/memory_lib")
PREFIX = "test_memory_lock_review.MemoryLockReviewTest."
CASES = (
    "test_tc008_held_forwards_cleanup_failure_without_hiding_the_body_error",
    "test_tc007_displaced_release_is_quiet_and_preserves_the_new_owner",
    "test_tc008_windows_same_path_with_another_case_is_an_order_error",
    "test_tc318_public_reader_recovers_a_damaged_primary",
)
MUTATIONS = (
    ("held-reporter", "locks", "self.release(report=report)", "self.release()"),
    ("quiet-takeover", "locks",
     "if not current or current.token != self.token:\n                        return",
     "if not current or current.token != self.token:\n                        raise LostLock()"),
    ("windows-case-alias", "locks", "order > self._order or path == self.path",
     "order > self._order"),
    ("damaged-primary", "reading", "except files.RestoreNeeded:\n        pass",
     "except files.RestoreNeeded:\n        if files.Path(path).exists():\n            raise"),
)


def probe(index=None):
    with tempfile.TemporaryDirectory(prefix="memory-lock-mutation-") as folder:
        root = Path(folder)
        shutil.copytree(ROOT / LIB, root / LIB, ignore=shutil.ignore_patterns("__pycache__"))
        tests = root / "tests"
        tests.mkdir()
        for name in ("_common.py", "test_memory_locks.py", "test_memory_lock_review.py"):
            shutil.copy2(ROOT / "tests" / name, tests / name)
        if index is not None:
            _, module, old, new = MUTATIONS[index]
            path = root / LIB / (module + ".py")
            source = path.read_text(encoding="utf-8")
            if source.count(old) != 1:
                return {"status": "invalid-mutation"}
            source = source.replace(old, new)
            ast.parse(source)
            path.write_text(source, encoding="utf-8")
        environment = {key: value for key, value in os.environ.items()
                       if not any(part in key.upper() for part in ("TOKEN", "SECRET", "PASSWORD", "API_KEY"))
                       and not key.startswith(("CLAUDE", "CODEX", "ANTHROPIC", "CLOUDFLARE", "CF_"))}
        for key in ("HOME", "USERPROFILE", "CORTHEX_HOME", "CORTHEX_MEMORY_HOME",
                    "CLAUDE_CONFIG_DIR", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
            environment[key] = str(root / key.lower())
            Path(environment[key]).mkdir()
        scratch = root / "scratch"
        scratch.mkdir()
        for key in ("TMPDIR", "TMP", "TEMP"):
            environment[key] = str(scratch)
        targets = CASES if index is None else (CASES[index],)
        executable = Path(sys.executable)
        if not executable.is_absolute() or not executable.is_file():
            return {"status": "missing-interpreter"}
        result = subprocess.run([str(executable), "-m", "unittest", "-v"] +
                                [PREFIX + case for case in targets], cwd=str(tests),
                                env=environment, capture_output=True, text=True, timeout=90)
        output = result.stdout + result.stderr
        def count(pattern):
            match = re.search(pattern, output)
            return int(match.group(1)) if match else 0
        found = count(r"Ran (\d+) tests?")
        failures, errors, skips = (count(r"failures=(\d+)"), count(r"errors=(\d+)"),
                                   count(r"skipped=(\d+)"))
        invalid = any(kind + ":" in output for kind in
                      ("SyntaxError", "IndentationError", "ImportError", "ModuleNotFoundError"))
        if index is None:
            valid = result.returncode == 0 and found == len(CASES) and skips == (0 if os.name == "nt" else 1)
            status = "passed" if valid else "baseline-failed"
        else:
            valid = result.returncode != 0 and found == 1 and failures + errors > 0 and not invalid
            status = "detected" if valid else "missed"
        return {"status": status, "tests": found, "failures": failures, "errors": errors,
                "skips": skips, "exit": result.returncode}


def main():
    baseline = probe()
    rows = []
    for index, (name, _, _, _) in enumerate(MUTATIONS):
        result = {"status": "not-applicable"} if index == 2 and os.name != "nt" else probe(index)
        rows.append(dict(result, variant=name))
    ok = baseline["status"] == "passed" and all(row["status"] in ("detected", "not-applicable") for row in rows)
    data = {"schema": 1, "os": platform.system(), "python": platform.python_version(),
            "baseline": baseline, "mutations": rows, "ok": ok}
    print("CORTHEX_LOCK_MUTATIONS=" + json.dumps(data, ensure_ascii=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
