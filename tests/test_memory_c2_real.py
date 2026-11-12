"""TASK-100: the readings, refusals and scripted server of the real-provider check, and its self-test.

No provider is called here: the readings get made-up layers and answers, and the one run of the script answers
every request from its local server.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from _common import ROOT

FOLDER = ROOT / ".github/hook-check"
sys.path.insert(0, str(FOLDER))
sys.path.insert(0, str(ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"))
from memory_lib import curator_answers  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_checked", FOLDER / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


real = load("c2_real")

ANTHROPIC, OPENAI = real.ANTHROPIC, real.OPENAI
YES, KOREAN, CHAT = ("the short yes gave a user decision with the user's answer first",
                     "the Korean decision gave a Korean item", "the small talk gave no item")


def ident(prefix, number):
    return "%s_%012d" % (prefix, number)


def quote(entry, speaker="user", words="words", start=0, end=None):
    return {"entry": entry, "speaker": speaker, "words": words, "start": start,
            "end": start + len(words) if end is None else end}


def item(number, quotes, kind="decision", status="current", title="제목", text="본문", **more):
    return dict(id=ident("i", number), kind=kind, status=status, title=title, text=text, quotes=list(quotes), **more)


def line(number, cites=(), part="decisions", text="한 줄"):
    return {"id": ident("s", number), "part": part, "pos": number, "text": text, "cites": list(cites)}


def layer(items=(), lines=(), candidates=(), waiting=0):
    return {"items": {value["id"]: value for value in items}, "lines": list(lines),
            "candidates": list(candidates), "waiting": waiting}


def candidate(first, second, status="open"):
    return {"id": "c_000000000001", "items": [first, second], "status": status}


def turns(count):
    """The entries of `count` turns, as `Home.turn` returns them."""
    return [{"prompt": ident("e", 2 * number + 1), "answer": ident("e", 2 * number + 2)} for number in range(count)]


def usage(call, result="ok", instructions=None, **more):
    return dict(call=call, result=result, instructions=instructions, **more)


def written(instructions, answer, failure=None):
    return {"instructions": instructions, "document": "<request/>", "failure": failure, "attempts": 1,
            "answer": answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)}


EMPTY = {"changes": [], "state": {"change": [], "add": [], "remove": []}}
KEPT = {"state": {"goal": [], "decisions": [], "progress": [], "blockers": [], "next": []}}


def request(entries, items=(), lines=(), kind="curate", instructions="curate-3", **body):
    """A request's body with a document that holds what the scripted server reads: lines, items and entries."""
    def escaped(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    parts = ['<request kind="%s" instructions="%s">' % (kind, instructions), "<state>"]
    parts += ['<line id="%s" part="decisions" cites="%s">%s</line>' % (name, " ".join(cites), escaped(text))
              for name, cites, text in lines]
    parts += ["</state>", '<items form="full">']
    parts += ['<item id="%s" kind="decision" speaker="user" date="2026-11-12"><title>%s</title></item>' % (
        name, escaped(title)) for name, title in items]
    parts += ["</items>", "<turns>"]
    parts += ['<entry id="%s" speaker="%s" at="2026-11-12T00:00:00.000Z">%s</entry>' % (name, speaker, escaped(text))
              for name, speaker, text in entries]
    parts += ["</turns>", "</request>"]
    return dict(body, messages=[{"role": "user", "content": "\n".join(parts)}])


class RefusalTests(unittest.TestCase):
    def run_main(self, arguments, **environment):
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        kept = {name: value for name, value in os.environ.items()
                if name not in ("CI", "GITHUB_ACTIONS", ANTHROPIC, OPENAI)}
        kept.update(environment)
        output = io.StringIO()
        with mock.patch.dict(os.environ, kept, clear=True), contextlib.redirect_stdout(output):
            code = real.main([base] + arguments)
        return code, output.getvalue(), Path(base)

    def test_it_never_calls_the_providers_in_ci(self):
        for name in ("CI", "GITHUB_ACTIONS"):
            with self.subTest(name):
                code, text, base = self.run_main([], **{name: "true", ANTHROPIC: "made-up"})
                self.assertEqual(code, 2)
                self.assertIn("never run in CI", text)
                self.assertEqual(list(base.iterdir()), [])

    def test_it_names_the_key_that_is_not_set_and_writes_nothing(self):
        code, text, base = self.run_main([])
        self.assertEqual(code, 2)
        self.assertIn(ANTHROPIC + " is not set", text)
        self.assertEqual(list(base.iterdir()), [])

    def test_a_repeat_below_one_and_a_limit_of_zero_are_refused(self):
        for arguments in (["--repeat", "0"], ["--limit", "0"]):
            with self.subTest(arguments):
                code, _, base = self.run_main(["--self-test"] + arguments)
                self.assertEqual(code, 2)
                self.assertEqual(list(base.iterdir()), [])

    def test_a_workflow_runs_it_as_a_self_test_only(self):
        lines = [(path.name, text) for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
                 for text in path.read_text(encoding="utf-8").splitlines() if "c2_real" in text and "run:" in text]
        self.assertTrue(lines)
        for name, text in lines:
            self.assertIn("c2_real.py", text, name)
            self.assertIn("--self-test", text, name)

    def test_a_run_stops_before_the_worker_once_the_cost_has_reached_the_limit(self):
        check = real.Check.__new__(real.Check)
        check.real, check.spent, check.options = True, 0.25, SimpleNamespace(limit=0.25)
        with self.assertRaises(real.Stopped) as stopped:
            check.afford()
        self.assertIn("0.2500 USD", str(stopped.exception))
        check.spent = 0.24
        check.afford()
        check.real, check.spent = False, 9.0  # A self-test's lines are the local server's made-up usage.
        check.afford()

    def test_a_case_s_outcome_is_the_worst_of_its_runs_and_stops_at_the_limit(self):
        check = real.Check.__new__(real.Check)
        check.report, check.options, check.keys = {"cases": {}}, SimpleNamespace(repeat=3), {}
        outcomes = iter(["pass", real.Stopped("the limit"), "never reached"])

        def runner(_, label):
            value = next(outcomes)
            if isinstance(value, Exception):
                raise value
            return {"outcome": value, "label": label}

        with mock.patch.dict(real.RUNNERS, {"TC-261": runner}):
            check.case("TC-261")
        entry = check.report["cases"]["TC-261"]
        self.assertEqual([run["outcome"] for run in entry["runs"]], ["pass", "not run"])
        self.assertEqual((entry["outcome"], entry["runs"][0]["label"]), ("not run", "tc-261-1"))

    def test_a_run_that_breaks_is_kept_with_a_key_masked_and_the_next_run_still_goes(self):
        check = real.Check.__new__(real.Check)
        check.report, check.options = {"cases": {}}, SimpleNamespace(repeat=2)
        check.keys = {ANTHROPIC: "REAL-KEY-VALUE"}
        outcomes = iter([RuntimeError("it broke with REAL-KEY-VALUE"), "recorded"])

        def runner(*_):
            value = next(outcomes)
            if isinstance(value, Exception):
                raise value
            return {"outcome": value}

        with mock.patch.dict(real.RUNNERS, {"TC-345": runner}):
            check.case("TC-345")
        entry = check.report["cases"]["TC-345"]
        self.assertEqual([run["outcome"] for run in entry["runs"]], ["crash", "recorded"])
        self.assertEqual(entry["outcome"], "crash")
        self.assertIn("<memory key>", entry["runs"][0]["crash"])
        self.assertNotIn("REAL-KEY-VALUE", entry["runs"][0]["crash"])


class EnvironmentTests(unittest.TestCase):
    def check(self, is_real):
        check = real.Check.__new__(real.Check)
        check.real, check.plugin = is_real, Path("plugin")
        check.keys = {ANTHROPIC: "REAL-ANTHROPIC", OPENAI: "REAL-OPENAI"}
        check.markers = {ANTHROPIC: "MARKER-ANTHROPIC", OPENAI: "MARKER-OPENAI"}
        check.server = SimpleNamespace(url="http://127.0.0.1:9")
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(home), True)
        return check, home

    def test_a_provider_s_run_gets_the_keys_and_the_network_variables_and_no_base_url(self):
        check, home = self.check(True)
        outer = {"HTTPS_PROXY": "http://127.0.0.1:1", "NO_PROXY": "api.example", "SSL_CERT_FILE": "/ca.pem",
                 "CORTHEX_MEMORY_ANTHROPIC_BASE_URL": "http://127.0.0.1:2", "UNRELATED_TOKEN": "x"}
        with mock.patch.dict(os.environ, outer):
            env = check.worker_environment(home, True)
        self.assertEqual((env[ANTHROPIC], env[OPENAI]), ("REAL-ANTHROPIC", "REAL-OPENAI"))
        self.assertEqual((env["HTTPS_PROXY"], env["NO_PROXY"], env["SSL_CERT_FILE"]),
                         ("http://127.0.0.1:1", "api.example", "/ca.pem"))
        self.assertNotIn("CORTHEX_MEMORY_ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CORTHEX_MEMORY_OPENAI_BASE_URL", env)
        self.assertNotIn("UNRELATED_TOKEN", env)
        self.assertEqual(env["HOME"], str(home))

    def test_a_seed_s_run_and_a_self_test_get_made_up_keys_and_the_local_server(self):
        for is_real, provider in ((True, False), (False, True), (False, False)):
            with self.subTest(real=is_real, provider=provider):
                check, home = self.check(is_real)
                with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:1"}):
                    env = check.worker_environment(home, provider)
                self.assertEqual((env[ANTHROPIC], env[OPENAI]), ("MARKER-ANTHROPIC", "MARKER-OPENAI"))
                self.assertEqual(env["CORTHEX_MEMORY_ANTHROPIC_BASE_URL"], "http://127.0.0.1:9")
                self.assertEqual(env["CORTHEX_MEMORY_OPENAI_BASE_URL"], "http://127.0.0.1:9")
                self.assertNotIn("HTTPS_PROXY", env)
                self.assertNotIn("REAL-ANTHROPIC", json.dumps(env))

    def test_a_hook_gets_its_host_s_variable_and_no_key(self):
        check, home = self.check(True)
        with mock.patch.dict(os.environ, {ANTHROPIC: "REAL-ANTHROPIC", OPENAI: "REAL-OPENAI"}):
            claude, codex = check.host_environment(home, "claude"), check.host_environment(home, "codex")
        self.assertEqual((claude["CLAUDECODE"], claude["CLAUDE_PLUGIN_ROOT"]), ("1", "plugin"))
        self.assertEqual(codex["PLUGIN_ROOT"], "plugin")
        self.assertNotIn("CLAUDECODE", codex)
        for env in (claude, codex):
            self.assertNotIn(ANTHROPIC, env)
            self.assertNotIn(OPENAI, env)

    def test_a_hook_s_input_has_the_fields_that_its_host_sends(self):
        contract = json.loads((FOLDER / "host-inputs.json").read_text(encoding="utf-8"))["hosts"]
        for host in ("claude", "codex"):
            for event, values in (("UserPromptSubmit", {"prompt": "질문"}), ("Stop", {"last_assistant_message": "답"})):
                with self.subTest(host=host, event=event):
                    value = real.host_input(host, event, Path("demo"), "session", "turn", **values)
                    self.assertEqual(set(value), set(contract[host]["events"][event]))
                    self.assertEqual(value["hook_event_name"], event)
                    for name, text in values.items():
                        self.assertEqual(value[name], text)
        self.assertEqual(real.host_input("claude", "Stop", Path("demo"), "s", "t", last_assistant_message="")["prompt_id"],
                         "t")
        self.assertIsNone(real.host_input("codex", "Stop", Path("demo"), "s", "t", last_assistant_message="")
                          ["transcript_path"])

    def test_the_files_that_hold_a_key_are_named(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(base), True)
        (base / "store/logs").mkdir(parents=True)
        (base / "store/logs/a.jsonl").write_text('{"text": "before KEY-ONE after"}', encoding="utf-8")
        (base / "store/b.json").write_text("nothing", encoding="utf-8")
        (base / "c.bin").write_bytes(b"\xff\xfeKEY-TWO")
        self.assertEqual(real.holding(base, ["KEY-ONE", "KEY-TWO"]), ["c.bin", "store/logs/a.jsonl"])
        self.assertEqual(real.holding(base, ["KEY-THREE"]), [])
        self.assertEqual(real.holding(base, []), [])


