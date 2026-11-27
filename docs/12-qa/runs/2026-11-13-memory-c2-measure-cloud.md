# MEMORY measured on redacted real conversations, in a cloud session

[한국어](2026-11-13-memory-c2-measure-cloud.ko.md)

2026-11-13 · TASK-047 · SPEC-014, SPEC-015, SPEC-023 · TC-250, TC-251 · commit `bb1792fcce23d29a9a8bc6103ad8cce6731c6cee`.

`.github/hook-check/c2_measure.py` ran its three parts from a clean clone of that commit, in a cloud session of Claude Code on Linux with Python 3.13.18, with the maintainer's memory keys, against the providers' own addresses. The `efforts` and `skip` parts ran from 04:26:25 UTC to about 05:44 UTC, and the `recall` part from 05:45:27 UTC to about 06:02 UTC. Both runs exited with 0. By the usage log they cost 0.604034 and 0.107688 USD, 0.711722 USD in all, in 385 requests, 94 of which were token counts that cost nothing. No file of either run holds a memory key, and no request went to a local server.

This report gives automatic numbers only. The quality of what was curated and recalled is not judged here: TASK-048 judges recall's candidates, and the efforts are compared by the quality of their items before any default changes. A model's answers vary, and two runs at each effort are two samples.

## The samples

- 14 samples, picked and redacted in the session from the maintainer's own past cloud sessions and project chat: 4 typed samples, prompts typed in cloud sessions with their answers (11 turns); 6 chat samples, the maintainer's messages in the project chat with the first plain answer to each (51 turns); and 4 app-made samples, long texts that the app wrote into sessions as user messages (one turn each, 9,908 to 41,679 characters), which serve the estimates and are left out of the recall part.
- Redaction turned keys, email addresses, IP addresses, phone numbers, home paths, machine names, the maintainer's names and account names, SSH hosts and handles in links into placeholders, and long IDs into made-up ones of the same shape. The samples are kept privately; this report gives numbers and neutral IDs only.
- While the trial runs' items were read on 2026-11-12, one sample was found to still hold an account name of the maintainer that the rules did not know, and another a third person's handle. Both were replaced, and the rules extended, before these runs. A trial run had sent the first of the two to the provider six times.
- All 66 prompts are Korean, so no English number here comes from real prompts.

## TC-250, the estimates against the count

- Each of the 94 curate documents, 84 in the efforts part and 10 in the recall part, was counted by the provider's free count before it was sent, and in every one the count equals the input tokens that were billed.
- The safe estimate was at or above the count for all 94: 1.100 to 1.273 times the count, median 1.183, in the efforts part, and 1.118 to 1.240, median 1.153, in the recall part.
- The working estimate was 0.550 to 0.637 of the count, median 0.592, in the efforts part, and 0.559 to 0.620, median 0.577, in the recall part.
- A line through the efforts part's 84 documents gives 0.411 tokens for each ASCII character, 1.45 for each other character, and 581.3, with errors of up to 529.4 tokens; the two numbers of characters correlate at 0.282. The recall part's 10 documents give 0.6268, 1.1932 and −1,244.8, with errors of up to 144.4 and a correlation of 0.818. The two lines differ, so neither is a rule to estimate by, and the estimates stay as they are.

## TC-251, effort

Each effort curated the 14 samples twice, each run in a home of its own: 28 curate requests. The input is the same at every effort; the output tokens include the model's thinking.

| Effort | Input tokens | Output tokens | Cost in USD | Items | State lines | Time to the answer's first text, median | Request time, mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| medium | 291,491 | 92,585 | 0.075441 | 74 | 67 | 12.4 s | 14.9 s |
| high | 291,423 | 231,588 | 0.144937 | 135 | 97 | 27.3 s | 34.9 s |
| xhigh | 291,436 | 709,025 | 0.383655 | 156 | 138 | 95.3 s | 103.4 s |

