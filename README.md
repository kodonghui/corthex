# CORTHEX

[한국어](README.ko.md)

CORTHEX is a plugin for Claude Code and Codex that helps one person run software projects with an AI collaborator, stage by stage: from domain discovery and requirements to screens, building, QA and the final presentation.

It does not add a service of its own. Installation and updates use the hosts' plugin marketplaces, and the core plugin is skills only. On top of that, CORTHEX adds three things:

- **Working principles** for the AI: lead with the result, keep facts and guesses apart, ask before anything that cannot be undone, keep records, and keep the field's standard terms.
- **A 13-stage workflow** in which every stage fills the same six slots (inputs, outputs, human view, sync, human checkpoints, trace IDs), so each artifact can be traced to the one before it.
- **A profile and a project registry**, so the same plugin fits different people and several projects at once.

Two optional plugins build on it. `corthex-memory` starts each session with the principles, your profile and the current project's settings. `corthex-nexus` puts the stages, checks and trace links of all your projects on one page.

> Status: core `corthex` 0.18.0; `corthex-memory` 0.2.1 is the C1 package with project approval context; release decisions and known limits are tracked in the MEMORY WBS and QA report; `corthex-nexus` is 0.6.0. The stage skills grow with real use. Memory model curation/recall are C2 work; NEXUS has its local hub and a first server you deploy yourself.

For a first run from installation to one reviewed requirement and a progress record, follow [Your first project](docs/first-project.md).

## Install

### Claude Code

```bash
claude plugin marketplace add kodonghui/corthex
claude plugin install corthex@corthex
```

Then start a session and say what you are working on, or run `/corthex:corthex`.

### Codex

```bash
codex plugin marketplace add kodonghui/corthex
codex plugin add corthex@corthex
```

### Optional: session start context

`corthex-memory` 0.2.0 adds session context and local conversation recording. Recording starts only after you accept the consent and turn it on for a registered project. It captures redacted prompts, final answers and session-end boundaries; tool calls, tool results and files are not recording inputs. C1 makes no model or network calls. Model curation, semantic search and recall are C2 work.

The memory store is `~/.corthex/corthex-memory/`, or the absolute directory in `CORTHEX_MEMORY_HOME`. Raw recordings use 100 days of retention by default; `retention` changes the period and a later session-start worker applies it. The `on` command creates a missing store. Hooks create none. Missing model keys do not prevent C1 recording; the management skill checks key presence and never asks for a key in chat.

Ask the memory skill to enable or stop recording, show status, exclude folders or entry kinds, change retention, delete all local memory, or repair its store record. Its C1 commands are `on`, `off`, `status`, `leave-out`, `retention`, `purge` and `repair`. It shows a proposal and obtains your yes before a confirmation code is applied. Unverifiable purge metadata is shown as unknown alongside the exact folder. `off` keeps existing memory and retention continues; removing the plugin also keeps the store. Confirmed `purge` deletes only that local folder, while host transcripts and any outside copies remain.

Python 3.8 or later must be on PATH (the hooks try `python3`, `python` and the Windows `py` launcher). Claude Code on Windows also needs Git for Windows or PowerShell 7. Hook diagnostics contain safe metadata and error codes; the acquired recording lock is held until its read, append and marker finish, even beyond a hook deadline.

```bash
claude plugin install corthex-memory@corthex   # Claude Code; installs corthex too
codex plugin add corthex-memory@corthex        # Codex, after corthex
```

In Codex, open `/hooks` and review and trust the plugin's hooks. Manage recording with the [memory skill](plugins/corthex-memory/skills/corthex-memory/SKILL.md). The C1 0.2.0 release passed installed-host QA and its release decision; the maintainer removed the C1 one-week trial on 2026-11-04. See the [release qualification](docs/12-qa/runs/2026-11-04-memory-020-release.md). Details: [Session start context](docs/architecture.md#session-start-context).

### Optional: project hub

`corthex-nexus` reads the stage sources of every registered project and writes one page, `~/.corthex/hub/index.html`, with each project's 13 stages, the checks on its trace IDs and the links between its items. Each stage shows the progress you recorded, such as its last checkpoint. The page works offline and loads nothing from the network.

```bash
claude plugin install corthex-nexus@corthex   # Claude Code; installs corthex too
codex plugin add corthex-nexus@corthex        # Codex, after corthex
```

