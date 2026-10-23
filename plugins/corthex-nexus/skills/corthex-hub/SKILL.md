---
name: corthex-hub
description: One page with every CORTHEX project's 13 stages, checks and trace links. Use when the user wants an overview of all their projects, asks where each project stands, what a trace ID such as REQ-003 connects to, or which IDs are missing, duplicated or unlinked; when a stage's progress, last checkpoint or next action should be recorded; and when sending project snapshots to their own NEXUS server.
license: Apache-2.0
compatibility: Needs Python 3.8 or later. Uses git when it is installed. Reads local files only; the optional push command sends snapshots to a server the user configured.
metadata:
  author: kodonghui
  version: "0.1.0"
---

# CORTHEX hub

The hub reads the stage sources of each registered project, checks how their trace IDs connect, and writes one HTML page with all the projects on it. It uses the files of the `corthex` skill: `~/.corthex/projects.json` for the projects on this machine and each project's `.corthex/project.json` for its stages and ID formats. It writes only under `~/.corthex/hub/` and never changes a repository.

Run the script in this skill's folder, `scripts/hub.py`, with Python 3: `python3 scripts/hub.py <command>`, or `py scripts\hub.py <command>` on Windows. Each command has `--help`.

## Show the hub

1. Run `hub.py build`. It reads every registered project, saves a snapshot of each and writes `~/.corthex/hub/index.html`. Name projects to build only those. `--no-scan` reuses the saved snapshots.
2. Tell the user where the page is and what the checks found, the most serious first, with the IDs. Open the page only if they ask.
3. The page loads nothing from the network and runs from the disk. It holds item titles from the projects, so share it only where the projects' material may go.

If a project is missing, register it with the `corthex` skill first. The hub reads a project only under the name it is registered with; when it says a project's `.corthex/project.json` gives another name, or a name registered for another folder, ask the user which name is right and fix the registration or the project's settings with the `corthex` skill. If a stage's source sits in another repository without a local checkout, the page says so; ask for the checkout's path and add it to the project's entry in `~/.corthex/projects.json`.

## Answer questions about IDs

For "what does SPEC-014 connect to?" or "which requirements have no spec?", run `hub.py snapshot <project>` and read the saved snapshot, `~/.corthex/hub/snapshots/<project>.json`. Each item has its `where` (file and line) and `links`; links count in both directions. Quote the IDs and the file locations, and say which stages were not read, because an ID defined in an unread stage looks undefined.

## Record progress

The page shows each stage's state only as recorded. It never guesses from files, because a file that exists is not a finished stage.

```bash
hub.py status <project> <stage> --state in_progress --next "Review SPEC-014 with the team"
hub.py status <project> 02-prd --state done --checkpoint "PRD approved in the kickoff review" --date 2026-01-12
```

- States are `done`, `in_progress`, `not_started` and `skipped`. Stage keys are `01-domain` to `13-presentation`.
- Record `done` only when the stage's human checkpoint was passed and recorded: say what was approved, by whom and where with `--checkpoint`, and when with `--date`. The script refuses `done` without both. An AI recommendation, a read receipt or an edit time is not a checkpoint.
- Record a state when the user tells you one, or after a stage's work as the stage skill says. Do not record what you only infer.
- `--check LEVEL MESSAGE` adds a finding from your own review, such as a spec row that contradicts its requirement. LEVEL is `error`, `warn` or `info`. Name the IDs in the message so the page links them. `--clear-checks` removes the stage's earlier findings first, and `--reset` removes everything recorded for the stage.
- Each write keeps the previous file as `~/.corthex/hub/status/<project>.json.bak`.

## Act on the checks

The checks and the forms of source the hub reads are in [references/reading.md](references/reading.md). In short: an ID defined twice is an error; an ID that is mentioned but not defined, or an item that names no item it comes from, is a warning; missing priorities and screens without states are notes.

- A check is a lead, not a verdict. Read the source at the given place before you report it as a problem.
- Fix sources through the stage skill, in the direction the stage's `truth` gives. When `truth` is `human`, the fix belongs in the human view, and the text copy follows.
- Never renumber an ID to clear a check. Mark a removed item as removed instead.

## Send snapshots to a NEXUS server (optional)

`hub.py push` sends saved snapshots to a NEXUS server that the user runs on their own domain. It sends only what the page shows: IDs, titles, states, checks, file locations and commit IDs, never file contents or local paths. The formats are in [references/snapshot.md](references/snapshot.md).

1. The user lists the projects that may be sent in `nexus.push` in `~/.corthex/profile.json`, and the address in `nexus.url`. Ask before the first push of each project.
2. The service token goes in the environment variables `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET`, never in a file, the profile, a command line or a message.
3. Run `hub.py push --dry-run` first and show what would be sent. Then run `hub.py push`.

## Never

- Never write into a project's repository from this skill, and never edit the snapshots by hand; build them again.
- Never record a state, a checkpoint or a finding the user did not give or you did not check.
- Never send a project that is not listed in `nexus.push`, and never put a token where it would be saved or shown.
