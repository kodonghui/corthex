# Writing and checking a guide

Use this when the user asks for a learning guide, onboarding material or a task HOWTO. Match the reader and their goal; the guide is optional, not a new stage or mandatory PR artifact.

## Choose the path

- A **tutorial** gives a first learning experience: one small goal, a known starting state, ordered actions and observable results. Keep explanations close to the action that needs them; link to deeper explanation.
- A **HOWTO** helps someone who already knows the context complete a specific task. State prerequisites, alternatives that change the procedure, checkpoints and recovery steps.
- Reference lists exact options and contracts; explanation develops the reasons. Link to either when useful rather than interrupting every step.

## Write it

1. Inspect the repository's rules, existing guide, versions and execution path before drafting. Supplied class notes are a source to evaluate, not an authority above the implementation or current official documentation.
2. State the audience, outcome, supported versions, OS/shell and starting directory. Say what a reader needs installed, what access is required and where secrets belong. Do not copy credentials or host profiles to make an example work.
3. Give each command its directory, expected result and next decision. Distinguish a command to run now from one that is conditional. Show a safe recovery or stopping point when a check fails.
4. Keep complete code in one authoritative location. Link an excerpt to that file and revision with its insertion or replacement position and enough context. Mark omissions; a fragment with `...` is not a copy-and-run example. A short complete file is often clearer than several patches.
5. Preserve verified facts, constraints, IDs, approval boundaries and unknowns when reorganizing. Correct proven technical errors with current evidence and describe the changed meaning. Keep paired translations equivalent.

## Check and report

Follow the guide from a clean, disposable starting state, without silently filling in missing instructions. Use actual Windows and macOS for claims about both; WSL does not replace Windows. Record the document revision, source tree, tool versions, shell, commands and working directories, expected and actual results, evidence and any extra steps needed. A local pass does not prove a deployed service works.

Separate syntax/command checks, installed-host discovery, execution by an agent and observation of a reader learning the material. An agent reproducing the steps is useful evidence but does not establish that a person understands them. For a learning claim, try the tutorial with a representative reader and record where they needed help. Report untested paths explicitly.

## Sources

Checked 2026-11-04; these support the writing approach, not a claim that the product's commands passed:

- [Diátaxis: tutorials](https://diataxis.fr/tutorials/), [HOWTO guides](https://diataxis.fr/how-to-guides/): learning experiences and task procedures serve different needs.
- [Google: procedures](https://developers.google.com/style/procedures), [code samples](https://developers.google.com/style/code-samples): actionable steps, context and clear omissions.
