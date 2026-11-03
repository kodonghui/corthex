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
    raw = sys.stdin.buffer.read()
    payload = json.loads(raw)
    seed = Path(os.environ["HOOKCHECK_BENCHMARK_SEED"])
    home = Path(os.environ["HOME"])
    root = home / ".corthex/corthex-memory"
    seed.relative_to(root)
    assert home.is_absolute() and seed.is_absolute() and seed.parent == root / "projects/demo/raw"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/corthex-memory/scripts"))
    from memory_lib import worker_support
    memory = worker_support.WorkerStore(root)
    entries = seed.read_bytes().splitlines(keepends=True)
    assert len(entries) == 1000
    previous = [p for p in seed.parent.glob("*.jsonl") if p != seed]
    assert len(previous) <= 1
    benchmark_support.resize_seed(memory, seed, entries, previous[0] if previous else None)
    before = len(benchmark_support.records(root, "logs/hooks-*.jsonl"))
    sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    code = benchmark_inner.main()
    after = len(benchmark_support.records(root, "projects/*/raw/*.jsonl"))
    rows = benchmark_support.records(root, "logs/hooks-*.jsonl")[before:]
    assert code == 0 and after == 1001 and len(rows) == 1 and rows[0]["outcome"] == "ok"
    value = {"hook": sys.argv[1], "pid": os.getpid(), "session": payload["session_id"],
             "nonce": os.environ["HOOKCHECK_BENCHMARK_NONCE"], "before": 1000, "after": after,
             "outcome": rows[0]["outcome"], "exit": code}
    folder = Path(os.environ["HOOKCHECK_BENCHMARK_OBSERVATIONS"])
    temporary = folder / (sys.argv[1] + "-" + str(os.getpid()) + ".tmp")
    temporary.write_text(json.dumps(value) + "\n", encoding="utf-8")
    temporary.replace(temporary.with_suffix(".json"))
    return code


if __name__ == "__main__":
    sys.exit(main())
