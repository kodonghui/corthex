---
name: corthex-hub
description: One page with every CORTHEX project's 13 stages, checks and trace links. Use when the user wants an overview of all their projects, asks where each project stands, what a trace ID such as REQ-003 connects to, or which IDs are missing, duplicated or unlinked; when a stage's progress, last checkpoint or next action should be recorded; and when sending project snapshots to their own NEXUS server or removing them from it.
license: Apache-2.0
compatibility: Needs Python 3.8 or later and uses installed Git. Local snapshot, build and status work offline; explicit server commands use only the configured NEXUS address and allowed projects.
metadata:
  author: kodonghui
  version: "0.6.0"
---

# CORTHEX hub

The hub reads registered projects, checks trace links, builds an offline page and connects an agent to its configured NEXUS space. It uses `~/.corthex/projects.json`, the profile and each project's `.corthex/project.json`. Generated files stay under `~/.corthex/hub/`; `status` can write only the repository's stage-record files. It never commits or pushes Git locally. Explicit CI setup can open a GitHub pull request for a missing push workflow.

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
- `--nexus CHECKPOINT` names a checkpoint passed in NEXUS, and the record keeps its link. `status` contacts no server. Without `--where`, the link comes from this device's last read of the profile's `nexus.url` by `push`, `push --job` or `todo`, which keep a small record per server under `~/.corthex/hub/servers/`: whether it is NEXUS v3, and when it was read, with no token or project data. For NEXUS v3 the link is the stage's page, `<nexus.url>/p/<project>/<part or _>/<stage>`; an older server gets its overview link, `<nexus.url>/overview/<project>/<part or _>/<stage>#<checkpoint>`, as before. Without a record of that server, `status` records the checkpoint without a link and says so: pass `--where` with the checkpoint's https link, or run `todo` once against that server to refresh the record, then run `status` again.

## Act on the checks

The checks and the forms of source the hub reads are in [references/reading.md](references/reading.md). In short: an ID defined twice is an error; an ID that is mentioned but not defined, or an item that names no item it comes from, is a warning; missing priorities and screens without states are notes.

- A check is a lead, not a verdict. Read the source at the given place before you report it as a problem.
- Fix sources through the stage skill, in the direction the stage's `truth` gives. When `truth` is `human`, the fix belongs in the human view, and the text copy follows.
- Never renumber an ID to clear a check. Mark a removed item as removed, or a deferred one as deferred, instead.

## Send snapshots to a NEXUS server (optional)

`hub.py push` takes a fresh snapshot and sends it to the configured server. It includes interpreted DDD/ERD/sitemap picture data and repository stage records from the last fetched default commit, with IDs, titles, checks and relative file locations. It sends no other files or local paths, except that a server whose held-commit answer lists `corthex-hub/0.3` gets that format, which adds the whole text of each user flow, screen definition and mockup page; other servers and a first push get 0.2. Read [references/snapshot.md](references/snapshot.md) for formats, redaction and limits.

1. The user lists the projects that may be sent in `nexus.push` in `~/.corthex/profile.json`, and the address in `nexus.url`. Ask before the first push of each project.
2. The service token goes in the environment variables `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET`, never in a file, the profile, a command line or a message.
   The hub uses the Nexus-Agent header pair by default and the CF-Access pair for a server recorded locally as v2. Override with profile `nexus.auth_headers` (`cf-access` or `nexus-agent`), or `CORTHEX_NEXUS_AUTH_HEADERS` (which takes precedence). Use `cf-access` for a v2 server without a local record, including CI. Only one pair is sent.
3. Run `hub.py push --dry-run` first and show what would be sent. Then run `hub.py push`. The dry run asks the server nothing, so whether the push is the project's first, and its format, are checked when it is sent; it shows 0.2. To show what a 0.3 push adds, run `hub.py snapshot PROJECT --format corthex-hub/0.3 --print`.
4. A push that the server answers by holding no such project, also after the user removed it, is the project's first: the hub sends nothing and refuses it with `first push needs --first`. Explain that the first upload also configures GitHub Actions through `gh` when available, and ask; after their yes for that project, run `hub.py push PROJECT --first`, which takes exactly one project. On a project that the server holds, `--first` changes nothing.
5. The hub drains pending writes, asks for the held commit and compares ancestry before sending. A descendant replaces it; an older or missing commit needs a fetch. Divergence names both commits: use `--replace-held` only after the user agrees. A phase-1 server needs the 0.2 release. Report the actual refusal; for a refused token, check the header selection as well as the token and Access setup.

For an owner-authenticated v2 NEXUS service, `hub.py preview-v2 PROJECT --project-id ID` builds the first-publication preview and its digest from the registered origin's fetched default-branch commit. The committed `.corthex/nexus-v2-sources.json` has format `nexus.sources/1` and an `artifacts` array. Each entry gives `part`, `stage` and an ordered `files` list of relative UTF-8 source paths. An empty list records a missing source. The preview prints paths and digests without sending anything.

