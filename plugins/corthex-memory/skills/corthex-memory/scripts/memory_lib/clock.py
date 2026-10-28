"""One high-resolution elapsed clock for deadlines and hook timings.

UTC timestamps and lease ages keep their wall clock. The entry script takes
its initial perf_counter sample before importing product modules.
"""

import time


def now():
    return time.perf_counter()
