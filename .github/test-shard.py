"""Run one share of the repository's unit tests, for CI jobs that split a lane.

`python .github/test-shard.py 1/2` runs the first of two shares. Run it from the
repository root, like `python -m unittest discover -s tests -v`: it discovers the
same tests in the same order and reports them the same way. The shares take the
discovered tests in turn, so each share gets part of every slow test class, and
together they run every test once.
"""

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1] / "tests"


def cases(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from cases(test)
        else:
            yield test


def main(argv):
    try:
        share, count = (int(part) for part in argv[1].split("/"))
    except (IndexError, ValueError):
        share = count = 0
    if len(argv) != 2 or not 1 <= share <= count:
        print("usage: python .github/test-shard.py SHARE/COUNT, such as 1/2", file=sys.stderr)
        return 2
    # `python -m unittest` puts the working folder first on the path, not a script's folder.
    sys.path[0] = str(Path.cwd())
    found = list(cases(unittest.defaultTestLoader.discover(str(TESTS))))
    chosen = found[share - 1::count]
    print("Running %d of %d discovered tests (share %d of %d)" % (len(chosen), len(found), share, count),
          flush=True)
    if not chosen:
        return 1
    # Like `python -m unittest`, show deprecation warnings unless -W chose otherwise.
    runner = unittest.TextTestRunner(verbosity=2, warnings=None if sys.warnoptions else "default")
    return 0 if runner.run(unittest.TestSuite(chosen)).wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
