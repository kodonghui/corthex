---
name: corthex-hub
description: One page with every CORTHEX project's 13 stages, checks and trace links. Use when the user wants an overview of all their projects, asks where each project stands, what a trace ID such as REQ-003 connects to, or which IDs are missing, duplicated or unlinked; when a stage's progress, last checkpoint or next action should be recorded; and when sending project snapshots to their own NEXUS server or removing them from it.
license: Apache-2.0
compatibility: Needs Python 3.8 or later and uses installed Git. Local snapshot, build and status work offline; explicit server commands use only the configured NEXUS address and allowed projects.
metadata:
  author: kodonghui
  version: "0.2.2"
---

# CORTHEX hub

The hub reads registered projects, checks trace links, builds an offline page and connects an agent to its configured NEXUS space. It uses `~/.corthex/projects.json`, the profile and each project's `.corthex/project.json`. Generated files stay under `~/.corthex/hub/`; `status` can write only the repository's stage-record files. It never commits, pushes Git or opens a pull request.

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
hub.py status <project> 05-erd --part orders --repository --state done --checkpoint "Order tables approved" --by "the maintainer" --date 2026-11-03
```

- States are `done`, `in_progress`, `not_started` and `skipped`. Stage keys are `01-domain` to `13-presentation`.
- Record `done` only when the stage's human checkpoint was passed and recorded: say what was approved, by whom and where with `--checkpoint`, and when with `--date`. The script refuses `done` without both. An AI recommendation, a read receipt or an edit time is not a checkpoint.
- Record a state when the user tells you one, or after a stage's work as the stage skill says. Do not record what you only infer.
- `--check LEVEL MESSAGE` adds a finding from your own review, such as a spec row that contradicts its requirement. LEVEL is `error`, `warn` or `info`. Name the IDs in the message so the page links them. `--clear-checks` removes the stage's earlier findings first, and `--reset` removes everything recorded for the stage.
- Each write keeps the previous file as `~/.corthex/hub/status/<project>.json.bak`.
- From 0.2, `--repository` creates the first repository record. Once records exist, `status` updates them automatically. Projects with `parts` require `--part`; each part has its own `.corthex/stages/<part>.json`, otherwise `.corthex/stages.json`. A repository checkpoint needs `--by ROLE` and a valid `--date`, optional safe HTTPS `--where` and optional `--nexus CHECKPOINT`. Commit it with the work's pull request, after checking the source; the script never does so. Snapshots show only the version merged into the fetched default branch.

## Act on the checks

The checks and the forms of source the hub reads are in [references/reading.md](references/reading.md). In short: an ID defined twice is an error; an ID that is mentioned but not defined, or an item that names no item it comes from, is a warning; missing priorities and screens without states are notes.

- A check is a lead, not a verdict. Read the source at the given place before you report it as a problem.
- Fix sources through the stage skill, in the direction the stage's `truth` gives. When `truth` is `human`, the fix belongs in the human view, and the text copy follows.
- Never renumber an ID to clear a check. Mark a removed item as removed instead.

## Send snapshots to a NEXUS server (optional)

`hub.py push` takes a fresh 0.2 snapshot and sends it to the configured server. It includes interpreted DDD/ERD/sitemap picture data and repository stage records from the last fetched default commit, with IDs, titles, checks and relative file locations. It sends no arbitrary files or local paths. Read [references/snapshot.md](references/snapshot.md) for formats, redaction and limits.

1. The user lists the projects that may be sent in `nexus.push` in `~/.corthex/profile.json`, and the address in `nexus.url`. Ask before the first push of each project.
2. The service token goes in the environment variables `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET`, never in a file, the profile, a command line or a message.
3. Run `hub.py push --dry-run` first and show what would be sent. Then run `hub.py push`.
4. The hub drains pending writes, asks for the held commit and compares ancestry before sending. A descendant replaces it; an older or missing commit needs a fetch. Divergence names both commits: use `--replace-held` only after the user agrees. A phase-1 server needs the 0.2 release. Report the actual refusal; a refused token needs its Access setup fixed.

`hub.py remove <project>` deletes a project from the server; ask before you run it. Taking a project out of `nexus.push` stops further pushes but leaves what the server holds.

## Agent work in NEXUS

Use these commands only for a project in `nexus.push`. They contact the configured server; local snapshot/build/status and listing the outbox stay offline. Each has `--help`, `--url` and `--json`. Text and reason/change values may come from the matching UTF-8 `--*-file`, with `-` for standard input. Never pass service-token values in arguments.

| Command | Purpose |
| --- | --- |
| `todo PROJECT [--session LABEL]` | Read ordered agent work and waiting/taken counts; a missing space is empty |
| `comment PROJECT --stage STAGE --text TEXT [--item ID]` | Comment on an item; a whole-picture comment needs `--quote` |
| `reply PROJECT COMMENT --text TEXT` | Reply to a comment |
| `answered PROJECT COMMENT` | Mark it answered |
| `decide PROJECT COMMENT --link HTTPS_URL [--text TEXT]` | Report where the user's decision was recorded |
| `propose PROJECT --stage STAGE --item ID --reason TEXT --change TEXT` | Propose a change; optional repeated items, `--adds`, `--source-file` and one comment/discrepancy target |
| `withdraw PROJECT PROPOSAL` | Withdraw the session's proposal |
| `reflect PROJECT EDIT EVENT` | Report opened/merged/closed/reflected/needs-user; PR events need `--pr`, reflected needs full `--commit` |
| `record PROJECT CHECKPOINT EVENT --pr HTTPS_URL` | Report its record PR opened/merged/closed |
| `show PROJECT ENTRY` | Read a comment, proposal, reflection or checkpoint in full |
| `claim PROJECT ENTRY`, `release PROJECT ENTRY` | Claim/end a session's agent work; claims are never queued |
| `outbox [PROJECT ...] [--send]` | List metadata without text, or retry pending writes |

Writes and claims require `--session` or `CORTHEX_NEXUS_SESSION`. Choose a label without personal data. Check source and explicit user work before taking agent work. A proposal is a suggestion, an accepted proposal is authorization to prepare the described change, and a passed checkpoint must come from the user; the agent never passes one.

An unsent agent write is kept for seven days under its original ID and session. Offline/token failures and retryable HTTP errors keep it; permanent refusals and expiry drop it with their reasons. Drain oldest first and stop at the first retained write. `--json` prints one outcome per project; exit 0 is done, 1 refused/failed, 2 invalid CLI and 3 kept. A kept write is not evidence that the server received it.

The write is queued before its first HTTP call. If its outbox cannot be written, the failed result gives one redacted `recovery` copy to you, with the original write ID. Keep that text in the session and report the loss; never put the recovery body in a log or generate a new ID when restoring it. Ordinary results and outbox listings contain no such text.

## Never

- Write only stage records when using `status`; never edit other repository files or snapshots from this skill.
- Never record a state, a checkpoint or a finding the user did not give or you did not check.
- Never send a project that is not listed in `nexus.push`, never remove one from the server without the user's go-ahead, and never put a token where it would be saved or shown.
