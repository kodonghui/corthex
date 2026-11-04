# Optional NEXUS work

This is the agent workflow for an installed `corthex-hub` skill and the project's configured NEXUS server. The hub's own skill and command help define its CLI. Use its installed `scripts/hub.py`, not a program in the current directory. Local stage work does not require the hub, a service token or a server.

## Read once in a session

After identifying the project, read its agent to-do once per project in this session, from either the entry skill or the first stage skill reached. Carry that fact in the session; changing stages does not trigger another read. An explicit request to refresh work may read again.

1. Check that the hub is installed and the project is in the profile's `nexus.push`, with a configured `nexus.url`. Otherwise continue local work. Never enable sending, register a new address or add a project to this list on your own.
2. Choose one stable session label without personal data. Use it in `--session` on `todo`, claims and writes. Keep the service credentials in the host's environment; never print them or pass them as command arguments.
3. At the start of work and after a source/record PR merge or checkpoint, fetch the configured default branch under the repository rules and synchronize that fetched commit before reading the to-do, once for this start/event. For an already authorized first send, run `push PROJECT --dry-run` and `push PROJECT` under the hub and repository rules; the hub checks held-commit ancestry. If the first send is not approved, show the dry-run and ask once, continue local work while waiting, and honor any existing instruction to defer that question. Do not push a worktree commit or enable an automatic network hook. A missing token/server response does not stop local work.
4. Run `hub.py todo PROJECT --session SESSION --json`. It drains the project's outbox before reading. A kept write is pending delivery, not a received comment; report the hub's result accurately.
5. A missing space is empty: say nothing. With no token or no server answer, say once that comments may be waiting, and continue the user's work. Do not keep retrying or ask for a token merely to finish local work.
6. Give one short list if work is waiting: open comments oldest first; open discrepancies, warn before info; pending reflections without a PR before those in review; then checkpoints waiting for their record or withdrawal correction. Include waiting-for-user and taken counts. Each group's returned 50 entries are a page with a total, not proof that no more exist.
7. Do the user's explicit task first. Work through the available to-do afterwards, in that order. Never infer that a proposal or a discrepancy authorizes a different change.

## Take an entry safely

Read the full entry and the latest relevant stage source, using `show PROJECT ENTRY` for comments, proposals, reflections and checkpoints. The to-do/overview contains discrepancies; `show` does not accept `nd_` IDs.

- Before acting, run `claim PROJECT ENTRY --session SESSION`. A failed claim is never queued. If another session holds it, skip it; a lost session label does not grant a new claim. Do not invent a new label to evade a hold.
- Claims last 60 minutes from the session's last write on the entry. Renew through a claim or a successful write, and release when leaving the work open. User writes are not blocked by an agent's claim.
- A reported open PR holds a reflection or checkpoint for every session until it is merged or closed, even after 60 minutes. Do not take it or open a second PR. Read the PR and report its actual state only after checking it.
- Read a refusal's status and code. Do not turn `claimed`, a changed source or a withdrawn checkpoint into a blind retry. Offline writes retain their original ID/session for seven days; use the outbox, never manufacture a replacement ID.

## Comments and decisions

Reply on the comment when the discussion continues in the session. A reply that leaves a question open stays a reply. When the user's choice settles it, write their words, where and when they said them in the project's records. Change stage sources through a PR as the repository requires.

While that PR is open, reply with its link and leave the comment open. After the decision is written in the records or the source PR is merged, use `decide PROJECT COMMENT --link HTTPS_URL` to link the written decision; it closes the comment. A link is required and must not contain secrets or an email address. A closed unmerged PR requires another question to the user on the comment. Never claim an AI recommendation was the user's decision.

## Reflect an accepted change

An accepted proposal authorizes preparing its described change. It does not authorize release, unrelated edits or overriding the project's permissions.

1. Claim the pending reflection and use `show` to read its proposal in full. Compare its recorded document version and affected items with the default branch's latest fetched source.
2. If the described change still fits, make one source PR under the project's rules and report `reflect PROJECT EDIT opened --pr HTTPS_URL`. The report releases the claim and the PR holds the entry.
3. If the source already contains it, report `reflected --commit FULL_COMMIT` after verifying that commit. If affected items changed or disappeared so it no longer fits, ask the user on the related comment and report `needs-user`; leave the decision to them.
4. Report `merged --pr HTTPS_URL` only after verifying the merge. Report `closed --pr HTTPS_URL` for an unmerged closure; ask the user again unless a replacement PR was opened and reported. Never open a duplicate merely because another session's claim expired.
5. After the merge, send a fresh snapshot only within the existing server/project authorization and after the first-send confirmation below. Verify the result; a queued write is not a redraw.

## Record the work and its checkpoint

Write the stage's state, next action and checked findings in the same PR as the work. Use `status PROJECT STAGE --repository` for the first record; later calls update repository records automatically. For a configured part use `--part PART`: it writes `.corthex/stages/PART.json`; an unpartitioned project uses `.corthex/stages.json`. Never copy one part's state over another. The hub writes files only; the agent follows the repository's commit/PR rules.

- Keep `in_progress` until the user passes the required checkpoint. `done` requires completed stage work and its last human checkpoint. A file, a read receipt and permission to continue are not approval.
- A checkpoint records what the user approved (their words when given), `--by` as a role such as `the maintainer`, `--date`, and a safe `--where` link to the approval. No personal name or email belongs in the repository. Session approvals link to their record in the project's records.
- For a checkpoint passed in NEXUS, claim it first; include its `--nexus CHECKPOINT` ID and the overview link. Once the PR is open, report `record PROJECT CHECKPOINT opened --pr HTTPS_URL`.
- Immediately before merge, use `show` to confirm the NEXUS checkpoint is still passed. A withdrawal means close the PR unmerged or remove that checkpoint. Report the actual merged/closed outcome. Do not say the state is recorded until the merged record has been pushed and read back.
- A pushed withdrawn checkpoint produces `checkpoint-withdrawn`. Correct the repository record through a PR; never erase the server warning by pretending the checkpoint is passed.

## Source annotations and sending

Keep the stage's existing six-slot contract and source-of-truth direction. In stage 01 preserve an existing explicit event timeline and its lane/place order in the domain source; do not infer one from a context table. In stages 05 and 07 name the glossary terms of the aggregates/read models each table or screen represents, or `terms: none`, and explicitly list the part's terms without a table/screen. The individual stage references give the forms the hub reads.

After a merged source/record PR, `push --dry-run` describes the snapshot from the latest fetched default commit. Before a project's first real send, show that description and obtain the user's confirmation, even if the project is already allowlisted. Existing approval applies only to its configured server and project. Then `push` sends it; it never commits or opens a PR. Follow the held-commit result; divergence needs agreement before `--replace-held`. Do not expose a token, send to a redirect, delete a project or mark a checkpoint passed to make a sync succeed.


## Project approval categories

Apply the core's project settings rule before a NEXUS action: a valid project `ask_before` list replaces the profile list, including an empty list; invalid categories preserve the profile list. Read the complete list when the session context says it was shortened. Existing explicit user authorization still applies, and irreversible actions keep their confirmation boundary. A claim, accepted proposal or passed checkpoint does not remove that rule or authorize a different release/send/delete action.
