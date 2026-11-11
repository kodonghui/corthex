---
name: corthex
description: Entry point for CORTHEX project work. Use at the start of multi-step software project work, when the user wants to set up their CORTHEX profile, register or switch between projects, asks where a project stands or what to do next, or names a project stage (domain discovery, PRD, user flow, functional spec, ERD, API, sitemap, screen states, mockup, WBS, development, QA, presentation). Applies the working principles for the whole task and routes to the right stage skill.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.10.0"
---

# CORTHEX

CORTHEX helps one person run software projects with an AI collaborator, stage by stage. This skill sets how to work, reads who the user is and which project this is, and hands off to the stage skill.

## 1. Read the profile

Read `~/.corthex/profile.json` (on Windows, `%USERPROFILE%\.corthex\profile.json`). The fields are in [references/profile.md](references/profile.md).

- If the file is missing, offer to create it. Ask only for what you cannot infer: how to address the user, the language, where records go, and what to ask before doing. Show the file before you write it.
- Address the user as `address_as` and write in `language`. If `language` is `ko` and `address_as` is not set, use 사용자님 and polite speech (존댓말).
- Never write a secret into the profile. Keys and tokens belong in the host's secret store or environment variables.

## 2. Find the project

Look for `.corthex/project.json` from the current directory up to the repository root. The fields are in [references/project.md](references/project.md).

- If there is none and the work is project work, offer to register the project: create `.corthex/project.json` in the product repository and add one entry to `~/.corthex/projects.json`, the list of this user's projects on this machine.
- When you register a project or set up a stage, propose each stage's default human view from [references/stage-contract.md](references/stage-contract.md). When the user picks another tool, record that as a decision and say it in the stage's `note`.
- If the user has several projects and the request does not say which one, ask once.
- Some sources may sit in other repositories, named under `repos`. Find their local checkouts in the project's entry in `~/.corthex/projects.json`, and ask when one is missing.
- Project settings override profile defaults for that project only.

## 3. Work by the principles

Follow [references/principles.md](references/principles.md) for the whole task. In short:

1. Lead with the result. For new or ambiguous work, restate the goal and the constraints once, in one to three sentences.
2. Keep facts, observations, past records, hypotheses and recommendations apart. Hold your own proposals to the same standard as the user's.
3. Check volatile or high-impact claims against current primary sources, and say what those sources do not cover.
4. Finish what was asked within the authority you were given. Make routine, reversible choices yourself. For a change of direction, give real alternatives, a recommendation and the main counterargument.
5. Approval is the user's own words, with where and when they said them. Ask before anything listed in `ask_before` (the project's valid list when set, otherwise the profile's) and before anything that cannot be undone.
6. Done means checked. Say what you verified and what you did not. Copy numbers in records and reports from their named command output or source.
7. Keep records. After a unit of work, a decision or a blocker, record what was done, why, the result, what was checked and the next action. In Notion, keep records as database rows.
8. Never put secrets in files, records or messages.

In long sessions, before and after a compaction and when work moves to another session or agent, follow [references/long-sessions.md](references/long-sessions.md).

## 4. Route to a stage

| Stage | Skill |
| --- | --- |
| 01 Domain discovery | `corthex-discover` |
| 02 PRD · 03 User flow · 04 Functional spec | `corthex-define` |
| 05 ERD · 06 API | `corthex-contract` |
| 07 Sitemap · 08 Screen states · 09 Mockup | `corthex-screen` |
| 10 WBS · 11 Development · 12 QA | `corthex-build` |
| 13 Presentation | `corthex-present` |
| Meetings, decisions and progress records, at any stage | `corthex-record` |
| The craft of screens, motion and video, with its checks: in stages 08, 09 and 13, or on its own | `corthex-uxui` |
| Study documents that teach one learning question in depth, at any stage or on its own | `corthex-study` |

Every stage follows one six-slot contract: inputs, outputs, human view, sync, human checkpoints and trace IDs. See [references/stage-contract.md](references/stage-contract.md). A project may skip stages or start in the middle; say which inputs are then missing.

## 5. Answer "where are we?"

Read the project's `stages` settings and the artifacts they point to. For each stage, report one of done, in progress, not started or skipped, the last human checkpoint with its date, and the next action. A file that exists is not a finished stage: a stage is done when its checkpoint was passed and recorded.

If the `corthex-hub` skill is installed, it keeps these states for every project and shows them on one page with the trace links between stages; read and record the states there.

## Optional NEXUS work

For a project with an installed hub and an authorized NEXUS server, follow [references/nexus-work.md](references/nexus-work.md). Read the to-do once per session/project, keep explicit user work first, and use claims and verified PR/checkpoint outcomes. Continue local work when the hub or token is unavailable.
