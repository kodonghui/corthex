# Hub files and formats

The hub's generated files are under `~/.corthex/hub/` (on Windows, `%USERPROFILE%\.corthex\hub\`). From 0.2, `status` can also write repository stage records, as described below:

| File | Written by | Holds |
| --- | --- | --- |
| `snapshots/<project>.json` | `snapshot`, `build` | what the project's stage sources define and link, and the checks |
| `status/<project>.json` | `status` | each stage's recorded state, checkpoint, next action and review findings |
| `status/<project>.json.bak` | `status` | the status file as it was before the last write |
| `index.html` | `build` | the hub page |
| `outbox/<project>/<time>.<write>.json` | agent writes | one redacted write awaiting a retry |
| `outbox/<project>.lock`, `<project>.guard` | commands that drain the outbox | the renewable lease and short operating-system guard, with no text or token |
| `outbox/<project>.order` | agent writes | write IDs in admission order, to break equal-millisecond ties without changing their creation times |

Files are written through a temporary file, so a failed write keeps the old one. Rebuilding regenerates snapshots and the page. Preserve stage records and unsent writes: rebuilding cannot recover either.

## Current snapshot: `corthex-hub/0.2`

0.2 keeps the legacy fields below and adds:

| Field | Meaning |
| --- | --- |
| `project.parts` | Optional, 1 to 50 distinct lowercase names joined by hyphens, each at most 100 characters; their order is the display order |
| `repos.".".url` | Canonical origin: HTTPS, lowercase host, no credentials, final `.git` or slash; SSH transports are converted to the same repository address |
| `repos.".".default` | `branch`, full `commit` and zoned commit `time` from `refs/remotes/origin/HEAD`, as last fetched |
| `records` | `from: repository` with its `commit` and `time`, or explicit `from: status-file` fallback |
| `stages.<stage>.checkpoints` | Repository checkpoint list for a project without parts; legacy `checkpoint`/`checkpoint_date` keep the last approval |
| `stages.<stage>.parts.<part>` | That part's `state`, `checkpoints`, `next`, `updated`; an absent record remains unknown |
| `pictures` | Each has `part`, pictured `stage`, full default `commit`, `time` and format-1 `source` |
| `left_out` | Picture omissions with `part`, `stage`, `why: size` or `other-repository` |
| `ask_before` | Up to 30 `entries`, their `source: project/profile/default`, and the inherited entries a project override leaves out, `left_out`. A project entry keeps an inherited one when it repeats it, ignoring case, alone or followed by a space or `(`: `deletions (data)` keeps `deletions` |
| `replaces` | Added only by a sending push when replacing the server's held commit |

Only pictures and repository stage records come from the fetched default commit. `ls-tree` and `cat-file` read regular blobs without a checkout, filters, hooks, submodules or the working branch's text. Replacement refs and automatic object fetches are disabled, so a local replacement or missing partial-clone blob cannot silently change the reported bytes or turn a local command into a network request. Missing Git, origin or origin HEAD gives no pictures and `pictures-not-sent`, with the command to record the head. Sources in another repository are omitted explicitly. A document starts a part name followed by `/`, `.` or `-`; the longest matching name wins. An unmatched document is pictured for the whole project with `part-unknown`.

Picture formats are described in [reading.md](reading.md). The snapshot carries interpreted picture data, never arbitrary source files. Limits remain 3,000 items, 2,000 checks and 1,000,000 compact UTF-8 bytes: remove whole pictures, largest first, before trimming items and checks. Each omitted picture is named in `left_out` and a check. All strings are redacted, including the actual service-token components and the user's home folder. A sensitive link is omitted whole.

## Repository stage records

`status --repository` creates the first `.corthex/stages/<part>.json` (`--part` required when the project declares parts), or `.corthex/stages.json` without parts. Once repository records exist, `status` writes there automatically. It writes ordered two-space JSON with a final LF through a unique temporary file and atomic replacement; it preserves other stages and part files. It never commits, pushes or opens a pull request.

The format is `{"format":1,"project":"acme-shop","part":"orders","stages":{...}}`; `part` is absent for a project without parts. A stage has `state`, a `checkpoints` list, `next`, optional `checks` and zoned `updated`. A checkpoint has `approved`, `by` (a role), calendar `date`, optional safe HTTPS `where` and optional NEXUS `nexus` ID. Add one with `--checkpoint TEXT --by ROLE --date YYYY-MM-DD [--where LINK] [--nexus ID]`. A NEXUS checkpoint defaults its link to the configured stage overview. `done` needs a dated checkpoint.

The snapshot reads these records from the fetched default commit, not from this write's working tree. Invalid records show unknown with `records-invalid`; they do not restore an old device approval. Only when no repository records exist does it use the legacy status file, with `records-in-status-file`. It retains legacy approval text without inventing a role or NEXUS ID. A legacy `done` without a checkpoint and valid date becomes `in_progress` with a warning.

## Outbox and command results

