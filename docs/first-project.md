# Your first project

[한국어](first-project.ko.md)

You will install the core plugin, set up a profile, register a disposable project, review one requirement and find its progress record. Allow one short session. You need Git and a working, already authenticated Claude Code or Codex installation. Host login and account billing are outside this tutorial; keep credentials on this machine. CORTHEX adds no paid service or background recording in this path.

Use an empty practice directory. If a profile or project registry already exists, ask the agent to preserve its entries and change only values you explicitly choose. Do not replace either file with a tutorial sample.

## 1. Install and open a fresh session

In PowerShell on Windows, or bash/zsh on macOS, run the two commands for your host:

| Claude Code | Codex |
| --- | --- |
| `claude plugin marketplace add kodonghui/corthex` | `codex plugin marketplace add kodonghui/corthex` |
| `claude plugin install corthex@corthex` | `codex plugin add corthex@corthex` |

Each command should exit successfully. Stop on an installation error and keep its safe error text and host version (`claude --version` or `codex --version`). If the marketplace is already registered, use the host's marketplace update command rather than deleting it. This tutorial installs only `corthex`; MEMORY and NEXUS are optional later choices.

From a parent directory of your choice, run these lines in either shell:

```text
mkdir corthex-practice
cd corthex-practice
git init
```

If the directory exists, choose a different practice name. Open a **new** host session there: `claude` or `codex`. In Claude Code invoke `/corthex:corthex`. In Codex ask: “Use the installed corthex entry skill. Show which skill file you loaded and read its profile and project references before writing anything.”

Expected: the entry skill is found in the installed plugin and the agent checks this directory and the existing profile/registry. If the skill is missing, stop; confirm installation in the host's plugin list and restart. Do not create a global instruction file or enable hooks to work around discovery.

## 2. Choose and review the profile and project

Send this request in the new session:

> This is a practice project named `corthex-practice`. Use English and address me as “you”. Keep records in Git at `docs/records/`. Preserve existing profile and registry values unless I choose a change. Show the proposed profile and project settings before writing them. For stage 02, I choose the repository Markdown view instead of the default Notion database: use `human: git`, `source: docs/02-prd/requirements.md` and `truth: source`. Record that choice as a decision with my exact words, this session and its actual date/time. We will start at stage 02; list the missing stage 01 inputs and propose one tiny glossary/context for this exercise before using it. No deployment or external messages.

Review the proposed paths and JSON. If they match your intent, tell the agent to apply them and approve the practice context. Do not say yes to values you do not want to change. The profile lives at `~/.corthex/profile.json` (`%USERPROFILE%\.corthex\profile.json` on Windows); the machine's registry is `~/.corthex/projects.json`; this repository's settings are `.corthex/project.json`. No account credentials belong in them.

Expected: the registry has one entry for this practice path, the project sets `records.kind` to `git` and `records.location` to `docs/records/`, and stage `02-prd` has the chosen `human`, `source`, `truth` and a `note` pointing to the decision. Other stages need no invented artifacts.

## 3. Write and review one requirement

Send:

> Use stage 02 to draft one Must functional requirement: when I add a note, the practice app saves its text. Use REQ-001, the approved practice context, and this request as its source. Keep the scope to this behaviour. Show the requirement and any open questions before freezing the scope.

Expected: `docs/02-prd/requirements.md` has REQ-001 in one EARS statement, with type, priority, context, source and status. Review what “saves” means for this practice and answer any necessary question. When satisfied, explicitly approve that scope. A file alone does not pass the checkpoint.

## 4. Find the result and record

Ask the agent to record the scope decision and progress, then report the current stage, what was checked and the next action. From the practice repository's terminal, run:

```text
git status --short
git diff --check
```

For new, untracked files, read them directly; `git diff` does not show their contents. Find `.corthex/project.json`, the requirement, a decision record and a progress record under `docs/records/`. The progress record should name the actual checked files and say that no app was implemented or deployed. Keep this practice directory until you decide whether to use or remove it.

You have completed the path when you can locate the installed skill, the profile and registry, REQ-001, its approval and the progress record. Continue with stage 03 when you want to develop the flow. This tutorial's agent/command reproduction is evidence about execution; whether a new reader learned from it requires observing a reader use it.
