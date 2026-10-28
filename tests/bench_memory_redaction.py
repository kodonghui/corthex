"""TC-028 manual benchmark. Emits metadata only, never text or environment.

Run from the checked commit on each OS with --samples 10. Imports, source
construction and one warm-up per case are outside the timed calls. Each input
is exactly 512 KiB of UTF-8. Uses an explicit empty redaction environment.
"""

import argparse
import base64
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
SLOW = ("pem-begin-name-repeat", "pem-end-name-repeat", "jwt-no-dots", "jwt-base64-json")
WORD_INPUTS = ("token", "passwd", "secret", "apikey")
# Each expression, including the private-span pass, has a hostile input.
GROWTH = ("private-openers", "pem-begin-name-repeat", "jwt-no-dots",
    "anthropic-near-minimum", "openai-near-minimum", "github-near-minimum",
    "gitlab-near-minimum", "slack-near-minimum", "aws-short-body", "google-short-body",
    "url-without-at", "authorization-repeat", "passwd-repeat", "token-repeat", "jwt-percent-repeat")


def slow_input(name, size):
    if name == "jwt-base64-json":
        return base64.b64encode(b'{"a":123}' * (size // 8 + 2)).decode("ascii")[:size]
    marker = "-" * 5
    prefix, seed = {
        "private-openers": ("", "<private>"),
        "pem-begin-name-repeat": (marker + "BEGIN ", "PRIVATE KEY "),
        "pem-end-name-repeat": (marker + "BEGIN PRIVATE KEY" + marker + "\nbody\n" + marker + "END ", "PRIVATE KEY "),
        "jwt-no-dots": ("", "eyJ"),
        "jwt-percent-repeat": ("", "%41eyJ"),
        "anthropic-near-minimum": ("", "sk-ant-" + "a" * 19 + " "),
        "openai-near-minimum": ("", "sk-proj-" + "a" * 19 + " "),
        "github-near-minimum": ("", "github_pat_" + "a" * 21 + " "),
        "gitlab-near-minimum": ("", "glpat-" + "a" * 19 + " "),
        "slack-near-minimum": ("", "xoxb-" + "a" * 9 + " "),
        "aws-short-body": ("", "AKIA" + "A" * 15 + " "),
        "google-short-body": ("", "AIza" + "a" * 34 + " "),
        "url-without-at": ("", "://" + "a" * 256 + ":" + "b" * 256 + "? "),
        "authorization-repeat": ("", "authorization"),
        "passwd-repeat": ("", "passwd"),
        "token-repeat": ("", "token"),
    }[name]
    return prefix + (seed * (size // len(seed) + 1))[:size - len(prefix)]


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
        **{name: slow_input(name, redaction.ENTRY_BYTES) for name in SLOW},
        **{name + "-repeat": fill(name) for name in WORD_INPUTS},
        "jwt-percent-repeat": slow_input("jwt-percent-repeat", redaction.ENTRY_BYTES),
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


def measure_growth(samples=3):
    """Measure every pattern without a guard hiding regex growth.

    Runs only in the test's bounded subprocess. Limits are raised in that
    disposable process; production limits and the 512 KiB benchmark stay fixed.
    """
    rows = []
    started = time.perf_counter()
    saved = redaction.ENTRY_BYTES, redaction.WINDOW_BYTES
    try:
        def timed(text):
            started = time.perf_counter()
            redaction.redact(text, {})
            return (time.perf_counter() - started) * 1000
        for name in GROWTH:
            size = 128 * 1024
            redaction.ENTRY_BYTES = redaction.WINDOW_BYTES = size + 1
            pilot_text = slow_input(name, size)
            pilot = min(timed(pilot_text) for _ in range(samples))
            # Calibrate once near 26 ms, avoiding successive doubling and a
            # warm-up at every size. The pilot already warms this expression.
            size = max(1024, min(4 * 1024 * 1024, int(size * 26 / max(pilot, 0.001))))
            while True:
                redaction.ENTRY_BYTES = redaction.WINDOW_BYTES = size * 4 + 1
                small_text, large_text = slow_input(name, size), slow_input(name, size * 4)
                # Interleave sizes and compare their minima: added scheduling
                # time cannot lower the best sample. Never retry a bad ratio.
                if timed(small_text) > 21:
                    pairs = [(timed(small_text), timed(large_text)) for _ in range(samples)]
                    small = min(pair[0] for pair in pairs)
                    large = min(pair[1] for pair in pairs)
                    if small > 21:
                        break
                size = int(size * 1.25)
                if size > 4 * 1024 * 1024:
                    raise RuntimeError("growth timing floor unavailable")
            rows.append({"input": name, "small_bytes": size, "large_bytes": size * 4,
                         "small_ms": round(small, 3), "large_ms": round(large, 3),
                         "ratio": round(large / small, 4), "samples": samples})
    finally:
        redaction.ENTRY_BYTES, redaction.WINDOW_BYTES = saved
    return {"schema": 1, "mode": "growth", "rows": rows, "environment_values": 0,
            "clock": "perf_counter", "pairing": "alternating sizes", "statistic": "minimum",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10, choices=range(1, 101))
    parser.add_argument("--growth", action="store_true")
    args = parser.parse_args()
    print(MARKER + json.dumps(measure_growth(args.samples) if args.growth else measure(args.samples), ensure_ascii=True))
