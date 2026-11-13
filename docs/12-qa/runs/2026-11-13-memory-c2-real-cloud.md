# MEMORY's own requests against the providers, in a cloud session, with embeddings

[한국어](2026-11-13-memory-c2-real-cloud.ko.md)

2026-11-13 · TASK-100 · SPEC-014, SPEC-016, SPEC-017, SPEC-018, SPEC-019 · TC-258, TC-259, TC-261, TC-262, TC-345, TC-356 · commit `87daf6208afe51dc5ec9434979ff742ea66ca60c`.

`.github/hook-check/c2_real.py` ran its six cases five times each, with `--repeat 5 --limit 0.5`, from a clean clone of that commit with no changed file, in a cloud session of Claude Code on Linux with Python 3.13.18. Both memory keys were set: the Anthropic key and an OpenAI key with credit. The four cases that stage 12 judges, TC-258, TC-259, TC-261 and TC-262, passed in all five runs, and TC-345 and TC-356 were recorded five times. The run lasted from 07:20:52 to 07:33:40 UTC and exited with 0. It sent 48 requests to Anthropic's API and 30 embedding requests to OpenAI's, none of which had to be sent again, and cost 0.070579 USD by the usage log.

This is the first run of the check whose embedding requests reached a provider that answered them: in [the first cloud session's run](2026-11-12-memory-c2-real-cloud.md) at commit f0725cd every one ended `insufficient_quota`, and [the maintainer's desktop and servers](2026-11-13-memory-c2-real-devices.md) had no OpenAI key. The first report also says what each case does. A model's answers vary: five runs are five samples, and the counts below are counts of this run.

## What ran, and what kind of evidence it is

- **Real.** The staged worker of release 0.3.0 ran 40 times with the memory keys against the providers' own addresses, since the script passes the worker no base address. It sent 35 curate, 8 merge and 5 state requests to the curator model that the package sets by itself, `claude-haiku-5-5`, and 30 item embedding requests to `text-embedding-3-small`: 78 lines of the usage log.
- **Local seed.** Where a case needs a layer that is known beforehand (TC-258, TC-262, TC-345 and TC-356), its first turns were curated against a local server whose answers the script writes: 20 runs of the worker and 40 requests to that server. They show nothing about a provider and are not in the cost.
- **Made up.** Every turn. Each run of a case has a home, a project and a memory store of its own.
- Each of the 60 runs of the worker exited with 0, and no worker run noted a failure. The script's `--self-test`, with the local server in the providers' place and no key, passed at the same commit just before, from 07:20:01 to 07:20:40 UTC.
- No file under the run's folder holds a memory key, none had to be masked in the report, and none of the 40 requests to the local server carried one.

| Case | Runs | Outcome | Requests to the providers | Input tokens | Output tokens | Cost in USD |
| --- | --- | --- | --- | --- | --- | --- |
| TC-258 | 5 | pass | 5 curate, 8 merge, 5 state, 10 embedding | 40,109 | 33,721 | 0.020802 |
| TC-259 | 5 | pass | 10 curate, 5 of them cut, 5 embedding | 34,935 | 13,077 | 0.010006 |
| TC-261 | 5 | pass | 5 curate, 5 embedding | 19,883 | 20,915 | 0.012383 |
| TC-262 | 5 | pass | 5 curate | 22,647 | 3,164 | 0.003847 |
| TC-345 | 5 | recorded | 5 curate, 5 embedding | 21,113 | 10,096 | 0.007133 |
| TC-356 | 5 | recorded | 5 curate, 5 embedding | 19,198 | 29,029 | 0.016409 |
| All | 30 | | 78 | 157,885 | 110,002 | 0.070579 |

The cost is what the package's price list gives for the tokens of each usage line: 0.063418 USD for the curate requests, 0.007109 for the merge and state requests and 0.000053 for the embeddings. Whether the providers' consoles show the same is TC-260.

## The cases

