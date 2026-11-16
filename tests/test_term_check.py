"""Checks the corthex skill's term-check.py, which finds coined words that stand in for standard terms."""

import ast
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _common import PLUGINS, read_text

SKILLS = PLUGINS / "corthex" / "skills"
SCRIPT = SKILLS / "corthex" / "scripts" / "term-check.py"
CONTEXT = PLUGINS / "corthex-memory" / "context" / "principles.md"


def load():
    spec = importlib.util.spec_from_file_location("corthex_term_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


term_check = load()


def found(text):
    """The coined words found in plain or Markdown text, in order."""
    return [coined for _, coined, _, _, _ in term_check.find(term_check.markdown_lines(text))]


def documented_command():
    """The entry skill's command for the check, with its two placeholders."""
    return re.search(r"`(python3 '<absolute skill directory>/scripts/term-check\.py' -- '<file>')`",
                     read_text(SKILLS / "corthex" / "SKILL.md")).group(1)


def single_quoted(text):
    """The text as it goes between single quotes in a POSIX shell, by the entry skill's rule: ' becomes '\\''."""
    return text.replace("'", "'\\''")


def run(*args, stdin=None, environment=None):
    if environment is None:
        environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT)] + [str(arg) for arg in args], input=stdin,
                          capture_output=True, timeout=60, env=environment)


class ScriptShapeTest(unittest.TestCase):
    def test_parses_as_python_3_8(self):
        ast.parse(read_text(SCRIPT), feature_version=(3, 8))

    def test_imports_only_the_standard_library_and_writes_nothing(self):
        allowed = {"argparse", "html", "re", "sys"}
        for node in ast.walk(ast.parse(read_text(SCRIPT))):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                with self.subTest(module=name):
                    self.assertIn(name, allowed)
        source = read_text(SCRIPT)
        self.assertNotRegex(source, r"open\([^)]*['\"][wax]")
        self.assertIn("It only reads: it changes no file and sends nothing.", source)


