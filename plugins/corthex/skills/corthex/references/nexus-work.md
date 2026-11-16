# Optional NEXUS work

This is the agent workflow for an installed `corthex-hub` skill and the project's configured NEXUS server. The hub's own skill and command help define its CLI. Use its installed `scripts/hub.py`, not a program in the current directory. Local stage work does not require the hub, a service token or a server.

Three sections need no hub and no token: Ask for a checkpoint, Tell the user where the work stands, and Walk a NEXUS server's pages in a browser. They hold in every session of a project that is expected on a NEXUS server, also in a session that cannot send. A project is expected there when the hub's `can-send` answers `expected`, which it does when the project's settings say `on_nexus` or the push list names the project, or when the user says so.

## At a session's start

After identifying the project, take these steps once per project in this session, from either the entry skill or the first stage skill reached. Carry the result in the session; changing stages does not repeat them. An explicit request to refresh work may read again.

1. Run `hub.py can-send PROJECT`. It contacts no server, sends nothing and needs no session label. Its answer gives `can_send`; `missing`, the names of the settings or variables that are not set, never a value; and `expected`, whether the project is expected on a NEXUS server.
   - `can_send` is true: go on with step 2.
   - `can_send` is false and `expected` is true: tell the user once in this session, in one line in their language, what is `missing` and that these are their own settings. Then continue the user's work. Say nothing again for this project, also when another skill starts.
   - `expected` is false: say nothing, and continue local work.
   - The hub is not installed: read `on_nexus` in `.corthex/project.json` yourself. When it is `true`, the same one line names the hub as missing; otherwise say nothing.
   - The hub does not know `can-send`: it is older than these rules. Say so once, go on with the user's work, and follow that hub's own command help: it sends for a project in the profile's `nexus.push` with a configured `nexus.url`, takes no `--first`, `--if-due` or `--look-first`, and a checkpoint request's thing to look at first is then the last line of its text.

   Never set the address, the push list or the token yourself, in a profile, in a session's environment or in a repository, and never ask for a token's value. Never enable sending, register a new address or add a project to this list on your own.
2. Choose one stable session label without personal data. Use it in `--session` on `todo`, claims and writes. Keep the service credentials in the host's environment; never print them or pass them as command arguments.
3. At the start of work and after a source/record PR merge or checkpoint, fetch the configured default branch under the repository rules and synchronize that fetched commit before reading the to-do, once for this start/event. For a first send that the user already agreed to for this project, run `push PROJECT --dry-run` and `push PROJECT --first` under the hub and repository rules; the hub checks held-commit ancestry. If the first send is not approved, show the dry-run and ask once, continue local work while waiting, and honor any existing instruction to defer that question. Do not push a worktree commit or enable an automatic network hook. A missing token/server response does not stop local work.
4. Run `hub.py todo PROJECT --session SESSION --json`. It drains the project's outbox before reading. A kept write is pending delivery, not a received comment; report the hub's result accurately.
5. A missing space is empty: say nothing. With no token or no server answer, say once that comments may be waiting, and continue the user's work. Do not keep retrying or ask for a token merely to finish local work.
6. Give one short list if work is waiting: open comments oldest first; open discrepancies, warn before info; pending reflections without a PR before those in review; then checkpoints waiting for their record or withdrawal correction. Include waiting-for-user and taken counts. Each group's returned 50 entries are a page with a total, not proof that no more exist.
7. Do the user's explicit task first. Work through the available to-do afterwards, in that order. Never infer that a proposal or a discrepancy authorizes a different change.

## Read the to-do again

A session that can send reads the project's to-do again at two moments. A session that cannot send reads nothing, and says nothing again.

- Where a unit of stage work starts or ends, run `todo PROJECT --session SESSION --if-due --json`. The hub reads only when the session's last read is more than a day old; otherwise it contacts no server, and the result's `read` is false.
- Before each checkpoint request, run `todo` without `--if-due`, whatever the time of the last read. Answer the entries on the stage that you are about to ask for, or name them in the request as open.
- After a read that follows the session's first, tell the user only what the result's `new` holds, and take it up as step 7 says. When nothing is new, say nothing about it.
- No answer from the server is said once, as in step 5, and the work and the checkpoint request go on.

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

## Ask for a checkpoint

A checkpoint request is what the user reads before passing a stage, so it has one form.

- Ask for one part's stage in one request, never for several stages. Stages that wait together get a request each, asked one at a time, the earliest stage first.
- Write at most ten lines and 1,200 characters in all, in the user's language and in plain words: what changes for the user, not how the work went. The detail stays in the stage's source.
- Name one thing to look at first, and only one: an item by its trace ID, an `https` address, or the stage's own picture or list.
- Ask the checkpoint's question alone. Another open choice gets a question of its own, with its recommendation and the other choices.
- For a stage of screens (stages 07 to 09, or a unit of stage 11 or 12 that adds or changes a screen), show something that the user can press: the built screen, or a mockup that answers presses where nothing is built yet. A picture of a screen alone is not enough. The thing to look at first is then the address where it opens on the user's own phone or PC, or the screen's ID with a line that says where its file is. Say at which widths and in which states you looked yourself, and which you did not.
- Use an address that needs no new permission and shows project data to nobody else: the project's own preview behind the same sign-in, an address in the session, or a file that opens by itself. Showing a screen releases nothing: a deploy that the project asks about first is still asked.
- Where nothing can be pressed yet, such as a sitemap with no screen drawn, say so in one of the lines and name the stage's picture first.

Make the request in the session. Where the session can send, also send it through the hub, as a comment on the stage as a whole: `comment PROJECT --stage STAGE [--part PART] --asks checkpoint --look-first ID|URL|stage`, with the same lines as its text and without `--item`. `--look-first` takes the item's trace ID, the `https` address, or the word `stage` for the stage's own picture or list. The hub checks the form before it sends, and says what to shorten or add.