The owner checks the preview and records its digest in NEXUS. With the resulting consent ID, run `hub.py publish-v2 PROJECT --project-id ID --consent CONSENT_ID`. Later publications use `--base-commit HELD_COMMIT`. Both commands accept `--commit COMMIT` to preserve the exact preview when the branch advances. The scoped publisher credential comes from `CORTHEX_NEXUS_PUBLISHER_TOKEN` over the configured HTTPS origin. The command uses the same idempotency key for up to three attempts and confirms the receipt's held commit. Treat a missing or mismatched receipt as an unresolved publication. The existing Access-based `push`, `push --job` and `setup-ci` keep their established contract.

A repository can also push on its own. Its push job runs `hub.py push --job` in the repository's CI for each commit that reaches the default branch, never for a pull request, with the server's address and the service token as the repository's secrets. It pushes the checkout's own project, only a commit newer than the one that the server holds, or that commit once more in a newer format that the server lists, and never a first push or a replacement; it sends no outbox and reads no to-do. Its answer says `sent`, with the server's answer in `pushed`, or `why`: `first-push-waits`, `already-held`, or `not-set` with the `missing` names. The job's file and how to add its secrets are in the NEXUS server's guide. Add it to a repository only when the user asks, by pull request. Use the explicitly authorized CI setup below to configure its secrets.

Only the user removes a project, in NEXUS under their own sign-in. `hub.py remove PROJECT` sends no removal: it reads the project's data and shows what a removal deletes, with the open comments, open proposals, pending reflections and checkpoints not yet recorded by ID, and the address of the project's data, `<nexus.url>/p/<project>#data`, where the user removes it. `--dry-run` does the same. Show both, offer to answer, reflect or record those entries first, and say that a removed project comes back only by a first push that the user agrees to and, while the project is in `nexus.push`, how to take it off the list. The project's outbox stays: a write that waits for a removed project is dropped with its `404` at the next contact. `404 project_not_found` is nothing to remove. A server from before the design revision has no project's data yet, so the hub shows its dry run instead, with the remark `server-older`. Taking a project out of `nexus.push` stops further pushes but leaves what the server holds.

### A session without a profile, and can-send

On a device with neither a profile nor `~/.corthex/projects.json`, such as a cloud session, the hub takes the address from `CORTHEX_NEXUS_URL`, the push list from `CORTHEX_NEXUS_PUSH` (project names separated by commas), the token from its two variables and the session label from `CORTHEX_NEXUS_SESSION`. It reads only the checkout's own project: the nearest `.corthex/project.json` from the current folder up to the repository's root, under its `name`. Another project is refused with `not this checkout's project`, a folder without such a file with `no project in this checkout`, and a project that the variable does not name, for each command that reaches the server, with `not in CORTHEX_NEXUS_PUSH`. On a device with a profile or a list of projects the variable is ignored, and a command that reaches the server carries the remark `push-variable-ignored`. These are the user's own settings: never set them, and never ask for the token's value.

`hub.py can-send PROJECT` says whether this session can send for the project, without contacting the server or sending the outbox. Its answer has `can_send`; `missing`, the names of the settings or variables that are missing, never a value; `expected`, true when the project settings' `on_nexus` is `true` or the push list names the project; and `source`, `profile` or `environment`. It is `done` either way, and `refused` only for a project that the hub cannot find. When `can_send` is false and `expected` is true, tell the user once in the session, in one line that names what is missing and says that these are their own settings, and go on with the work; when `expected` is false, say nothing.

## Set up repository CI

`hub.py setup-ci PROJECT` configures the repository Actions secrets `CORTHEX_NEXUS_URL`, `CORTHEX_NEXUS_CLIENT_ID`, and `CORTHEX_NEXUS_CLIENT_SECRET` from this process's environment. The explicit command authorizes that GitHub write for the named, allowed project. A successful `push PROJECT --first` performs the same setup; a dry run, a refused/failed upload and `push --job` never configure CI. If its effective upload address differs from the environment's `CORTHEX_NEXUS_URL`, automatic setup skips before any secret write and reports the mismatch without either address. The upload receipt stays unchanged and CI setup is a separate one-line diagnostic. A CI setup failure cannot undo a completed upload; retry with `setup-ci`.

