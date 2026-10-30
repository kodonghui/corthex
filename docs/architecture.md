# Architecture

[한국어](architecture.ko.md)

How CORTHEX is put together, and why. The file formats are defined once, in the entry skill's references, and this page links to them instead of repeating them.

Status: 0.1.0. The core plugin, `corthex`, exists, and so do the first parts of `corthex-memory` (the session start context) and `corthex-nexus` (the local project hub and a NEXUS server to deploy yourself). The rest of both is planned (see [Roadmap](#roadmap)).

## Goals

- Anyone can install CORTHEX from a public Git repository, in Claude Code and in Codex, with each host's own plugin commands.
- One person can run several projects, and the same plugin fits different people through a profile instead of edited files.
- Each project stage hands traceable work to the next one.
- CORTHEX adds no service or updater of its own. The hosts' marketplaces install and update it, its instructions are skills, and the optional memory plugin uses the hosts' hooks.

Out of scope: a custom updater or machine sync, editing the user's global instruction files, and storing secrets.

## Repository layout

```text
.
├── .claude-plugin/marketplace.json      marketplace for Claude Code
├── .agents/plugins/marketplace.json     marketplace for Codex
├── plugins/
│   ├── corthex/                         core plugin, skills only
│   │   ├── .claude-plugin/plugin.json   manifest for Claude Code
│   │   ├── plugin.json                  Agent Plugins 1.0 manifest, read by Codex
│   │   ├── LICENSE, NOTICE
│   │   └── skills/
│   │       ├── corthex/                 entry skill
│   │       │   ├── references/          principles, profile, project, stage contract
│   │       │   └── assets/              example profile.json and project.json
│   │       ├── corthex-discover/ …      stage skills, one reference file per stage
│   │       ├── corthex-record/          minutes, decisions, progress
│   │       └── corthex-uxui/            craft for screens, motion and video
│   │           ├── references/          names, values, video, checks and their sources
│   │           └── scripts/             two read-only checks: page-check.js in the page, media-check.py with FFmpeg
│   ├── corthex-memory/                  session context and C1 hooks
│   │   ├── .claude-plugin/plugin.json   manifest for Claude Code
│   │   ├── .codex-plugin/plugin.json    manifest for Codex; no root plugin.json
│   │   ├── hooks/hooks.json             four C1 hooks, read by both hosts
│   │   ├── scripts/hook.py              common C1 hook entry, Python standard library only
│   │   ├── scripts/session_start.py     compatibility entry for the 0.1.0 base
│   │   ├── context/principles.md        short form of the working principles
│   │   ├── skills/corthex-memory/scripts/memory_lib/   shared C1 store, context and hook modules
│   │   └── LICENSE, NOTICE
│   └── corthex-nexus/                   project hub, a skill with a script
│       ├── .claude-plugin/plugin.json   manifest for Claude Code
│       ├── plugin.json                  Agent Plugins 1.0 manifest, read by Codex
│       ├── skills/corthex-hub/
│       │   ├── scripts/hub.py           snapshots, checks, page, push and remove, Python standard library only
│       │   ├── assets/hub.html          page template that loads nothing from the network
│       │   └── references/              what the hub reads and checks, and its file formats
│       └── LICENSE, NOTICE
├── nexus/                               NEXUS server, a Cloudflare Worker; not a plugin
│   ├── src/                             Worker, D1 storage, snapshot checks, copy of the hub page
│   ├── test/                            Node tests over an in-memory stand-in for D1
│   ├── wrangler.jsonc                   Worker settings, copied into wrangler.local.jsonc to deploy
│   └── README.md                        how to deploy it behind Cloudflare Access
├── tests/                               checks, Python standard library only
└── docs/
```

## Two manifests, one set of skills

Claude Code reads a plugin's manifest from `.claude-plugin/plugin.json`. Codex and the other Agent Plugins clients read `plugin.json` at the plugin root, and Codex takes its own settings from `extensions.com.openai` in that file. Agent Plugins 1.0 does not list Claude Code among its compatible clients, so the plugin keeps both files. They share one `skills/` folder.

A plugin with hooks is the exception. Codex CLI 0.164.0 does not run a plugin's hooks when the plugin has a root `plugin.json`, even with `.codex-plugin/plugin.json` beside it ([openai/codex#39895](https://github.com/openai/codex/issues/39895), reproduced on 2026-10-23). Without a root `plugin.json`, Codex reads `.codex-plugin/plugin.json` and finds `hooks/hooks.json` on its own. So `corthex-memory` has `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`, and no root `plugin.json`. It therefore does not go to other Agent Plugins clients or to OpenAI's directory, which does not take plugins with hooks anyway. `corthex-nexus` has no hooks, so it keeps both files like the core plugin.

`tests/test_manifests.py` keeps the manifests in line:

- `name`, `version`, `description`, `author`, `homepage`, `repository`, `license` and `keywords` are equal in the Claude Code manifest and the Codex manifest.
- Each plugin has one Codex manifest, and a plugin with hooks has no root `plugin.json`.
- The root `plugin.json` names its schema in `$schema` and uses only the keys that schema allows.
- The version lives in the manifests, not in the marketplace entries.

## Two marketplaces

| File | Read by | Install |
| --- | --- | --- |
| `.claude-plugin/marketplace.json` | Claude Code. Codex also reads it for compatibility. | `claude plugin marketplace add kodonghui/corthex`, then `claude plugin install corthex@corthex` |
| `.agents/plugins/marketplace.json` | Codex | `codex plugin marketplace add kodonghui/corthex`, then `codex plugin add corthex@corthex` |

Both files list the same plugins under the same marketplace name, so the install id is `corthex@corthex` in both hosts.

The optional plugins install the same way, as `corthex-memory@corthex` and `corthex-nexus@corthex`. Each declares `corthex` as a dependency, so Claude Code installs it too; in Codex, add `corthex` first.

## Why the core plugin is skills only

A plugin that holds only skills goes unchanged to Claude Code, Codex, OpenAI's plugin directory and other Agent Plugins clients. OpenAI's directory does not accept plugins with hooks, and Codex does not run Claude Code's `userConfig`. Each skill can also be used on its own, for example uploaded to claude.ai.

So the core plugin has no hooks, commands, agents, MCP servers or user settings. Anything that needs them goes into a separate plugin, and `tests/test_manifests.py` enforces the rule. A skill may still carry scripts in its own `scripts/` folder, as the Agent Skills format allows: `corthex-uxui` has two read-only checks there, which the agent runs like any other command.

## Skills

| Skill | Stages |
| --- | --- |
| `corthex` | entry: profile, projects, principles, routing |
| `corthex-discover` | 01 domain discovery |
| `corthex-define` | 02 PRD, 03 user flow, 04 functional spec |
| `corthex-contract` | 05 ERD, 06 API |
| `corthex-screen` | 07 sitemap, 08 screen states, 09 mockup |
| `corthex-build` | 10 WBS, 11 development, 12 QA |
| `corthex-present` | 13 presentation |
| `corthex-record` | minutes, decisions and progress, at any stage |
| `corthex-uxui` | the craft of screens, motion and video, with its checks: in 08, 09 and 13, or on its own |

`corthex-nexus` adds one more skill, `corthex-hub` (see [Project hub](#project-hub)).

- **Nine skills, not one per stage.** Hosts show every skill's description in each session, and Codex caps that first list at 2% of the context window (8,000 characters when the window is unknown). Grouping keeps the list short. The details of each stage sit in `references/` and are read only when needed. `corthex-uxui` is a skill of its own rather than part of a stage skill: its craft and checks serve stages 08, 09 and 13, and also screen and video work outside a CORTHEX project, which only a description of its own lets the host find.
- **Names start with `corthex-`** so they stay distinct when a skill is used outside the plugin. Inside the plugin, both hosts show them as `corthex:<skill>`.
- **Frontmatter is portable.** Skills use only the fields of the Agent Skills format (`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`), because claude.ai uploads and the Skills API reject host-specific fields. Bodies stay under 500 lines, and links stay inside the skill's own folder, one level deep.
- **Skill text is English.** Replies follow the language in the user's profile.

Measured on 0.1.0 with local installs: `claude plugin details` (Claude Code 2.1.309) reported about 1,000 always-on tokens for the eight descriptions, and in Codex CLI 0.164.0 the eight entries took about 3,200 characters of the skill list. With `corthex-uxui`, Claude Code 2.1.310 reports about 1,240 tokens for the nine, against about 1,050 for the eight on the same version. Its description adds about 580 characters to Codex's list; Codex was not measured again.

## Working principles

Claude Code does not load a `CLAUDE.md` at a plugin's root as context, and its documentation says to put such instructions in a skill. So the principles live in the entry skill, in [principles.md](../plugins/corthex/skills/corthex/references/principles.md), and apply while a CORTHEX skill is in use.

The `corthex-memory` plugin adds a short version at the start of each session with a hook, for people who install it (see [Session start context](#session-start-context)). CORTHEX itself never edits the user's global instruction files.

## Stage contract

Every stage fills six slots: inputs, outputs, human view, sync, human checkpoints and trace IDs. Each stage's text source stays in the product repository. The human view (Notion, Miro, an ERD tool, Figma and so on) can differ from team to team, and the project's settings say which side is the truth for each stage.

The AI reaches a human view through an MCP server, a connector or an API when the tool has one. A tool with only import and export depends on a person's exports, so the AI says how old its copy is. For the ERD, CORTHEX suggests ERD Editor to new projects, because it keeps the diagram in the repository and has an MCP server. For domain discovery, the AI and the user run event storming on a Miro board through Miro's MCP server, one frame per step. By default the AI drafts each step and people correct it on the board, and the result goes into one domain design document.

- The contract, the stage keys and the trace ID rules: [stage-contract.md](../plugins/corthex/skills/corthex/references/stage-contract.md).
- Each stage's slots, steps, checks and output template: `references/<stage>.md` in the stage skill, such as [02-prd.md](../plugins/corthex/skills/corthex-define/references/02-prd.md).
- `tests/test_stages.py` checks that every stage fills all six slots, that each stage skill links its stages, that all stage skills share one procedure, that the procedure and the contract keep the rules for a human view the AI cannot reach, and that stages 06, 08, 11 and 12 account for every response, keep the error codes in one list, lead each response to a screen state and a test case, and keep tests off production; that stages 04, 06, 08 and 12 and the contract go through one list of kinds of cases; and that the browser agent runs of QA keep their rules. It also checks that every stage has a default human view, that another choice is recorded as a decision, that each MCP server is added the same way in every file, and that the resolver example in stage 09 follows its schema.

Stages 06, 08, 11 and 12 work from the API contract, written before the code. Each operation lists every response it can return, such as 200, 401 or 422, with an example, or says why it cannot return one, and every error has one shape (Problem Details, RFC 9457) with a code from one list. The front end builds against a mock server made from the contract, and each response leads to a screen state. Contract tests check the back end against the contract on a development or staging server. QA writes a test case for each response and each screen state, named like `API-001#401` and `SCR-002#permission`, and keeps API tests in the repository that fire every listed response that a real server can be made to return. Before a release, browser agents, such as Aside, walk every user flow on localhost or a test site and report what works, what does not and their impressions; the flows that work become end-to-end tests that run on every pull request. Stages 04, 06, 08 and 12 go through one list of twelve kinds of cases, from access and input to AI answers, so that every case the spec names gets a response, a screen state and a test.

When a project is registered or a stage is set up, the AI proposes the stage's default human view from the contract: a Miro board for domain discovery, Notion databases for the PRD, the user flows and the functional spec, ERD Editor for the ERD, Swagger UI for the API, views the AI draws from the files for the sitemap and the screen states, Figma or Claude Design for the mockup, GitHub Projects or Notion for the WBS, pull requests for development, the test plan, the test and run reports and the bug tracker for QA, and slides built from the scene table for the presentation. When the user or the team picks another tool, the AI records the choice as a decision and says it in the stage's settings, so no stage moves to another tool without a recorded decision. Each stage's reference file says how to connect its default tool and keep it in line with the text source.

## Profile and projects

| File | Where | Holds |
| --- | --- | --- |
| `profile.json` | `~/.corthex/` on each machine | how to address the user, language, where records go, what to ask about first |
| `project.json` | `.corthex/` in each product repository, committed | name, team or personal, records, other repositories that hold sources, ID formats, and each stage's human view, source and truth |
| `projects.json` | `~/.corthex/` on each machine | the projects on this machine and the local paths of their repositories |

The fields are in [profile.md](../plugins/corthex/skills/corthex/references/profile.md) and [project.md](../plugins/corthex/skills/corthex/references/project.md).

- These are plain files rather than Claude Code's `userConfig`, because both hosts can read a file.
- The profile never holds secrets. Keys belong in the host's secret store or in environment variables.
- `project.json` is committed so that everyone on a team sees the same settings. `projects.json` stays on the machine because paths differ between machines.
- Unknown fields are kept and ignored, so a later version can add fields without breaking an older one.

## Session start context

`corthex-memory` 0.1.0 has one hook. Whenever a session starts, `scripts/session_start.py` adds a short context: at startup, on resume, after `/clear`, after compaction and when a session is forked. A resumed or forked session already holds an earlier copy in its history, and the new copy brings in any change to the files since then. The context has:

- the working principles in short form, which `tests/test_memory.py` keeps equal to the list in the entry skill;
- the profile from `~/.corthex/profile.json`. Without one, it gives the defaults, including the default `ask_before` list. If the file exists but cannot be read, it says so, tells the agent not to replace the file, and gives the defaults;
- the project: the nearest `.corthex/project.json` up to the repository root, or else the project in `~/.corthex/projects.json` whose path or repository holds the current folder. For each stage it gives the human view, the truth and the source. Other projects on the machine are listed by name.

It reads only those files, writes nothing and makes no network calls. If anything fails, the hook adds nothing and the session starts as usual.

- **Repository settings in a fixed format only.** `project.json` comes from a repository you may not have checked yet, and Codex adds hook context as a developer message. So from that file the hook shows only short ASCII values without spaces: names, tool names, paths, links and the `truth` value. Free text, such as the title and stage notes, is never shown; a stage that has a note is marked, so the agent can read the note in the file. Other values that do not fit their format are shown as left out. The profile and the project list are the user's own files and are shown as written, one line per value.
- **Size.** The context stays under 8,000 bytes of UTF-8. Claude Code moves hook context over 10,000 characters into a file, and Codex does so over the handler's `additionalContextLimit`, which `hooks/hooks.json` sets to 8,000 tokens instead of the default 2,500. A character or a token takes at least one byte, so neither host moves the context. Larger settings are cut, and the text says so.
- **Codex asks for trust.** Codex runs a plugin's hooks only after you review and trust them in `/hooks`: once after installing, and again after an update changes the hook.
- **Stopping it.** Disable or remove the plugin. In Claude Code, run `claude plugin disable corthex-memory@corthex`. In Codex, set `enabled = false` under `[plugins."corthex-memory@corthex"]` in `~/.codex/config.toml`, or run `codex plugin remove corthex-memory@corthex`. The hook stores nothing, so there is nothing else to undo.
- **Windows.** The hook has two commands. `command` tries `python3`, `python` and then the `py` launcher, joined by `||`. Claude Code runs it on every system: on Windows in Git Bash, or in PowerShell when Git Bash is missing, with the plugin folder as an environment variable. PowerShell 7 accepts `||` but Windows PowerShell 5.1 does not, so with Claude Code on Windows the hook needs Git for Windows or PowerShell 7. Without either, the hook fails and the session starts without the context. Codex on Windows runs `commandWindows` instead, always in PowerShell: PowerShell 7 when it is installed, else Windows PowerShell 5.1, even when Git Bash is there. That command tries `python` and then `py -3` with `if ($LASTEXITCODE -ne 0)`, which 5.1 understands, and finds the script through the `CLAUDE_PLUGIN_ROOT` variable that Codex sets.
- **Checked so far.** On 2026-10-23, on Linux, with Claude Code 2.1.309 and Codex CLI 0.164.0 in isolated settings and a local stand-in for the model API:
  - The context reached the first model request in both hosts, without the title or the notes of the project file. Codex ran the hook only when it was trusted; the test skipped the review with `--dangerously-bypass-hook-trust`.
  - After the profile changed, a resumed session (`claude -p --resume`, `codex exec resume`) and a forked one (`claude -p --resume … --fork-session`) carried the new copy as well as the earlier ones from their history.
  - In Codex, a 28,872-byte test context reached the model whole with `additionalContextLimit` set to 8,000, and was replaced by a preview without it.
  - On 2026-10-24, on a Windows Server 2025 runner with Claude Code 2.1.310, Codex CLI 0.164.0 and the same stand-in (`.github/workflows/windows-hook-check.yml`): with Git Bash, and with PowerShell 7 but no Git Bash, the context reached the model in both hosts. With only Windows PowerShell 5.1, the `||` command could not be parsed, so Claude Code started without the context, and Codex got it through `commandWindows`.

  Forking in Codex and macOS are not tested yet. The hook needs `python3`, `python` or the Windows `py` launcher on the PATH of the shell that runs it.

## Memory store library

C1 starts with the shared library in `plugins/corthex-memory/skills/corthex-memory/scripts/memory_lib/` (TASK-001, TASK-002). Keeping it inside the future memory skill makes the skill self-contained when copied on its own, and its links can stay inside its folder as the Agent Skills rules require. The future `scripts/memory.py` imports its sibling `memory_lib`. The plugin's future `scripts/hook.py` and `scripts/worker.py` find that same scripts directory from their own resolved file location, under the plugin root's `skills/corthex-memory/scripts`, rather than from the working directory or an installed package. No duplicate library or global Python installation is needed. The skill entry point and the hook/worker imports are added by their later tasks.

`base.py` defines the four random ID prefixes, UTC times and dates, C1 records' stable UTF-8 JSON representation, private directories and files, the store location and Windows device-name mapping on every OS. Resolving `CORTHEX_MEMORY_HOME` or importing the library creates nothing. Only the future `on` command may create the store; file writes require an existing parent folder. `files.py` appends a complete JSONL object with one write, skips and counts damaged lines, replaces files through a same-folder temporary and a backup, restores readable backups, and bounds Windows move/deletion retries to one second. Reads retry Windows sharing failures for one second without restoring an old backup; only a missing file or unparseable content can restore, after rechecking the original under the caller's record lock. Unlocked reads raise `RestoreNeeded` without moving files. `read_json()` and `read_jsonl()` accept `holding_lock=True` only while the caller keeps that lock; appends restore a missing primary before adding an entry. `reading.py` connects the short lock attempt for unlocked readers (TASK-003). Short appends roll back to their prior fstat size under the caller's record lock. `delete_file()` removes a whole file with its backup and temporary siblings, and macOS durable writes try `F_FULLFSYNC` before falling back to fsync. An empty store override uses the default; a relative override raises a structured `configuration-invalid` error without a path, for the later hooks/commands/status to handle. A missing directory root fails promptly instead of walking forever. Its safe notices let the later failure logger record `damaged-line` with a count and `restored` without paths or error text. Callers must redact and validate records, hold the locks added in TASK-003, and carry concurrent appends over when rewriting a log. Rebuildable files skip the disk flush and backup. The existing 0.1.0 session-start hook is unchanged and does not use this library yet.

The file tests cover TC-001–005 and TC-316–317 with temporary homes and stores, generated IDs and made-up text: table ordering and byte equality, paths and permissions, damaged/cut lines, killed appenders, process stops after each replacement step, recovery under the caller's record lock, whole-file deletion and simulated Darwin flush branches. The Windows tests hold a target open in another process. They read no real memory store or host settings.

Windows directories use the default creation mode to inherit their parent's permissions. Python 3.13 gives `mkdir(0700)` a protected ACL, so the library requests 0700 only on POSIX; the Windows test reads the temporary child's ACL control flag to check inheritance ([Python's mkdir contract](https://docs.python.org/3.13/library/os.html#os.mkdir)).

`memory_lib/locks.py` provides TASK-003's file leases: exclusive creation with `pid`, `device`, UTC `at` and a random `token`; mtime-based expiry and background refresh at stage 05's six intervals; and token checks before each protected change. Stale takeover renames to a private `.stale` name and checks identity, token and expiry again. A raced fresh lease is restored without overwriting a newer one, using a hard link or exclusive copy. Refresh touches an opened descriptor (a native file handle through the standard library on Windows), so a replaced path cannot redirect it. Acquisition order is enforced across threads in one process, including pending acquisitions, and reset after fork. Within one kind, paths are ordered as memory-folder-relative strings, ignoring case on Windows. Inherited leases reject a child PID before acquiring any instance mutex, so a vanished parent thread cannot block check, refresh or release. A caller supplies a finite monotonic deadline and may request one nonblocking attempt. Only confirmed purge/project deletion callers may request immediate takeover. These leases do not replace the later apply/tombstone checks or carry-over of appends. Tests use real processes for TC-006–008 and TC-318; deterministic mtime ageing exercises expiry without waiting minutes. Hooks and commands are still connected by their later tasks.

`memory_lib/reading.py` first reads JSON/JSONL/custom-parser records without a lease; a readable backup alone requires the matching recovery lease and a locked recheck. Ordinary callers retain their absolute acquisition/read/move deadlines. Only recording opts into TASK-060: the 50 ms after redaction limit lock waiting, each lock is tried once even after expiry, and acquired recovery finishes with ordinary one-second Windows sharing retries. Token/device fences still precede moves. Other callers and the expired-diagnostic exclusive-create attempt remain unchanged. Failed acquisition preserves both files; release retries independently for one second and preserves completed values. Hooks borrow recovery locks with no other lease held.

`memory_lib/configuration.py` provides TASK-004's strict, offline configuration checks and effective defaults. Its packaged `configuration.schema.json` stays byte-identical to the stage 06 schema, checked by tests, so the skill can travel without the repository's docs. The validator rejects unsupported schema keywords and remote references. Defaults and the host-derived temporary-device flag stay separate from the original document; missing consent, an unaccepted consent version or a disabled project cannot enable recording. Invalid fields have deterministic paths that omit values and dynamic map keys. JSON Schema integers include finite numbers with no fractional part, including `1.0`; effective integer fields become Python integers.

`memory_lib/store.py` reads and validates `store.json` before configuration access, restores readable backups, and blocks other store access for an unknown format, a migration or an unrecoverable record. It never rolls an opaque newer record back to an older backup, and a schema-invalid configuration never restores old consent from a backup. Configuration writes hold the store lease and check its token and device before shared mutations, including retries of a file move. `memory_lib/diagnostics.py` provides TASK-005's daily failure lines and hook timings under their log leases. It accepts only fixed codes or built-in exception kinds and validated metadata, never exception text or paths, creates no directories, and skips a write when its deadline or lease is lost. Callers still gate work on consent and enabled projects and supply the hook start time. Blocked stores produce no diagnostic reads or writes: commands return `store-newer` or `store-damaged`, and a readable store backup is restored before `restored` can be logged. These tests exercise the library and a quiet subprocess caller; C1 hook and command integration comes in later tasks.

Store reads require the caller's absolute operation deadline. Recovery uses the public reading and file-parser functions under store.lock; a caller already holding that lease supplies it explicitly. Permission and other operational I/O errors propagate for internal command handling; only missing/unparseable records with no recovery become store-damaged. RestoreNeeded is explicitly handled as RuntimeError, and lock contention remains lock-busy.

Diagnostic store reads and any recovery finish before the log lease. Under that lease, guards check the header file identity, size and mtime without reading/restoring it, retaining the deadline/token/change fence. Known LockBusy/LostLock classes and class-name notices map to lock-busy/lost-lock; other class names retain the fixed-code/built-in rules. Configuration and timing lease-release failures use the failure logger when the caller deadline still permits it; releasing the failure log never reports recursively.

Configuration patterns use engine-independent character classes, with printable ASCII price-page URLs; a Node ECMA-u parity test checks the same boundary values as Python. TC-011/012/014 retain passing library evidence but remain not run until their hook/status entry-point tasks execute them. The failure logger also accepts the worker code string lost-lock; additional model/sync codes remain later work.

Recovery readers optionally revalidate caller state after acquisition and before moves. Configuration recovery checks the store gate and lease device before any locked configuration read; a changed device in a header backup is rejected before restoration. Daily diagnostic append/recovery/open retries receive the original absolute deadline, including Windows backup sharing failures.

`memory_lib/projects.py` prepares TASK-006 using only the user's project list and directory metadata. It resolves the session folder and each registered primary/repository folder, walks the session's real ancestors from deepest to shallowest, and compares device/file identities without spelling or case folding. A tie at the winning folder between projects is `project-clash`; aliases of one project are one owner. `find()` also requires current consent and an enabled project, so a disabled deeper project never falls back to an enabled parent. `locate()` retains the registered match for the later retention-worker decision. Missing/unreadable lists give `no-project-list`, and repository project settings are never opened. Exclusions use kinds and folders relative to the project's primary folder, resolved by directory identity; a missing exclusion creates nothing and takes effect when the folder exists. Callers pass the store/configuration gate first and handle the safe errors through diagnostics. The existing project registry accepts one UTF-8 BOM, matching the legacy readers; memory-store JSON remains strict UTF-8. Entries with invalid string names still take part in folder matching; a deepest invalid winner gives no project rather than falling back to an enabled parent.

`memory_lib/redaction.py` prepares TASK-007's six steps in stage 06's order: (1) normalize unpaired surrogates to U+FFFD, preserve valid pairs, count normalized UTF-8 bytes and cut a 520 KiB guard window; (2) ASCII-case-insensitive private spans; (3) private-key blocks; (4) longest-first exact environment values of at least 12 characters, normalized identically, with memory keys taking their own label; (5) the canonical patterns; and (6) a final 512 KiB character-safe cut. If the guard cut the source, step 6 first drops output from after the source 512 KiB point while retaining a mark starting before it. Earlier shrinking cannot bring an uncertain guard fragment into the entry. With an uncut source the existing final-cut behavior remains. `cut` gives the normalized byte size before step 1's cut whenever either cut removed text. Errors propagate; future callers must neither write nor send source text on failure. The transformer writes, sends and logs nothing. The private-key name fields on BEGIN and END each have a 40-character bound; JWT requires a preceding character outside the base64url alphabet. Code patterns match both stage-06 language copies byte for byte. Tests generate key-shaped values only in memory. `tests/bench_memory_redaction.py` measures exactly 524,288 UTF-8 bytes per input, an empty environment, one warm-up and ten complete calls on each checked OS/Python, reporting only names, counts and median/maximum times. Four adversarial inputs cover private-key BEGIN and END names, repeated eyJ and base64 JSON without dots. Imports and input construction are excluded. Size-growth tests check the patterns without letting the guard window hide growth; whole-hook deadlines remain later integration QA. The 0.1.0 base formatter is preserved.

`memory_lib/raw_log.py` applies TASK-060 to TASK-008's per-host/session appends and turn markers. Redaction runs once; its following 50 ms limit only raw/store-record recovery lock waiting, with one attempt at each even after expiry. An acquired raw lease finishes the tail read, append and marker past the hook deadline. Read backwards at most 8 MiB, splitting only new blocks and joining fragments once, without per-block/per-line lease or header reads. A missing raw file uses the same bounded reader for its backup, with the existing locked recheck and guarded recovery move. Empty logs start at seq 1. Without a complete positive-seq line, a window that misses the file start gives no append and damaged-line/error; a whole-file read starts at seq 1 on a new line, skips/counts damage and returns ok. Where a complete seq line exists, parsed cut-tail/turn-invalid sequences remain reserved. Without a turn-defining entry in the window, an answer starts a new turn. Lease/store identity checks immediately fence shared open/write/rollback and marker creation; Windows sharing failures use the ordinary one-second retry. New turns create markers exclusively; joined answers check a known marker directly or scan names. Recording has no deadline result; a foreign lock not acquired gives lock-busy. A returned append remains even if its marker fails. Notices are written by the caller after release and no directories are provisioned. TC-029–032, TC-322–324 and TC-326 cover real interrupted writers/contention, late completion, first attempts and the size bound.

`memory_lib/context.py` holds the unchanged 0.1.0 base formatter. The legacy session-start entry remains a compatibility wrapper; the new `scripts/hook.py` dispatches all four documented events through `memory_lib/hooks.py`. Input uses strict UTF-8 with one optional BOM and a single JSON object. Host precedence uses plugin-directory identity, then CLAUDECODE, then turn/prompt field presence. A readable store gate precedes diagnostics; bad-input and unknown-host can log without consent, while raw entries/markers and hook timings retain their enabled-project gates. Recording-only hooks load no network client or SQLite. After expiry, diagnostics use the cached, rechecked store identity, one exclusive-create log-lock attempt and the expired file-operation deadline; no new retry budget is invented, and release retains its independent retry. Late failures keep their own codes; finish preserves its supplied outcome and ms show lateness. Hooks opt into best-effort diagnostics before calling the logger, so expiry during a header read or lock creation still gets one non-waiting acquisition attempt and a completed line under an acquired lease. Busy late locks are skipped without stale takeover or a new retry budget; ordinary logger callers retain strict deadlines. The dispatcher calls process even after expiry. Whole-hook deadlines never skip redaction or recording; a later step explicitly returns deadline only when it skips or shortens work named in stage 06's deadline table. TC-321 covers contention and header changes. TASK-010–012 connect prompt, final-answer and end-boundary recording to the dispatcher. Prompts are redacted once before their recording exclusions; missing answers and answer/boundary exclusions stop early. Redaction and recording run even when reached after hook expiry; completed C1 recording retains its supplied outcome. Recall, curation triggers and worker starts are deferred. The framework creates no store or project directories. Recording uses 50ms only for lock waiting. Missing raw/ or unprocessed/ folders are not recreated: only an exception-class failure is written, with no hook timing.


Recording hooks receive raw notices after lease release and then write diagnostics. The optional raw-log notice collector preserves existing library callers while letting the hook choose diagnostics and remaining steps after a recording failure.

Deadlines and hook elapsed time use `memory_lib/clock.py` and its `now()` backed by `time.perf_counter()`. The entry point samples the same counter before product imports so their cost is included. UTC timestamps and lease-age checks retain their wall clock.

## Project hub

`corthex-nexus` 0.1.0 has one skill, `corthex-hub`, with one script, `scripts/hub.py`. It turns the files the projects already have into one page for all of them, without a server. The NEXUS server in `nexus/` is optional and puts the same page on the user's own address.

- **Snapshot.** For each project in `~/.corthex/projects.json`, the script reads the stage sources that `.corthex/project.json` names, also in the project's other repositories, and saves what they define and link: trace IDs with their titles and fields, the file and line of each, the links between them, and the checks. A project is read only under the name it is registered with: when its `.corthex/project.json` gives another name, or an unregistered folder gives a registered project's name, the script reads nothing and says why, so a repository's settings cannot save or send its items under another project's name. It reads text only and never runs project code: Git comes from an absolute folder in PATH, never from the current folder, and runs without the repository's fsmonitor hook, clean filters or optional locks, and without looking inside submodules, so reading a repository's state starts none of its programs and rewrites nothing. When a tracked file uses a clean filter, such as Git LFS, the snapshot does not say whether the working tree has changes. It skips files whose names, or whose folders' names, look like secrets, also when a link leads to them, and translations beside their originals, such as `spec.ko.md` beside `spec.md`, when they define only the original's IDs, so those are not defined twice. The forms it reads and the checks are in [reading.md](../plugins/corthex-nexus/skills/corthex-hub/references/reading.md).
- **Progress.** A stage's state, last checkpoint and next action come only from what was recorded with `hub.py status`, because a file that exists is not a finished stage. `done` is refused without a checkpoint and its date. Findings of a review are recorded the same way.
- **Page.** `hub.py build` writes `~/.corthex/hub/index.html`: for each project the 13 stages with their states and counts, the checks, each stage's settings and items, a trace view for every ID (what it comes from and what it leads to), and search. The data is inside the page, its Content Security Policy blocks every request, and it shows text only as text, so it works from the disk and offline. It follows the profile's language, Korean or English, and the system's light or dark mode. A saved snapshot of a project that is no longer in `~/.corthex/projects.json` stays on the disk but is left off the page.
- **What leaves the machine.** Nothing, unless the user runs `hub.py push`. A snapshot holds IDs, titles, fields, checks, file locations relative to their repositories and commit IDs. It holds no other file contents and no local paths, secrets and email addresses in titles become `[redacted]`, and a link that holds one is left out. The formats are in [snapshot.md](../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md).
- **Push.** `hub.py push` sends the snapshots of the projects listed in the profile's `nexus.push` to `nexus.url`, over HTTPS, with a Cloudflare Access service token from environment variables. It does not follow redirects, so a refused token is reported instead of sent on, and it shows the server's reason when a snapshot is refused. `hub.py remove` deletes a project from the server.
- **Server.** `nexus/` is a Cloudflare Worker with a Cloudflare D1 database, which the user deploys on their own Cloudflare account. It answers only requests that Cloudflare Access checked, through `ctx.access`, so a Worker without Access shows nothing. It has no `workers.dev` or preview addresses and no static assets, which would take that check away. It checks each snapshot against the format, keeps the newer snapshot of each project, up to 30 projects of 1 MiB, and serves the same page with a policy that allows only its own script, by its hash. All database code is in one file, so another database can replace D1 later. Setup: [nexus/README.md](../nexus/README.md).

Checked so far: `tests/test_hub.py` builds a project from the stage skills' own output templates and checks every item, link and finding the hub reads from them, then each source form, the status file, the page and the push client against a local stand-in server. It passes on Linux with Python 3.8 and 3.13. The page was opened in Chromium at 1440 and 320 pixels wide, in light and dark mode, with no script errors, no sideways scrolling and no network requests. A real project spread over three repositories, with requirements exported from Notion, was read without changing it. Windows and macOS have not been run yet.

For the server, `nexus/test/` checks the Worker over an in-memory SQLite stand-in for D1, and `tests/test_nexus.py` runs it on the machine: `hub.py` pushes a project made from the stage templates, reads it back, has an older snapshot refused and removes the project, and without Access every request gets `403`. With Wrangler 4.152.0, `wrangler deploy --dry-run` bundles the Worker, and `wrangler dev` ran the same steps in the Workers runtime with Access simulated, and returned `403` without it. The snapshot of the real project, 92 items and about 40 KB, passed the server's checks and came back unchanged. On 2026-10-24 the server was deployed on the maintainer's own address behind Cloudflare Access: requests without a sign-in were sent to the Access sign-in, a sign-in from a phone reached the page, and a push with a service token stored a sample project.

## Versions and releases

- Versions are semantic. The version appears in both manifests and in every skill's `metadata.version`, and the tests keep them equal.
- A release is a Git tag named `<plugin>--v<version>`, such as `corthex--v0.1.0`. `claude plugin tag` creates it after checking that the manifest and the marketplace entry agree.
- Users get updates through their host's marketplace commands.

## Checks

| Check | Command | Covers |
| --- | --- | --- |
| Repository checks | `python -m unittest discover -s tests -v` | manifests and marketplaces, skill format, stage contract, the memory hook and its script, the hub script, its page and its push client, the `corthex-uxui` scripts (on made-up clips when FFmpeg is installed), the NEXUS server with `hub.py` when Node 22.13 or later is installed, links and translations of the docs, no secrets or private text |
| Server checks | `node --test nexus/test/*.test.js` | the NEXUS Worker: the Access check, snapshot checks, storage, the page and its security headers |
| Claude Code validation | `claude plugin validate --strict .`, then `claude plugin validate --strict plugins/<plugin>` for each plugin | Claude Code's own schema for the marketplace and the plugins |

CI runs the repository and server checks on Linux, Windows and macOS, and the Claude Code validation and a Wrangler build of the server on Linux, for every pull request and every push to `main`. It installs FFmpeg on Linux and Windows so the media check runs on made-up clips there; on macOS those tests are skipped. A pull request that changes `corthex-memory` or the Windows hook check also runs the memory hook in Claude Code and Codex on Windows, with Git Bash, with PowerShell 7 only and with Windows PowerShell 5.1 only, against a local stand-in for the model API.

## Roadmap

Planned, not in 0.1.0. Both need components the core plugin leaves out.

- `corthex-memory`, later versions: hooks that collect conversation records, summarize them into each project's current state and bring back what matters. The current state then joins the session start context. Requirements: [docs/02-prd/memory.md](02-prd/memory.md). User flows: [docs/03-user-flow/memory/](03-user-flow/memory/README.md). Functional spec: [docs/04-functional-spec/memory.md](04-functional-spec/memory.md). Memory store: [docs/05-erd/memory.md](05-erd/memory.md). Interfaces: [docs/06-api/memory.md](06-api/memory.md). Work breakdown: [docs/10-wbs/memory.md](10-wbs/memory.md).
- `corthex-nexus`, later versions: decided by its requirements, [docs/02-prd/nexus.md](02-prd/nexus.md). Editors for sitemaps and user flows on the NEXUS server, and an MCP server over the same data, are candidates there (decision D5). The server's storage can move from D1 to Postgres if memory comes to be shared across devices.

## Sources

Checked on 2026-10-23.

- Claude Code: [Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference), [Marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference), [Plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies), [Publish and distribute a plugin](https://code.claude.com/docs/en/plugins/publish), [Skills](https://code.claude.com/docs/en/skills)
- OpenAI: [Codex plugins](https://developers.openai.com/codex/plugins/build), [Submit your Claude Code plugin to OpenAI](https://developers.openai.com/plugins/guides/submit-claude-plugin), [Build skills](https://learn.chatgpt.com/docs/build-skills)
- Agent Plugins: [Plugin manifest](https://agent-plugins.org/plugin-authors/manifest), [Client extensions](https://agent-plugins.org/plugin-authors/client-extensions), [Compatible clients](https://agent-plugins.org/compatible-clients)
- Hooks: [Claude Code hooks reference](https://code.claude.com/docs/en/hooks), [Codex hooks](https://learn.chatgpt.com/docs/hooks), [openai/codex#39895](https://github.com/openai/codex/issues/39895)
- Cloudflare Access: [Authenticate agents](https://developers.cloudflare.com/cloudflare-one/access-controls/authenticate-agents/), [Service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
- Cloudflare Workers and D1: [Cloudflare Access for Workers](https://developers.cloudflare.com/workers/configuration/cloudflare-access/), [Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/), [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- [Agent Skills specification](https://agentskills.io/specification)
