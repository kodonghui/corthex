# Projects

One person can run several projects. Each project describes itself in its own repository, and each machine keeps a short list of the projects on it.

## Project settings: `.corthex/project.json`

This file lives in the product repository and is committed with it, so everyone on the project sees the same settings.

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | Short project id in lowercase letters, digits and hyphens, such as `acme-shop` |
| `title` | string | Display name, in any language |
| `team` | boolean | `true` when several people work on the project |
| `language` | string | Language for project documents, when it differs from the profile |
| `records` | object | Where this project's records go: `kind` (`notion`, `git` or `none`) and `location` (a link or a path) |
| `ids` | object | Optional overrides of the trace ID prefixes, such as `{ "requirement": "FR" }` |
| `stages` | object | One entry per stage key, described below |

Each entry in `stages` is keyed by a stage key (`01-domain` to `13-presentation`, listed in [stage-contract.md](stage-contract.md)) and has:

| Field | Meaning |
| --- | --- |
| `human` | Where people look at and edit this stage, such as `notion`, `miro`, `erdcloud`, `figma`, `swagger-ui` or `github` |
| `source` | Path of the text source in the repository, a file or a folder |
| `truth` | Which side wins when the two differ: `source` (the text in the repository) or `human` (the tool named in `human`) |
| `skip` | Optional. `true` when the project does not use this stage |

A stage without an entry uses the default paths in its contract, with `truth` set to `source`.

An example is in this skill's folder at `assets/project.example.json`.

## The project list: `~/.corthex/projects.json`

This file lives on the machine, never in a repository, because paths differ between machines.

```json
{
  "projects": [
    { "name": "acme-shop", "path": "/path/to/acme-shop", "records": "<link>" }
  ]
}
```

- Add an entry when a project is registered on this machine. Update its `path` when the repository moves.
- Remove an entry only when the user asks. The project's own files stay where they are.
