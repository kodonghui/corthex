"""TASK-013/014 library checks; session-start integration remains TASK-017."""

import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest import mock

from _common import ROOT
import test_memory
import test_memory_store

SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import clock, configuration, context, files, start_memory as summary, store

UTC = timezone.utc


def item(number=0, text="A fact.", kind="fact", speaker="agent", said="2026-10-24T12:00:00.000Z"):
    return {"id": "i_%012d" % number, "kind": kind, "text": text,
            "quotes": [{"speaker": speaker, "said": said}]}


def state(number=0, part="goal", text="A goal.", pos=0, cites=()):
    return {"id": "s_%012d" % number, "part": part, "text": text, "pos": pos, "cites": list(cites)}


def memory_part(result):
    return result.text.split("\n\n## Memory\n\n", 1)[1]


class StartMemoryTest(unittest.TestCase):
    def test_stage06_example_matches_every_byte_in_both_documents(self):
        notice = ("Curation is waiting for CORTHEX_MEMORY_ANTHROPIC_API_KEY, which the hook's environment "
                  "does not have. Memory keys are read only from the environment that the host starts in, "
                  "such as a shell profile or a cloud environment's secret settings.")
        pinned = item(text="Keep raw logs on the device; only the curated layer is synced.",
                      kind="decision", speaker="user")
        pinned["id"] = "i_7f3k2m9q4x1v"
        rows = [state(text="Ship corthex-memory 0.2.0 with recording and the start summary.", cites=["i_2b8d0w5n6c3r"]),
                state(1, "decisions", "Curation runs in one detached background process.", cites=["i_9k1m4t7v2q8x"]),
                state(2, "progress", "The interfaces of stage 06."),
                state(3, "next", "Write the hook script.")]
        result = summary.build_summary("Base", [summary.Notice("key", notice)], [pinned], rows, zone=UTC)
        actual = result.text[len("Base\n\n"):].encode("utf-8")
        for name in ("memory.md", "memory.ko.md"):
            doc = (ROOT / "docs/06-api" / name).read_text(encoding="utf-8")
            expected = doc.split("```text\n## Memory\n", 1)[1].split("\n```", 1)[0]
            self.assertEqual(actual, ("## Memory\n" + expected).encode("utf-8"))
        self.assertFalse(result.text.endswith("\n"))
        self.assertEqual(result.pins, (pinned["id"],))

    def test_tc050_largest_unshortened_legacy_fixture_and_10000_byte_state(self):
        case = test_memory.SessionStartTest("test_repository_values_outside_their_format_are_left_out")
        captured = []
        original = case.run_hook
        def capture(*args, **kwargs):
            result = original(*args, **kwargs)
            captured.append(json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])
            return result
        with mock.patch.object(case, "run_hook", side_effect=capture):
            checked = case.run()
        self.assertTrue(checked.wasSuccessful(), checked.errors + checked.failures)
        base = max(captured, key=lambda text: len(text.encode("utf-8")))
        self.assertNotIn(context.SHORTENED, base)
        self.assertLessEqual(len(base.encode("utf-8")) + 2 + 4000, 7999)
        rows = [state(n, summary.PARTS[n % 5], "x" * 200, n) for n in range(50)]
        self.assertEqual(sum(len(row["text"].encode("utf-8")) for row in rows), 10000)
        result = summary.build_summary(base, state=rows)
        self.assertTrue(result.text.startswith(base + "\n\n"))
        self.assertLessEqual(len(result.text.encode("utf-8")), 7999)
        self.assertLessEqual(len(("## Memory\n\n" + memory_part(result)).encode("utf-8")), 4000)
        self.assertRegex(result.text, r"Left out for room: [1-9][0-9]* current state lines and 0 pinned items\.$")

    def test_tc051_item_controls_and_unicode_separators_cannot_start_a_line(self):
        text = "\x00 \tOne\n# Heading\r\x85two\u2028three\u2029four\x7f five  "
        result = summary.build_summary("Base", pins=[item(text=text)], zone=UTC)
        body = memory_part(result)
        self.assertTrue(body.startswith(summary.REFERENCE))
        line = body.split("Pinned:\n", 1)[1]
        self.assertEqual(len(line.splitlines()), 1)
        self.assertTrue(line.startswith("- i_000000000000 | fact | agent | 2026-10-24 | "))
        self.assertTrue(line.endswith("One # Heading two three four five"))

    def test_tc052_deciding_quote_controls_speaker_and_device_local_date(self):
        pins = [item(0, kind="decision", speaker="user", said="2026-10-24T23:30:00.000Z"),
                item(1, kind="decision", speaker="agent"), item(2, speaker="user")]
        pins[0]["quotes"].append({"speaker": "agent", "said": "2026-10-26T00:00:00.000Z"})
        result = summary.build_summary("Base", pins=pins, zone=timezone(timedelta(hours=9)))
        self.assertIn("| decision | user decision | 2026-10-25 |", result.text)
        self.assertIn("| decision | agent | 2026-10-24 |", result.text)
        self.assertIn("| fact | user | 2026-10-24 |", result.text)
        self.assertEqual(result.pins, tuple(pin["id"] for pin in pins))
        west = summary.item_line(pins[1], timezone(timedelta(hours=-13)))
        self.assertIn("| 2026-10-23 |", west)

    def test_item_text_limit_includes_ellipsis_and_keeps_utf8_boundaries(self):
        for text, expected in (("a" * 300, "a" * 300), ("a" * 301, "a" * 297 + "..."),
                               ("가" * 101, "가" * 99 + "..."), ("😀" * 76, "😀" * 74 + "...")):
            with self.subTest(char=text[0], size=len(text)):
                line = summary.item_line(item(text=text), UTC)
                actual = line.split(" | ")[-1]
                self.assertEqual(actual, expected)
                self.assertLessEqual(len(actual.encode("utf-8")), 300)

    def test_tc053_library_empty_memory_has_exact_blank_lines_and_no_final_lf(self):
        result = summary.build_summary("Base")
        self.assertEqual(result.text, "Base\n\n## Memory\n\n" + summary.REFERENCE + "\n\n" + summary.NOTHING)
        self.assertEqual(result.pins, ())

    def test_state_order_labels_normalization_and_first_three_citations(self):
        cites = [item(n)["id"] for n in (1, 2, 3, 4)]
        rows = [state(3, "next", "next\u2028line", 9), state(2, "goal", "second", 1),
                state(1, "goal", "first\t # one", 1, cites),
                state(4, "blockers", "blocked\x00now"), state(5, "progress", "work"),
                state(6, "decisions", "decided")]
        before = copy.deepcopy(rows)
        result = summary.build_summary("Base", state=rows)
        actual = result.text.split("Current state:\n", 1)[1]
        self.assertEqual(actual, "- Goal: first # one (i_000000000001, i_000000000002, i_000000000003)\n- Goal: second\n"
                         "- Decision in force: decided\n- Work in progress: work\n"
                         "- Blocker: blocked now\n- Next action: next line")
        self.assertEqual(rows, before)

    def test_tc403_a_dead_end_and_the_done_condition_show_under_their_own_labels(self):
        # TASK-111 (REQ-228): only a blocker that starts with "Dead end:" and a next action that starts with
        # "Done when:", as the curator writes them; the marker and the white space after it are left out.
        cites = [item(n)["id"] for n in (1, 2)]
        rows = [state(1, "blockers", "Dead end:\t Polling the raw lock hangs on Windows.", 1, cites[:1]),
                state(2, "blockers", "Windows sharing.", 2),
                state(3, "blockers", "dead end: written in small letters.", 3),
                state(4, "blockers", "Dead end:", 4, cites[1:]),
                state(5, "next", "Done when: the hook check passes.", 1, cites),
                state(6, "next", "Write the tests; Done when: is in the text.", 2),
                state(7, "progress", "Dead end: in another part.", 1),
                state(8, "goal", "Done when: in another part.", 1),
                state(9, "progress", "", 2)]
        result = summary.build_summary("Base", state=rows)
        actual = result.text.split("Current state:\n", 1)[1]
        self.assertEqual(actual, "- Goal: Done when: in another part.\n"
                         "- Work in progress: Dead end: in another part.\n"
                         "- Work in progress:\n"
                         "- Dead end: Polling the raw lock hangs on Windows. (i_000000000001)\n"
                         "- Blocker: Windows sharing.\n"
                         "- Blocker: dead end: written in small letters.\n"
                         "- Dead end: (i_000000000002)\n"
                         "- Done when: the hook check passes. (i_000000000001, i_000000000002)\n"
                         "- Next action: Write the tests; Done when: is in the text.")

    def test_state_is_not_cut_to_the_item_text_limit(self):
        result = summary.build_summary("Base", state=[state(text="가" * 200)])
        self.assertIn("가" * 200, result.text)
        self.assertNotIn("...", result.text)

    # SPEC-148: where to read a source again (TASK-112)

    def test_stage06_pointer_examples_match_both_documents(self):
        decided = item(text="Keep raw logs on the device; only the curated layer is synced.", kind="decision",
                       speaker="user")
        decided["id"] = "i_7f3k2m9q4x1v"
        decided["quotes"][0].update(entry="e_5h2j8n3p0r6t", words="the ERD in docs/05-erd/memory.md says so")
        cited = {"entry": "e_0a1b2c3d4e5f", "words": "after 3f9a0c4 in tests/test_memory_locks.py."}
        dead = dict(state(1, "blockers", "Dead end: Polling the raw lock in a loop hangs on Windows."),
                    cites=["i_2b8d0w5n6c3r", "e_8m1k4r7t2w5y"])
        lines = [summary.item_line(decided, UTC) + summary.pointer_text(summary.item_pointers(decided)),
                 summary.state_line(dead) + summary.pointer_text(summary.line_pointers(dead, {"i_2b8d0w5n6c3r": cited}.get))]
        for name in ("memory.md", "memory.ko.md"):
            doc = (ROOT / "docs/06-api" / name).read_text(encoding="utf-8")
            example = doc.split("| reread: e_5h2j8n3p0r6t", 1)[0].rsplit("```text\n", 1)[1] + "| reread: e_5h2j8n3p0r6t"
            example += doc.split("| reread: e_5h2j8n3p0r6t", 1)[1].split("\n```", 1)[0]
            self.assertEqual(example.split("\n"), lines)

    def test_a_word_is_a_commit_or_a_path_only_in_its_exact_form(self):
        words = ("Run 3f9a0c4, then 0123456789abcdef0123456789abcdef01234567 (40) but not 3f9a0c, "
                 "0123456789abcdef0123456789abcdef012345678, deadbeef, 1234567, 3F9A0C4 or 3f9a0c4g. "
                 "Read docs/05-erd/memory.md: \"tests/test_a.py\" [x/y.cfg] {u/v.js} <w/x.go>; 'q/r.txt' y/z.rs! "
                 "a/.env ./run.sh? not a/b, a/b/, x/y.toolong99, http://h/a.md, https://h/b.md, a/b., Makefile, "
                 "x/y.m-d, 가/나.md, a/b.한글 or a b/c.py　d/e.py")
        self.assertEqual(list(summary.named(words)), [
            "3f9a0c4", "0123456789abcdef0123456789abcdef01234567", "docs/05-erd/memory.md", "tests/test_a.py",
            "x/y.cfg", "u/v.js", "w/x.go", "q/r.txt", "y/z.rs", "a/.env", "./run.sh", "가/나.md", "b/c.py",
            "d/e.py"])
        # An unpaired surrogate becomes U+FFFD, as in an item's text, so a pointer always encodes.
        self.assertEqual(list(summary.named("\ud800/x.md")), ["�/x.md"])

    def test_markdown_marks_a_line_number_and_a_following_particle_are_not_part_of_a_pointer(self):
        words = ("Fixed in `plugins/x/recall.py` and **docs/x.md**, see src/a.py:42, src/b.py:42-50. and "
                 "src/c.py:3:7; plugins/y/start.py를 고쳤고 커밋 a4ab96e에서 문서/설계.md의 표를 바꿨습니다 "
                 "(`3f9a0c4`). Not 1.5/2.0, v1.2/v1.3, 2026/11.04, logs/run.1, src/**/*.py, a/b.py:x, a/b.py-1, "
                 "a4ab96ex or a/b.toolong99를")
        self.assertEqual(list(summary.named(words)), [
            "plugins/x/recall.py", "docs/x.md", "src/a.py", "src/b.py", "src/c.py", "plugins/y/start.py", "a4ab96e",
            "문서/설계.md", "3f9a0c4"])

    def test_a_mention_a_bracket_or_quotation_mark_of_any_script_and_a_table_s_bar_end_a_word(self):
        words = ("fix @plugins/x/recall.py now; “src/a.py”를 고침 （src/b.py） 「abc1234」 ‘deadbeef1’ 【docs/x.md】 "
                 "《a/b.md》 see src/c.py... | docs/d.md| a.py|b/e.py src/f.py#L42 --config=a/g.json "
                 "src/h.py、src/i.py。 경로：src/j.py src/k.py！ x/l.py?!")
        self.assertEqual(list(summary.named(words)), [
            "plugins/x/recall.py", "src/a.py", "src/b.py", "abc1234", "deadbeef1", "docs/x.md", "a/b.md", "src/c.py",
            "docs/d.md", "b/e.py", "src/f.py", "a/g.json", "src/h.py", "src/i.py", "src/j.py", "src/k.py", "x/l.py"])

    def test_a_path_ends_at_its_first_extension_that_a_character_that_is_not_ascii_follows(self):
        # What follows, even when it holds another "/", is not part of the path.
        words = "src/a.py와docs/b.md src/c.py에서/x docs/v1.x/d.md a/b.c/e.py 문서/f.md를/g a/b.한글/h"
        self.assertEqual(list(summary.named(words)), ["src/a.py", "src/c.py", "docs/v1.x/d.md", "a/b.c/e.py",
                                                      "문서/f.md"])

    def test_a_git_range_names_both_of_its_commits(self):
        words = ("regressed in 5feb73a..a8d6bf9, see abc1234...def5678를 and e8b8714.. but 1234567..abcdef1 has one; "
                 "not deadbee..cafe123x or 3f9a0c4....a8d6bf9")
        self.assertEqual(list(summary.named(words)), ["5feb73a", "a8d6bf9", "abc1234", "def5678", "e8b8714",
                                                      "abcdef1"])

    def test_the_entry_id_pattern_matches_the_raw_log_s_and_the_item_types(self):
        # The start hook keeps its own copy, as of the item ID, so that it imports no more than it needs.
        from memory_lib import base, item_types, raw_log
        values = [base.new_id("e") for _ in range(200)] + [
            "e_0123456789ab", "e_0123456789AB", "e_0123456789a", "e_0123456789abc", "e_0123456789ai",
            "e_0123456789al", "e_0123456789ao", "e_0123456789au", "i_0123456789ab", "e_0123456789ab\n"]
        for value in values:
            found = {bool(pattern.match(value)) for pattern in (summary.ENTRY_ID, raw_log.ENTRY_ID, item_types.ENTRY)}
            self.assertEqual(found, {bool(raw_log.ENTRY_ID.fullmatch(value))}, value)

    def test_pointers_are_three_at_most_each_once_within_80_bytes_without_a_control_bar_or_backtick(self):
        long = "d/" + "a" * 75 + ".md"
        self.assertEqual(len(long.encode("utf-8")), 80)
        wide = "d/" + "가" * 25 + ".md"  # 2 + 75 + 3 = 80 bytes
        values = ["e_5h2j8n3p0r6t", long + "x", "d/a|b.md", "d/a`b.md", "d/a\x07b.md", "e_5h2j8n3p0r6t", long,
                  "d/" + "가" * 26 + ".md", wide]
        self.assertEqual(summary.pointers(values), ("e_5h2j8n3p0r6t", long, wide))
        taken = []

        def lazily():
            for value in ("a/b.md", "c/d.md", "e/f.md", "g/h.md"):
                taken.append(value)
                yield value
        self.assertEqual(summary.pointers(lazily()), ("a/b.md", "c/d.md", "e/f.md"))
        self.assertEqual(taken, ["a/b.md", "c/d.md", "e/f.md"])  # a line with three reads no further source

    def test_a_pointer_holds_no_format_character(self):
        # A direction mark or a zero-width character would show another path than the pointer's bytes.
        values = ["docs/‮gnp.py", "src/a​.py", "d/‍b.md", "d/­c.md", "﻿d/e.md", "src/a.py"]
        self.assertEqual(summary.pointers(values), ("src/a.py",))
        self.assertEqual(summary.pointers(summary.named("see src/a​.py and docs/b.md")), ("docs/b.md",))
        self.assertEqual(summary.pointer_text(()), "")
        self.assertEqual(summary.pointer_text(("a/b.md", "3f9a0c4")), " | reread: a/b.md, 3f9a0c4")

    def test_a_line_points_to_its_entries_first_then_to_its_items_quotes_item_by_item(self):
        first, second = item(1), item(2)
        quotes = {first["id"]: {"words": "see a/one.md and 3f9a0c4"}, second["id"]: {"words": "b/two.md 3f9a0c4"}}
        asked = []

        def quote(value):
            asked.append(value)
            return quotes.get(value)
        line = state(cites=[first["id"], "e_5h2j8n3p0r6t", "i_000000000009", second["id"], "e_0a1b2c3d4e5f"])
        self.assertEqual(summary.line_pointers(line, quote), ("e_5h2j8n3p0r6t", "e_0a1b2c3d4e5f", "a/one.md"))
        self.assertEqual(asked, [first["id"]])
        asked.clear()
        line = state(cites=[first["id"], "i_000000000009", second["id"]])
        self.assertEqual(summary.line_pointers(line, quote), ("a/one.md", "3f9a0c4", "b/two.md"))
        self.assertEqual(asked, [first["id"], "i_000000000009", second["id"]])
        # An item's line: its deciding quote's entry, then its words; another quote of the item gives none.
        value = dict(item(3), quotes=[{"entry": "e_5h2j8n3p0r6t", "words": "the d/x.py file", "speaker": "user",
                                       "said": "2026-10-24T12:00:00.000Z"},
                                      {"entry": "e_0a1b2c3d4e5f", "words": "y/z.py", "speaker": "user",
                                       "said": "2026-10-24T12:00:00.000Z"}])
        self.assertEqual(summary.item_pointers(value), ("e_5h2j8n3p0r6t", "d/x.py"))

    def test_pointers_go_from_the_last_line_back_before_any_line_and_are_not_counted(self):
        pins = [item(n, "pin %d" % n) for n in range(2)]
        rows = [state(10 + n, "next", "Step %d" % n, n) for n in range(4)]
        table = {value["id"]: ("e_5h2j8n3p0r6t", "d/" + "p" * 60 + ".md") for value in pins + rows}
        asked = []

        def reread(value):
            asked.append(value["id"])
            return table[value["id"]]
        whole = summary.build_summary("Base", pins=pins, state=rows, zone=UTC, reread=reread)
        self.assertEqual(memory_part(whole).count(" | reread: e_5h2j8n3p0r6t, d/"), 6)
        # A pinned item is asked for with its record and a state line with its value, in the block's order.
        self.assertEqual(asked, [value["id"] for value in pins + rows])
        bare = summary.build_summary("Base", pins=pins, state=rows, zone=UTC)
        self.assertNotIn("reread", bare.text)
        # The memory part, its heading included, without pointers, and what each line's pointers add to it.
        room = len(("## Memory\n\n" + memory_part(bare)).encode("utf-8"))
        cost = len(summary.pointer_text(table[pins[0]["id"]]).encode("utf-8"))
        seen = []
        for kept in range(6, -1, -1):
            # A base that leaves the memory part just the room for `kept` lines' pointers.
            base = "b" * (summary.SUMMARY_BYTES - 2 - (room + cost * kept))
            asked.clear()
            shown = summary.build_summary(base, pins=pins, state=rows, zone=UTC, reread=reread)
            text = memory_part(shown)
            pointed = [line for line in text.split("\n") if " | reread: " in line]
            seen.append(len(pointed))
            # The lines that keep their pointers are the first ones of the block, pins first, and once the room
            # left could hold no pointer, no line's pointers are asked for.
            ordered = [line for line in text.split("\n") if line.startswith("- ")]
            self.assertEqual(pointed, ordered[:len(pointed)])
            self.assertEqual(asked, [value["id"] for value in pins + rows][:kept])
            self.assertNotIn("Left out for room", text)
            self.assertEqual(shown.pins, tuple(value["id"] for value in pins))
            self.assertTrue(shown.text.startswith(base + "\n\n"))
        self.assertEqual(seen, [6, 5, 4, 3, 2, 1, 0])
        # Once every pointer is gone, lines go as they do without pointers, and the same lines and pins show; then
        # no pointer is asked for.
        for size in range(summary.SUMMARY_BYTES - 2 - room - 200, summary.SUMMARY_BYTES - 2 - room + 400, 37):
            base = "b" * size
            asked.clear()
            pointed = summary.build_summary(base, pins=pins, state=rows, zone=UTC, reread=reread)
            plain = summary.build_summary(base, pins=pins, state=rows, zone=UTC)
            self.assertEqual(pointed.pins, plain.pins)
            if "Left out for room" in plain.text:
                self.assertEqual(pointed.text, plain.text)
                self.assertEqual(asked, [])
        # With room for two lines' pointers and a half, the third line's are asked for, do not fit, and no later
        # line's are asked for.
        base = "b" * (summary.SUMMARY_BYTES - 2 - (room + cost * 2 + cost // 2))
        asked.clear()
        text = memory_part(summary.build_summary(base, pins=pins, state=rows, zone=UTC, reread=reread))
        self.assertEqual(sum(" | reread: " in line for line in text.split("\n")), 2)
        self.assertEqual(asked, [value["id"] for value in pins + rows][:3])
        # A line without pointers takes no room, so the lines after it still get theirs.
        table[pins[1]["id"]] = ()
        base = "b" * (summary.SUMMARY_BYTES - 2 - (room + cost * 2))
        text = memory_part(summary.build_summary(base, pins=pins, state=rows, zone=UTC, reread=reread))
        pointed = [line for line in text.split("\n") if " | reread: " in line]
        self.assertEqual(len(pointed), 2)
        self.assertIn(" | pin 0 | reread: ", pointed[0])
        self.assertIn(": Step 0 | reread: ", pointed[1])

    def test_tc054_seven_notices_follow_table_order_and_count_two_left(self):
        kinds = ("pin-dropped", "temporary", "sync-unreachable", "retention", "key", "consent", "stopped")
        notices = [summary.Notice(kind, kind + ".") for kind in kinds]
        result = summary.build_summary("Base", notices=notices)
        group = memory_part(result).split("\n\n", 1)[0]
        self.assertEqual(group, "Notices from the memory plugin:\n- stopped.\n- consent.\n- key.\n"
                         "- retention.\n- sync-unreachable.\n2 more notices are in the memory status.")

    def test_tc329_notice_bytes_include_dash_space_and_lf_stop_without_skipping(self):
        notices = [summary.Notice("key", "가" * 99), summary.Notice("key", "b" * 297),
                   summary.Notice("retention", "cannot fit"), summary.Notice("rebuilt", "x")]
        result = summary.build_summary("Base", notices)
        group = memory_part(result).split("\n\n", 1)[0]
        shown = [row for row in group.splitlines() if row.startswith("- ")]
        self.assertEqual(sum(len((row + "\n").encode("utf-8")) for row in shown), 600)
        self.assertEqual(len(shown), 2)
        self.assertIn("2 more notices are in the memory status.", group)
        self.assertNotIn("- x", group)
        one_left = summary.build_summary("Base", notices[:3])
        self.assertIn("1 more notices are in the memory status.", one_left.text)
        first_too_big = summary.build_summary("Base", [summary.Notice("key", "x" * 598), notices[-1]])
        self.assertNotIn("\n- ", first_too_big.text)
        self.assertIn("2 more notices are in the memory status.", first_too_big.text)

    def test_state_drop_order_cycles_before_oldest_pins(self):
        rows = [state(n * 2 + pos, part, part + str(pos) + "x" * 400, pos)
                for n, part in enumerate(summary.PARTS) for pos in (0, 1)]
        pins = [item(0, "first pin"), item(1, "second pin")]
        # The base leaves enough room for both pins and some state.
        result = summary.build_summary("b" * 5000, pins=pins, state=rows, zone=UTC)
        self.assertIn("Left out for room:", result.text)
        self.assertEqual(result.pins, tuple(pin["id"] for pin in pins))
        # Find byte budgets yielding each prefix of the mandated round-robin removal order.
        order = [(part, pos) for pos in (1, 0) for part in reversed(summary.PARTS)]
        seen = set()
        for base_size in range(4000, 7700, 100):
            shown = summary.build_summary("b" * base_size, pins=pins, state=rows, zone=UTC)
            missing = [(part, pos) for part, pos in order if part + str(pos) not in shown.text]
            self.assertEqual(missing, order[:len(missing)])
            seen.add(len(missing))
            if len(missing) < len(order):
                self.assertEqual(shown.pins, tuple(pin["id"] for pin in pins))
        self.assertGreater(len(seen), 5)

    def test_pins_drop_oldest_first_and_return_only_displayed_ids(self):
        pins = [item(n, "가" * 100) for n in range(50)]
        original = copy.deepcopy(pins)
        result = summary.build_summary("Base", pins=pins, zone=UTC)
        self.assertGreater(len(result.pins), 0)
        self.assertLess(len(result.pins), len(pins))
        self.assertEqual(result.pins, tuple(pin["id"] for pin in pins[-len(result.pins):]))
        self.assertLessEqual(len(result.text.encode("utf-8")) - len("Base\n\n"), 4000)
        self.assertEqual(pins, original)

    def test_tc328_7000_byte_base_is_whole_while_memory_yields_room(self):
        base = "가" * 2333 + "a"
        self.assertEqual(len(base.encode("utf-8")), 7000)
        rows = [state(n, summary.PARTS[n % 5], "가" * 100, n) for n in range(34)]
        result = summary.build_summary(base, state=rows)
        self.assertTrue(result.text.startswith(base + "\n\n"))
        self.assertLessEqual(len(result.text.encode("utf-8")), 7999)
        self.assertIn("Left out for room:", result.text)
        self.assertNotIn(context.SHORTENED, result.text)

    def test_all_rows_removed_retains_notice_and_count_then_shortens_base(self):
        notice = summary.Notice("consent", "A notice that stays.")
        pins = [item(0, "pin")]
        result = summary.build_summary("b" * 8000, [notice], pins, [state(text="goal")], zone=UTC)
        block = "## Memory\n\nNotices from the memory plugin:\n- A notice that stays.\n\n" + summary.REFERENCE
        block += "\n\nLeft out for room: 1 current state lines and 1 pinned items."
        expected_base = context.shorten("b" * 8000, 7999 - len(block.encode("utf-8")) - 2)
        self.assertEqual(result.text, expected_base + "\n\n" + block)
        self.assertNotIn(summary.NOTHING, result.text)
        self.assertEqual(result.pins, ())

    def test_base_only_keeps_legacy_8000_limit_and_memory_is_strictly_under_it(self):
        for text in ("", "a" * 8000, "a" * 8001, "가" * 4000):
            old = text
            if len(old.encode("utf-8")) > 8000:
                while old and len((old + context.SHORTENED).encode("utf-8")) > 8000:
                    old = old[:len(old) * 9 // 10].rstrip()
                old += context.SHORTENED
            self.assertEqual(context.shorten(text), old)
        self.assertEqual(len(context.shorten("a" * 8000)), 8000)
        self.assertLessEqual(len(summary.build_summary("a" * 8000).text.encode("utf-8")), 7999)

    def test_library_composition_opens_no_files(self):
        with mock.patch.object(Path, "open", side_effect=AssertionError("unexpected file read")):
            result = summary.build_summary("Base", pins=[item()], state=[state()], zone=UTC)
        self.assertIn("Pinned:", result.text)

    def test_tc051_invalid_pin_metadata_is_omitted_without_room_counts(self):
        valid = item(2)
        invalid = []
        for field, value in (("id", "i_x\n# Injected"), ("id", "e_000000000001"),
                             ("id", "i_00000000000u"), ("id", "i_00000000000I"),
                             ("id", "i_000000000000\n"), ("id", "i_00000000000"),
                             ("id", "i_0000000000000"), ("id", None),
                             ("kind", "decision\n# Injected"), ("kind", "other"), ("kind", []),
                             ("speaker", "user decision"), ("speaker", "system"), ("speaker", [])):
            with self.subTest(field=field, value=value):
                pin = item(1)
                if field == "speaker":
                    pin["quotes"][0][field] = value
                else:
                    pin[field] = value
                invalid.append(pin)
                result = summary.build_summary("Base", pins=[pin, valid], zone=UTC)
                self.assertEqual(result.pins, (valid["id"],))
                self.assertNotIn("Injected", result.text)
                self.assertNotIn("Left out for room:", result.text)
        empty = summary.build_summary("Base", pins=invalid, zone=UTC)
        self.assertTrue(empty.text.endswith(summary.NOTHING))
        self.assertEqual(empty.pins, ())
        crowded = summary.build_summary("a" * 7998, pins=invalid + [valid], zone=UTC)
        self.assertTrue(crowded.text.endswith("Left out for room: 0 current state lines and 1 pinned items."))

    def test_tc051_each_schema_kind_and_speaker_remains_displayable(self):
        pins = [item(n, kind=kind, speaker=speaker) for n, (kind, speaker) in enumerate(
            (kind, speaker) for kind in ("decision", "preference", "lesson", "reference", "fact")
            for speaker in ("user", "agent"))]
        result = summary.build_summary("Base", pins=pins, zone=UTC)
        self.assertEqual(result.pins, tuple(pin["id"] for pin in pins))

    def test_state_citations_keep_only_first_three_valid_item_ids(self):
        a, b, c, d = (item(n)["id"] for n in (1, 2, 3, 4))
        row = state(cites=["e_000000000001", "e_000000000002", b,
                           "i_x\n## Injected", None, 1, "i_00000000000u", a, c, d])
        result = summary.build_summary("Base", state=[row])
        self.assertTrue(result.text.endswith("- Goal: A goal. (%s, %s, %s)" % (b, a, c)))
        self.assertNotIn("e_", result.text)
        self.assertNotIn("Injected", result.text)
        self.assertNotIn(d, result.text)
        self.assertNotIn("Left out for room:", result.text)

    def test_tc051_lone_surrogates_become_replacements_and_cf_is_preserved(self):
        text = "left\ud800 # heading\udc00 \ud83d\ude00 a\u202eb\u200bc"
        result = summary.build_summary("Base", pins=[item(text=text)], state=[state(text=text)], zone=UTC)
        normalized = "left\ufffd # heading\ufffd 😀 a\u202eb\u200bc"
        self.assertEqual(result.text.count(normalized), 2)
        self.assertNotIn("\ud800", result.text)
        self.assertNotIn("\udc00", result.text)
        result.text.encode("utf-8")
        clipped = summary.item_line(item(text="\ud800" * 101), UTC).split(" | ")[-1]
        self.assertEqual(clipped, "\ufffd" * 99 + "...")
        self.assertEqual(len(clipped.encode("utf-8")), 300)

    def test_state_position_precedes_id_and_controls_which_line_is_dropped(self):
        rows = [state(1, text="second " + "b" * 200, pos=1),
                state(9, text="first " + "a" * 200, pos=0)]
        result = summary.build_summary("Base", state=rows)
        self.assertLess(result.text.index("first "), result.text.index("second "))
        block = result.text[len("Base\n\n"):]
        base = "x" * (7998 - len(block.encode("utf-8")))
        crowded = summary.build_summary(base, state=rows)
        self.assertIn("first ", crowded.text)
        self.assertNotIn("second ", crowded.text)
        self.assertTrue(crowded.text.startswith(base + "\n\n"))
        self.assertTrue(crowded.text.endswith("Left out for room: 1 current state lines and 0 pinned items."))

    def test_tc050_empty_memory_at_7999_is_whole_and_8000_shortens_base(self):
        block = "## Memory\n\n" + summary.REFERENCE + "\n\n" + summary.NOTHING
        for size in (7999, 8000):
            with self.subTest(total=size):
                base = "x" * (size - 2 - len(block.encode("utf-8")))
                result = summary.build_summary(base)
                self.assertLessEqual(len(result.text.encode("utf-8")), 7999)
                if size == 7999:
                    self.assertEqual(result.text, base + "\n\n" + block)
                else:
                    self.assertEqual(result.text.count(context.SHORTENED), 1)

    def test_tc050_unreadable_memory_at_7999_is_whole_and_8000_shortens_base(self):
        notice = summary.unreadable("the store record is damaged")
        block = "## Memory\n\n" + notice.text
        for size in (7999, 8000):
            with self.subTest(total=size):
                base = "x" * (size - 2 - len(block.encode("utf-8")))
                result = summary.build_summary(base, [notice])
                self.assertLessEqual(len(result.text.encode("utf-8")), 7999)
                self.assertTrue(result.text.endswith(block))
                if size == 7999:
                    self.assertEqual(result.text, base + "\n\n" + block)
                else:
                    self.assertEqual(result.text.count(context.SHORTENED), 1)

    def test_tc050_all_rows_removed_respects_the_7999_boundary(self):
        block = "## Memory\n\n" + summary.REFERENCE
        block += "\n\nLeft out for room: 1 current state lines and 1 pinned items."
        for size in (7999, 8000):
            with self.subTest(total=size):
                base = "x" * (size - 2 - len(block.encode("utf-8")))
                result = summary.build_summary(base, pins=[item()], state=[state(text="x" * 5000)], zone=UTC)
                self.assertLessEqual(len(result.text.encode("utf-8")), 7999)
                self.assertTrue(result.text.endswith(block))
                self.assertEqual(result.pins, ())
                if size == 7999:
                    self.assertEqual(result.text, base + "\n\n" + block)
                else:
                    self.assertEqual(result.text.count(context.SHORTENED), 1)

    def test_tc050_one_state_line_stays_at_7999_and_is_dropped_at_8000(self):
        row = state(text="the one state line " * 15)
        block = summary.build_summary("Base", state=[row]).text[len("Base\n\n"):]
        for size in (7999, 8000):
            with self.subTest(total=size):
                base = "x" * (size - 2 - len(block.encode("utf-8")))
                result = summary.build_summary(base, state=[row])
                self.assertLessEqual(len(result.text.encode("utf-8")), 7999)
                self.assertTrue(result.text.startswith(base + "\n\n"))
                if size == 7999:
                    self.assertEqual(result.text, base + "\n\n" + block)
                else:
                    self.assertNotIn("the one state line", result.text)
                    self.assertTrue(result.text.endswith("Left out for room: 1 current state lines and 0 pinned items."))

    def test_unshortened_base_option_preserves_default_legacy_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home, repo, principles = root / "home", root / "repo", root / "principles.md"
            home.mkdir()
            (repo / ".git").mkdir(parents=True)
            principles.write_text("A" * 9000, encoding="utf-8")
            with mock.patch.object(context, "shorten", wraps=context.shorten) as shorten:
                raw = context.build_context(repo, home, principles, limit=None)
            shorten.assert_not_called()
            self.assertIn("A" * 9000, raw)
            self.assertNotIn(context.SHORTENED, raw)
            self.assertEqual(context.build_context(repo, home, principles), context.shorten(raw))

    def test_memory_shortens_the_raw_base_once_and_rejects_an_already_shortened_base(self):
        raw = "a" * 8790
        block = "## Memory\n\n" + summary.REFERENCE + "\n\n" + summary.NOTHING
        limit = 7999 - 2 - len(block.encode("utf-8"))
        once = context.shorten(raw, limit)
        twice = context.shorten(context.shorten(raw), limit)
        self.assertNotEqual(len(once), len(twice))
        with mock.patch.object(context, "shorten", wraps=context.shorten) as shorten:
            result = summary.build_summary(raw)
        shorten.assert_called_once_with(raw, limit)
        self.assertEqual(result.text, once + "\n\n" + block)
        self.assertEqual(result.text.count(context.SHORTENED), 1)
        with self.assertRaisesRegex(ValueError, "unshortened base"):
            summary.build_summary(context.shorten(raw))


class C1NoticeTest(test_memory_store.StoreCase):
    def notices(self):
        return summary.c1_notices(self.memory, deadline=clock.now() + 3)

    def test_tc055_library_consent_version_is_shared_and_notice_precedes_empty_block(self):
        for version in (1, 2):
            with mock.patch.object(configuration, "CONSENT_VERSION", version):
                notice = self.notices()
                self.assertIn("version %d of the consent text." % version, notice[0].text)
                result = summary.build_summary("Base", notice)
                self.assertIn("Notices from the memory plugin:\n- " + notice[0].text, result.text)
                self.assertTrue(result.text.endswith(summary.REFERENCE + "\n\n" + summary.NOTHING))
                document = {"consent": {"at": test_memory_store.AT, "version": version}}
                files.write_json(self.root / "configuration.json", document, "TBL-002")
                self.assertTrue(self.memory.configuration(deadline=clock.now() + 3).consented())
                self.assertEqual(self.notices(), ())
                (self.root / "configuration.json").unlink()

    def test_tc055_library_unreadable_is_one_line_without_other_notices_or_blocks(self):
        (self.root / "store.json").write_bytes(b"not JSON")
        notice = self.notices()
        expected = "Memory could not be read: the store record is damaged. The memory status says more."
        self.assertEqual(notice[0].text, expected)
        result = summary.build_summary("Base", [summary.Notice("consent", "must not show")] + list(notice),
                                       [item()], [state()], zone=UTC)
        self.assertEqual(result.text, "Base\n\n## Memory\n\n" + expected)
        self.assertEqual(result.pins, ())

    def test_missing_store_is_distinct_from_missing_record_and_creates_nothing(self):
        absent = self.folder / "absent-store"
        self.assertIsNone(summary.c1_notices(store.MemoryStore(absent), deadline=clock.now() + 3))
        self.assertFalse(absent.exists())
        (self.root / "store.json").unlink()
        before = self.snapshot()
        self.assertEqual(self.notices()[0].text,
                         "Memory could not be read: the store record is missing. The memory status says more.")
        self.assertEqual(self.snapshot(), before)

    def test_future_format_and_migration_are_opaque_and_skip_configuration(self):
        for header in ({"format": 2}, dict(self.header, migrating={"unread": True})):
            (self.root / "store.json").write_text(json.dumps(header), encoding="utf-8")
            (self.root / "configuration.json").write_bytes(b"not JSON")
            before = self.snapshot()
            self.assertEqual(self.notices()[0].text,
                             "Memory could not be read: the store format is not supported. The memory status says more.")
            self.assertEqual(self.snapshot(), before)

    def test_invalid_configuration_uses_first_sanitized_field_without_values_or_paths(self):
        documents = [({"retention": {"days": 0}, "triggers": {"turns": 0}}, "retention.days"),
                     ({"unexpected private value": "private data"}, "<unknown>"),
                     ({"projects": {"project": {"since": test_memory_store.AT, "enabled": "private data"}}}, "projects.*.enabled")]
        for document, field in documents:
            with self.subTest(field=field):
                (self.root / "configuration.json").write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(configuration.ConfigurationInvalid) as caught:
                    self.memory.configuration(deadline=clock.now() + 3)
                self.assertEqual(caught.exception.field, field)
                before = self.snapshot()
                self.assertEqual(self.notices()[0].text,
                                 "Memory could not be read: configuration is invalid at %s. The memory status says more." % field)
                self.assertEqual(self.snapshot(), before)

    def test_relative_memory_home_is_exclusive_and_never_echoes_its_value(self):
        with mock.patch.dict(os.environ, {"CORTHEX_MEMORY_HOME": "private-relative-folder"}):
            notices = summary.c1_notices(deadline=clock.now() + 3)
        self.assertEqual(summary.build_summary("Base", notices).text,
                         "Base\n\n## Memory\n\nMemory could not be read: CORTHEX_MEMORY_HOME is not an absolute path.")

    def test_record_backup_uses_existing_recovery_before_selecting_notices(self):
        backup = self.root / "store.json.bak"
        (self.root / "store.json").replace(backup)
        self.assertEqual(self.notices()[0].kind, "consent")
        self.assertEqual(self.memory.record(deadline=clock.now() + 3), self.header)

    def test_operational_error_propagates_for_later_hook_internal_handling(self):
        with mock.patch.object(self.memory, "configuration", side_effect=PermissionError()):
            with self.assertRaises(PermissionError):
                self.notices()


if __name__ == "__main__":
    unittest.main()