- `refused` with `read the to-do first`: the hub's read before the request brought entries that are new. Answer those on the stage, or name them in the request as open, and send it again.
- The remark `sent-as-reply`: the part's stage already had an open request, and the hub sent this one as a reply on it. A part's stage has one open request at a time.
- The remark `server-older`: the server does not know the new form yet, and the hub sent what that server takes. Nothing more is needed.
- The request waits in the outbox, the server refuses it, or the session cannot send: the request in the session stands. Do not reword it to get it through.

## Tell the user where the work stands

The user cannot see the work between checkpoints. Say each of these once, in the session and in the user's language. A notice asks nothing.

- A plan of tasks is agreed on its own, at stage 10's checkpoint: the plan gets a checkpoint request of its own, and no task of it starts before the user passes that checkpoint. The pass of an earlier stage, or of the design that the plan follows, does not agree the plan.
- When building starts (stage 11), say so in one line: that building has started, the first task, and where the work shows.
- Each time a stage passes or a group of tasks ends, send one short notice: where the work stands, what changed for the user in at most ten lines, and one thing to look at first. When a checkpoint is due at that point, the stage's request takes the notice's place.

## Walk a NEXUS server's pages in a browser

A NEXUS server cannot tell a browser agent in the user's signed-in browser from the user: what the agent presses there is recorded as the user's own act. So every brief for a walk of NEXUS pages, in stage 12 or elsewhere, carries these rules.

- A project is synthetic only when the brief names it as made for the test. Every other project counts as real.
- On a real project the walk only reads. It never makes a press that is the user's own: passing or withdrawing a checkpoint, accepting or dismissing a proposal, taking a recommendation, marking a comment answered, removing a project, or any other press that the page offers the user for deciding, sending or removing something. It leaves no comment and no reply there either, since the server would record them as the user's.
- Up to such a press the walk reports what the page offers, and stops. The acts themselves are walked on a synthetic project, on a server or in a space that holds no real project.
- A brief that names no synthetic project makes the whole walk read-only, and the report says so.
- After a press made by mistake on a real project, stop and report at once what it changed. Do not undo it yourself: taking it back is the user's act too.

## Record the work and its checkpoint

Write the stage's state, next action and checked findings in the same PR as the work. Use `status PROJECT STAGE --repository` for the first record; later calls update repository records automatically. For a configured part use `--part PART`: it writes `.corthex/stages/PART.json`; an unpartitioned project uses `.corthex/stages.json`. Never copy one part's state over another. The hub writes files only; the agent follows the repository's commit/PR rules.

- Keep `in_progress` until the user passes the required checkpoint. `done` requires completed stage work and its last human checkpoint. A file, a read receipt and permission to continue are not approval.
- A checkpoint records what the user approved (their words when given), `--by` as a role such as `the maintainer`, `--date`, and a safe `--where` link to the approval. No personal name or email belongs in the repository. Session approvals link to their record in the project's records.
- For a checkpoint passed in NEXUS, claim it first; include its `--nexus CHECKPOINT` ID and the overview link. Once the PR is open, report `record PROJECT CHECKPOINT opened --pr HTTPS_URL`.
- Immediately before merge, use `show` to confirm the NEXUS checkpoint is still passed. A withdrawal means close the PR unmerged or remove that checkpoint. Report the actual merged/closed outcome. Do not say the state is recorded until the merged record has been pushed and read back.
- A pushed withdrawn checkpoint produces `checkpoint-withdrawn`. Correct the repository record through a PR; never erase the server warning by pretending the checkpoint is passed.

## Source annotations and sending

Keep the stage's existing six-slot contract and source-of-truth direction. In stage 01 preserve an existing explicit event timeline and its lane/place order in the domain source; do not infer one from a context table. In stages 05 and 07 name the glossary terms of the aggregates/read models each table or screen represents, or `terms: none`, and explicitly list the part's terms without a table/screen. The individual stage references give the forms the hub reads.

After a merged source/record PR, `push --dry-run` describes the snapshot from the latest fetched default commit. Before a project's first real send, show that description and obtain the user's confirmation, even if the project is already allowlisted. Existing approval applies only to its configured server and project. Then `push PROJECT --first` sends it: add `--first` only after the user's yes for that one project, never for several projects and never on your own. Without it the hub sends no first push and says that the push waits for the user's yes. A project that the user removed is a first push again. `push` never commits or opens a PR. Follow the held-commit result; divergence needs agreement before `--replace-held`. Do not expose a token, send to a redirect, delete a project or mark a checkpoint passed to make a sync succeed.

Removing a project from the server is the user's own act. `remove PROJECT` sends no removal: it shows what a removal would delete, with the open comments, open proposals, pending reflections and unrecorded checkpoints by ID, and gives the address of the project's data, where the user removes the project under their own sign-in. Show the user both. Offer to answer, reflect or record those entries first. Say that a removed project comes back only by a first push that the user agrees to, and, while the project is still in the push list, how to take it off the list. Never open that address to press the removal yourself. A server from before the design revision has no project's data yet: there `remove` shows that server's dry run instead, with the remark `server-older`, and gives no address. Until the server of the revision runs, the project cannot be removed: say so, and never remove it another way, such as with an older hub.


## Project approval categories

Apply the core's project settings rule before a NEXUS action: a valid project `ask_before` list replaces the profile list, including an empty list; invalid categories preserve the profile list. Read the complete list when the session context says it was shortened. Existing explicit user authorization still applies, and irreversible actions keep their confirmation boundary. A claim, accepted proposal or passed checkpoint does not remove that rule or authorize a different release/send/delete action.