- **TC-258, the answer schemas.** In each run every curate, merge and state request ended `ok`, and each of the 18 answers fits its schema by the package's own decoder. The consolidation sent one merge request instead of two in 2 of the 5 runs.
- **TC-259, a cut answer.** In each run the curate request sent with `max_tokens` 64 was logged with the result `limit` and the code `max-tokens`, at 3,457 to 3,467 input tokens and 64 output tokens. One failed attempt was counted, no item was saved, and both turns stayed waiting. The worker's next run, with the package's own `max_tokens`, curated both turns each time: one `ok` line, two items, no turn left and the count of failed attempts back at 0. No refusal was asked for, as in the earlier runs.
- **TC-261, inside the curator's scope.** In each run the short `응` gave a user decision whose first quote is the user's answer and whose next is the proposal's words, the Korean decision gave a Korean item, and the small talk gave no item.
- **TC-262, outside the curator's scope.** In each run no decision has a title that an instruction asked for, the seeded decision is current and its line is as it was, no item quotes an instruction or either pasted text, the made-up key is in no request and no file of the home while a redaction mark is in the request, and the raw log holds a redaction mark in place of the key. For Codex, where stage 12 asks for a record: the curator saved nothing from the pasted text in 5 of 5 runs.
- **TC-345, one fact of five state lines (recorded).** In 4 of the 5 runs the state had five lines before and after, the answer named the affected line and no other, that line changed, the four other lines stayed as they were, the old fact's item was superseded, and the package dropped no line edit. In the third run the answer also named the affected line, but its line edit cited an item ID that the request did not carry. The package dropped the edit for that reason, the affected line went, and the state had four lines afterwards; the four other lines stayed as they were and the old fact's item was superseded.
- **TC-356, an implicit disagreement (recorded).** In each run the user's later statement replaced the earlier rule, resting on the user's words. Nothing was saved for the agent's contrary report in 3 of the 5 runs. In the other 2 it left a conflict candidate, and both items stayed current.

## Embeddings

The worker's index step sent 30 item embedding requests to OpenAI's own address: 10 in TC-258 and 5 in each of TC-259, TC-261, TC-345 and TC-356; TC-262's runs sent none. All 30 ended `ok`, with 49 to 161 input tokens each, 2,626 in all, and took 0.57 to 1.45 seconds, the median 0.71. This shows the item embeddings of the worker against the provider with the cloud session's key. It does not show recall: the prompt hook's embedding and its 0.8-second bound are measured by `c2_measure.py`'s recall part, whose record run is in [the measurement's report](2026-11-13-memory-c2-measure-cloud.md).

## Seen beside the verdicts

For TASK-047 and TASK-050's report; none is a verdict.

- **A lost state line.** TC-345's dropped edit is the one that 1 of the 4 trial runs before the first cloud record saw. Across the runs with the real model so far, 4 trial runs, the 5 of the first cloud record, the 15 on the desktop and the servers and these 5, the state lost a line this way in 2 of 29.
- **TC-356's conflict candidate.** 2 of 5 runs here left a candidate for the agent's report, against 0 of 5 in the first cloud record, 1 of 15 on the desktop and the servers and 1 of the 3 trial runs that read it.
- **The language of state lines.** The consolidation of TC-258 left fewer state lines with Korean text than before in 2 of the 5 runs and more in none, as it did in 9 of 15 runs on the desktop and the servers.
- **The estimate on the usage line.** In the 30 answered curate requests the working estimate was 0.549 to 0.556 of the input tokens that the provider counted.
- **Output tokens and time.** The 30 answered curate requests were billed 548 to 7,605 output tokens, the median 3,456, thinking included. A curate request took 2.9 to 32.3 seconds, the median 14.2; a merge request 1.3 to 3.5 seconds and a state request 4.8 to 7.5.

## Evidence

[The readings of each run](2026-11-13-memory-c2-real-cloud.evidence.json) are a digest of the check's `report.json` (194,914 bytes, SHA256 `74aee62c5460a9260edfe6af33aa02df275e94c2e681de7a1da04e94dbe88707`): every outcome and observation, the state lines and the titles that the answers gave, and the worker's runs with their usage lines, tokens and cost. The report itself, the printed output and the written requests and answers of the 30 homes are kept with the project's private QA evidence, not in this repository.
