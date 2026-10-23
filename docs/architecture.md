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
│   │       └── corthex-record/          minutes, decisions, progress
│   ├── corthex-memory/                  session start context, with a hook
│   │   ├── .claude-plugin/plugin.json   manifest for Claude Code
│   │   ├── .codex-plugin/plugin.json    manifest for Codex; no root plugin.json
│   │   ├── hooks/hooks.json             one SessionStart hook, read by both hosts
│   │   ├── scripts/session_start.py     builds the context, Python standard library only
│   │   ├── context/principles.md        short form of the working principles
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

So the core plugin has no hooks, commands, agents, MCP servers or user settings. Anything that needs them goes into a separate plugin, and `tests/test_manifests.py` enforces the rule.

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

`corthex-nexus` adds one more skill, `corthex-hub` (see [Project hub](#project-hub)).

- **Eight skills, not fourteen.** Hosts show every skill's description in each session, and Codex caps that first list at 2% of the context window (8,000 characters when the window is unknown). Grouping keeps the list short. The details of each stage sit in `references/` and are read only when needed.
- **Names start with `corthex-`** so they stay distinct when a skill is used outside the plugin. Inside the plugin, both hosts show them as `corthex:<skill>`.
- **Frontmatter is portable.** Skills use only the fields of the Agent Skills format (`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`), because claude.ai uploads and the Skills API reject host-specific fields. Bodies stay under 500 lines, and links stay inside the skill's own folder, one level deep.
- **Skill text is English.** Replies follow the language in the user's profile.

Measured on 0.1.0 with local installs: `claude plugin details` (Claude Code 2.1.309) reports about 1,000 always-on tokens for the eight descriptions, and in Codex CLI 0.164.0 the eight entries take about 3,200 characters of the skill list.

## Working principles

Claude Code does not load a `CLAUDE.md` at a plugin's root as context, and its documentation says to put such instructions in a skill. So the principles live in the entry skill, in [principles.md](../plugins/corthex/skills/corthex/references/principles.md), and apply while a CORTHEX skill is in use.

The `corthex-memory` plugin adds a short version at the start of each session with a hook, for people who install it (see [Session start context](#session-start-context)). CORTHEX itself never edits the user's global instruction files.

## Stage contract

Every stage fills six slots: inputs, outputs, human view, sync, human checkpoints and trace IDs. Each stage's text source stays in the product repository. The human view (Notion, Miro, an ERD tool, Figma and so on) can differ from team to team, and the project's settings say which side is the truth for each stage.

- The contract, the stage keys and the trace ID rules: [stage-contract.md](../plugins/corthex/skills/corthex/references/stage-contract.md).
- Each stage's slots, steps, checks and output template: `references/<stage>.md` in the stage skill, such as [02-prd.md](../plugins/corthex/skills/corthex-define/references/02-prd.md).
- `tests/test_stages.py` checks that every stage fills all six slots, that each stage skill links its stages, and that all stage skills share one procedure.

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
- **Windows.** The hook command tries `python3`, then `python`, joined by `||`. On Windows, Claude Code runs hook commands in Git Bash, or in PowerShell when Git Bash is missing. PowerShell 7 accepts `||` but Windows PowerShell 5.1 does not, so with Claude Code on Windows the hook needs Git for Windows or PowerShell 7. Without either, the hook fails and the session starts without the context. The hook has not been run on Windows yet, in either host.
- **Checked so far.** On 2026-10-23, on Linux, with Claude Code 2.1.309 and Codex CLI 0.164.0 in isolated settings and a local stand-in for the model API:
  - The context reached the first model request in both hosts, without the title or the notes of the project file. Codex ran the hook only when it was trusted; the test skipped the review with `--dangerously-bypass-hook-trust`.
  - After the profile changed, a resumed session (`claude -p --resume`, `codex exec resume`) and a forked one (`claude -p --resume … --fork-session`) carried the new copy as well as the earlier ones from their history.
  - In Codex, a 28,872-byte test context reached the model whole with `additionalContextLimit` set to 8,000, and was replaced by a preview without it.

  Forking in Codex and macOS are not tested yet. The hook needs `python3` or `python` on the PATH of the shell that runs it.

## Project hub

`corthex-nexus` 0.1.0 has one skill, `corthex-hub`, with one script, `scripts/hub.py`. It turns the files the projects already have into one page for all of them, without a server. The NEXUS server in `nexus/` is optional and puts the same page on the user's own address.

- **Snapshot.** For each project in `~/.corthex/projects.json`, the script reads the stage sources that `.corthex/project.json` names, also in the project's other repositories, and saves what they define and link: trace IDs with their titles and fields, the file and line of each, the links between them, and the checks. It reads text only and never runs project code: Git runs without the repository's fsmonitor hook and without optional locks, so reading a repository's state starts none of its programs and rewrites nothing. It skips files whose names, or whose folders' names, look like secrets. The forms it reads and the checks are in [reading.md](../plugins/corthex-nexus/skills/corthex-hub/references/reading.md).
- **Progress.** A stage's state, last checkpoint and next action come only from what was recorded with `hub.py status`, because a file that exists is not a finished stage. `done` is refused without a checkpoint and its date. Findings of a review are recorded the same way.
- **Page.** `hub.py build` writes `~/.corthex/hub/index.html`: for each project the 13 stages with their states and counts, the checks, each stage's settings and items, a trace view for every ID (what it comes from and what it leads to), and search. The data is inside the page, its Content Security Policy blocks every request, and it shows text only as text, so it works from the disk and offline. It follows the profile's language, Korean or English, and the system's light or dark mode. A saved snapshot of a project that is no longer in `~/.corthex/projects.json` stays on the disk but is left off the page.
- **What leaves the machine.** Nothing, unless the user runs `hub.py push`. A snapshot holds IDs, titles, fields, checks, file locations relative to their repositories and commit IDs. It holds no other file contents and no local paths, and secrets and email addresses in titles become `[redacted]`. The formats are in [snapshot.md](../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md).
- **Push.** `hub.py push` sends the snapshots of the projects listed in the profile's `nexus.push` to `nexus.url`, over HTTPS, with a Cloudflare Access service token from environment variables. It does not follow redirects, so a refused token is reported instead of sent on, and it shows the server's reason when a snapshot is refused. `hub.py remove` deletes a project from the server.
- **Server.** `nexus/` is a Cloudflare Worker with a Cloudflare D1 database, which the user deploys on their own Cloudflare account. It answers only requests that Cloudflare Access checked, through `ctx.access`, so a Worker without Access shows nothing. It has no `workers.dev` or preview addresses and no static assets, which would take that check away. It checks each snapshot against the format, keeps the newer snapshot of each project, up to 30 projects of 1 MiB, and serves the same page with a policy that allows only its own script, by its hash. All database code is in one file, so another database can replace D1 later. Setup: [nexus/README.md](../nexus/README.md).

Checked so far: `tests/test_hub.py` builds a project from the stage skills' own output templates and checks every item, link and finding the hub reads from them, then each source form, the status file, the page and the push client against a local stand-in server. It passes on Linux with Python 3.8 and 3.13. The page was opened in Chromium at 1440 and 320 pixels wide, in light and dark mode, with no script errors, no sideways scrolling and no network requests. A real project spread over three repositories, with requirements exported from Notion, was read without changing it. Windows and macOS have not been run yet.

For the server, `nexus/test/` checks the Worker over an in-memory SQLite stand-in for D1, and `tests/test_nexus.py` runs it on the machine: `hub.py` pushes a project made from the stage templates, reads it back, has an older snapshot refused and removes the project, and without Access every request gets `403`. With Wrangler 4.152.0, `wrangler deploy --dry-run` bundles the Worker, and `wrangler dev` ran the same steps in the Workers runtime with Access simulated, and returned `403` without it. The snapshot of the real project, 92 items and about 40 KB, passed the server's checks and came back unchanged. The server has not been deployed to Cloudflare yet.

## Versions and releases

- Versions are semantic. The version appears in both manifests and in every skill's `metadata.version`, and the tests keep them equal.
- A release is a Git tag named `<plugin>--v<version>`, such as `corthex--v0.1.0`. `claude plugin tag` creates it after checking that the manifest and the marketplace entry agree.
- Users get updates through their host's marketplace commands.

## Checks

| Check | Command | Covers |
| --- | --- | --- |
| Repository checks | `python -m unittest discover -s tests -v` | manifests and marketplaces, skill format, stage contract, the memory hook and its script, the hub script, its page and its push client, the NEXUS server with `hub.py` when Node 22.5 or later is installed, links and translations of the docs, no secrets or private text |
| Server checks | `node --test nexus/test/*.test.js` | the NEXUS Worker: the Access check, snapshot checks, storage, the page and its security headers |
| Claude Code validation | `claude plugin validate --strict .`, then `claude plugin validate --strict plugins/<plugin>` for each plugin | Claude Code's own schema for the marketplace and the plugins |

CI runs the repository and server checks on Linux, Windows and macOS, and the Claude Code validation and a Wrangler build of the server on Linux, for every pull request and every push to `main`.

## Roadmap

Planned, not in 0.1.0. Both need components the core plugin leaves out.

- `corthex-memory`, later versions: hooks that collect conversation records, summarize them into each project's current state and bring back what matters. The current state then joins the session start context.
- `corthex-nexus`, later versions: editors for sitemaps and user flows on the NEXUS server, and an MCP server over the same data. The server's storage can move from D1 to Postgres if memory comes to be shared across devices.

## Sources

Checked on 2026-10-23.

- Claude Code: [Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference), [Marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference), [Plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies), [Publish and distribute a plugin](https://code.claude.com/docs/en/plugins/publish), [Skills](https://code.claude.com/docs/en/skills)
- OpenAI: [Codex plugins](https://developers.openai.com/codex/plugins/build), [Submit your Claude Code plugin to OpenAI](https://developers.openai.com/plugins/guides/submit-claude-plugin), [Build skills](https://learn.chatgpt.com/docs/build-skills)
- Agent Plugins: [Plugin manifest](https://agent-plugins.org/plugin-authors/manifest), [Client extensions](https://agent-plugins.org/plugin-authors/client-extensions), [Compatible clients](https://agent-plugins.org/compatible-clients)
- Hooks: [Claude Code hooks reference](https://code.claude.com/docs/en/hooks), [Codex hooks](https://learn.chatgpt.com/docs/hooks), [openai/codex#39895](https://github.com/openai/codex/issues/39895)
- Cloudflare Access: [Authenticate agents](https://developers.cloudflare.com/cloudflare-one/access-controls/authenticate-agents/), [Service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
- Cloudflare Workers and D1: [Cloudflare Access for Workers](https://developers.cloudflare.com/workers/configuration/cloudflare-access/), [Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/), [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- [Agent Skills specification](https://agentskills.io/specification)