class ReadingTests(unittest.TestCase):
    def test_tc258_needs_each_kind_of_request_logged_ok_with_an_answer_that_fits(self):
        merged = {"merges": [], "conflicts": []}
        run = {"usage": [usage("curate", instructions="curate-3"), usage("consolidate", instructions="merge-2"),
                         usage("consolidate", instructions="state-2"), usage("embed-items", "failed")],
               "requests": [written("curate-3", EMPTY), written("merge-2", merged), written("state-2", KEPT)]}
        found = real.schemas(run)
        self.assertEqual(found["merge"], {"usage results": {"ok": 1}, "answers": 1, "answers that fit the schema": 1})
        self.assertTrue(real.accepted(found))
        for name, change in (("no state request", lambda value: (value["usage"].pop(2), value["requests"].pop(2))),
                             ("a failed merge", lambda value: value["usage"].append(
                                 usage("consolidate", "failed", "merge-2"))),
                             ("an answer that does not fit", lambda value: value["requests"].__setitem__(
                                 0, written("curate-3", {"changes": []}))),
                             ("an answer that is no JSON", lambda value: value["requests"].__setitem__(
                                 1, written("merge-2", "not JSON"))),
                             ("a request without a usage line", lambda value: value["usage"].pop(0))):
            with self.subTest(name):
                other = {"usage": list(run["usage"]), "requests": list(run["requests"])}
                change(other)
                self.assertFalse(real.accepted(real.schemas(other)))

    def test_an_answer_fits_by_its_own_kind_s_schema(self):
        self.assertTrue(real.fits(written("state-2", KEPT)))
        self.assertFalse(real.fits(written("curate-3", KEPT)))
        self.assertFalse(real.fits(written("merge-2", EMPTY)))

    def test_the_answers_of_a_kind_leave_out_failed_requests_and_what_is_no_json(self):
        rows = [written("curate-3", EMPTY), written("curate-3", "", "max-tokens"), written("curate-3", "{"),
                written("state-2", KEPT)]
        self.assertEqual(real.answers(rows), [EMPTY])
        self.assertEqual(real.answers(rows, "state"), [KEPT])
        self.assertEqual(real.answers(rows, "merge"), [])

    def test_tc259_needs_the_result_limit_and_the_code_max_tokens_on_each_curate_line(self):
        before, after = layer(waiting=2), layer(waiting=2)
        record = {"recent": [{"kind": "curate", "result": "failed", "error": "max-tokens", "at": "now"}],
                  "failures": {"count": 1}}
        run = {"usage": [usage("curate", "limit", "curate-3", error="max-tokens", input=900, output=64, cost=0.1)]}
        found = real.cut(run, before, after, record)
        self.assertTrue(found["logged with the result limit and the code max-tokens"])
        self.assertEqual(found["the curation record's latest attempt"],
                         {"kind": "curate", "result": "failed", "error": "max-tokens"})
        self.assertEqual((found["failed attempts counted"], found["turns left to curate"]), (1, [2, 2]))
        for name, rows in (("an answer that was not cut", [usage("curate", "ok", "curate-3")]),
                           ("another failure", [usage("curate", "failed", "curate-3", error="api_error")]),
                           ("a limit without its code", [usage("curate", "limit", "curate-3")]),
                           ("no request", [])):
            with self.subTest(name):
                self.assertFalse(real.cut({"usage": rows}, before, after, {})[
                    "logged with the result limit and the code max-tokens"])

    def test_tc261_reads_the_yes_the_korean_item_and_the_small_talk(self):
        proposal, yes, korean, small = ids = turns(4)
        agreed = item(1, [quote(yes["prompt"], words="응"), quote(proposal["answer"], "agent", "제안")])
        decided = item(2, [quote(korean["prompt"])], title="릴리스 노트", text="두 언어로 쓴다.")
        found = real.inside(layer([agreed, decided])["items"], ids)
        self.assertEqual([found[name] for name in (YES, KOREAN, CHAT)], [True, True, True])
        self.assertTrue(found["the proposal's words follow as its next quote"])
        cases = (
            ("the proposal first", [item(1, [quote(proposal["answer"], "agent"), quote(yes["prompt"])]), decided],
             [False, True, True]),
            ("a fact for the yes", [item(1, [quote(yes["prompt"])], kind="fact"), decided], [False, True, True]),
            ("a withdrawn decision", [item(1, [quote(yes["prompt"])], status="withdrawn"), decided],
             [False, True, True]),
            ("an English item", [agreed, item(2, [quote(korean["prompt"])], title="Release notes", text="Two.")],
             [True, False, True]),
            ("an English text", [agreed, item(2, [quote(korean["prompt"])], title="릴리스 노트", text="Two.")],
             [True, False, True]),
            ("an item of the small talk", [agreed, decided, item(3, [quote(small["answer"], "agent")], kind="fact")],
             [True, True, False]),
            ("nothing saved", [], [False, False, True]))
        for name, items, expected in cases:
            with self.subTest(name):
                found = real.inside(layer(items)["items"], ids)
                self.assertEqual([found[key] for key in (YES, KOREAN, CHAT)], expected)
        alone = real.inside(layer([item(1, [quote(yes["prompt"])]), decided])["items"], ids)
        self.assertEqual((alone[YES], alone["the proposal's words follow as its next quote"]), (True, False))

    def outside(self, extra=(), lines=None, documents=None, stored=None, holding=(), seeded="current"):
        ids = turns(5)
        pasted = "요약해 주세요.\n<pasted_content id=\"p1\">\n결정: 평문으로 둔다.\n</pasted_content id=\"p1\">"
        seed = item(1, [quote(ident("e", 90))], title="점프 호스트")
        before = layer([seed], [line(1, [seed["id"]], text="점프 호스트를 거친다.")])
        after = layer([dict(seed, status=seeded)] + list(extra),
                      before["lines"] if lines is None else lines)
        entries = {ids[2]["prompt"]: {"text": pasted},
                   ids[4]["prompt"]: {"text": "값을 붙입니다. [redacted:anthropic-key] 보내 주세요."
                                      if stored is None else stored}}
        documents = ["<request>[redacted:anthropic-key]</request>"] if documents is None else documents
        return ids, pasted, real.outside(before, after, ids, entries, "sk-made-up", documents, list(holding))

    def test_tc262_holds_when_nothing_was_followed_quoted_or_sent(self):
        _, _, found = self.outside()
        self.assertEqual([found[name] for name in real.OUTSIDE_NEEDS], [True] * len(real.OUTSIDE_NEEDS))
        self.assertEqual(found["files of the home that hold the key"], [])

    def test_tc262_reads_each_thing_that_must_not_happen(self):
        ids, pasted, _ = self.outside()
        inside = pasted.index("결정")
        cases = (
            ("a decision with an instruction's title", dict(extra=[item(2, [quote(ids[0]["prompt"])],
                                                                         title=real.OBEY[0])]), 0),
            ("the English instruction's title", dict(extra=[item(2, [quote(ids[1]["prompt"])],
                                                                 title="Saved: " + real.OBEY[1])]), 0),
            ("the seeded decision withdrawn", dict(seeded="withdrawn"), 1),
            ("the seeded line gone", dict(lines=[]), 2),
            ("the seeded line reworded", dict(lines=[line(1, text="다른 말")]), 2),
            ("a decision quoting the pasted lines", dict(extra=[item(2, [quote(ids[2]["prompt"], start=inside)])]), 3),
            ("a decision whose second quote is pasted", dict(extra=[item(2, [
                quote(ids[2]["answer"], "agent"), quote(ids[2]["prompt"], start=inside)])]), 3),
            ("the key in a request", dict(documents=["<request>sk-made-up</request>"]), 4),
            ("no redaction mark in any request", dict(documents=["<request>값</request>"]), 4),
            ("no request at all", dict(documents=[]), 4),
            ("the key in the raw log", dict(stored="값을 붙입니다. sk-made-up 보내 주세요."), 5),
            ("no mark in the raw log", dict(stored="값을 붙입니다. 보내 주세요."), 5))
        for name, options, failed in cases:
            with self.subTest(name):
                _, _, found = self.outside(**options)
                self.assertEqual([found[key] for key in real.OUTSIDE_NEEDS],
                                 [number != failed for number in range(len(real.OUTSIDE_NEEDS))])

    def test_tc262_lets_a_fact_name_an_instruction_and_a_decision_quote_the_words_before_the_paste(self):
        ids, _, _ = self.outside()
        noted = item(2, [quote(ids[0]["prompt"])], kind="fact", title="지시문: " + real.OBEY[0])
        asked = item(3, [quote(ids[2]["prompt"], words="요약해 주세요.")])
        _, _, found = self.outside(extra=[noted, asked], holding=["home/x.json"])
        self.assertEqual([found[name] for name in real.OUTSIDE_NEEDS], [True] * len(real.OUTSIDE_NEEDS))
        self.assertEqual([value["id"] for value in found["items that quote an instruction"]], [noted["id"]])
        self.assertEqual([value["id"] for value in found["items that quote Claude Code's pasted prompt"]],
                         [asked["id"]])
        self.assertEqual(found["files of the home that hold the key"], ["home/x.json"])

    def test_tc345_says_which_lines_the_answer_names_and_which_stay(self):
        old = item(3, [quote(ident("e", 5))], title="포트 8443")
        others = [item(number, [quote(ident("e", number))]) for number in (1, 2, 4, 5)]
        lines = [line(number, [ident("i", number)], text="줄 %d" % number) for number in range(1, 6)]
        before = layer([old] + others, lines)
        new = item(6, [quote(ident("e", 11))], title="포트 9443")
        changed = [dict(value) for value in lines]
        changed[2] = dict(changed[2], text="포트는 9443", cites=[new["id"]])
        after = layer([dict(old, status="superseded", superseded_by=new["id"]), new] + others, changed)
        answer = {"changes": [{"action": "replace", "kind": "decision", "targets": [old["id"]], "conflicts": [],
                               "title": "포트 9443"}],
                  "state": {"change": [{"line": lines[2]["id"]}], "add": [], "remove": []}}
        found = real.one_fact(before, after, answer, old["id"])
        self.assertEqual(found["the affected line"], [lines[2]["id"]])
        self.assertTrue(found["the answer names the affected line"])
        self.assertEqual(found["unaffected lines that the answer names"], [])
        self.assertEqual(found["unaffected lines that stay as they were"], "4 of 4")
        self.assertEqual((found["lines before"], found["lines after"], found["the old fact's item"]),
                         (5, 5, "superseded"))
        self.assertEqual(found["changes of the answer"][0]["targets"], [old["id"]])
        self.assertEqual((found["the affected line after"], found["line edits that the package dropped, by reason"],
                          found["IDs that the line edits cite and the request does not carry"]),
                         ("changed", "none", []))

        # An edit that cites an ID of the answer's own making is dropped, and the decision line goes with its item.
        answer["state"]["change"] = [{"line": lines[2]["id"], "cites": [ident("i", 99), ident("e", 11)]}]
        gone = layer([dict(old, status="superseded", superseded_by=new["id"]), new] + others,
                     [value for value in lines if value is not lines[2]])
        record = {"recent": [{"kind": "curate", "result": "ok", "edit_reasons": {"cites": 1, "text": 2}},
                             {"kind": "curate", "result": "ok", "edit_reasons": {"line": 4}}]}
        found = real.one_fact(before, gone, answer, old["id"], record, '<entry id="%s">' % ident("e", 11))
        self.assertTrue(found["the answer names the affected line"])
        self.assertEqual((found["lines after"], found["the affected line after"]), (4, "gone"))
        self.assertEqual(found["line edits that the package dropped, by reason"], "cites: 1, text: 2")
        self.assertEqual(found["IDs that the line edits cite and the request does not carry"], [ident("i", 99)])
        self.assertEqual(found["unaffected lines that stay as they were"], "4 of 4")

        answer["state"] = {"change": [{"line": lines[0]["id"]}], "add": [{"text": "새 줄"}],
                           "remove": [{"line": lines[4]["id"]}]}
        reworded = [dict(lines[0], text="다시 쓴 줄"), lines[1], lines[2], lines[3]]
        found = real.one_fact(before, layer([old] + others, reworded), answer, old["id"])
        self.assertFalse(found["the answer names the affected line"])
        self.assertEqual(found["unaffected lines that the answer names"], [lines[0]["id"], lines[4]["id"]])
        self.assertEqual(found["unaffected lines that stay as they were"], "2 of 4")
        self.assertEqual(found["lines that the answer adds"], ["새 줄"])
        self.assertEqual(found["the old fact's item"], "current")

        found = real.one_fact(before, before, None, old["id"])
        self.assertFalse(found["the answer names the affected line"])
        self.assertEqual(found["unaffected lines that stay as they were"], "4 of 4")
        self.assertEqual(found["the affected line after"], "as it was")
        self.assertEqual(real.one_fact(before, before, None, others[0]["id"], {"recent": []})["the affected line after"],
                         "as it was")
        self.assertEqual(real.became({}, {}, []), "no line cited the item")

    def test_a_line_whose_citations_changed_is_not_as_it_was(self):
        old = item(1, [quote(ident("e", 1))])
        other = item(2, [quote(ident("e", 2))])
        lines = [line(1, [old["id"]]), line(2, [other["id"]])]
        moved = [lines[0], dict(lines[1], cites=[old["id"]])]
        found = real.one_fact(layer([old, other], lines), layer([old, other], moved), EMPTY, old["id"])
        self.assertEqual(found["unaffected lines that stay as they were"], "0 of 1")

    def test_tc356_says_what_became_of_each_rule(self):
        later = turns(2)
        first, second = item(1, [quote(ident("e", 91))]), item(2, [quote(ident("e", 92))])
        before = layer([first, second])
        newer = item(3, [quote(later[0]["prompt"])])
        told = item(4, [quote(later[1]["answer"], "agent")], kind="fact")
        cases = (
            ("replaced on the user's words",
             layer([dict(first, status="superseded", superseded_by=newer["id"]), second, newer]),
             "the later statement replaced the rule", "nothing was saved for the later statement", True),
            ("a candidate for each",
             layer([first, second, newer, told],
                   candidates=[candidate(first["id"], newer["id"]), candidate(told["id"], second["id"])]),
             "a conflict candidate, and both stay current", "a conflict candidate, and both stay current", True),
            ("both without a candidate", layer([first, second, newer, told]),
             "both stay current, without a candidate", "both stay current, without a candidate", True),
            ("a dismissed candidate is not open",
             layer([first, second, newer], candidates=[candidate(first["id"], newer["id"], "dismissed")]),
             "both stay current, without a candidate", "nothing was saved for the later statement", True),
            ("nothing saved", layer([first, second]), "nothing was saved for the later statement",
             "nothing was saved for the later statement", True),
            ("the agent's words replaced the user's rule",
             layer([first, dict(second, status="superseded", superseded_by=told["id"]), told]),
             "nothing was saved for the later statement", "the later statement replaced the rule", False))
        for name, after, user, agent, rests in cases:
            with self.subTest(name):
                found = real.disagreement(before, after, EMPTY, [first["id"], second["id"]], later)
                self.assertEqual((found["the user's later rule"], found["the agent's statement"],
                                  found["each replacement rests on the user's words"]), (user, agent, rests))
        found = real.disagreement(before, cases[0][1], {"changes": [{"action": "replace", "kind": "decision",
                                                                    "targets": [first["id"]], "conflicts": [],
                                                                    "title": "새 규칙", "text": "..."}]},
                                  [first["id"], second["id"]], later)
        self.assertEqual(found["replacements of the user's rules"],
                         [{"item": first["id"], "by": newer["id"], "speaker of the deciding quote": "user"}])
        self.assertEqual(found["changes of the answer"], [{"action": "replace", "kind": "decision",
                                                           "targets": [first["id"]], "conflicts": [],
                                                           "title": "새 규칙"}])

    def test_a_run_is_kept_without_its_documents_and_answers(self):
        run = {"exit": 0, "usage": [usage("curate")], "failures": [],
               "requests": [written("curate-3", "답 text"), written("state-2", "", "max-tokens")]}
        run["requests"][0]["document"] = "<request>문서</request>"
        kept = real.trimmed(run)
        self.assertEqual(kept["requests"][0], {"instructions": "curate-3", "failure": None, "attempts": 1,
                                               "document_bytes": len("<request>문서</request>".encode("utf-8")),
                                               "answer_bytes": len("답 text".encode("utf-8"))})
        self.assertEqual(kept["requests"][1]["failure"], "max-tokens")
        self.assertNotIn("문서", json.dumps(kept, ensure_ascii=False))
        self.assertIn("document", run["requests"][0])

    def test_the_cost_is_the_sum_of_the_provider_s_usage_lines_by_call(self):
        check = real.Check.__new__(real.Check)
        check.usage, check.spent = [], 0.0
        check.account({"usage": [usage("curate", input=100, output=10, cost=0.5),
                                 usage("curate", "limit", input=50, output=5, cost=0.25, error="max-tokens")]}, True)
        check.account({"usage": [usage("curate", input=7, output=7, cost=9.0)]}, False)  # A seed's lines.
        check.account({"usage": [usage("embed-items", "failed", error="insufficient_quota", cost=0.0)]}, True)
        found = check.cost()
        self.assertEqual(found["calls"]["curate"], {"requests": 2, "results": {"ok": 1, "limit": 1}, "input": 150,
                                                    "output": 15, "usd": 0.75})
        self.assertEqual(found["calls"]["embed-items"]["results"], {"failed: insufficient_quota": 1})
        self.assertEqual((found["usd"], found["requests"]), (0.75, 3))

    def test_a_leak_is_a_key_in_a_file_in_the_report_or_in_a_local_request(self):
        self.assertFalse(real.leaked({"files_with_key": [], "local_requests_with_key": 0}))
        for report in ({"files_with_key": ["a"]}, {"key_in_report": True}, {"local_requests_with_key": 1}):
            self.assertTrue(real.leaked(report))


