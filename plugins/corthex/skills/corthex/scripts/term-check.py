#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""corthex · term-check.py

Finds coined native words that stand in for a field's standard terms in Korean text, such as
길 for 경로 or 물음 for 질문, so that they can be fixed before a document, record or prompt is
published or handed over. It only reads: it changes no file and sends nothing.

Each finding is a candidate, not a verdict. A word on the list can be the right word in its
sentence, such as 길 for a road; keep it then, and say why in the review.

Use
  python3 term-check.py page.html notes.md
  python3 term-check.py - < draft.md
  python3 term-check.py --list
  (on Windows, py instead of python3)

Markdown, HTML and plain text are read. Code is skipped: fenced and indented Markdown code,
inline code in backticks, and HTML code, pre, script and style elements.

Exit code: 0 nothing found, 1 candidates found, 2 a file could not be read or the arguments
were wrong.
"""

import argparse
import html.parser
import re
import sys

VERSION = "1.0"

HANGUL = "가-힣"
NOT_BEFORE = "(?<![%s])" % HANGUL
NOT_AFTER = "(?![%s])" % HANGUL
# Particles and copulas that may follow a noun. The noun itself must stand alone, so that a
# compound or another word that starts with the same syllables, such as 길이 or 물음표, is left out.
PARTICLES = ("에서는", "에서도", "에서만", "에서", "에게", "에는", "에도", "에만", "으로는", "으로도", "으로", "로는", "로도",
             "과는", "와는", "까지", "부터", "처럼", "마다", "입니다", "이라는", "이라고", "이란", "라는", "라고", "이고",
             "이며", "이다", "이나", "은", "는", "이", "가", "을", "를", "과", "와", "의", "에", "로", "도", "만", "나", "란")


def noun(word, particles=PARTICLES):
    tail = "|".join(sorted((re.escape(p) for p in particles), key=len, reverse=True))
    return NOT_BEFORE + "(?:" + word + ")(?:" + tail + ")?" + NOT_AFTER


# 길이 reads as "length" far more often than as 길 with a subject particle, so 길 takes no 이.
WAY_PARTICLES = tuple(p for p in PARTICLES if not p.startswith("이"))

# (coined word, standard terms to use, pattern). The examples in references/principles.md, in principle 9
# of SKILL.md and in corthex-study's writing.md come from this table; tests/test_term_check.py checks that.
TERMS = (
    ("길", "경로 (path), 방법", noun("길", WAY_PARTICLES)),
    ("물음", "질문, 연구 질문", noun("물음")),
    ("낱말", "단어, 용어, 키워드", noun("낱말")),
    ("갈말", "용어", noun("갈말")),
    ("묶음", "번들, 압축 파일(zip), 패키지, 배치", noun("묶음")),
    ("대역", "목(mock), 스텁, 테스트 더블", noun("대역")),
    ("판", "버전", noun("판")),
    ("확인 지점", "체크포인트", noun("확인 ?지점")),
    ("화면 나무", "화면 트리", noun("화면 ?나무")),
    ("흐름 상자", "흐름 노드, 플로 노드", noun("흐름 ?상자")),
    ("관문", "필수 조건(gate), 게이트", noun("관문")),
    ("증거 사다리", "증거 수준", noun("증거 ?사다리")),
    ("재는/잰", "측정하는/측정한", NOT_BEFORE + "(?:재는|잰|재어|재서|쟀다|쟀습니다|잽니다)" + NOT_AFTER),
    ("떼어 놓은", "격리된, 분리된", NOT_BEFORE + "떼어 ?(?:놓은|놓고|둔|두고)" + NOT_AFTER),
    ("얼개", "구조, 아키텍처", noun("얼개")),
    ("본보기", "예시, 샘플", noun("본보기")),
    ("갈래", "유형, 종류, 분기", noun("갈래")),
    ("덩이", "청크(chunk), 덩어리", noun("덩이")),
    ("꼬리표", "태그, 레이블", noun("꼬리표")),
    ("열쇠", "키 (API 키, 캐시 키 등)", noun("열쇠")),
    ("시스템 글", "시스템 프롬프트", noun("시스템 ?글")),
    ("오류 글", "오류 메시지", noun("오류 ?글")),
    ("글 속성", "텍스트 속성", noun("글 ?속성")),
    ("입구 스킬", "진입점 스킬, 엔트리 스킬", noun("입구 ?스킬")),
    ("누리집", "웹사이트, 홈페이지", noun("누리집")),
    ("갈무리", "저장, 캡처, 정리", noun("갈무리")),
    ("누름단추", "버튼", noun("누름 ?단추")),
    ("끌어오기 요청", "풀 리퀘스트(PR)", noun("끌어오기 ?요청")),
    ("꼴", "형식, 형태", noun("꼴")),
    ("시험대", "테스트베드, 벤치마크", noun("시험대")),
    ("시험 세트", "테스트 세트, 벤치마크", noun("시험 ?세트")),
    ("지어낸 자료", "합성 데이터", noun("지어낸 ?(?:자료|데이터)")),
    ("씨앗", "시드(seed)", noun("씨앗")),
    ("앞머리", "프리픽스(prefix), 접두부, 프런트매터(frontmatter)", noun("앞머리")),
    ("머리글", "헤더", noun("머리글")),
    ("날 기록", "원본 로그, 원시 로그", noun("날 ?기록")),
    ("훑기", "스캔", noun("훑기")),
)

# Set phrases where a listed word is the ordinary word. A phrase exempts only the match that starts
# inside it, so a coined word right next to a set phrase is still found.
SET_PHRASES = (
    re.compile("막다른 ?길"),
    re.compile("막힌 ?길"),
    re.compile("(?:가는|오는) 길에"),
    re.compile("길 (?:수|것|때|만큼|뿐|듯)(?![가-힣])"),  # 길다 (to be long), as in "답변이 길 수 있다"
    re.compile("(?:주파수|파장|에너지|Hz|eV|nm) ?대역"),
    re.compile("의 열쇠"),
    # A verb that ends a note with -ㅁ, such as "라고 물음" (asked) or "부모에 묶음" (grouped under the parent).
    re.compile("(?:라고|이라고|다고|냐고) 물음(?![가-힣])"),
    re.compile("(?:에|로|으로|끼리) 묶음(?![가-힣])"),
    # A rate, as in "한 번 꼴로" (about once), and the idiom "시험대에 오르다" (to be put to the test).
    re.compile("(?:번|하나|명|개|건|회|일|주|달|해|년|[0-9]) 꼴"),
    re.compile("시험대에 (?:오르|올라|올랐|올린|서|섰|선)"),
)

COMPILED = tuple((coined, standard, re.compile(pattern)) for coined, standard, pattern in TERMS)
SKIPPED_ELEMENTS = {"code", "pre", "script", "style", "kbd", "samp", "textarea"}
INLINE_ELEMENTS = {"a", "abbr", "b", "bdi", "bdo", "cite", "data", "del", "dfn", "em", "font", "i", "ins", "mark", "q",
                   "s", "small", "span", "strong", "sub", "sup", "time", "u", "var", "wbr"}
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")
HTML_SUFFIXES = (".html", ".htm", ".xhtml")


def blank(text):
    """The same text with every character but line breaks replaced by a space."""
    return re.sub(r"[^\n]", " ", text)


def markdown_lines(text):
    """The text's lines, with fenced code and inline code blanked out so that line numbers still match.

    Indented lines are read as text: in these documents they are nested list items far more often than code.
    """
    lines = []
    fence = None
    for line in text.split("\n"):
        opened = FENCE.match(line)
        if fence:
            if opened and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
            lines.append(blank(line))
        elif opened:
            fence = opened.group(1)
            lines.append(blank(line))
        else:
            lines.append(INLINE_CODE.sub(lambda m: blank(m.group(0)), line))
    return lines


class TextOfPage(html.parser.HTMLParser):
    """Collects the visible text of an HTML page, line by line, without code and scripts.

    An inline element, such as b or span, joins the text around it as the page shows it; any other tag
    separates it, so that words in two paragraphs on one line are not read as one word.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = {}
        self.skipping = 0

    def add(self, text):
        line, _ = self.getpos()
        for offset, part in enumerate(text.split("\n")):
            self.lines[line + offset] = self.lines.get(line + offset, "") + part

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED_ELEMENTS:
            self.skipping += 1
        elif tag not in INLINE_ELEMENTS:
            self.add(" ")

    def handle_endtag(self, tag):
        if tag in SKIPPED_ELEMENTS:
            self.skipping = max(0, self.skipping - 1)
        elif tag not in INLINE_ELEMENTS:
            self.add(" ")

    def handle_data(self, data):
        if not self.skipping:
            self.add(data)


