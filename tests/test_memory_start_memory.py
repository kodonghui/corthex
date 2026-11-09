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