class ScriptedTests(unittest.TestCase):
    def setUp(self):
        self.server = real.Scripted()
        self.addCleanup(self.server.close)

    def test_a_seed_turn_gets_its_script_s_change_and_line_and_the_answer_fits(self):
        turn = real.SEED_345[2]
        entry, reply = ident("e", 1), ident("e", 2)
        answer = self.server.answer(request([(entry, "user", turn.prompt), (reply, "agent", turn.reply)]))
        curator_answers.decode(answer)
        self.assertEqual(answer["changes"], [{"action": "add", "targets": [], "kind": "decision",
                                              "quotes": [{"entry": entry, "words": turn.prompt}],
                                              "title": turn.script["title"], "text": turn.script["text"],
                                              "conflicts": []}])
        self.assertEqual(answer["state"]["add"], [{"part": "decisions", "after": "", "text": turn.script["text"],
                                                   "cites": [], "changes": [1]}])

    def test_a_turn_without_a_script_an_agent_s_entry_and_other_words_get_nothing(self):
        small = real.INSIDE_261[3]
        answer = self.server.answer(request([(ident("e", 1), "user", small.prompt),
                                             (ident("e", 2), "agent", real.SEED_345[2].prompt),
                                             (ident("e", 3), "user", "스크립트에 없는 말")]))
        self.assertEqual(answer, EMPTY)

    def test_a_short_yes_quotes_the_user_first_and_then_the_proposal_before_it(self):
        proposal, yes = real.INSIDE_261[0], real.INSIDE_261[1]
        entries = [(ident("e", 1), "user", proposal.prompt), (ident("e", 2), "agent", proposal.reply),
                   (ident("e", 3), "user", yes.prompt), (ident("e", 4), "agent", yes.reply)]
        answer = self.server.answer(request(entries))
        curator_answers.decode(answer)
        self.assertEqual(answer["changes"][0]["quotes"], [{"entry": ident("e", 3), "words": "응"},
                                                          {"entry": ident("e", 2), "words": proposal.reply}])

    def test_a_changed_fact_replaces_its_item_and_changes_only_the_lines_that_cite_it(self):
        old, other = ident("i", 1), ident("i", 2)
        lines = [(ident("s", 1), [old], "포트는 8443"), (ident("s", 2), [other], "CSV만 읽는다")]
        items = [(old, real.SEED_345[2].script["title"]), (other, real.SEED_345[1].script["title"])]
        answer = self.server.answer(request([(ident("e", 9), "user", real.CHANGE_345.prompt)], items, lines))
        curator_answers.decode(answer)
        self.assertEqual((answer["changes"][0]["action"], answer["changes"][0]["targets"]), ("replace", [old]))
        self.assertEqual([edit["line"] for edit in answer["state"]["change"]], [ident("s", 1)])
        self.assertEqual((answer["state"]["add"], answer["state"]["remove"]), ([], []))

    def test_a_rule_that_disagrees_names_the_earlier_rule_as_a_conflict(self):
        squash = ident("i", 1)
        items = [(squash, real.SEED_356[0].script["title"]), (ident("i", 2), real.SEED_356[1].script["title"])]
        answer = self.server.answer(request([(ident("e", 9), "user", real.LATER_356[0].prompt)], items))
        curator_answers.decode(answer)
        self.assertEqual((answer["changes"][0]["action"], answer["changes"][0]["targets"],
                          answer["changes"][0]["conflicts"]), ("add", [], [squash]))

    def test_a_merge_request_merges_the_two_seeded_decisions_and_a_state_request_keeps_the_state(self):
        items = [(ident("i", 2), real.SEED_258[1].script["title"]), (ident("i", 1), real.SEED_258[0].script["title"]),
                 (ident("i", 3), real.SEED_258[2].script["title"])]
        answer = self.server.answer(request([], items, kind="merge", instructions="merge-2"))
        curator_answers.decode(answer, curator_answers.merge_schema())
        self.assertEqual(answer["merges"][0]["items"], [ident("i", 1), ident("i", 2)])
        self.assertEqual(answer["merges"][0]["quotes"], [{"item": ident("i", 1), "number": 1},
                                                         {"item": ident("i", 2), "number": 1}])
        alone = self.server.answer(request([], items[:1], kind="merge", instructions="merge-2"))
        self.assertEqual(alone, {"merges": [], "conflicts": []})
        kept = self.server.answer(request([], kind="state", instructions="state-2"))
        curator_answers.decode(kept, curator_answers.state_schema())
        self.assertEqual(kept, KEPT)

    def test_a_request_for_few_tokens_gets_an_answer_that_was_cut(self):
        turn = real.CUT_259[0]
        body = request([(ident("e", 1), "user", turn.prompt)], max_tokens=real.CUT)
        answer = self.server.answer(body)
        self.assertIsInstance(answer, bytes)
        self.assertIn(b'"stop_reason": "max_tokens"', answer)
        self.assertNotIn(b"content_block_delta", answer)
        whole = self.server.answer(dict(body, max_tokens=64000))
        self.assertEqual(len(whole["changes"]), 1)

    def test_every_scripted_turn_has_its_own_prompt(self):
        prompts = [turn.prompt for turn in real.TURNS]
        self.assertEqual(len(prompts), len(set(prompts)))
        self.assertEqual(set(self.server.scripts), {turn.prompt for turn in real.TURNS if turn.script})
        for turn in real.TURNS:
            self.assertIn(turn.host, ("claude", "codex"))

    def test_the_made_up_key_s_turn_is_redacted_by_the_package_and_has_no_script(self):
        from memory_lib import redaction
        key = "sk-ant-" + "madeup" + "0" * 32
        turn = real.key_turn(key)
        self.assertIsNone(turn.script)
        self.assertIn(key, turn.prompt)
        kind, pattern = redaction.COMPILED[1]
        self.assertEqual(kind, "anthropic-key")
        self.assertEqual(pattern.search(turn.prompt).group(0), key)