- Resolve the project's own GitHub origin, not its display name: the `marong` project may live in a `marong2` repository. Inspect the default branch before deciding whether a workflow is missing. Only `github.com` HTTPS or SSH origins are supported; pin the child process's `GH_HOST` to `github.com` so another session default cannot redirect setup. The NEXUS URL must be a non-loopback HTTPS origin.
- Require all three values in the environment. Never print them, put them in an argument, write a local file, export a dotenv file, or add them to a PR. `gh secret set` receives each value through stdin; its output is captured and discarded. The values are stored only as the explicitly requested encrypted GitHub Actions secrets. Do not copy the session's NEXUS credentials into the child environment.
- Find `gh` only in absolute PATH folders outside the current directory. If it is missing or not logged in, skip setup and report one line. Do not install it, log in for the user, request a token value, or change global credentials. A GitHub permission/transport failure is reported without raw CLI output.
- If `.github/workflows/corthex-nexus-push.yml` exists on the default branch, leave it intact. Otherwise open or reuse one PR with the bundled workflow, the immutable compatible hub pin and read-only permissions. Never merge it, force-push, overwrite a different workflow, execute repository code, or change the local branch/worktree from this command. The agent follows the repository's checks before merging the returned PR.
- `setup-ci PROJECT --dry-run` reads authentication/repository state and shows the plan without configuring secrets or creating a PR. `--json` returns metadata only. No setup command makes a first NEXUS upload, passes a checkpoint or removes data.

After setup, verify a default-branch push job's receipt, not just its green status: `sent: true` means delivery, `already-held` means the server already has that commit, and `not-set` or `first-push-waits` means no delivery. The workflow has no automatic retry service. Disable it in Actions or revert its PR to stop it. Secret deletion or rotation is a separate explicit user action.

## Agent work in NEXUS

Use these commands only for a project in `nexus.push`. They contact the configured server; local snapshot/build/status and listing the outbox stay offline. Each has `--help`, `--url` and `--json`. Text and reason/change values may come from the matching UTF-8 `--*-file`, with `-` for standard input. Never pass service-token values in arguments.

| Command | Purpose |
| --- | --- |
| `todo PROJECT [--session LABEL] [--if-due]` | Read ordered agent work and waiting/taken counts; a missing space is empty. `--if-due` reads only when the session's last read is due |
| `comment PROJECT --stage STAGE --text TEXT [--item ID]` | Comment on an item of any of the 13 stages, or on the stage as a whole without `--item`; optional `--quote`, `--asks`, and `--look-first` with `--asks checkpoint` |
| `reply PROJECT COMMENT --text TEXT` | Reply to a comment; optional `--asks`, and `--look-first` with `--asks checkpoint` |
| `answered PROJECT COMMENT` | Mark it answered |
| `decide PROJECT COMMENT --link HTTPS_URL [--text TEXT]` | Report where the user's decision was recorded |
| `propose PROJECT --stage STAGE --item ID --reason TEXT --change TEXT` | Propose a change; optional repeated items, `--adds`, `--source-file` with `--source-path`, and one comment/discrepancy target. See Propose a change, below |
| `withdraw PROJECT PROPOSAL` | Withdraw the session's proposal |
| `reflect PROJECT EDIT EVENT` | Report opened/merged/closed/reflected/needs-user; PR events need `--pr`, reflected needs full `--commit` |
| `record PROJECT CHECKPOINT EVENT --pr HTTPS_URL` | Report its record PR opened/merged/closed |
| `show PROJECT ENTRY` | Read a comment, proposal, reflection or checkpoint in full |
| `claim PROJECT ENTRY`, `release PROJECT ENTRY` | Claim/end a session's agent work; claims are never queued |
| `outbox [PROJECT ...] [--send]` | List metadata without text, or retry pending writes |

`todo` keeps the time of each session's read, as the server's answer names it, in `~/.corthex/hub/reads/<project>.json` for seven days; sessions without a label share one entry. Its result says whether it read the server (`read`), the time of the session's read before (`since`) and, by list, the IDs that are new since then (`new`, all of them after the session's first read). Run plain `todo` when a session starts work on a project, and `todo --if-due` at each step where a unit of stage work starts or ends: it reads only when the session has no kept read, or the kept time is more than a day old or more than an hour ahead, and otherwise contacts no server and sends no outbox. After a read that follows the session's first, tell the user only what is in `new`. A server of before the design revision names no read, so nothing is kept, `--if-due` reads each time, and the result carries the remark `server-older`.

When your comment or reply leaves a question for the user, `--asks` says what it asks, so that the user's page offers the right answer: `answer` for an answer in words, `recommended` when the text holds a recommendation that the user can take as recommended, and `checkpoint` when it asks the user to pass the stage's checkpoint, which takes the user's own pass: taking a recommendation passes no checkpoint. The user's next entry clears it. A NEXUS server from before the redesign takes comments only on the pictured stages (`01-domain`, `05-erd`, `07-sitemap`), with `--quote` when `--item` is left out, and no `--asks`; it refuses the rest as `invalid_request`, so comment there without them.

