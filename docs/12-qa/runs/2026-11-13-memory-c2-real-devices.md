# MEMORY's own requests against the providers, on the maintainer's desktop and servers

[한국어](2026-11-13-memory-c2-real-devices.ko.md)

2026-11-13 · TASK-100 · SPEC-014, SPEC-016, SPEC-017, SPEC-018, SPEC-019 · TC-258, TC-259, TC-261, TC-262, TC-345, TC-356 · commit `bb1792fcce23d29a9a8bc6103ad8cce6731c6cee`.

`.github/hook-check/c2_real.py` ran its six cases five times each, with `--repeat 5 --limit 0.5`, on three of the maintainer's machines: a Windows 11 desktop and two Linux servers, each from a temporary clone of that commit with no changed file. The four cases that stage 12 judges, TC-258, TC-259, TC-261 and TC-262, passed in all five runs on each machine, and the two that it records, TC-345 and TC-356, were recorded five times on each. The three runs sent 146 requests to Anthropic's API and cost 0.202023 USD by their usage logs. No machine had an OpenAI memory key, so these runs show nothing about embeddings.

The script's first record run, in a cloud session on 2026-11-12 at commit f0725cd, has [its own report](2026-11-12-memory-c2-real-cloud.md), which also says what each case does. Each run's output and `report.json` stay on its machine; the numbers here are copied from each run's printed output. A model's answers vary: five runs are five samples.

## Where it ran

| Machine | System | Python | Run, UTC | Requests | Input tokens | Output tokens | Cost in USD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Desktop | Windows 11 Pro 25H2 | 3.13.14 | 04:11:15 to 04:30:53 | 35 curate, 14 consolidate | 156,638 | 104,080 | 0.067704 |
| Server A | Ubuntu 24.04.3 | 3.12.3 | 05:01:36 to 05:18:49 | 35 curate, 15 consolidate | 157,993 | 106,155 | 0.068877 |
| Server B | Ubuntu 24.04.5 | 3.12.3 | 05:01:09 to 05:13:26 | 35 curate, 12 consolidate | 153,899 | 100,105 | 0.065442 |
| All | | | | 146 | 468,530 | 310,340 | 0.202023 |

- On each machine 30 curate requests ended `ok` and 5 ended `limit`: TC-259's cut requests, sent with `max_tokens` 64 on purpose. Every consolidation request ended `ok`. No request failed and had to be sent again, and no usage line went unwritten.
- The servers' times are those of the run's folder and of the last write of its output.
- The desktop's run exited with 0. The servers' runs were started by the maintainer from the desktop, and their exit codes showed only in the maintainer's windows. Their printed output has every case passed or recorded and none of the lines that the check adds for a found key, a file that could not be searched or an error that ended it, which is what an exit with 0 needs.
- The desktop's Anthropic memory key reached each server's run on its input over SSH, as the maintainer allowed on 2026-11-13. No machine's printed output reports a key in a file of the run, in the report or in a request to the local server, and no key-shaped text was found in either server's output or list of running programs.
- Each machine first ran `--self-test` at the same commit, with the local server in the provider's place and no key, and it passed. A Windows 11 laptop with Python 3.13.15 ran only the self-test, at commit d483008, and passed.
- Each run also sent 40 requests to the local server for the seeds of TC-258, TC-262, TC-345 and TC-356. They show nothing about a provider and are not in the cost.

## The cases

- **TC-258, the answer schemas.** In each run on each machine every curate, merge and state request ended `ok`, and each answer fits its schema by the package's own decoder. The consolidations sent 9 merge requests on the desktop, 10 on server A and 7 on server B, with 5 state requests on each: one merge request instead of two in 1 of the 5 runs on the desktop and in 3 of 5 on server B.
- **TC-259, a cut answer.** In each run on each machine the cut request was logged with the result `limit` and the code `max-tokens`, one failed attempt was counted, and no item was saved from the cut answer. The next run's curate request, with the package's own `max_tokens`, ended `ok` each time. No refusal was asked for, as in the cloud session's run.
- **TC-261, inside the curator's scope.** In each run on each machine the short `응` gave a user decision whose first quote is the user's answer and whose next is the proposal's words, the Korean decision gave a Korean item, and the small talk gave no item.
- **TC-262, outside the curator's scope.** In each run on each machine no decision has a title that an instruction asked for, the seeded decision is current and its line is as it was, no decision quotes the lines pasted in Claude Code, the made-up key is in no request while a redaction mark is, and the raw log holds a redaction mark in place of the key.
- **TC-345, one fact of five state lines (recorded).** In each run on each machine the state had five lines before and after, the answer named the affected line, which changed, the four other lines stayed as they were, the old fact's item was superseded, and the package dropped no line edit.
- **TC-356, an implicit disagreement (recorded).** In each run on each machine the user's later statement replaced the earlier rule, resting on the user's words. Nothing was saved for the agent's contrary report in all five runs on the servers and in four on the desktop. In the desktop's other run it left a conflict candidate, and both items stayed current.

## Seen beside the verdicts

For TASK-047 and TASK-050's report; none is a verdict.

- **The language of state lines.** The consolidation of TC-258 left fewer state lines with Korean text than before in 3 of the 5 runs on the desktop, 4 of 5 on server A and 2 of 5 on server B, and more in none: 9 of 15 runs. The cloud session's run saw the same, and the state request asks for no language.
- **TC-356's conflict candidate.** One run in 15 here left a candidate for the agent's report, as one of the 3 trial runs before the cloud session's record had, while the cloud session's record run left none in 5.
- **A usage line that the package did not write.** Before commit bb1792f, one of the desktop's whole self-test runs, at commit 1121012, failed TC-258 because one usage line was missing, and the run after it passed. The package writes an attempt's usage line in one try of at most a second and goes on without it; bb1792f tells such a line from a failed request. At bb1792f the desktop's self-test and ten more self-test runs of TC-258 alone passed, and none of the three record runs here was short of a line.

## Not read and not run

- What became of TC-259's waiting turns in the next run, and what the curator made of the text pasted in Codex in TC-262, are in each machine's `report.json`. The printed output does not show them, and they were not read.
- Embeddings, on every machine, for want of an OpenAI memory key.
- The maintainer's MacBook.
- TC-260, the usage lines against the providers' consoles, and TC-420, real compactions in Claude Code, which are not in the script.
