# Working on this repository

This repository is a plugin marketplace for Claude Code and Codex. Read [docs/architecture.md](docs/architecture.md) for the design.

## Rules

- The core plugin, `plugins/corthex`, holds skills only: no hooks, commands, agents, MCP servers or user settings. Anything that needs them is a separate plugin.
- A plugin with hooks has `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` and no root `plugin.json`, because Codex skips a plugin's hooks when a root `plugin.json` exists.
- Scripts use the Python standard library only, run on Python 3.8 or later on Windows, macOS and Linux, and write only under `~/.corthex/` or where the user says. A script may call a program the user installed, such as Git or FFmpeg; it takes the program from a path the user gave or from an absolute folder on PATH, never from the current folder, and says what is missing when it cannot run without it. Hook scripts also keep their output under the hosts' limits, and add nothing and exit 0 when they fail.
- A check that runs inside a web page, such as `corthex-uxui`'s `page-check.js`, is one plain JavaScript file with no dependencies. It reads the page and sends and changes nothing, and `tests/test_uxui.py` keeps it that way.
- Nothing leaves the user's machine unless they ask: a script uses the network only in a command made for sending, to an address the user set, for projects the user listed.
- Skills follow the Agent Skills format: only the portable frontmatter fields, the name equal to the folder name, a body under 500 lines, and links that stay inside the skill's folder.
- Skill text is English. README and docs come in pairs, `<name>.md` and `<name>.ko.md`, and a change to one is made to both.
- How to address the user, their language and where records go come from the profile. Never write a person's name, title, email or home path into a skill, doc or example.
- The two manifests of a plugin agree on their shared fields. A version change updates both manifests and every skill's `metadata.version` together.
- A change to the stage contract updates the stage's reference file, `skills/corthex/references/stage-contract.md` when IDs or slots change, the stage table in `corthex-nexus`'s `hub.py`, and the tests. `tests/test_hub.py` reads the stage skills' output templates, so a template change must stay readable by the hub.
- `nexus/` is the NEXUS server, a Cloudflare Worker and not a plugin. It is plain JavaScript with no runtime dependencies; Wrangler is its only development dependency, and its tests use Node's built-in test runner. All database code stays in `nexus/src/store.js`. `nexus/src/hub.html` is a copy of the hub page template, so copy it again after changing the template; `tests/test_nexus.py` compares them. The shared `wrangler.jsonc` keeps the example address and names no database.
- Never commit secrets. Keys belong in the host's secret store or environment variables.

## Checks

Run before every commit:

```bash
python -m unittest discover -s tests -v
claude plugin validate --strict .
claude plugin validate --strict plugins/corthex
claude plugin validate --strict plugins/corthex-memory
claude plugin validate --strict plugins/corthex-nexus
node --test nexus/test/*.test.js     # Node 22.13 or later
```

## Releases

A release is a tag named `<plugin>--v<version>`. After the checks pass on `main`, create it with `claude plugin tag plugins/<plugin>`, which also checks that the manifest and the marketplace entry agree.
