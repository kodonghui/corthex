"""Fixture setup around a byte-identical product hook; only the child is timed."""
import io
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_support
import benchmark_inner


@benchmark_support.serialized_fixture
def main():
    benchmark_support.fixture_stage("read-input")
    raw = sys.stdin.buffer.read()
    payload = json.loads(raw)
    seed = Path(os.environ["HOOKCHECK_BENCHMARK_SEED"])
    home = Path(os.environ["HOME"])
    root = home / ".corthex/corthex-memory"
    seed.relative_to(root)
    assert home.is_absolute() and seed.is_absolute() and seed.parent == root / "projects/demo/raw"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/corthex-memory/scripts"))
    from memory_lib import worker_support
    benchmark_support.fixture_stage("open-wrapper-store")
    memory = worker_support.WorkerStore(root)
    benchmark_support.fixture_stage("read-seed")
    entries = seed.read_bytes().splitlines(keepends=True)
    assert len(entries) == 1000
    previous = [p for p in seed.parent.glob("*.jsonl") if p != seed]
    assert len(previous) <= 1
    benchmark_support.fixture_stage("restore-seed")
    benchmark_support.resize_seed(memory, seed, entries, previous[0] if previous else None)
    benchmark_support.fixture_stage("read-before-diagnostics")
    before = len(benchmark_support.records(root, "logs/hooks-*.jsonl"))
    sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    benchmark_support.fixture_stage("run-timed-child-and-publish-clock")
    code = benchmark_inner.main()
    benchmark_support.fixture_stage("read-after-raw")
    after = len(benchmark_support.records(root, "projects/*/raw/*.jsonl"))
    benchmark_support.fixture_stage("read-after-diagnostics")
    rows = benchmark_support.records(root, "logs/hooks-*.jsonl")[before:]
    assert code == 0 and after == 1001 and len(rows) == 1 and rows[0]["outcome"] == "ok"
    value = {"hook": sys.argv[1], "pid": os.getpid(), "session": payload["session_id"],
             "nonce": os.environ["HOOKCHECK_BENCHMARK_NONCE"], "before": 1000, "after": after,
             "outcome": rows[0]["outcome"], "exit": code}
    folder = Path(os.environ["HOOKCHECK_BENCHMARK_OBSERVATIONS"])
    benchmark_support.fixture_stage("publish-observation")
    temporary = folder / (sys.argv[1] + "-" + str(os.getpid()) + ".tmp")
    temporary.write_text(json.dumps(value) + "\n", encoding="utf-8")
    temporary.replace(temporary.with_suffix(".json"))
    return code


if __name__ == "__main__":
    sys.exit(main())