A checkpoint request is a comment with `--asks checkpoint` on the stage as a whole, or a reply with it on the stage's open request. It names one thing to look at first in `--look-first`: an item's trace ID that the pushed snapshot holds, an `https` address, or `stage` for the stage's page, which the hub sends as `<nexus.url>/p/<project>/<part>/<stage>`, with `_` for the project as a whole. Keep it to at most 10 lines and 1,200 characters, counted after redaction, and leave out `--item`; a request out of form, or `--look-first` without `--asks checkpoint`, is a wrong command line that sends and keeps nothing. Before it sends, the hub reads the to-do, whatever the time of the session's last read. When entries came in since the session's read before, it holds the request back once, `refused` with `read the to-do first` and the result's `new`: answer the entries on the stage, or name them in the request as open, and send it again. When the stage already has an open request, the hub sends the same text as a reply on it, with the remark `sent-as-reply`, also from the outbox. A server from before the design revision gets the thing to look at first as the text's last line, with the remark `server-older`. A request that cannot be sent waits in the outbox, exit 3, and you make the request in the session meanwhile; at the next contact the hub reads the to-do again before it sends the request, in the form that the server then takes, and that read changes nothing of what `todo` says is new. A reply with `--look-first stage` needs its comment's stage from the server, so when the hub cannot read it, nothing is kept and the result is `failed`: send it again, or name an ID or an address.

Writes and claims require `--session` or `CORTHEX_NEXUS_SESSION`. Choose a label without personal data. Check source and explicit user work before taking agent work. A proposal is a suggestion, an accepted proposal is authorization to prepare the described change, and a passed checkpoint must come from the user; the agent never passes one.

### Propose a change

A proposal puts a change on a stage's picture, 01, 05 or 07, for the user to accept or reject: `--change` says what changes and `--reason` why. NEXUS has no field for another way. When you have another way worth weighing, write it inside `--reason`, as its last sentence, in the form NEXUS shows, in the user's language: `Other way: …` in English, `다른 방법: …` in Korean.

`--source-file` gives the whole proposed text of one file, from which NEXUS works out the changes. The hub sends it with that file's repository path, `source_path`, which tells NEXUS which of the drawing's files the text replaces. The path is the file's own in the project's checkout, found as `can-send` finds it, or `--source-path` for a file outside it. Before anything is sent or kept, the hub checks the path, and refuses the command line (exit 2) when:

- `--source-file` is outside the checkout without `--source-path`, `--source-path` names another path than the file has in the checkout, or `--source-path` comes without `--source-file`;
- `--source-path` is not a plain repository path: the hub turns `\` into `/` on every platform, and refuses a leading `/`, a drive letter, empty, `.` or `..` segments and more than 300 characters, since NEXUS reads only paths in the repository;
- the stage is skipped, has no source, or has its source in another repository, so NEXUS has no picture of it from this checkout;
- the path is not under the stage's `source` in the project's settings, which is where the picture reads its files;
- it does not end in an extension that the stage's picture reads: `.md` or `.markdown` for 01, `.sql` for 05, `.yaml` or `.yml` for 07;
- it is a translation beside its original, such as `orders.ko.md` next to `orders.md`, which the picture does not read;
- its name, or a folder on its path, looks like a secret's, such as `secrets.md`, which the picture never reads;
- it belongs to another part than `--part`, by the picture's own rule: a file belongs to the part that its path under the stage's source starts with, followed by `/`, `.` or `-`; without `--part`, it belongs to no part.

NEXUS refuses a `source_path` that names no file the drawing reads, and needs one when the drawing reads several files. The hub prints its answer's detail: `source_path names no file the drawing reads`, or `source_path is needed: the drawing reads several files`. A NEXUS server from before v3 takes no `source_path` and refuses such a proposal as it stands; the hub prints that answer too.

Every result also has `remarks`, names for what the hub did otherwise than the command line says, which the lines for a person say in words; the list is usually empty.

An unsent agent write is kept for seven days under its original ID and session. Offline/token failures and retryable HTTP errors keep it; permanent refusals and expiry drop it with their reasons. Drain oldest first and stop at the first retained write. `--json` prints one outcome per project; exit 0 is done, 1 refused/failed, 2 invalid CLI and 3 kept. A kept write is not evidence that the server received it.

The write is queued before its first HTTP call. If its outbox cannot be written, the failed result gives one redacted `recovery` copy to you, with the original write ID. Keep that text in the session and report the loss; never put the recovery body in a log or generate a new ID when restoring it. Ordinary results and outbox listings contain no such text.

## Never

- Write only stage records when using `status`; never edit other repository files or snapshots from this skill.
- Never record a state, a checkpoint or a finding the user did not give or you did not check.
- Never send a project that is not listed in `nexus.push`, never put a token where it would be saved or shown, and leave a project's removal to the user, in NEXUS.