Eight request names can wait: `comment`, `reply`, `answered`, `decision`, `proposal`, `withdraw-proposal`, `report-edit`, `report-checkpoint`. Each format-1 file holds `write`, `project`, `request`, generated API `path`, `session`, UTC `made`, already redacted `body`, `tries` and optional `failure`. It contains no token. Each retry uses the same quoted `Idempotency-Key` and session. `outbox` lists metadata only; `--send` drains it oldest first, stopping at the first retryable failure.

Every fresh agent write is queued before HTTP, then sent through that same drain. A separate ID-only ordering file breaks equal-time ties; older creation times still come first. A lost lease cannot discard the current write or overwrite a newer holder's metadata. If persistence fails completely, only that failed command's optional `recovery` gives the calling agent one copy of the original redacted file, including its ID/body. Keep it in the session, never a log; normal output and queue listings contain no recovery text.

No network, no answer within 30 seconds, missing/refused token, HTTP 429/500/502/503/504 or `access_missing`/`access_other_app` keeps a write. Other refusals and seven-day expiry drop it with its reason, never its text. An exclusive-create per-project lease renews after sends, is stale after 120 seconds and fences former owners. A short OS lock serializes lease operations; a busy second writer can append a unique unsent file for a later drain. Claims, pushes and removals never wait in the outbox.

`--json` gives one line per project: `command`, `project`, `outcome`, `answer`, `problem`, `failure`, `outbox` counts (`sent`, `dropped`, `waiting`), with optional drop `notices`. Exit 0 means done, 1 refused/failed, 2 invalid command line, 3 a write kept. Without it, the same result is readable text. URLs come from `--url`, environment, then profile; only configured HTTPS (or loopback HTTP) is contacted, never a redirect. Tokens come only from environment variables.

## Legacy snapshot: `corthex-hub/0.1`

```json
{
  "schema": "corthex-hub/0.1",
  "generator": "corthex-nexus 0.1.0",
  "generated_at": "2026-01-12T10:00:00+09:00",
  "project": {
    "name": "acme-shop", "title": "Acme Shop", "team": true, "language": "en",
    "records": { "kind": "notion", "link": "https://example.com/records" }
  },
  "ids": { "REQ": "requirement", "SPEC": "spec" },
  "repos": {
    ".": { "commit": "<full commit id>", "branch": "main", "dirty": false, "web": "https://github.com/example/acme-shop" },
    "design": { "checkout": false, "url": "https://github.com/example/acme-shop-design", "web": "https://github.com/example/acme-shop-design" }
  },
  "stages": {
    "02-prd": {
      "name": "PRD", "human": "notion", "link": "https://example.com/prd", "truth": "human",
      "source": "design:prd/", "repo": "design", "source_state": "found", "read": true, "files": 3, "items": 12,
      "copied": { "oldest": "2026-01-11T09:00", "newest": "2026-01-11T09:00" },
      "state": "done", "checkpoint": "PRD approved in the kickoff review", "checkpoint_date": "2026-01-12",
      "next": "Write the user flows", "updated": "2026-01-12T10:00:00+09:00"
    }
  },
  "items": [
    {
      "id": "REQ-001", "kind": "requirement", "stage": "02-prd", "where": "design:prd/requirements.md:3",
      "title": "Send an order confirmation", "status": "active", "type": "functional", "priority": "Must",
      "links": ["CTX-001"]
    }
  ],
  "checks": [
    {
      "rule": "unknown-ref", "level": "warn", "by": "scan", "stage": "02-prd",
      "message": "REQ-009 is mentioned but not defined in 02-prd: …", "refs": ["REQ-009"],
      "args": { "id": "REQ-009", "stage": "02-prd", "places": ["design:prd/flows.md:7"] }
    }
  ],
  "summary": { "items": 12, "kinds": { "requirement": 12 }, "checks": { "error": 0, "warn": 1, "info": 0 }, "states": { "done": 1, "unknown": 12 } },
  "truncated": false
}
```

- `ids` maps each prefix to its kind.
- `repos` has `.` for the project's own repository and one entry per alias in the project's `repos`. `checkout: false` means this machine has no local copy. `web` is set for GitHub repositories and lets the page link each `where` to the file at that commit. `dirty` says whether the working tree has changes, not counting changes inside submodules. It is left out when a tracked file uses a clean filter, such as Git LFS, because Git would have to run the filter to tell.
- Each stage has `source_state`: `found`, `missing`, `none` (no text source), `no-checkout`, `skipped` or `invalid`. `default_source: true` marks the contract's default path. `read` and `files` are set for stages that were read, `skipped` counts the files that were not.
- `state` is `done`, `in_progress`, `not_started` or `skipped` as recorded, and `unknown` when nothing is recorded. A stage with `skip: true` and no record shows as `skipped`.
- Items are in stage order, then by ID. `where` is `file:line`, with the repository alias in front for another repository. Optional fields: `title`, `status`, `type`, `priority`, `link`, `parent`, `screen_doc`, `states` and `links`.
- Checks are ordered by level, then stage. `by` is `scan` for the rules in [reading.md](reading.md) and `review` for findings recorded with `status --check`. `args` holds the values of the message, so the page can show it in another language.

### What a snapshot leaves out

