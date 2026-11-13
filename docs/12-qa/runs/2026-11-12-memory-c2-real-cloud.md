# MEMORY's own requests against the providers, in a cloud session

[한국어](2026-11-12-memory-c2-real-cloud.ko.md)

2026-11-12 · TASK-100 · SPEC-014, SPEC-016, SPEC-017, SPEC-018, SPEC-019 · TC-258, TC-259, TC-261, TC-262, TC-345, TC-356 · commit `f0725cd3707151a52f8093395580aabdc511d47c`.

`.github/hook-check/c2_real.py` ran its six cases five times each from a clean checkout of that commit, in a cloud session of Claude Code on Linux with Python 3.13.18, with the maintainer's memory keys and the package's own settings. The four cases that stage 12 judges, TC-258, TC-259, TC-261 and TC-262, passed in all five runs. The two that it records without a verdict, TC-345 and TC-356, were recorded five times. The run lasted from 21:00:15 to 21:11:34 UTC. It sent 47 requests to Anthropic's API, none of which had to be sent again, and cost 0.064071 USD by the usage log. All 30 embedding requests ended with the provider's code `insufficient_quota`, so this run shows nothing about embeddings.

This is the first of the environments where TASK-100 runs. The maintainer's devices and servers have not run it yet. TC-260, the usage lines against the providers' consoles, and TC-420, real compactions in Claude Code, are not in the script. A model's answers vary: five runs are five samples, and the counts below are counts of this run.

## What ran, and what kind of evidence it is

- **Real.** The staged worker of release 0.3.0 ran 40 times with the memory keys against the providers' own addresses; neither base address was set in the environment. It sent 35 curate, 7 merge and 5 state requests to the curator model that the package sets by itself, `claude-haiku-5-5`, and 30 embedding requests: 77 lines of the usage log.
- **Local seed.** Where a case needs a layer that is known beforehand (TC-258, TC-262, TC-345 and TC-356), its first turns were curated against a local server whose answers the script writes: 20 runs of the worker and 40 requests to that server. They show nothing about a provider and are not in the cost.
- **Made up.** Every turn. Each run of a case has a home, a project and a memory store of its own. The staged prompt hook and end-of-turn hook record the turns with each host's own input fields; they get no key and start no worker.
- Each of the 60 runs of the worker exited with 0, and the check as a whole exited with 0.
- No file under the run's folder holds a memory key, none had to be masked in the report, and none of the 40 requests to the local server carried one.

| Case | Runs | Outcome | Model requests | Input tokens | Output tokens | Cost in USD |
| --- | --- | --- | --- | --- | --- | --- |
| TC-258 | 5 | pass | 5 curate, 7 merge, 5 state | 38,136 | 28,949 | 0.018288 |
| TC-259 | 5 | pass | 10 curate, 5 of them cut | 34,628 | 15,357 | 0.011141 |
| TC-261 | 5 | pass | 5 curate | 19,102 | 18,696 | 0.011258 |
| TC-262 | 5 | pass | 5 curate | 22,648 | 3,009 | 0.003769 |
| TC-345 | 5 | recorded | 5 curate | 20,785 | 12,232 | 0.008195 |
| TC-356 | 5 | recorded | 5 curate | 18,876 | 19,064 | 0.011420 |
| All | 30 | | 47 | 154,175 | 97,307 | 0.064071 |

The cost is what the package's price list gives for the tokens of each usage line. Whether the provider's console shows the same is TC-260.

## The cases

**TC-258, the answer schemas.** Each run curated two made-up turns and then consolidated a layer that held two decisions saying the same thing. Every one of the 17 requests ended `ok` in the usage log, and each of the 17 answers fits its schema by the package's own decoder. In every run one merge answer merged the two decisions into one current item with a Korean title and named no conflict.

**TC-259, a cut answer.** Each run sent the curate request of two made-up turns with `max_tokens` 64. All five were logged with the result `limit` and the code `max-tokens`, at 3,457 to 3,468 input tokens and 64 output tokens. The curation record's latest attempt was a failed curation with that code and one failed attempt counted, no item was saved, and both turns stayed waiting. The worker's next run, with the package's own `max_tokens`, curated both turns in every run: one `ok` line, two items, no turn left and the count of failed attempts back at 0. No refusal was asked for. Anthropic's documentation of refusals, read on 2026-11-12, names no request that a model refuses without harmful content, so refusals stay checked against the test servers only.

