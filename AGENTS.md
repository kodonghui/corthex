# Working on this repository

This repository is a plugin marketplace for Claude Code and Codex. Read [docs/architecture.md](docs/architecture.md) for the design.

## Rules

- The core plugin, `plugins/corthex`, holds skills only: no hooks, commands, agents, MCP servers or user settings. Anything that needs them is a separate plugin.
- Skills follow the Agent Skills format: only the portable frontmatter fields, the name equal to the folder name, a body under 500 lines, and links that stay inside the skill's folder.
- Skill text is English. README and docs come in pairs, `<name>.md` and `<name>.ko.md`, and a change to one is made to both.
- How to address the user, their language and where records go come from the profile. Never write a person's name, title, email or home path into a skill, doc or example.
- The two manifests of a plugin agree on their shared fields. A version change updates both manifests and every skill's `metadata.version` together.
- A change to the stage contract updates the stage's reference file, `skills/corthex/references/stage-contract.md` when IDs or slots change, and the tests.
- Never commit secrets. Keys belong in the host's secret store or environment variables.

## Checks

Run before every commit:

```bash
python -m unittest discover -s tests -v
claude plugin validate --strict .
claude plugin validate --strict plugins/corthex
```

## Releases

A release is a tag named `<plugin>--v<version>`. After the checks pass on `main`, create it with `claude plugin tag plugins/<plugin>`, which also checks that the manifest and the marketplace entry agree.
