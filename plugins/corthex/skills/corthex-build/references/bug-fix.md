# Fixing a bug

A bug is the product doing something other than an approved document says. Fix every bug by these steps, whichever stage finds it, so that the document with the cause is put right first and the same failure cannot come back unnoticed. The entry skill's note that a project may start in the middle does not hold here. When the fix needs a new or different requirement or user flow, it is a feature change instead: follow the `corthex` skill's change procedure.

## Status, severity and priority

| Status | Means | Set when |
| --- | --- | --- |
| `open` | Reported and not yet fixed | The bug is recorded |
| `fixed` | A fix is merged and its regression test passes, or, after a production incident, a fix is live and its record names what is still owed | The fix's pull request is merged, or the incident's fix is live |
| `verified` | The fix was checked where the bug was seen | The reporter or QA confirms it, with evidence |
| `closed` | Not fixed, with the reason: a duplicate of another bug, not a bug, or not to be fixed | A duplicate names the bug it repeats; "not a bug" and "not to be fixed" are the user's decisions |

| Severity | Means |
| --- | --- |
| S1 critical | The service is down, data is lost or exposed, money is wrong or there is a security hole, with no way around it |
| S2 major | A main flow fails, with no way around it |
| S3 minor | Something fails, with a way around it |
| S4 trivial | Something looks or reads wrong and still works |

Open S1 and S2 bugs block a release under the [release gate](12-qa.md#release-gate).

Set priority separately from severity:

| Priority | When to fix it |
| --- | --- |
| P1 | Before the next release |
| P2 | In the next planned work |
| P3 | When convenient |

## Steps

1. **Record.** Write one Markdown file per bug using the [bug file template](12-qa.md#output-template). Give the bug a BUG ID, the status `open`, a severity and a priority. Set `found_in` to a QA run with its ID, production, or a user's report in their own words. Keep when it was found and the environment in the file.
2. **Reproduce.** Write steps that make it happen on a development or staging target, or where it was seen when it happens only there, and keep the evidence. When it does not happen again, record what was tried, keep it `open` and ask the reporter for more.
3. **Find the stage of the cause.** Compare what happens with the approved documents from the top down, and name the first one that is wrong or silent: 04 functional spec (a missing exception or a wrong acceptance criterion), 05 ERD or 06 API (a column, a limit or a response), 07 to 09 screens (a missing or wrong screen state), 10 WBS (a spec row no task covers, or a task that leaves part of one out), 11 development (the code differs from documents that are right), or 12 QA (a case or gate was wrong). A wrong domain rule or term (01), or a missing or wrong requirement or user flow (02, 03) makes it a feature change. Record the stage as a hypothesis, with what supports it, until the regression test confirms it. Set `defect_type` using the table below. For a bug found after release, also record the escape analysis.
4. **Fix that document first.** Change the cause stage's source with its stage skill, its checks and its checkpoint, then each later document it affects, in order. When only the code was wrong, record “no document change”.
5. **Write the regression test first.** Add a test case (TC) for the bug that names the BUG, the spec row and the response or screen state it checks, and run it against the code as it is: it must fail, and the record names the commit it failed on. Automate it as `contract`, `api` or `e2e` where possible. Otherwise write `manual` or `agent` steps with evidence of the failure and explain why they are manual. Mark a check that needs a real device, such as sound on a phone, `device`.
6. **Apply and check the fix.** Fix the code if its behaviour needs to change. In a pull request that names the BUG and the SPEC IDs (stage 11), make the regression test pass and run the tests of the area the fix touches. For a test or gate defect, check the corrected case or gate against the evidence it should have caught. Set the status to `fixed` when the fix is merged, with the pull request and the commit.
7. **Verify.** Check the fix where the bug was seen, or in the closest environment allowed, and set `verified` with the evidence. The regression test stays in the suite for good.

## Defect types

| Type | Means | Do |
| --- | --- | --- |
| Implementation | The documents are right and the code differs | Fix the code, add a regression test and record “no document change” |
| Spec | A stage 04 to 09 document is wrong or silent | Fix it first, then update the later documents it affects |
| Missing requirement | A stage 01 to 03 document lacks the required rule, requirement or flow | Follow the feature change procedure |
| Platform assumption | A document assumed OS or device behaviour that does not hold, such as a scheduled job finishing within 15 minutes | Fix the requirement or spec that made the assumption, record the assumption and how it was checked, and add a `device` case |
| Test or gate | A case was wrong or the gate let a failure through | Fix the test plan. When the same kind recurs in two or more projects, tell the user it may need a change to CORTHEX's skills and cite the bugs |

## Escape analysis

For every bug found after release, record which case should have caught it, why it missed the bug or why the gate let it through, and what changes in the test plan. Give the full analysis for S1 and S2. Use one line in the `Escape` field for lower severities. Keep it blameless by naming the steps and rules involved.

## Production incidents

For an S1 in production, or an S2 that stops people now, restoring the service comes first.

1. Roll back to the last good version, or ship the smallest fix, with the checks that time allows and under the project's rules for production, its ask-before list included. Say which checks were skipped.
2. Record the bug at once, with the times it started, was noticed and was restored.
3. Before any other change ships, except further fixes for this incident, finish steps 3 to 7: the document with the cause, the escape analysis, a regression test that fails on the broken version and passes on the fix, and the check where it was seen. Until then the bug stays `fixed`, not `verified`, and its record names what is still owed.
4. When the user wants one, write a retrospective with the `corthex-record` skill.

## Checks

- Every bug file has a status, severity, priority, where it was found, defect type, cause stage, the environment, and steps that reproduce it or a record of what was tried.
- Every bug found after release records which case should have caught it, how it escaped and what changes in the test plan.
- Every fixed bug names the stage of its cause and the document changed, or says that only the code was wrong.
- Every fixed bug has a regression test case that failed before the fix and passes after it, each with its commit, or `manual` or `agent` steps with evidence and the reason they are not automated. The only exception is a production incident's fix whose record names what is still owed.
- Every `verified` bug has evidence from where it was seen.
- After a production incident, no other change shipped before the bug's document and regression test were done, or the record says why.
