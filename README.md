# CORTHEX

[한국어](README.ko.md)

CORTHEX is a plugin for Claude Code and Codex that helps one person run software projects with an AI collaborator, stage by stage: from domain discovery and requirements to screens, building, QA and the final presentation.

It does not add a service of its own. Installation and updates use the hosts' plugin marketplaces, and the core plugin is skills only. On top of that, CORTHEX adds three things:

- **Working principles** for the AI: lead with the result, keep facts and guesses apart, ask before anything that cannot be undone, and keep records.
- **A 13-stage workflow** in which every stage fills the same six slots (inputs, outputs, human view, sync, human checkpoints, trace IDs), so each artifact can be traced to the one before it.
- **A profile and a project registry**, so the same plugin fits different people and several projects at once.

Two optional plugins build on it. `corthex-memory` starts each session with the principles, your profile and the current project's settings. `corthex-nexus` puts the stages, checks and trace links of all your projects on one page.

> Status: 0.1.0, early development. The stage skills are outlines that will grow with real use. `corthex-memory` has session context and local recording hooks; C1 remains in progress. `corthex-nexus` has the local hub page and a first NEXUS server that you deploy yourself.

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

`corthex-memory` adds the working principles, your profile and the current project's settings at the start of each session. It stays on the local machine and makes no network calls. With an existing memory store, hook diagnostics contain only safe error codes; late failures keep their original codes. Late completion alone does not turn success into failure; hook deadlines skip or shorten only the specified later steps, and never skip redaction or recording. Without a store, nothing is written. It needs Python 3 on the PATH (it tries `python3`, `python` and the Windows `py` launcher), and with Claude Code on Windows also Git for Windows or PowerShell 7.

With an existing local memory store, consent and an enabled registered project, hooks also record prompts, final answers and session-end boundaries after redaction. These records stay on this machine; hooks create no memory store. Recording waits up to 50ms for another process's lock, then finishes reading, appending and its marker under the acquired lock, so a slow disk can take it past the whole-hook deadline.

```bash
claude plugin install corthex-memory@corthex   # Claude Code; installs corthex too
codex plugin add corthex-memory@corthex        # Codex, after corthex
```

In Codex, open `/hooks` once and trust the plugin's hook; Codex skips plugin hooks until you do. To stop it, disable or remove the plugin. Details: [Session start context](docs/architecture.md#session-start-context).

### Optional: project hub

`corthex-nexus` reads the stage sources of every registered project and writes one page, `~/.corthex/hub/index.html`, with each project's 13 stages, the checks on its trace IDs and the links between its items. Each stage shows the progress you recorded, such as its last checkpoint. The page works offline and loads nothing from the network.

```bash
claude plugin install corthex-nexus@corthex   # Claude Code; installs corthex too
codex plugin add corthex-nexus@corthex        # Codex, after corthex
```

Then ask for the hub, or run `/corthex-nexus:corthex-hub`. It needs Python 3.8 or later. It can also send project snapshots to a NEXUS server on your own domain, but only for the projects you list. The server is a Cloudflare Worker behind Cloudflare Access that you deploy on your own Cloudflare account: [nexus/](nexus/README.md). Details: [Project hub](docs/architecture.md#project-hub).

## Skills

| Skill | Stages | Use it to |
| --- | --- | --- |
| `corthex` | entry | set up your profile, register a project, see where a project stands and what comes next |
| `corthex-discover` | 01 | run event storming with you on a board such as Miro, step by step, and write the domain design: contexts, context map and glossary |
| `corthex-define` | 02–04 | write requirements, user flows and the functional spec |
| `corthex-contract` | 05–06 | keep the database schema and the API contract in line with the spec |
| `corthex-screen` | 07–09 | sitemap, screen states, mockups and design tokens |
| `corthex-build` | 10–12 | work breakdown, development and QA |
| `corthex-present` | 13 | script, scene table and slides for the presentation |
| `corthex-record` | any | minutes, decision log and progress records |
| `corthex-uxui` | 08, 09, 13, or on its own | turn design words into named parts and numbers for screens, motion and video, and measure line breaks, contrast, target size, flashes and loudness before showing the result |
| `corthex-hub` | all, in `corthex-nexus` | see every project's stages, checks and trace links on one page, and record each stage's progress |

## Profile and projects

- `~/.corthex/profile.json` holds how to address you, your language, where records go and what to ask about first. The `corthex` skill offers to create it. It never holds secrets.
- `.corthex/project.json` in each product repository says, stage by stage, where people look at the work (`human`), where the text source lives (`source`) and which side wins when they differ (`truth`).
- `~/.corthex/projects.json` lists the projects on one machine.
- `~/.corthex/hub/` holds the hub's snapshots, the progress you recorded and the page, when `corthex-nexus` is installed.

[The architecture notes](docs/architecture.md) explain the design and link to each format.

## Compatibility

- Claude Code reads `.claude-plugin/marketplace.json` and each plugin's `.claude-plugin/plugin.json`.
- Codex and other [Agent Plugins](https://agent-plugins.org) clients read `.agents/plugins/marketplace.json` and the core plugin's root `plugin.json`. `corthex-memory` has hooks, so it has `.codex-plugin/plugin.json` instead and works in Claude Code and Codex only. `corthex-nexus` has no hooks and keeps a root `plugin.json`.
- The skills follow the [Agent Skills](https://agentskills.io) format and are shared by both, so each skill can also be used on its own.
- `corthex-uxui` has two optional check scripts, which only read. `page-check.js` runs inside the page under test, pasted into the browser's console or passed to a browser automation tool such as Playwright; `media-check.py` needs Python 3.8 or later and FFmpeg.

## Development

See [Contributing](CONTRIBUTING.md) for the branch, commit, PR and release rules.

```bash
python -m unittest discover -s tests -v
claude plugin validate --strict .
claude plugin validate --strict plugins/corthex
claude plugin validate --strict plugins/corthex-memory
claude plugin validate --strict plugins/corthex-nexus
node --test nexus/test/*.test.js     # Node 22.13 or later
```

## License

[Apache-2.0](LICENSE). See [NOTICE](NOTICE).
