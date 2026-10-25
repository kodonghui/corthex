"""Checks the corthex-uxui skill's two scripts: media-check.py on made-up clips, page-check.js as text."""

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import PLUGINS, read_text

SKILL = PLUGINS / "corthex" / "skills" / "corthex-uxui"
MEDIA = SKILL / "scripts" / "media-check.py"
PAGE = SKILL / "scripts" / "page-check.js"
CHECKLIST = SKILL / "references" / "checklist.md"
FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")
WHITE, BLACK, RED, GREY = (255, 255, 255), (0, 0, 0), (255, 0, 0), (127, 127, 127)
# What page-check.js must never call: anything that sends data or changes the page it measures.
PAGE_WRITES = re.compile(
    r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|localStorage|sessionStorage|indexedDB|cookie)\b"
    r"|\.(?:append|appendChild|prepend|insertBefore|insertAdjacent\w*|removeChild|replaceChild|replaceWith|remove"
    r"|setAttribute|removeAttribute|toggleAttribute|focus|click|scrollTo|scrollBy|scrollIntoView|dispatchEvent"
    r"|open|write)\s*\("
    r"|\.(?:innerHTML|outerHTML|textContent|innerText|value|className|scrollTop|scrollLeft)\s*=(?!=)"
    r"|\.style\.\w+\s*=(?!=)|classList\.(?:add|remove|toggle|replace)\s*\("
)


def load_media_check():
    spec = importlib.util.spec_from_file_location("corthex_media_check", MEDIA)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def emitted(text):
    """The check names a script reports: the quoted names in the second argument of each add() call (not a method such as set.add)."""
    names = set()
    for argument in re.findall(r"(?<![\w.])add\(\s*[^,]+,\s*([^,]+),", text):
        names.update(re.findall(r'"([a-z][a-z-]*)"', argument))
    return names


def documented(heading):
    """The check names that checklist.md lists under one script's heading."""
    text = read_text(CHECKLIST)
    start = text.index(heading)
    end = text.find("\n### ", start + len(heading))
    part = text[start:] if end == -1 else text[start:end]
    line = next(line for line in part.splitlines() if line.startswith("- **Check names**"))
    return set(re.findall(r"`([a-z][a-z-]*)`", line))


def media_check(*args):
    return subprocess.run([sys.executable, str(MEDIA)] + [str(arg) for arg in args], capture_output=True, timeout=300)


def blinking(path, seconds, period, lit, dark=BLACK, box=None):
    """A 160x90 clip at 30 fps showing `lit` for the first half of every `period` frames, else `dark`.

    With `box`, only a square of that many pixels in the top left corner changes.
    """
    on = "lt(mod(N,%d),%d)" % (period, (period + 1) // 2)
    if box:
        on += "*lt(X,%d)*lt(Y,%d)" % (box, box)
    planes = ":".join("%s='if(%s,%d,%d)'" % (plane, on, a, b) for plane, a, b in zip("rgb", lit, dark))
    graph = "color=c=black:s=160x90:r=30:d=%s,format=gbrp,geq=%s" % (seconds, planes)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", graph, "-c:v", "ffv1", str(path)],
                   check=True, capture_output=True, timeout=120)


def patches(path, together):
    """Two side-by-side patches of 4x8 cells, each flashing five times a second for one second: together, or one after the other.

    The clip is 480x270 at 30 fps, so a cell of the default 48-cell grid is 10x10 pixels and a patch is a sixth of the field.
    """
    flash = "lt(mod(N,6),3)"
    first = "lt(N,30)*" + flash
    second = first if together else "gte(N,30)*lt(N,60)*" + flash
    on = "(lt(X,40)*%s+gte(X,40)*%s)*lt(X,80)*lt(Y,80)" % (first, second)
    graph = "color=c=black:s=480x270:r=30:d=2.5,format=gbrp,geq=" + ":".join("%s='255*%s'" % (plane, on) for plane in "rgb")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", graph, "-c:v", "ffv1", str(path)],
                   check=True, capture_output=True, timeout=120)


