# Changing approved work

Once a stage's checkpoint has been passed, its items are what the user approved. Later work that changes them goes by one of two procedures, whichever stage it starts in. The entry skill's note that a project may skip stages or start in the middle does not hold for either.

## Which procedure

| The work | Procedure |
| --- | --- |
| A new feature, a feature removed or put off, a change of scope, a redesign or a merger with another product: anything that adds, removes, defers or changes the meaning of a requirement (REQ), a user flow (FL) or a spec row (SPEC) | [Feature change](#feature-change), below |
| The product does something other than an approved document says | The `corthex-build` skill's bug-fix procedure, in that skill's `references/bug-fix.md` |
| A bug whose fix needs a new or different requirement or user flow | Feature change |
| Work that changes no approved item, such as a refactor that keeps every behaviour | Stage 11 alone; the pull request says that no approved item changes |

When it is unclear which one applies, take the feature change and say why. Size is no reason to skip it: a small change goes through the same stages, with short results.

## Feature change

1. **Open the change.** Start a progress record of the change with the `corthex-record` skill: the request in the user's own words, where and when they said it, and the baseline, which is each stage's last passed checkpoint with its date and the commit or export it approved.
2. **Go through every stage from 01.** In order, from 01 domain discovery to 12 QA, and on to 13 when the project uses it, take each stage with its skill and write the stage's result as a difference from its approved version: the items added, changed, deferred or removed, by ID. In stage 01 that is `corthex-discover`'s procedure for adding to an existing product, in which only the changed contexts go through the steps. A stage that does not change gets "no change" and one line of reason, written after reading its approved items, never assumed. Do not skip a stage because it looks unaffected, and do not start the new design at a later stage. A stage the project marks `skip: true` stays skipped and is listed as skipped, and a stage never done is listed as not started, with the inputs it would have given. New items get new IDs; an existing ID is never reused or renumbered.
3. **List what the change takes away.** Collect every approved item that the change removes, defers or changes in meaning: requirements, flows, spec rows, tables, API operations, screens, tasks, decisions (DEC), and open pull requests with their branches. For each one give its ID or link, its approved text quoted, where and when it was approved, what the change does to it and why.
4. **Ask about each item on its own.** Put the items from step 3 to the user in a message of their own, numbered, each with the choices keep, change, defer or remove; a deferred item also needs a date to look at it again and an owner. Each item needs an answer that names it, such as "keep 1, defer 2 to March, remove 3" or "remove 1 to 5". Approval of the design or of a stage, or a yes to a message that also asks something else, answers none of them. An item without its own answer stays as it was approved. Record each answer as a decision (DEC) with the user's words, with the `corthex-record` skill.
5. **Close or date pull requests and branches.** When the answers remove the work of an open pull request, close it then and there, with a comment that names the decision. When they defer it, write the date to look at it again and the owner on the pull request and in the change's record. No such pull request stays open without one or the other. Deleting a branch is a deletion: ask first.
6. **Change the documents stage by stage.** Update each stage's source in order, with its stage skill, its checks and its checkpoint. Mark a deferred item `deferred` and a removed item `removed`, each with the date and the decision, and keep its ID.
7. **Close the change.** The change's record lists each stage's result, each item from step 3 with its answer and decision, and each pull request closed or dated, so that the user can later find what was dropped and why without asking again.

## At every checkpoint: what was dropped or changed

Every stage skill's checkpoint step does this, in a change and in first-time work alike.

- Compare the stage's source with the version its last passed checkpoint approved, by the commit or export that checkpoint recorded. List this stage's items that are now removed, deferred or changed in meaning, and the approved items of earlier stages that this stage should carry and does not, such as a requirement no spec row covers. Give each one's ID, its approved text, the change and the reason, and name the decisions and open pull requests it touches. Say "none" when there are none; at a stage's first checkpoint, compare only with the earlier stages.
- Ask about each listed item as a question of its own, before the checkpoint's question, as step 4 above says. Passing the checkpoint answers none of them.
- Record the commit or export that the checkpoint approves, so that the next checkpoint can compare with it.