def html_lines(text):
    page = TextOfPage()
    page.feed(text)
    page.close()
    count = text.count("\n") + 1
    return [page.lines.get(number, "") for number in range(1, count + 1)]


def excerpt(line, start, end, width=36):
    left = max(0, start - width)
    right = min(len(line), end + width)
    text = line[left:right].strip()
    return ("…" if left else "") + text + ("…" if right < len(line) else "")


def set_phrase_spans(line):
    """Where the line uses a listed word in a set phrase, as (start, end) pairs."""
    return [hit.span() for phrase in SET_PHRASES for hit in phrase.finditer(line)]


def find(lines):
    """Each candidate as (line number, coined word, standard terms, the matched text, an excerpt)."""
    found = []
    for number, line in enumerate(lines, 1):
        spans = None
        for coined, standard, pattern in COMPILED:
            for match in pattern.finditer(line):
                if spans is None:
                    spans = set_phrase_spans(line)
                if any(start <= match.start() < end for start, end in spans):
                    continue
                found.append((number, coined, standard, match.group(0), excerpt(line, match.start(), match.end())))
    return found


def read(name):
    """A file's text, or standard input's for -, read as UTF-8 whatever the console's encoding."""
    if name == "-":
        stream = getattr(sys.stdin, "buffer", None)
        return stream.read().decode("utf-8-sig") if stream else sys.stdin.read()
    with open(name, encoding="utf-8-sig") as handle:
        return handle.read()


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Find coined native words that stand in for standard terms in Korean text.")
    parser.add_argument("files", nargs="*", help="Markdown, HTML or text files; - reads standard input")
    parser.add_argument("--list", action="store_true", help="print the coined words and the standard terms, then stop")
    parser.add_argument("--version", action="version", version="term-check " + VERSION)
    args = parser.parse_args(argv)
    if args.list:
        for coined, standard, _ in TERMS:
            print("%s → %s" % (coined, standard))
        return 0
    if not args.files:
        parser.print_usage(sys.stderr)
        print("term-check: name at least one file, or - for standard input", file=sys.stderr)
        return 2
    total = 0
    counts = {}
    failed = False
    for name in args.files:
        try:
            text = read(name)
        except (OSError, UnicodeDecodeError) as error:
            print("%s: cannot read: %s" % (name, error), file=sys.stderr)
            failed = True
            continue
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = html_lines(text) if name.lower().endswith(HTML_SUFFIXES) else markdown_lines(text)
        for number, coined, standard, matched, around in find(lines):
            print("%s:%d: %s → %s | %s" % (name, number, matched, standard, around))
            counts[coined] = counts.get(coined, 0) + 1
            total += 1
    if total:
        summary = ", ".join("%s %d" % (coined, counts[coined]) for coined, _, _ in TERMS if coined in counts)
        print("%d candidate%s: %s. Use the standard term, or keep a word that is right in its sentence and say why."
              % (total, "" if total == 1 else "s", summary))
    elif not failed:
        print("No coined words found.")
    if failed:
        return 2
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
