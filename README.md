# CORTHEX

[한국어](README.ko.md)

CORTHEX is a plugin for Claude Code and Codex that helps one person run software projects with an AI collaborator, stage by stage: from domain discovery and requirements to screens, building, QA and the final presentation.

It does not add a runtime of its own. Installation and updates use the hosts' plugin marketplaces, and everything else is skills. On top of that, CORTHEX adds three things:

- **Working principles** for the AI: lead with the result, keep facts and guesses apart, ask before anything that cannot be undone, and keep records.
- **A 13-stage workflow** in which every stage fills the same six slots (inputs, outputs, human view, sync, human checkpoints, trace IDs), so each artifact can be traced to the one before it.
- **A profile and a project registry**, so the same plugin fits different people and several projects at once.

> Status: 0.1.0, an early skeleton. The stage skills are outlines that will grow with real use.

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

## Skills

| Skill | Stages | Use it to |
| --- | --- | --- |
| `corthex` | entry | set up your profile, register a project, see where a project stands and what comes next |
| `corthex-discover` | 01 | turn a domain workshop into bounded contexts and a glossary |
| `corthex-define` | 02–04 | write requirements, user flows and the functional spec |
| `corthex-contract` | 05–06 | keep the database schema and the API contract in line with the spec |
| `corthex-screen` | 07–09 | sitemap, screen states, mockups and design tokens |
| `corthex-build` | 10–12 | work breakdown, development and QA |
| `corthex-present` | 13 | script, scene table and slides for the presentation |
| `corthex-record` | any | minutes, decision log and progress records |

## Profile and projects

- `~/.corthex/profile.json` holds how to address you, your language, where records go and what to ask about first. The `corthex` skill offers to create it. It never holds secrets.
- `.corthex/project.json` in each product repository says, stage by stage, where people look at the work (`human`), where the text source lives (`source`) and which side wins when they differ (`truth`).
- `~/.corthex/projects.json` lists the projects on one machine.

[The architecture notes](docs/architecture.md) explain the design and link to each format.

## Compatibility

- Claude Code reads `.claude-plugin/marketplace.json` and each plugin's `.claude-plugin/plugin.json`.
- Codex and other [Agent Plugins](https://agent-plugins.org) clients read `.agents/plugins/marketplace.json` and each plugin's root `plugin.json`.
- The skills follow the [Agent Skills](https://agentskills.io) format and are shared by both, so each skill can also be used on its own.

## Development

```bash
python -m unittest discover -s tests -v
claude plugin validate --strict .
claude plugin validate --strict plugins/corthex
```

## License

[Apache-2.0](LICENSE). See [NOTICE](NOTICE).