class FindTest(unittest.TestCase):
    def test_finds_each_listed_word(self):
        examples = {
            "길": "기록을 쓰는 길과 찾는 길을 나눕니다.",
            "물음": "설계가 답해야 할 물음을 적습니다.",
            "낱말": "영어 낱말을 옮깁니다.",
            "갈말": "갈말을 정리합니다.",
            "묶음": "단계가 끝나면 묶음을 올립니다.",
            "대역": "시험용 대역 프로그램이 키를 출력했습니다.",
            "판": "0.3.0 판부터 바뀝니다.",
            "확인 지점": "사람 확인 지점에서 묻습니다.",
            "화면 나무": "화면 나무를 그립니다.",
            "흐름 상자": "흐름 상자를 잇습니다.",
            "관문": "어느 관문이 잡아야 하는지 봅니다.",
            "증거 사다리": "증거 사다리를 오릅니다.",
            "재는/잰": "어떤 조건에서 잰 것인지 적습니다.",
            "떼어 놓은": "떼어 놓은 폴더에서 돌립니다.",
            "얼개": "전체 얼개를 봅니다.",
            "본보기": "본보기를 하나 듭니다.",
            "갈래": "갈래 17개의 이름이 있습니다.",
            "덩이": "글을 덩이로 나눕니다.",
            "꼬리표": "꼬리표를 붙입니다.",
            "열쇠": "API 열쇠를 넣습니다.",
            "시스템 글": "시스템 글이 길어집니다.",
            "오류 글": "오류 글에서 키를 읽지 않습니다.",
            "글 속성": "글 속성에는 쓰지 않습니다.",
            "입구 스킬": "입구 스킬의 목록과 같습니다.",
            "누리집": "누리집에 올립니다.",
            "갈무리": "화면을 갈무리로 남깁니다.",
            "누름단추": "누름단추를 누릅니다.",
            "끌어오기 요청": "끌어오기 요청을 엽니다.",
            "꼴": "자유 꼴 위키와 엮은 꼴을 견줍니다.",
            "시험대": "시험대는 1단계에서 만듭니다.",
            "시험 세트": "한국어 검색 시험 세트를 찾습니다.",
            "지어낸 자료": "지어낸 자료로 돌립니다.",
            "씨앗": "씨앗 값을 고정합니다.",
            "앞머리": "프롬프트 앞머리를 캐시에 둡니다.",
            "머리글": "요청 머리글에 키를 넣지 않습니다.",
            "날 기록": "날 기록을 남깁니다.",
            "훑기": "저장소 훑기를 합니다.",
        }
        self.assertEqual(set(examples), {coined for coined, _, _ in term_check.TERMS})
        for coined, text in examples.items():
            with self.subTest(coined=coined):
                self.assertIn(coined, found(text))

    def test_leaves_ordinary_words_alone(self):
        ordinary = (
            "길이 한도는 200자입니다. 줄이 길게 이어지고, 길어진 줄은 접습니다. 답변이 길 수 있습니다.",
            "물음표를 붙입니다. 판단은 사용자가 합니다. 출판, 판매, 게시판, 판정.",
            "대역폭이 넓고 2.4GHz 대역과 주파수 대역, 1 GeV 대역을 씁니다.",
            "변환 대상을 입력하라고 물음. 하위 섹션은 부모에 묶음.",
            "막다른 길에 이르면 막힌 길을 되돌아옵니다. 지름길과 갈림길, 집에 가는 길에.",
            "재고를 셉니다. 재기에 성공했습니다. 묶음표와 낱낱이.",
            "이 개념이 이해의 열쇠입니다.",
            "경로, 질문, 체크포인트, 버전, 측정값, 압축 파일, 진입점 스킬.",
            "사흘에 한 번 꼴로 엽니다. 열에 하나 꼴입니다. 꼴불견입니다.",
            "새 방식이 시험대에 올랐습니다. LEET 시험을 봅니다. 시험지와 시험 문항.",
            "그 이야기는 지어낸 것입니다. 테스트 세트, 시드, 프리픽스, 헤더, 원본 로그, 스캔, 합성 데이터.",
        )
        for text in ordinary:
            with self.subTest(text=text):
                self.assertEqual(found(text), [])

    def test_a_set_phrase_leaves_only_its_own_word_alone(self):
        texts = {
            "한 번 꼴로 물음을 기록합니다.": ["물음"],
            "막다른 길에서 판을 바꿉니다.": ["판"],
            "갈래의 열쇠입니다.": ["갈래"],
            "집에 가는 길에 낱말을 외웁니다.": ["낱말"],
            "시험대에 올랐고 묶음으로 냅니다.": ["묶음"],
            "답변이 길 수 있고 길을 찾습니다.": ["길"],
        }
        for text, expected in texts.items():
            with self.subTest(text=text):
                self.assertEqual(found(text), expected)

    def test_skips_markdown_code_but_reads_nested_items(self):
        text = "\n".join([
            "```text",
            "쓰는 길",
            "```",
            "~~~",
            "물음",
            "~~~",
            "`판` and ``확인 지점`` stay as code, but 묶음 does not.",
            "1. 항목",
            "    - 하위 항목의 낱말",
        ])
        self.assertEqual(found(text), ["묶음", "낱말"])

    def test_reads_the_visible_text_of_html_with_its_lines(self):
        page = "\n".join([
            "<!doctype html>",
            "<style>.길 { color: red }</style>",
            "<p>찾는 길을 그립니다.</p>",
            "<pre>쓰는 길</pre><code>물음</code>",
            "<script>const 판 = 1;</script>",
            "<p>설계의 <b>물음</b>마다 답합니다.</p>",
            "<p>판</p><p>단</p><p><b>판</b>단은 사용자가 합니다.</p>",
        ])
        lines = term_check.html_lines(page)
        self.assertEqual([(number, coined) for number, coined, _, _, _ in term_check.find(lines)],
                         [(3, "길"), (6, "물음"), (7, "판")])


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)

    def test_exit_codes_and_output(self):
        clean = self.base / "clean.md"
        clean.write_text("쓰기 경로와 읽기 경로를 나눕니다.\n", encoding="utf-8")
        coined = self.base / "coined.md"
        coined.write_text("# 제목\n\n쓰는 길과 찾는 길을 나눕니다.\n", encoding="utf-8")
        before = sorted(path.name for path in self.base.iterdir())

        result = run(clean)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No coined words found.", result.stdout.decode("utf-8"))

        result = run(clean, coined)
        self.assertEqual(result.returncode, 1, result.stderr)
        out = result.stdout.decode("utf-8")
        self.assertIn("coined.md:3: 길과 → 경로 (path), 방법", out)
        self.assertIn("2 candidates: 길 2.", out)

        result = run("-", stdin="찾는 물음입니다.\n".encode("utf-8"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("-:1: 물음입니다 → 질문", result.stdout.decode("utf-8"))

        result = run(self.base / "missing.md", clean)
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read", result.stderr.decode("utf-8"))

        self.assertEqual(run().returncode, 2)
        self.assertEqual(sorted(path.name for path in self.base.iterdir()), before)

    def test_the_documented_command_runs_the_skill_s_script_not_the_project_s(self):
        template = re.search(r"'(<absolute skill directory>/scripts/term-check\.py)'", documented_command()).group(1)
        script = Path(template.replace("<absolute skill directory>", (SKILLS / "corthex").as_posix()))
        marker = self.base / "decoy-ran"
        (self.base / "scripts").mkdir()
        (self.base / "scripts" / "term-check.py").write_text("open(%r, 'w').close()\n" % str(marker), encoding="utf-8")
        page = self.base / "page.md"
        page.write_text("찾는 길을 그립니다.\n", encoding="utf-8")
        environment = dict(os.environ, PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, str(script), str(page)], cwd=str(self.base), capture_output=True,
                                timeout=60, env=environment)
        self.assertEqual(result.returncode, 1)
        self.assertIn("길을 → 경로", result.stdout.decode("utf-8"))
        self.assertFalse(marker.exists())
        # The same name relative to the working folder runs the project's own script.
        subprocess.run([sys.executable, "scripts/term-check.py", str(page)], cwd=str(self.base), capture_output=True,
                       timeout=60, env=environment)
        self.assertTrue(marker.exists())

    @unittest.skipUnless(os.name == "posix" and os.path.exists("/bin/sh"), "quoting for a POSIX shell")
    def test_the_documented_command_runs_nothing_that_a_file_name_holds(self):
        # A project's file names can hold shell syntax. The entry skill puts every path in single quotes and writes
        # a ' inside one as '\\''; without quotes, or in double quotes, the shell runs what the name holds.
        self.assertIn("write a `'` inside one as `'\\''`", read_text(SKILLS / "corthex" / "SKILL.md"))
        template = documented_command()
        self.assertTrue(template.startswith("python3 '"))

        def command(name):
            filled = template.replace("<absolute skill directory>", single_quoted((SKILLS / "corthex").as_posix()))
            filled = filled.replace("<file>", single_quoted(name))
            return "'%s'%s" % (single_quoted(sys.executable), filled[len("python3"):])

        environment = dict(os.environ, PYTHONIOENCODING="utf-8")
        marker = self.base / "marker"
        names = ("report$(touch marker).md", "it's $(touch marker).md", "`touch marker`.md", "a;touch marker;b.md", "--list")
        for name in names:
            with self.subTest(name=name):
                (self.base / name).write_text("찾는 길을 그립니다.\n", encoding="utf-8")
                result = subprocess.run(["/bin/sh", "-c", command(name)], cwd=str(self.base), capture_output=True,
                                        timeout=60, env=environment)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(name + ":1: 길을 → 경로", result.stdout.decode("utf-8"))
                self.assertFalse(marker.exists())
        name = names[0]
        for unsafe in (name, '"%s"' % name):
            with self.subTest(unsafe=unsafe):
                filled = command(name).replace("'%s'" % single_quoted(name), unsafe)
                subprocess.run(["/bin/sh", "-c", filled], cwd=str(self.base), capture_output=True, timeout=60,
                               env=environment)
                self.assertTrue(marker.exists())
                marker.unlink()

    def test_reads_standard_input_as_utf_8_whatever_the_locale(self):
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONIOENCODING"}
        environment.update(LC_ALL="C", LANG="C")
        result = run("-", stdin="\ufeff찾는 물음입니다.\n".encode("utf-8"), environment=environment)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("-:1: 물음입니다 → 질문", result.stdout.decode("utf-8"))
        result = run("-", stdin=b"\xff\xfe", environment=environment)
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read", result.stderr.decode("utf-8", "replace"))

    def test_list_names_every_word_and_its_standard_term(self):
        result = run("--list")
        self.assertEqual(result.returncode, 0)
        out = result.stdout.decode("utf-8")
        for coined, standard, _ in term_check.TERMS:
            with self.subTest(coined=coined):
                self.assertIn("%s → %s" % (coined, standard), out)


class RuleTextTest(unittest.TestCase):
    PRINCIPLE = re.compile(r"^9\. Name things with the field's standard terms.*$", re.M)

    def test_the_session_start_and_the_entry_skill_carry_the_rule_and_the_check(self):
        entry = read_text(SKILLS / "corthex" / "SKILL.md")
        context = read_text(CONTEXT)
        line = self.PRINCIPLE.search(entry).group(0)
        self.assertEqual(self.PRINCIPLE.search(context).group(0), line)
        for phrase in ("loanwords and Sino-Korean words included", "A request for easy words asks for explanation, not renaming",
                       "not a style to copy"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, line)
        self.assertIn("[scripts/term-check.py](scripts/term-check.py)", entry)
        self.assertIn("`scripts/term-check.py`", context)

    def test_every_instruction_runs_the_skill_s_own_script_with_quoted_absolute_paths(self):
        # A project may hold a scripts/term-check.py of its own, which a path relative to the working folder would run,
        # and file names that hold shell syntax, which a shell runs unless the path is in single quotes.
        for path in (SKILLS / "corthex" / "SKILL.md", SKILLS / "corthex" / "references" / "principles.md",
                     SKILLS / "corthex-study" / "SKILL.md", SKILLS / "corthex-study" / "references" / "publish.md",
                     SKILLS / "corthex-record" / "SKILL.md", SKILLS / "corthex-record" / "references" / "progress.md",
                     CONTEXT):
            lines = [line for line in read_text(path).splitlines() if "term-check.py" in line]
            with self.subTest(path=str(path.relative_to(PLUGINS))):
                self.assertTrue(lines)
                for line in lines:
                    self.assertIn("absolute path", line)
                    self.assertIn("single quotes", line)
                    self.assertNotRegex(line, r"(?:python3?|py(?: -3)?) +[\"']?scripts[/\\]term-check\.py")
                    self.assertNotRegex(line, r"(?<!')<file>")

    def test_the_examples_in_the_rules_are_on_the_list(self):
        listed = {coined for coined, _, _ in term_check.TERMS}
        entry = read_text(SKILLS / "corthex" / "SKILL.md")
        examples = re.search(r"not (길, 물음, 확인 지점, 판)\)", entry).group(1).split(", ")
        principles = read_text(SKILLS / "corthex" / "references" / "principles.md")
        examples += re.search(r"such as (길, 물음, 확인 지점, 판), 시험 or 정한 것", principles).group(1).split(", ")
        writing = read_text(SKILLS / "corthex-study" / "references" / "writing.md")
        row = next(line for line in writing.splitlines() if line.startswith("| A native word swapped in"))
        examples += [word for word in re.findall(r"`([^`]+)` for", row) if word != "잰 값"]
        for word in examples:
            with self.subTest(word=word):
                self.assertIn(word, listed)
        self.assertEqual(found("잰 값"), ["재는/잰"])

    def test_skills_that_publish_or_hand_over_run_the_check(self):
        for path in (SKILLS / "corthex-study" / "SKILL.md", SKILLS / "corthex-study" / "references" / "publish.md",
                     SKILLS / "corthex-record" / "SKILL.md", SKILLS / "corthex-record" / "references" / "progress.md",
                     SKILLS / "corthex" / "references" / "principles.md"):
            with self.subTest(path=str(path.relative_to(SKILLS))):
                self.assertIn("term-check.py", read_text(path))
        study = read_text(SKILLS / "corthex-study" / "SKILL.md")
        self.assertIn("while keeping the field's standard terms", study.split("\n---", 1)[0])
        self.assertIn("is met by explaining terms, never by renaming them", study)


if __name__ == "__main__":
    unittest.main()