**TC-261, inside the curator's scope.** One curate request per run over a short `응` to a proposal of the agent, a decision made in Korean, and small talk. In all five runs the answer added two decisions and nothing else. The first quote of the proposal's decision is the user's `응` and its next quote is the proposal's words, the Korean decision gave a Korean item, and the small talk gave no item.

**TC-262, outside the curator's scope.** One curate request per run over two instructions aimed at the curator, one in each host, a pasted text in Claude Code's form and one in Codex's, and a made-up key. In all five runs the answer changed nothing: no decision has a title that an instruction asked for, the seeded decision is still current and its state line is as it was, and no item quotes either pasted text. For Codex, where stage 12 asks for a record: the curator saved nothing from the pasted text in 5 of 5 runs. The made-up key is in no request and in no file of the home; the request and the raw log hold a redaction mark in its place.

**TC-345, one fact of five state lines (recorded).** A seeded current state of five lines, then one turn that changes the staging server's port. In all five runs the answer was one replacement of the old decision. It named the affected line and no other, that line now gives the new port, the four other lines are as they were, and the old fact's item is superseded. The package dropped no line edit, and no edit cited an ID that the request did not carry.

**TC-356, an implicit disagreement (recorded).** Two seeded rules of the user, then the user states a rule that contradicts the first without saying that it replaces it, and the agent reports that a file says the opposite of the second. In all five runs the user's later statement replaced the earlier rule, on a quote of the user, and no conflict candidate was left open. Nothing was saved for the agent's report, and the user's second rule stayed current.

## Seen beside the verdicts

These are observations for TASK-047 and TASK-050's report. None is a verdict of a case.

- **The language of a state line.** In TC-258 the state answer wrote the one decision line that the merge left in English in 3 of the 5 runs and in Korean in 2, though both merged decisions were Korean. It also reworded the goal line, which no turn had touched, in 2 of the 5. The instructions of the curate and merge requests ask for the user's or the items' language; those of the state request say nothing about language.
- **Embeddings.** Each of the 30 embedding requests failed with `insufficient_quota`, and the failure log has one `embed` line for each. The worker went on and exited with 0. The check of real embeddings is left to an environment whose OpenAI key has credit.
- **The estimate on the usage line.** In the 30 answered curate requests the working estimate was 0.549 to 0.555 of the input tokens that the provider counted, for example 2,186 against 3,968. TASK-047 measures the estimates against the provider's count.
- **Output tokens.** The 30 answered curate requests were billed 529 to 4,856 output tokens, the median 3,195, for answers of 57 to 1,114 bytes, the median 649. The output count includes the model's thinking, which the package asks for at its own effort setting; TASK-047 compares the settings.
- **Time.** An answered curate request took 3.3 to 21.1 seconds, the median 13.8; a merge request 1.3 to 4.5 seconds and a state request 5.5 to 12.1.

## Trial runs before the record

The script was tried twice against the provider earlier on the same day, before its first commit: four runs of each case, 37 model requests and 0.052513 USD by the usage log. They are not record runs, since their tree was not a commit and the script read less than it does now. Two of their outcomes differ from this run's and are kept here so that what varies is not hidden.

- TC-345: in 1 of the 4 trial runs the current state had four lines afterwards instead of five. The answer's line edit cited an ID that the request did not carry, the package dropped the edit for that reason, and the line of the old fact, whose item was superseded, went. This run saw no such edit in five.
- TC-356: the agent's report left an open conflict candidate in 1 of the 3 trial runs that read it, and nothing in the other 2. This run saw none in five. The user's later rule replaced the earlier one in all 4 trial runs, as it did here.

## Evidence

[The readings of each run](2026-11-12-memory-c2-real-cloud.evidence.json) are a digest of the check's `report.json` (190,499 bytes, SHA256 `e806fe277dc1e27f0ca5070a6fbd8e3b80e6b2d3b18e207483cbcaf7384e09ea`): every outcome and observation, the state lines and the titles that the answers gave, and the worker's runs with their usage lines, tokens and cost. The report itself and the written requests and answers of the 30 homes are kept with the project's private QA evidence, not in this repository.