Then ask for the hub, or run `/corthex-nexus:corthex-hub`. It needs Python 3.8 or later. It can also send project snapshots to a NEXUS server on your own domain, but only for the projects you list. The server and browser application now live in the separate product repository, with an approved Node/SQLite runtime behind Access and a Tunnel and retained Worker compatibility: [nexus/](https://github.com/kodonghui/corthex-nexus/blob/codex/nexus-0.2/nexus/README.md). Details: [Project hub](docs/architecture.md#project-hub).

For an authorized server, the core entry and stage skills read agent work at a session's start, again once a day has passed and before each checkpoint request, keep your explicit task first and coordinate claims, accepted changes and checkpoint records through the hub. Missing credentials leave local work available. The first real snapshot send still requires your confirmation. See the [NEXUS workflow](plugins/corthex/skills/corthex/references/nexus-work.md).

## Skills

| Skill | Stages | Use it to |
| --- | --- | --- |
| `corthex` | entry | set up your profile, register a project, see where a project stands and what comes next, and change approved work: a feature change goes through every stage again from 01, and each approved item it drops is asked about on its own |
| `corthex-discover` | 01 | run event storming with you on a board such as Miro, step by step, and write the domain design: contexts, context map and glossary, whose DDD board NEXUS then draws |
| `corthex-define` | 02–04 | write requirements, user flows and the functional spec |
| `corthex-contract` | 05–06 | keep the database schema and the API contract in line with the spec |
| `corthex-screen` | 07–09 | sitemap, screen states, mockups and design tokens, starting from IBM Carbon's tokens |
| `corthex-build` | 10–12 | work breakdown, development and QA with browser, desktop and Android walks, a release gate, after-release checks and one Markdown file per bug |
| `corthex-present` | 13 | script, scene table and slides for the presentation |
| `corthex-record` | any | minutes, decision log, progress records and retrospectives |
| `corthex-uxui` | 08, 09, 13, or on its own | turn design words into named parts and numbers for screens, motion and video, and measure line breaks, contrast, target size, flashes and loudness before showing the result |
| `corthex-study` | any, or on its own | turn one learning question into a study page and a record: read your material, check primary sources, run code or a measured experiment, and write it plainly enough for a high-school student |
| `corthex-diagram` | any, or on its own | draw flows, structures, comparisons and changes in one visual grammar, where the shape says what a box is and the line says what happens to data, in Mermaid that GitHub and Notion draw, and lint it before it goes out; draw how an index, a data structure or an algorithm works as a concept figure, with every node in a fixed place, layer by layer and step by step |
| `corthex-hub` | all, in `corthex-nexus` | see every project's stages, checks and trace links on one page, and record each stage's progress |

## Profile and projects

- `~/.corthex/profile.json` holds how to address you, your language, where records and study documents go, and what to ask about first. The `corthex` skill offers to create it. It never holds secrets. By default you answer every stage's checkpoint. With `checkpoints` you name the stages whose checkpoints you answer in person and a delegate who answers the others; what you listed in `ask_before`, anything that cannot be undone, the release decision, and a merge or a deploy that you did not hand over in your own words still come to you.
- `.corthex/project.json` in each product repository says, stage by stage, where people look at the work (`human`), where the text source lives (`source`) and which side wins when they differ (`truth`).
- `~/.corthex/projects.json` lists the projects on one machine.
- `~/.corthex/hub/` holds the hub's snapshots, the progress you recorded and the page, when `corthex-nexus` is installed.

When records go to Notion, the project's `records.location` or the profile's `records.hub` points to the records database. Records are rows, and tables inside a record are inline databases. See the [record skill](plugins/corthex/skills/corthex-record/SKILL.md).

[The architecture notes](docs/architecture.md) explain the design and link to each format.

## Compatibility

- Claude Code reads `.claude-plugin/marketplace.json` and each plugin's `.claude-plugin/plugin.json`.
- Codex and other [Agent Plugins](https://agent-plugins.org) clients read `.agents/plugins/marketplace.json` and the core plugin's root `plugin.json`. `corthex-memory` has hooks, so it has `.codex-plugin/plugin.json` instead and works in Claude Code and Codex only. `corthex-nexus` has no hooks and keeps a root `plugin.json`.
- The skills follow the [Agent Skills](https://agentskills.io) format and are shared by both, so each skill can also be used on its own.
- Work that needs a real browser or a desktop app uses programs you install yourself, in this order: Aside for web pages, with sign-ins and sign-ups through Aside Vault, then ego lite or Playwright; agent-desktop for desktop apps; and the host's computer use only where neither can do the job and you have said yes for that task. See [the computer-and-web reference](plugins/corthex/skills/corthex/references/computer-and-web.md).
- `corthex-uxui` has two optional check scripts, which only read. `page-check.js` runs inside the page under test, pasted into the browser's console or passed to a browser automation tool such as Playwright; `media-check.py` needs Python 3.8 or later and FFmpeg.
- The entry skill `corthex` has one check script, `term-check.py`, which only reads and needs Python 3.8 or later. Before a Korean document, record, prompt or handoff goes out, it finds coined native words used in place of a field's standard terms, such as `길` for `경로` (path), in Markdown, HTML or plain text.
- `corthex-diagram` has one check script, `diagram-check.py`, which only reads and needs Python 3.8 or later. It checks Mermaid flowcharts, in `.mmd` files or in Markdown, against the skill's visual grammar: box kinds and shapes, lines into and out of stores, labelled branches, the legend, Korean line breaks and text contrast. A flowchart of a structure, such as a context map, says `%% grammar: structure` and is checked only for its syntax, line breaks and contrast. A second script, `concept-figure.py`, draws concept figures, such as an HNSW search over three layers, from a JSON spec as SVG, writing only the path it is given. It checks first that every move follows a link on its layer and that every node shown is on that layer.

## Working with NEXUS

When your profile names your NEXUS server, NEXUS is where you look at a project's work: the DDD board, the ERD and the sitemap as pictures, and every other stage as a list, where you talk about the items and pass the checkpoints. For each new project the entry skill asks you once whether to put it on NEXUS; on your yes it adds the project to your push list, and it sends the first snapshot once you have seen what it would send and said yes to that too. The stage skills then merge a stage's draft of documents, send it and ask for the checkpoint with the stage's NEXUS address. Event storming still runs its steps on a Miro board, because NEXUS draws a DDD board only once the contexts have IDs and cannot edit yet; from the third checkpoint on, you review the board in NEXUS. Without a NEXUS server, each stage proposes the tool in its contract, and nothing is said about NEXUS.

For a configured NEXUS project, the entry and stage skills use the installed hub to read work at a session's start, again once a day has passed and before each checkpoint request. A session that cannot send for a project that is expected on a NEXUS server says so once, in one line that names what is missing, and goes on with your work. Do the user's current request first, then comments, discrepancies, reflections and checkpoints. Missing credentials or an unavailable server do not stop local work. Respect claims/open PRs and the repository's PR rules for decisions, reflections and stage records. The first real send has its own confirmation. A checkpoint is asked for one stage at a time, in at most ten lines with one thing to look at first, and a stage of screens comes with something to press; you are told once when building starts and each time a stage passes; and a browser walk of your NEXUS pages leaves your own presses to you. [NEXUS workflow](plugins/corthex/skills/corthex/references/nexus-work.md).

The current NEXUS hub is 0.4.0. Server/browser setup, migration and rollback belong to [the separate product repository](https://github.com/kodonghui/corthex-nexus/blob/codex/nexus-0.2/nexus/README.md). Upgrade the server to a0.2-compatible runtime before the hub. A comment on a stage without a picture and the hub's `--asks` need the redesign's server; a 0.2 server refuses them and takes the rest as before. The design revision's commands of 0.4.0 also work with a server of before: there `todo` keeps no session read, a checkpoint request goes without `look_first`, with the thing to look at first as the text's last line, and `remove` shows the server's dry run, each with the remark `server-older`. Until the server of the revision runs, a project cannot be removed with this hub; after it, the user removes a project in NEXUS under their own sign-in. The Node/SQLite runtime stays behind Access and a Tunnel, with the Worker/D1 compatibility path retained. Package numbers here do not assert a published tag or a production switch.

## Development

See [Contributing](CONTRIBUTING.md) for the branch, commit, PR and release rules.

```bash
python -m unittest discover -s tests -v
claude plugin validate --strict .
claude plugin validate --strict plugins/corthex
claude plugin validate --strict plugins/corthex-memory
claude plugin validate --strict plugins/corthex-nexus
```

## License

[Apache-2.0](LICENSE). See [NOTICE](NOTICE), which also credits the IBM Carbon design tokens that stage 09 copies.
