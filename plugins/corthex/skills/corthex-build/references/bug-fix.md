# Fixing a bug

A bug is the product doing something other than an approved document says. Fix every bug by these steps, whichever stage finds it, so that the document with the cause is put right first and the same failure cannot come back unnoticed. The entry skill's note that a project may start in the middle does not hold here. When the fix needs a new or different requirement or user flow, it is a feature change instead: follow the `corthex` skill's change procedure.

## Status and severity

| Status | Means | Set when |
| --- | --- | --- |
| `open` | Reported and not yet fixed | The bug is recorded |
| `fixed` | A fix is merged and its regression test passes | The fix's pull request is merged |
| `verified` | The fix was checked where the bug was seen | The reporter or QA confirms it, with evidence |
| `closed` | Not fixed, with the reason: a duplicate of another bug, not a bug, or not to be fixed | A duplicate names the bug it repeats; "not a bug" and "not to be fixed" are the user's decisions |

| Severity | Means |
| --- | --- |
| S1 critical | The service is down, data is lost or exposed, money is wrong or there is a security hole, with no way around it |
| S2 major | A main flow fails, with no way around it |
| S3 minor | Something fails, with a way around it |
| S4 trivial | Something looks or reads wrong and still works |

## Steps

1. **Record.** Give the bug a BUG ID, the status `open` and a severity, with the report in the reporter's own words, where and when it was made, and the environment, in the form in [12-qa.md](12-qa.md).
2. **Reproduce.** Write steps that make it happen on a development or staging target, or where it was seen when it happens only there, and keep the evidence. When it does not happen again, record what was tried, keep it `open` and ask the reporter for more.
3. **Find the stage of the cause.** Compare what happens with the approved documents from the top down, and name the first one that is wrong or silent: 04 functional spec (a missing exception or a wrong acceptance criterion), 05 ERD or 06 API (a column, a limit or a response), 07 to 09 screens (a missing or wrong screen state), or 11 development (the code differs from documents that are right). A missing or wrong requirement or user flow (02, 03) makes it a feature change. Record the stage as a hypothesis, with what supports it, until the regression test confirms it.
4. **Fix that document first.** Change the cause stage's source with its stage skill, its checks and its checkpoint, then each later document it affects, in order. When only the code was wrong, no document changes; say so.
5. **Write the regression test first.** Add a test case (TC) for the bug that names the BUG, the spec row and the response or screen state it checks, and run it against the code as it is: it must fail, and the record names the commit it failed on. Automate it as `contract`, `api` or `e2e` where it can be; where it cannot, such as sound on a real phone, write it as `manual` or `agent` steps with evidence of the failure, and say why it is not automated.
6. **Fix the code.** In a pull request that names the BUG and the SPEC IDs (stage 11), make the regression test pass and run the tests of the area the fix touches. Set the status to `fixed`, with the pull request and the commit.
7. **Verify.** Check the fix where the bug was seen, or in the closest environment allowed, and set `verified` with the evidence. The regression test stays in the suite for good.

## Production incidents

For an S1 in production, or an S2 that stops people now, restoring the service comes first.

1. Roll back to the last good version, or ship the smallest fix, with the checks that time allows and under the project's rules for production, its ask-before list included. Say which checks were skipped.
2. Record the bug at once, with the times it started, was noticed and was restored.
3. Before any other change ships, except further fixes for this incident, finish steps 3 to 7: the document with the cause, a regression test that fails on the broken version and passes on the fix, and the check where it was seen. Until then the bug stays `fixed`, not `verified`, and its record names what is still owed.
4. When the user wants one, write a retrospective with the `corthex-record` skill.

## Checks

- Every bug has a status, a severity, the environment, and steps that reproduce it or a record of what was tried.
- Every fixed bug names the stage of its cause and the document changed, or says that only the code was wrong.
- Every fixed bug has a regression test case that failed before the fix and passes after it, each with its commit, or `manual` or `agent` steps with evidence and the reason they are not automated.
- Every `verified` bug has evidence from where it was seen.
- After a production incident, no other change shipped before the bug's document and regression test were done, or the record says why.
