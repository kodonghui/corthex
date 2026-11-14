"""Checks the optional NEXUS workflow of the core skills: one text in every skill, and the rules it keeps."""

import unittest

from _common import PLUGINS, read_text

SKILLS = PLUGINS / "corthex" / "skills"
# The entry skill and the stage skills, each with its own copy, since a skill's links stay inside its folder.
OWNERS = [
    "corthex", "corthex-build", "corthex-contract", "corthex-define",
    "corthex-discover", "corthex-present", "corthex-record", "corthex-screen",
]


def section(text, heading):
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def workflow():
    return read_text(SKILLS / "corthex" / "references" / "nexus-work.md")


class NexusWorkTest(unittest.TestCase):
    def test_every_skill_carries_the_same_workflow(self):
        copies = sorted(path.parent.parent.name for path in SKILLS.glob("*/references/nexus-work.md"))
        self.assertEqual(copies, sorted(OWNERS))
        first = workflow()
        for skill in OWNERS:
            with self.subTest(skill=skill):
                self.assertEqual(read_text(SKILLS / skill / "references" / "nexus-work.md"), first)

    def test_every_skill_points_to_it_in_the_same_words(self):
        blocks = {skill: section(read_text(SKILLS / skill / "SKILL.md"), "## Optional NEXUS work") for skill in OWNERS}
        first = blocks[OWNERS[0]]
        self.assertIn("(references/nexus-work.md)", first)
        self.assertIn("hold in every session, also in one without the hub", first)
        self.assertIn("say once, in one line, what is missing for a project that is expected on a NEXUS server", first)
        for skill, block in blocks.items():
            with self.subTest(skill=skill):
                self.assertEqual(block, first)

    def test_some_rules_hold_without_the_hub(self):
        text = workflow()
        intro = text[:text.index("\n## ")]
        for rule in (
            "Local stage work does not require the hub, a service token or a server.",
            "Three sections need no hub and no token",
            "also in a session that cannot send",
            "when the hub's `can-send` answers `expected`",
            "when the project's settings say `on_nexus` or the push list names the project, or when the user says so",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, intro)
        for heading in ("## Ask for a checkpoint", "## Tell the user where the work stands",
                        "## Walk a NEXUS server's pages in a browser"):
            with self.subTest(heading=heading):
                self.assertIn(heading[3:], intro)
                self.assertEqual(text.count("\n" + heading + "\n"), 1)

    def test_a_checkpoint_request_has_one_form(self):
        ask = section(workflow(), "## Ask for a checkpoint")
        for rule in (
            "one part's stage in one request, never for several stages",
            "asked one at a time, the earliest stage first",
            "at most ten lines and 1,200 characters in all",
            "in the user's language and in plain words",
            "one thing to look at first, and only one",
            "Ask the checkpoint's question alone",
            "something that the user can press",
            "A picture of a screen alone is not enough",
            "at which widths and in which states you looked yourself, and which you did not",
            "needs no new permission and shows project data to nobody else",
            "Showing a screen releases nothing",
            "Make the request in the session.",
            "`comment PROJECT --stage STAGE [--part PART] --asks checkpoint --look-first ID|URL|stage`",
            "`--look-first` takes the item's trace ID, the `https` address, or the word `stage`",
            "without `--item`",
            "`refused` with `read the to-do first`",
            "The remark `sent-as-reply`",
            "A part's stage has one open request at a time",
            "The remark `server-older`",
            "Do not reword it to get it through",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, ask)

    def test_the_user_is_told_where_the_work_stands(self):
        tell = section(workflow(), "## Tell the user where the work stands")
        for rule in (
            "Say each of these once",
            "A notice asks nothing.",
            "A plan of tasks is agreed on its own, at stage 10's checkpoint",
            "no task of it starts before the user passes that checkpoint",
            "When building starts (stage 11), say so in one line",
            "Each time a stage passes or a group of tasks ends, send one short notice",
            "in at most ten lines, and one thing to look at first",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, tell)

    def test_a_browser_walk_leaves_the_users_presses_to_the_user(self):
        walk = section(workflow(), "## Walk a NEXUS server's pages in a browser")
        for rule in (
            "every brief for a walk of NEXUS pages",
            "A project is synthetic only when the brief names it as made for the test",
            "On a real project the walk only reads",
            "passing or withdrawing a checkpoint, accepting or dismissing a proposal, taking a recommendation, "
            "marking a comment answered, removing a project",
            "It leaves no comment and no reply there either",
            "reports what the page offers, and stops",
            "A brief that names no synthetic project makes the whole walk read-only, and the report says so",
            "stop and report at once what it changed",
            "Do not undo it yourself",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, walk)
        testers = read_text(SKILLS / "corthex-build" / "references" / "browser-agents.md")
        self.assertIn("keep to the walk rules in [nexus-work.md](nexus-work.md)", testers)

    def test_the_agent_never_turns_sending_on(self):
        text = workflow()
        for rule in (
            "Never enable sending, register a new address or add a project to this list on your own.",
            "never print them or pass them as command arguments",
            "obtain the user's confirmation, even if the project is already allowlisted",
            "Never set the address, the push list or the token yourself, in a profile, in a session's environment or "
            "in a repository, and never ask for a token's value.",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_a_session_says_once_when_it_cannot_send(self):
        start = section(workflow(), "## At a session's start")
        for rule in (
            "1. Run `hub.py can-send PROJECT`. It contacts no server, sends nothing and needs no session label.",
            "the names of the settings or variables that are not set, never a value",
            "`can_send` is false and `expected` is true: tell the user once in this session, in one line",
            "that these are their own settings",
            "Say nothing again for this project, also when another skill starts",
            "`expected` is false: say nothing, and continue local work",
            "read `on_nexus` in `.corthex/project.json` yourself",
            "the same one line names the hub as missing",
            "The hub does not know `can-send`: it is older than these rules. Say so once",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, start)
        # The steps stay in order, and the session asks before it reads.
        steps = [start.index("\n%d. " % number) for number in range(1, 8)]
        self.assertEqual(steps, sorted(steps))
        self.assertLess(start.index("can-send PROJECT"), start.index("todo PROJECT --session SESSION --json"))

    def test_the_to_do_is_read_again(self):
        again = section(workflow(), "## Read the to-do again")
        for rule in (
            "A session that cannot send reads nothing, and says nothing again.",
            "Where a unit of stage work starts or ends, run `todo PROJECT --session SESSION --if-due --json`",
            "more than a day old",
            "Before each checkpoint request, run `todo` without `--if-due`",
            "or name them in the request as open",
            "tell the user only what the result's `new` holds",
            "When nothing is new, say nothing about it",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, again)

    def test_the_first_push_and_a_removal_wait_for_the_user(self):
        text = workflow()
        for rule in (
            "run `push PROJECT --dry-run` and `push PROJECT --first`",
            "add `--first` only after the user's yes for that one project, never for several projects and never on "
            "your own",
            "A project that the user removed is a first push again",
            "Removing a project from the server is the user's own act. `remove PROJECT` sends no removal",
            "Never open that address to press the removal yourself",
            "A server from before the design revision has no project's data yet",
            "shows that server's dry run instead, with the remark `server-older`, and gives no address",
            "Until the server of the revision runs, the project cannot be removed",
            "never remove it another way, such as with an older hub",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_the_project_settings_say_that_a_project_is_expected(self):
        row = next(line for line in read_text(SKILLS / "corthex" / "references" / "project.md").splitlines()
                   if line.startswith("| `on_nexus` |"))
        for rule in (
            "| boolean | Optional.",
            "no address",
            "It is data: it enables nothing, sends nothing and is never a permission to push",
            "Any other form counts as not set",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, row)


if __name__ == "__main__":
    unittest.main()