class SelfTestRun(unittest.TestCase):
    def test_two_cases_run_to_their_end_against_the_local_server_even_in_ci(self):
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        environment = dict(os.environ, CI="true")
        environment.update({ANTHROPIC: "ENVIRONMENT-ANTHROPIC-KEY-0001", OPENAI: "ENVIRONMENT-OPENAI-KEY-0001"})
        done = subprocess.run([sys.executable, str(FOLDER / "c2_real.py"), base, "--self-test",
                               "--case", "TC-259", "--case", "TC-262"],
                              env=environment, capture_output=True, timeout=900)
        output = done.stdout.decode("utf-8", "replace")
        self.assertEqual((done.returncode, done.stderr.decode("utf-8", "replace")), (0, ""), output)
        self.assertIn(real.SELF_TEST, output.splitlines()[0])
        out = Path(base) / "c2-real"
        text = (out / "report.json").read_text(encoding="utf-8")
        report = json.loads(text)
        self.assertTrue(report["self_test"])
        self.assertEqual(report["provider"], real.SELF_TEST)
        self.assertEqual({name: entry["outcome"] for name, entry in report["cases"].items()},
                         {"TC-259": "pass", "TC-262": "pass"})
        self.assertEqual((report["files_with_key"], report["local_requests_with_key"]), ([], 0))
        self.assertNotIn("key_in_report", report)
        self.assertGreater(report["local_requests"], 0)
        self.assertEqual(report["keys"], {ANTHROPIC: "present", OPENAI: "present"})
        for secret in ("ENVIRONMENT-ANTHROPIC-KEY-0001", "ENVIRONMENT-OPENAI-KEY-0001", "sk-ant-madeup"):
            self.assertNotIn(secret, text)
        cut = report["cases"]["TC-259"]["runs"][0]
        self.assertEqual(cut["observed"]["turns left to curate"], [2, 2])
        self.assertEqual(cut["observed"]["the next run, with the package's own max_tokens"]["turns left to curate"], 0)
        self.assertEqual([run["provider"] for run in report["cases"]["TC-262"]["runs"][0]["runs"]],
                         [real.SEED, real.SELF_TEST])
        requests = [json.loads(line) for line in (out / "tc-262-1/requests.jsonl").read_text(
            encoding="utf-8").splitlines()]
        self.assertEqual([row["instructions"] for row in requests], ["curate-3", "curate-3"])
        self.assertIn("[redacted:anthropic-key]", requests[1]["document"])
        self.assertIn(real.PASTED[1], requests[1]["document"])


if __name__ == "__main__":
    unittest.main()
