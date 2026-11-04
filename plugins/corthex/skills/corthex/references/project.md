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
| `records` | object | Where this project's records go: `kind` (`notion`, `git` or `none`) and `location` (a link to the records database, or a path) |
| `ask_before` | array of strings | Optional. Kinds of actions to ask about first in this project. A valid list replaces the profile's `ask_before` for this project, including an empty list. Anything that cannot be undone is still asked. Non-list values, non-string entries, blank categories and strings that cannot be encoded as UTF-8 are invalid and keep the profile's list. Review reductions of this list separately, because this file is committed in the repository. |
| `repos` | object | Optional. Other repositories that hold some of this project's sources, by a short alias in lowercase letters, digits and hyphens, such as `{ "design": "https://github.com/acme/acme-design" }` |
| `ids` | object | Optional trace ID formats by kind, described below |
| `stages` | object | One entry per stage key, described below |

Each entry in `stages` is keyed by a stage key (`01-domain` to `13-presentation`, listed in [stage-contract.md](stage-contract.md)) and has:

| Field | Meaning |
| --- | --- |
| `human` | Where people look at and edit this stage, such as `notion`, `miro`, `erd-editor`, `erdcloud`, `figma`, `swagger-ui` or `github`. Propose the stage's default from the table of default human views in [stage-contract.md](stage-contract.md), and when the user picks another, record the choice as a decision and say it in `note` |
| `link` | Optional. Link to the human view, such as the URL of the shared database, or the path of a file in the repository. The settings file is committed, so in a public repository ask before adding a link to a private workspace, or say in `note` where the view is kept instead |
| `source` | Path of the text source, a file or a folder, relative to the repository root with forward slashes. Put an alias from `repos` and a colon in front for another repository, such as `design:docs/prd/`. In a folder, translations beside their originals are not read as sources (see [stage-contract.md](stage-contract.md)). Leave it out while the stage has no text copy |
| `truth` | Which side wins when the two differ: `source` (the text) or `human` (the tool named in `human`) |
| `note` | Optional. Why the stage is set up this way, with the decision and its date |
| `skip` | Optional. `true` when the project does not use this stage |

A stage without an entry uses the default paths in its contract, with `truth` set to `source`. A stage with an entry but no `source` has only the human view; say so when you report on the stage, and offer to start a text copy.

## Trace ID formats: `ids`

The keys are the ID kinds listed in [stage-contract.md](stage-contract.md): `context`, `term`, `requirement`, `flow`, `spec`, `table`, `api`, `screen`, `task`, `test`, `bug`, `decision` and `scene`. Each value is either:

- a prefix, such as `"requirement": "FR"`, for IDs like `FR-001`; or
- an object with `prefix`, one prefix or a list of them, and `digits`, the number of digits, such as `"spec": { "prefix": ["AUTH", "CHAT"], "digits": 3 }` for IDs like `AUTH-001` and `CHAT-001`.

Use the list form when a project numbers one kind of item per area, such as one prefix per bounded context. Follow the format a project already uses; never renumber existing items to fit a default.

An example with all of these fields is in this skill's folder at `assets/project.example.json`.

## The project list: `~/.corthex/projects.json`

This file lives on the machine, never in a repository, because paths differ between machines.

```json
{
  "projects": [
    {
      "name": "acme-shop",
      "path": "/path/to/acme-shop",
      "repos": { "design": "/path/to/acme-design" },
      "records": "<link>"
    }
  ]
}
```

- Add an entry when a project is registered on this machine. Update its `path` when the repository moves.
- `repos` gives the local checkout of each alias in the project's `repos`. When a stage's source is in a repository with no local checkout, say so and ask for its path, or offer to clone it.
- Remove an entry only when the user asks. The project's own files stay where they are.
