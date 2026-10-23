# Architecture

[한국어](architecture.ko.md)

How CORTHEX is put together, and why. The file formats are defined once, in the entry skill's references, and this page links to them instead of repeating them.

Status: 0.1.0. The core plugin, `corthex`, exists, and so does the first part of `corthex-memory`: the session start context. The rest of `corthex-memory` and `corthex-nexus` are planned (see [Roadmap](#roadmap)).

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
│   └── corthex-memory/                  session start context, with a hook
│       ├── .claude-plugin/plugin.json   manifest for Claude Code
│       ├── .codex-plugin/plugin.json    manifest for Codex; no root plugin.json
│       ├── hooks/hooks.json             one SessionStart hook, read by both hosts
│       ├── scripts/session_start.py     builds the context, Python standard library only
│       ├── context/principles.md        short form of the working principles
│       └── LICENSE, NOTICE
├── tests/                               checks, Python standard library only
└── docs/
```

## Two manifests, one set of skills

Claude Code reads a plugin's manifest from `.claude-plugin/plugin.json`. Codex and the other Agent Plugins clients read `plugin.json` at the plugin root, and Codex takes its own settings from `extensions.com.openai` in that file. Agent Plugins 1.0 does not list Claude Code among its compatible clients, so the plugin keeps both files. They share one `skills/` folder.

A plugin with hooks is the exception. Codex CLI 0.164.0 does not run a plugin's hooks when the plugin has a root `plugin.json`, even with `.codex-plugin/plugin.json` beside it ([openai/codex#39895](https://github.com/openai/codex/issues/39895), reproduced on 2026-10-23). Without a root `plugin.json`, Codex reads `.codex-plugin/plugin.json` and finds `hooks/hooks.json` on its own. So `corthex-memory` has `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`, and no root `plugin.json`. It therefore does not go to other Agent Plugins clients or to OpenAI's directory, which does not take plugins with hooks anyway.

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

The memory plugin installs the same way, as `corthex-memory@corthex`. It declares `corthex` as a dependency, so Claude Code installs both; in Codex, add both.

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

`corthex-memory` 0.1.0 has one hook. When a session starts, after `/clear` and after compaction, `scripts/session_start.py` adds a short context. It skips resumed and forked sessions, whose history already holds it. The context has:

- the working principles in short form, which `tests/test_memory.py` keeps equal to the list in the entry skill;
- the profile from `~/.corthex/profile.json`, or the defaults when there is none;
- the project: the nearest `.corthex/project.json` up to the repository root, or else the project in `~/.corthex/projects.json` whose path or repository holds the current folder. For each stage it gives the human view, the truth and the source, with notes cut to 160 characters. Other projects on the machine are listed by name.

It reads only those files, writes nothing and makes no network calls. Each value is put on one line and the project settings are marked as data, so a note cannot add headings or instructions of its own. The context stays under 8,000 characters and about 2,000 tokens, because Claude Code moves hook output over 10,000 characters into a file and Codex does so over about 2,500 tokens. Notes are dropped first, then the text is shortened. If anything fails, the hook adds nothing and the session starts as usual.

- **Codex asks for trust.** Codex runs a plugin's hooks only after you review and trust them in `/hooks`: once after installing, and again after an update changes the hook.
- **Stopping it.** Disable or remove the plugin. In Claude Code, run `claude plugin disable corthex-memory@corthex`. In Codex, set `enabled = false` under `[plugins."corthex-memory@corthex"]` in `~/.codex/config.toml`, or run `codex plugin remove corthex-memory@corthex`. The hook stores nothing, so there is nothing else to undo.
- **Checked so far.** On Linux, with Claude Code 2.1.309 and Codex CLI 0.164.0 in isolated settings and a local stand-in for the model API, the context reached the first model request in both hosts. Codex ran the hook only when it was trusted; the test skipped the review with `--dangerously-bypass-hook-trust`. A resumed session (`claude -p --resume`, `codex exec resume`) carried the context once, from its history, in both hosts. Forked sessions, Windows and macOS are not tested yet. The hook needs `python3` or `python` on the PATH of the shell that runs it; on Windows, Claude Code runs hooks in Git Bash, or in PowerShell when Git Bash is missing.

## Versions and releases

- Versions are semantic. The version appears in both manifests and in every skill's `metadata.version`, and the tests keep them equal.
- A release is a Git tag named `<plugin>--v<version>`, such as `corthex--v0.1.0`. `claude plugin tag` creates it after checking that the manifest and the marketplace entry agree.
- Users get updates through their host's marketplace commands.

## Checks

| Check | Command | Covers |
| --- | --- | --- |
| Repository checks | `python -m unittest discover -s tests -v` | manifests and marketplaces, skill format, stage contract, the memory hook and its script, links and translations of the docs, no secrets or private text |
| Claude Code validation | `claude plugin validate --strict .`, then `claude plugin validate --strict plugins/<plugin>` for each plugin | Claude Code's own schema for the marketplace and the plugins |

CI runs the repository checks on Linux, Windows and macOS, and the Claude Code validation on Linux, for every pull request and every push to `main`.

## Roadmap

Planned, not in 0.1.0. Both need components the core plugin leaves out.

- `corthex-memory`, later versions: hooks that collect conversation records, summarize them into each project's current state and bring back what matters. The current state then joins the session start context.
- `corthex-nexus` (optional): an MCP server with app screens for a hub of all projects and for editing sitemaps and flows, run by the user on their own domain.

## Sources

Checked on 2026-10-23.

- Claude Code: [Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference), [Marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference), [Plugin dependencies](https://code.claude.com/docs/en/plugins/dependencies), [Publish and distribute a plugin](https://code.claude.com/docs/en/plugins/publish), [Skills](https://code.claude.com/docs/en/skills)
- OpenAI: [Codex plugins](https://developers.openai.com/codex/plugins/build), [Submit your Claude Code plugin to OpenAI](https://developers.openai.com/plugins/guides/submit-claude-plugin), [Build skills](https://learn.chatgpt.com/docs/build-skills)
- Agent Plugins: [Plugin manifest](https://agent-plugins.org/plugin-authors/manifest), [Client extensions](https://agent-plugins.org/plugin-authors/client-extensions), [Compatible clients](https://agent-plugins.org/compatible-clients)
- Hooks: [Claude Code hooks reference](https://code.claude.com/docs/en/hooks), [Codex hooks](https://learn.chatgpt.com/docs/hooks), [openai/codex#39895](https://github.com/openai/codex/issues/39895)
- [Agent Skills specification](https://agentskills.io/specification)