- Current items by kind: medium 29 decisions, 20 facts, 13 preferences, 8 references, 4 lessons; high 44, 33, 25, 23, 10; xhigh 48, 42, 21, 23, 22.
- Changes the package dropped: one at medium, for its quote. Line edits it dropped: 10 at medium (5 for what they cited, 5 for their decision), 6 at high and 2 at xhigh (for their decision).
- Runs that made no item: 8 at medium, 4 at high, 2 at xhigh. A sample's two runs at one effort differed by five items or more in 9 of the 42 pairs, for example 6 items and none at medium, or 17 and 9 at xhigh.
- A request took 1.2 to 42.6 seconds at medium, 4.9 to 88.8 at high, and 8.9 to 190.3 at xhigh.
- The package's default is xhigh. Against high, xhigh made 16% more items at 2.6 times the cost and 3 times the time. Whether those items are worth it is a question of their quality, which this report does not judge, so the default is not changed here; the maintainer is asked once, with the numbers and a judgement of quality.

## TC-251, vector length

The recall part replayed the 10 typed and chat samples in time order in one home. Each prompt was asked at 512 and at 1,536 numbers before its sample was recorded, the lengths taking turns to be asked first, with the threshold at 2 so that nothing was injected. A prompt whose embedding was late was asked once more with 30 seconds.

| Length | Prompts | Ranked | Late, then ranked | Short | Hook time from outside, median and p95 | Embedding, median | Best score, median | Fifth score, median |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 512 | 60 | 53 | 3 | 7 | 615.0 and 818.6 ms | 403 ms | 0.361 | 0.280 |
| 1,536 | 60 | 53 | 2 | 7 | 599.0 and 728.5 ms | 400 ms | 0.321 | 0.227 |

- Both lengths gave the same best item for 42 of the 53 prompts ranked at both. Their five candidates shared 3 to 5 items, median 4. The best score at 1,536 was lower by 0.051 at the median, from 0.094 lower to 0.018 higher.
- Late means that the embedding did not come back within the hook's 0.8 seconds (API-010), so the hook went on without recall. 6 of the 178 prompt embedding requests ended in a timeout.
- By turn: the median hook time was 624.3 ms asked first and 591.6 ms asked later at 512, and 588.0 and 611.2 ms at 1,536, so the order moves the times as much as the length does.
- As the installed hook recorded the turns, its p95 was 684.1 ms at 512 (30 prompts) and 717.8 ms at 1,536 (32). Those embeddings repeated a text that had been sent seconds before (23 and 30 of them), so they are no reading of a text that is new to the provider.
- The 7 prompts that the default `recall.skip` skipped were asked once more without the skip. All 7 were ranked below the threshold, with a median best score of 0.332 at 512 and 0.272 at 1,536. TASK-048 judges whether recall would have served them.
- The default of 512 stays: 1,536 gave lower scores and mostly the same best item here, and neither length was judged by quality.

## The share that `recall.skip` skips

- At the default of 8 characters, 9 of the 66 prompts are skipped as short, 13.6%: 9 of the 55 project-chat messages and none of the 11 prompts typed in cloud sessions. None is skipped as a command.
- At other values: 2 at 4, 7 at 6, 10 at 10, 11 at 12 and 17 at 16. If a Hangul syllable counted as 2, 3 would be skipped at 8.
- The English share is not measured, since no prompt is English.

## Cost by the usage log

| Part | Requests | Cost in USD |
| --- | --- | --- |
| efforts | 84 curate, 84 counts | 0.604034 |
| recall | 10 curate, 10 counts, 19 item embeddings, 178 prompt embeddings | 0.107688 (curate 0.107009, embeddings 0.000680) |

Whether the providers' consoles show the same is TC-260.

## Limits

- One cloud session on Linux, whose times are not a device's.
- Few samples, all the maintainer's own and nearly all Korean: 14 samples and 66 prompts.
- Two runs at each effort, whose results vary widely within a pair.
- No quality judgement: these numbers say how much was made and how fast, not how good it is.