class ScriptTextTest(unittest.TestCase):
    def test_media_check_parses_as_python_3_8(self):
        ast.parse(read_text(MEDIA), feature_version=(3, 8))

    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "needs Python 3.10 or later")
    def test_media_check_imports_only_the_standard_library(self):
        imported = set()
        for node in ast.walk(ast.parse(read_text(MEDIA))):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module.split(".")[0])
        self.assertLessEqual(imported, set(sys.stdlib_module_names))

    def test_check_names_are_documented(self):
        self.assertEqual(emitted(read_text(PAGE)), documented("### page-check.js"))
        self.assertEqual(emitted(read_text(MEDIA)), documented("### media-check.py"))

    def test_loudness_targets_are_documented(self):
        text = read_text(CHECKLIST)
        table = text[text.index("## 4. Loudness"):text.index("## 5.")]
        rows = [line.split("|")[2] for line in table.splitlines() if line.startswith("|")][2:]
        self.assertEqual(sorted(re.search(r"`([a-z-]+)`", row).group(1) for row in rows), sorted(load_media_check().TARGETS))

    def test_page_check_sends_nothing_and_changes_nothing(self):
        match = PAGE_WRITES.search(read_text(PAGE))
        self.assertIsNone(match, match and match.group(0))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_page_check_parses(self):
        result = subprocess.run(["node", "--check", str(PAGE)], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))

    def test_media_check_takes_programs_from_absolute_folders_only(self):
        find_program = load_media_check().find_program
        name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        here = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / name
            program.write_text("", encoding="utf-8")
            program.chmod(0o755)
            os.chdir(tmp)
            try:
                with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([".", ""])}):
                    self.assertIsNone(find_program("ffmpeg"), "a program in the current folder")
                with mock.patch.dict(os.environ, {"PATH": tmp}):
                    self.assertEqual(find_program("ffmpeg"), str(program))
                self.assertEqual(find_program(str(program)), str(program))
            finally:
                os.chdir(here)

    def test_media_check_without_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "no-ffmpeg")
            result = media_check(Path(tmp) / "clip.mp4", "--ffmpeg", missing, "--ffprobe", missing)
        self.assertEqual(result.returncode, 2)
        self.assertIn("needs ffmpeg and ffprobe", result.stderr.decode("utf-8", "replace"))


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe are not installed")
class MediaCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        blinking(cls.base / "fast.mkv", 2, 6, WHITE)               # 5 flashes a second
        blinking(cls.base / "slow.mkv", 6, 15, WHITE)              # 2 a second, for six seconds
        blinking(cls.base / "red.mkv", 2, 6, RED, dark=GREY)       # 5 a second, red only: both states as bright
        blinking(cls.base / "spot.mkv", 2, 6, WHITE, box=16)       # 5 a second, over 16x16 pixels
        patches(cls.base / "turns.mkv", together=False)            # two sixths of the field, one after the other
        patches(cls.base / "pair.mkv", together=True)              # the same two at once: a third of the field
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000",
                        "-af", "volume=-20dB", "-c:a", "pcm_s16le", str(cls.base / "quiet.wav")],
                       check=True, capture_output=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def measure(self, name, *args):
        result = media_check(self.base / name, "--json", *args)
        report = json.loads(result.stdout.decode("utf-8"))
        return result.returncode, report, {(check["level"], check["check"]) for check in report["checks"]}

    def test_fast_flashing_fails(self):
        code, report, checks = self.measure("fast.mkv")
        self.assertEqual(code, 1)
        self.assertIn(("error", "flash"), checks)
        self.assertEqual(report["flash"]["general"]["maxPerSec"], 5)

    def test_slow_flashing_passes_and_long_flashing_is_named(self):
        code, report, checks = self.measure("slow.mkv")
        self.assertEqual(code, 0)
        self.assertEqual(report["flash"]["general"]["maxPerSec"], 2)
        self.assertEqual(report["flash"]["result"], "pass")
        self.assertIn(("warn", "flash-extended"), checks)

    def test_red_flashes_are_counted_apart(self):
        code, report, checks = self.measure("red.mkv")
        self.assertEqual(code, 1)
        self.assertIn(("error", "flash"), checks)
        self.assertEqual((report["flash"]["general"]["maxPerSec"], report["flash"]["red"]["maxPerSec"]), (0, 5))

    def test_a_small_flashing_area_passes_with_a_warning(self):
        code, report, checks = self.measure("spot.mkv")
        self.assertEqual(code, 0)
        self.assertEqual(report["flash"]["result"], "pass-area")
        self.assertLess(report["flash"]["maxArea"], 0.25)
        self.assertIn(("warn", "flash-area"), checks)

    def test_areas_add_up_only_while_they_flash_together(self):
        code, report, checks = self.measure("turns.mkv")
        self.assertEqual((code, report["flash"]["result"]), (0, "pass-area"))
        self.assertAlmostEqual(report["flash"]["maxArea"], 1 / 6, places=2)
        self.assertIn(("warn", "flash-area"), checks)
        code, report, checks = self.measure("pair.mkv")
        self.assertEqual((code, report["flash"]["result"]), (1, "fail"))
        self.assertAlmostEqual(report["flash"]["maxArea"], 1 / 3, places=2)
        self.assertIn(("error", "flash"), checks)

    def test_loudness_is_judged_against_the_target(self):
        code, report, checks = self.measure("quiet.wav")
        self.assertEqual(code, 1)
        self.assertIn(("error", "loudness"), checks)
        self.assertLess(report["loudness"]["integrated"], -30)
        code, report, checks = self.measure("quiet.wav", "--target", "none")
        self.assertEqual((code, checks), (0, set()))

    def test_a_size_or_fps_asked_for_fails_without_video(self):
        code, report, checks = self.measure("quiet.wav", "--target", "none", "--expect-size", "1920x1080", "--expect-fps", "30")
        self.assertEqual((code, checks), (1, {("error", "size"), ("error", "fps")}))

    def test_it_reads_local_files_only(self):
        result = media_check("http://127.0.0.1:9/clip.mp4", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("whitelist", json.loads(result.stdout.decode("utf-8"))["error"])

    def test_it_changes_no_file(self):
        def listing():
            return {path.name: (path.stat().st_size, path.stat().st_mtime_ns, path.read_bytes())
                    for path in sorted(self.base.iterdir())}
        before = listing()
        result = media_check(*(sorted(self.base.iterdir()) + ["--json"]))
        self.assertEqual(len(json.loads(result.stdout.decode("utf-8"))), len(before))
        self.assertEqual(listing(), before)


if __name__ == "__main__":
    unittest.main()