- Arbitrary file contents; 0.2 additionally carries the interpreted picture data described above.
- Local paths: `where` and `source` are relative to their repository.
- Secrets and email addresses in titles and fields, which become `[redacted]`, and user names and passwords in links. A link that holds a secret or an email address, even percent-encoded, is left out whole, since it would not work with the secret taken out.

Limits: 3,000 items, 2,000 checks and 1,000,000 bytes per snapshot. After whole-picture omission in 0.2, items are dropped from the end, then checks, and a `truncated` check gives how many of each were kept. A project whose settings alone are over the limit gets no snapshot. Titles have up to 120 characters, and an item up to 60 links.

## Status file

```json
{
  "project": "acme-shop",
  "stages": {
    "02-prd": {
      "state": "done",
      "checkpoint": "PRD approved in the kickoff review",
      "checkpoint_date": "2026-01-12",
      "next": "Write the user flows",
      "checks": [{ "level": "warn", "message": "SPEC-004 contradicts REQ-002 on refunds", "at": "2026-01-12" }],
      "updated": "2026-01-12T10:00:00+09:00"
    }
  }
}
```

Use `hub.py status` to change it. The file is kept on the machine; it is not part of any repository.

## Page data

`index.html` holds its data in `<script id="hub-data" type="application/json">`:

```json
{ "schema": "corthex-hub-page/0.2", "generated_at": "…", "lang": "en", "origin": "local", "projects": [], "missing": [] }
```

`projects` holds the snapshots. `lang` is `ko` when the profile's `language` starts with `ko`, otherwise `en`. A NEXUS server serves the same page with `origin` set to `server`. The page loads nothing from the network: its Content Security Policy allows no requests, and it shows text only as text.

## NEXUS push

Settings in `~/.corthex/profile.json`:

```json
{ "nexus": { "url": "https://nexus.example.com", "push": ["acme-shop"] } }
```

- `url`: the server. `--url` and the environment variable `CORTHEX_NEXUS_URL` take precedence. It must use `https`; `http` works only for `localhost`, `127.0.0.1` and `::1`, for testing.
- `push`: the projects that may be sent. `hub.py push` with no names sends these; a name that is not listed is refused.
- `hub.py remove` sends no removal: for each project it names, listed in `push` or not, it reads `GET /api/spaces/<project>/data` and gives the address of the project's data, `<url>/p/<project>#data`, where the user removes the project under their own sign-in.
- The service token is read from `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET` and sent as the Cloudflare Access headers `CF-Access-Client-Id` and `CF-Access-Client-Secret`. A server on this machine may be used without a token.

Each push first drains the outbox and reads `GET /api/snapshots/<project>/held`, then makes a fresh snapshot. No held snapshot or the same commit needs no `replaces`; a descendant replaces the held commit. An older or missing commit needs a fetch; divergence needs explicit user agreement before `--replace-held`. Commit times never decide ancestry. `--dry-run` sends nothing, including the outbox and held question. A server from before the design revision has no project's data, so `remove` reads its removal preview, `GET /api/snapshots/<project>/removal`, with the remark `server-older`. `remove` keeps the local queue; a write for a removed project is dropped with its `404` at the next contact.

`POST <url>/api/snapshots` sends compact JSON and returns the revision and 0.2 space/picture/checkpoint counts. Redirects are not followed. A phase-1 held endpoint without a Problem code requires a server upgrade. The hub reports the server's Problem Details and retains only retryable agent writes, never pushes.

## NEXUS server

The server in `nexus/` answers only requests whose Access signature, issuer and audience it verifies. Agent commands use the service role. Human actions use the signed-in user role and same-origin protections. Refusals use `application/problem+json` with `type`, `title`, `status`, `detail`, `instance`, stable `code`, `traceId` and applicable extra fields; they never expose tokens or author identities. Page refusals have an HTML explanation.

| Request | Reply |
| --- | --- |
| `POST /api/snapshots` | The revision and, for 0.2, resulting space/picture/discrepancy/checkpoint counts; a 0.1 snapshot retains its legacy name/revision answer |
| `GET /api/snapshots` | `{"projects": [...]}`, with each project's `name`, `revision`, `generated_at`, `received_at` and `bytes` |
| `GET /api/snapshots/<project>` | the stored snapshot |
| `GET /api/spaces/<project>/data` | the project's data: its stored snapshot, the agent's last read and what a removal deletes, with the open entries by ID. `hub.py remove` reads this. |
| `DELETE /api/snapshots/<project>` | `{"name": "acme-shop", "removed": true}`, or `404` when the server does not hold the project. A server of the design revision takes it only under the user's own sign-in; `hub.py remove` never sends it. |
| `GET /` | the hub page, with `origin` set to `server` |

The server refuses a request with:

- `400` for an invalid/unknown snapshot format (0.1 and 0.2 are supported), or a snapshot dated more than 10 minutes ahead;
- `403` when Access did not check the request, when an Access application other than the ones in `ACCESS_AUD` checked it, or when a browser sent a change from another site;
- `409` for stale/incorrectly replaced commits, a mismatched repository or a space's quota; same-commit and commitless snapshots keep the generation-time guard;
- `413` when the snapshot is larger than 1 MiB, and `415` when it is not sent as `application/json`.
