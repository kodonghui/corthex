"""Checks the NEXUS workflow of the core skills: one text in every skill, and the rules it keeps."""

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
        blocks = {skill: section(read_text(SKILLS / skill / "SKILL.md"), "## Work in NEXUS") for skill in OWNERS}
        first = blocks[OWNERS[0]]
        self.assertIn("(references/nexus-work.md)", first)
        self.assertIn("NEXUS is where the user reads every stage, talks about its items and passes its checkpoints", first)
        self.assertIn("ask once to put it there", first)
        self.assertIn("Merge a stage's draft of documents and push it before its checkpoint request", first)
        self.assertIn("give the stage's NEXUS address whenever you show its work", first)
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
            "Make the request in the session, with the stage's NEXUS address as Show the work in NEXUS says.",
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

    def test_a_draft_of_documents_is_merged_before_its_request(self):
        text = workflow()
        merge = section(text, "## Merge a draft before its checkpoint request")
        self.assertLess(text.index("## Merge a draft before its checkpoint request"),
                        text.index("## Ask for a checkpoint"))
        for rule in (
            "For a project that is expected on a NEXUS server",
            "when its pull request holds documents only: the stage's sources and its record",
            "as `in_progress`, with a next action that says that the stage waits for its checkpoint",
            "A merged file is not a finished stage",
            "Once the project's checks pass, merge the pull request into the default branch",
            "Where the project's rules ask the user before a merge, ask once, or follow the user's standing answer",
            "because the session cannot send, the project's first push waits for the user's yes (`--first`)",
            "the server refused the push or no server answered, say in the request's lines that NEXUS does not show "
            "the draft yet",
            "Only then make the checkpoint request",
            "A request that waits in the hub's outbox stands in the session meanwhile",
            "is another pull request",
            "nothing is taken back from the default branch for that alone",
            "The checks fail, or the user's answer about the merge is still open: nothing is merged, and no request "
            "is made",
            "also changes code, settings or anything that a merge would release: this section does not hold",
            "The project is not expected on a NEXUS server: this section does not hold",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, merge)
        steps = [merge.index("\n%d. " % number) for number in range(1, 6)]
        self.assertEqual(steps, sorted(steps))

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
            "Never set the token, in a profile, in a session's environment or in a repository, and never ask for its "
            "value.",
            "Change the address or the push list only on the user's word: an address that they give, and one project "
            "at a time as Put a project on NEXUS says, each shown before it is written.",
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
            "when `missing` is only `nexus.push`, make that line the offer to add the project on this device, as Put a "
            "project on NEXUS says",
            "Say nothing again for this project, also when another skill starts",
            "`expected` is false: when the profile names a NEXUS server and the project's settings have no "
            "`on_nexus`, ask once as Put a project on NEXUS says. Otherwise say nothing, and continue local work.",
            "when it is not set and the profile names a NEXUS server, ask once as Put a project on NEXUS says",
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
            "the entry skill asks the user once whether to put the project on NEXUS and writes the answer here",
            "Any other form counts as not set",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, row)

    def test_a_project_is_put_on_nexus_once(self):
        text = workflow()
        put = section(text, "## Put a project on NEXUS")
        self.assertLess(text.index("## Put a project on NEXUS"), text.index("## At a session's start"))
        for rule in (
            "When the profile names a NEXUS server (`nexus.url`) and a project's settings have no `on_nexus` while the "
            "push list does not name the project, ask the user once",
            "Recommend yes, and say in plain words what it means",
            "Ask nothing when the profile names no server, so that a user without NEXUS hears nothing of it.",
            "Write the answer in the project settings as `on_nexus`, `true` or `false`",
            "A `false` keeps the project off NEXUS until the user asks again",
            "A yes in the user's own words for this project lets you add its name to the profile's `nexus.push`, after "
            "showing the change.",
            "Its first push still has a yes of its own: once the default branch holds the project's work, show `push "
            "PROJECT --dry-run`, ask, and send it with `--first` on that yes",
            "One yes covers one project; never add another one with it.",
            "The project's settings travel with its repository, but each device has its own push list.",
            "offer once to add the project on this device, and add it on a yes in the user's own words, after showing "
            "the change.",
            "A project that the server already holds needs no `--first` from this device.",
            "never set the token or ask for its value",
            "cannot be drawn",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, put)

    def test_the_work_is_shown_in_nexus(self):
        text = workflow()
        show = section(text, "## Show the work in NEXUS")
        self.assertIn("NEXUS is every stage's default human view", text[:text.index("\n## ")])
        for rule in (
            "give the project's address once: `<nexus.url>/p/<project>`",
            "give the stage's address, `<nexus.url>/p/<project>/<part>/<stage>`, with `_` as the part of a project "
            "without parts, and `#item=<ID>` for one item",
            "`#step=` with `1-b`, `2`, `3`, `4`, `5`, `6`, `7`, `8-a` or `8-b–9`",
            "Work on a branch shows there only after its merge and push",
            "NEXUS cannot edit yet",
            "the Miro board on which stage 01's steps run",
            "ask before writing one into a file of a public repository",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, show)

    def test_nexus_is_every_stages_default_human_view(self):
        contract = section(read_text(SKILLS / "corthex" / "references" / "stage-contract.md"), "## Default human views")
        for rule in (
            "On a project on the user's NEXUS server, NEXUS is every stage's default human view.",
            "the DDD board of 01, the ERD of 05 and the sitemap of 07 as pictures and every other stage as a list",
            "(nexus-work.md)",
            "Without a NEXUS server, or for a project kept off it, propose the tool in this table.",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, contract)
        self.assertLess(contract.index("NEXUS is every stage's default human view"), contract.index("| Stage |"))
        entry = read_text(SKILLS / "corthex" / "SKILL.md")
        self.assertIn("On a project on the user's NEXUS server, that default is NEXUS for every stage.", entry)
        for path in sorted(SKILLS.glob("corthex-*/references/[01][0-9]-*.md")):
            row = next((line for line in read_text(path).splitlines() if line.startswith("| Human view |")), None)
            if row is None:
                continue
            with self.subTest(stage=path.stem):
                self.assertIn("on a project on nexus", row.lower())
        for skill in ("corthex-build", "corthex-contract", "corthex-define", "corthex-discover", "corthex-present",
                      "corthex-screen"):
            steps = section(read_text(SKILLS / skill / "SKILL.md"), "## How a stage runs")
            with self.subTest(skill=skill):
                self.assertIn("On a project on NEXUS, NEXUS shows the stage whatever `human` names", steps)
                self.assertIn("On a project on NEXUS, merge the stage's draft of documents and push it first, then ask "
                              "with the stage's NEXUS address", steps)

    def test_stage_01_steps_run_on_miro_and_nexus_draws_the_board(self):
        discover = read_text(SKILLS / "corthex-discover" / "SKILL.md")
        self.assertIn("The steps run on a Miro board, also on a project on NEXUS", discover)
        self.assertIn("Check before step 0 that the session has Miro's tools.", discover)
        board = read_text(SKILLS / "corthex-discover" / "references" / "event-storming-board.md")
        self.assertLess(board.index("\n## NEXUS\n"), board.index("\n## Miro\n"))
        nexus = section(board, "## NEXUS")
        for rule in (
            "NEXUS draws a board only once the document has a context heading with its CTX ID",
            "steps 0 to 9 run on the Miro board, and so does a team's live workshop",
            "ask for checkpoint 3 there",
            "`<nexus.url>/p/<project>/<part>/01-domain#step=<step>`",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, nexus)
        self.assertIn("Before step 0, check that this session has Miro's tools", section(board, "## Miro"))
        domain = read_text(SKILLS / "corthex-discover" / "references" / "01-domain.md")
        self.assertIn("Check that this session has Miro's tools", domain)
        self.assertIn("ask for checkpoint 3 with the board's NEXUS address", domain)
        self.assertIn("| Lane | Events |", domain[domain.index("## Output template"):])


if __name__ == "__main__":
    unittest.main()
