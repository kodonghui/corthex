"""TC-028 manual benchmark. Emits metadata only, never text or environment.

Run from the checked commit on each OS with --samples 10. Imports, source
construction and one warm-up per case are outside the timed calls. Each input
is exactly 512 KiB of UTF-8. Uses an explicit empty redaction environment.
"""

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"))
from memory_lib import redaction

MARKER = "CORTHEX_REDACTION_BENCH="


def fill(seed):
    data = seed.encode("utf-8")
    value = (data * (redaction.ENTRY_BYTES // len(data) + 1))[:redaction.ENTRY_BYTES].decode("utf-8", "ignore")
    return value + "." * (redaction.ENTRY_BYTES - len(value.encode("utf-8")))


def inputs():
    return {
        "prose": fill("A made-up project plans a small change, reviews it and runs checks. 가나다 🙂\n"),
        "password-repeat": fill("password"),
        "private-openers": fill("<private>"),
        "pem-header-without-key": fill("-" * 5 + "BEGIN " + "A" * 1024 + "\n"),
        "token-digits": fill("token=" + "0" * 512 + " "),
        "url-without-at": fill("://" + "a" * 256 + ":" + "b" * 256 + "? "),
    }


def measure(samples=10):
    rows = []
    for name, text in inputs().items():
        assert len(text.encode("utf-8")) == redaction.ENTRY_BYTES
        redaction.redact(text, {})
        times = []
        for _ in range(samples):
            started = time.perf_counter()
            result = redaction.redact(text, {})
            times.append((time.perf_counter() - started) * 1000)
            assert len(result.text.encode("utf-8")) <= redaction.ENTRY_BYTES
        rows.append({"input": name, "bytes": redaction.ENTRY_BYTES, "samples": samples,
                     "median_ms": round(statistics.median(times), 3), "max_ms": round(max(times), 3)})
    return {"schema": 1, "os": platform.system(), "python": platform.python_version(),
            "warmups": 1, "environment_values": 0, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10, choices=range(1, 101))
    args = parser.parse_args()
    print(MARKER + json.dumps(measure(args.samples), ensure_ascii=True))
