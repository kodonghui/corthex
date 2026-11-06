---
name: corthex-present
description: "CORTHEX stage 13, the presentation. Use when preparing a project demo or final presentation: turning project records into a script, the script into a scene table (SCENE IDs) with screens, narration and timing, and the scene table into slides or a demo video plan."
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.8.0"
---

# Presentation

This skill covers one stage. Its contract, steps, checks and output template are in the reference file.

| Key | Stage | Contract |
| --- | --- | --- |
| `13-presentation` | Presentation | [references/13-presentation.md](references/13-presentation.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first. If the stage has no entry yet, propose the default human view that the stage's reference file names; when the user picks another, record the choice as a decision and write the entry with a `note`.
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from a person's latest export: ask for a new export at the start and before each checkpoint, and give the date of the copy you used. With `truth: human`, hand over each change as steps a person can apply in the tool or as a file the tool can import, and report it as proposed, not as done, until a newer export shows it. With `truth: source`, a change is done once it is in the source: give the person the file or the steps for the tool, and report the tool as not yet updated until a newer export shows the change.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Silence, a read receipt or an edit is not approval.
7. **Record.** Record decisions and the next action with `corthex-record`. If the `corthex-hub` skill is installed, also record the stage's state there.

## Notes for this stage

- Every claim on a slide comes from a record, a test result or a demo the audience can see. Mark plans as plans.
- Pick one way to make the demo video and keep to it; switching tools late costs more than it saves.
- For a video built as HTML and rendered to MP4, and for what each slide should draw, use the `corthex-uxui` skill. It adds motion, transitions and sound to this stage's scene table, keeps the SCENE IDs, and measures flashes and loudness before anyone is shown the video.

## Optional NEXUS work

For a project with an installed hub and an authorized NEXUS server, follow [references/nexus-work.md](references/nexus-work.md). Read the to-do once per session/project, keep explicit user work first, and use claims and verified PR/checkpoint outcomes. Continue local work when the hub or token is unavailable.
