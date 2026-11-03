# NEXUS: requests, commands and formats

[한국어](nexus.ko.md)

Stage 06 of CORTHEX's own project, for NEXUS 0.2: the requests that the NEXUS server answers, in the OpenAPI contract [nexus.openapi.yaml](nexus.openapi.yaml), and in this file the rules that the contract follows, the hub's commands and the formats of the files that go with them. Status: drafted on 2026-11-02, while the memory plugin is being built, as the maintainer chose that day, on the recommendations of the user flows, the functional spec and the server's data. The maintainer passed its checkpoint on 2026-11-03, together with stages 03 to 05, 07 and 08, so the requests, the commands and the formats are frozen for NEXUS 0.2 before stage 10 plans the work: a later breaking change needs the maintainer's decision. The maintainer's choice of 2026-11-03 to hold stage 01's event storming in NEXUS added the optional `timeline` to the DDD board's picture source, a compatible change, and named the work board of phase ② beside editing; the maintainer passed both the same day ([For the checkpoint](#for-the-checkpoint)). The contract is the source of every request, answer, example and error code that it holds; this file explains them and is the source of the rest. When this file and its Korean translation differ, this file is the source.

Inputs: the functional spec in [docs/04-functional-spec/nexus.md](../04-functional-spec/nexus.md) (SPEC-101 to SPEC-142), above all its [notes for stage 06](../04-functional-spec/nexus.md#stage-06-requests-commands-and-formats); the server's data and the files in [docs/05-erd/nexus.md](../05-erd/nexus.md) and [nexus.sql](../05-erd/nexus.sql) (TBL-101 to TBL-118), with their [notes for stage 06](../05-erd/nexus.md#stage-06-requests-commands-and-formats) and their limits; the requirements in [docs/02-prd/nexus.md](../02-prd/nexus.md); the glossary and the DDD board in [docs/01-domain/nexus.md](../01-domain/nexus.md), whose words this file keeps; and phase 1 as it runs: the server in [app.js](../../nexus/src/app.js), [snapshot.js](../../nexus/src/snapshot.js) and [store.js](../../nexus/src/store.js), and the hub in [hub.py](../../plugins/corthex-nexus/skills/corthex-hub/scripts/hub.py) with its [snapshot.md](../../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md) and [reading.md](../../plugins/corthex-nexus/skills/corthex-hub/references/reading.md). The sitemap (stage 07) comes later, so no screen ID is an input yet; the requests serve the screens that the user flows and the functional spec name.

The stage's default contract is `api/openapi.yaml`, read in Swagger UI. The NEXUS server has an HTTP API, so its contract is OpenAPI 3.1, as the stage asks, kept beside the other part's interfaces as `docs/06-api/nexus.openapi.yaml`. People read it in the Korean copy in the project's Notion records, and the file itself in any OpenAPI viewer, such as Swagger UI; `.corthex/project.json` records the choice. The hub's commands are no HTTP requests, so this file defines them, in the form of MEMORY's [interfaces](memory.md): each with an API ID, the behaviours that it serves and its outcomes.

## How to read this file

- The server's requests are the operations of the contract, API-101 to API-132. Each has its `operationId`, the behaviours (SPEC) that it serves, who may send it, every response that it can give, each with a named example, and under `x-corthex.omit` the responses that it cannot give, with the reason. [Interfaces](#interfaces) lists them; the contract defines them.
- The hub's commands, API-133 to API-150, are defined in [The hub's commands](#the-hubs-commands), with their options, outcomes and exit codes.
- A response is written as its request's ID and its status, as `API-105#409`, and an outcome of a command as its ID and the outcome, as `API-136#refused`.
- An error code is written as `commit_not_replaced`. [Error codes](#error-codes) lists each with its status, its meaning, the members that it adds, the message that the user sees and what the client does, as the contract's `components.x-corthex.errors` holds them.
- Times from the server are in UTC with milliseconds, as `2026-11-03T09:00:00.000Z`; times from a device or from Git keep their zone. Sizes in bytes count UTF-8, and lengths in characters count code points, as in stage 05.
- Status: `built` for what phase 1 serves as it runs, `active` for what NEXUS 0.2 adds or changes. Editing on a PC (SPEC-134) and the work board (SPEC-142) are phase ②, which adds their requests then.
- `~/.corthex/` is the CORTHEX folder in the user's home folder, `%USERPROFILE%\.corthex\` on Windows. The hub's files are under `~/.corthex/hub/`, as in phase 1.

## Sources

Documents read on 2026-11-02:

- Cloudflare Access and Workers. [Cloudflare Access](https://developers.cloudflare.com/workers/configuration/cloudflare-access/): a Worker gets `ctx.access` only for a request that Access authenticated, with the application's `aud` and `getIdentity()`, and gets none when it serves static assets. [Application token](https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/application-token/): a person's token holds `sub` and `email`, and a service token's holds the token's client ID in `common_name` and an empty `sub`. [Validate JWTs](https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validating-json/): the token comes in the header `Cf-Access-Jwt-Assertion`, and the team's keys are at `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`. [Service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/): a client sends the headers `CF-Access-Client-Id` and `CF-Access-Client-Secret`.
- Limits of the free plan: [Workers](https://developers.cloudflare.com/workers/platform/limits/), 10 ms of CPU time and 50 subrequests for each request and 100,000 requests a day; [D1](https://developers.cloudflare.com/d1/platform/limits/), 50 queries for each invocation and 500 MB for each database.
- [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html), Problem Details for HTTP APIs: an absent `type` means `about:blank`; the media type is `application/problem+json`; a problem may add members of its own, which a client that does not know them ignores; and `status` is the response's own status.
- [The Idempotency-Key HTTP header field](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/), version 08 of 2026-10-22, an Internet-Draft and not an RFC: the key is a String of Structured Field Values, in double quotes; a key sent again with another request should get `422`, and one whose first request is still being processed `409`. [Write IDs](#write-ids) says where NEXUS differs.

Not yet seen: both kinds of sign-in on a real Access setup, and what `getIdentity()` returns for a service token, which the documents do not say. [Sign-in](#sign-in) keeps this open.

## Interfaces

Every behaviour of the functional spec has an interface, apart from editing on a PC (SPEC-134) and the work board (SPEC-142), which phase ② adds. The step view (SPEC-141) has no request of its own: it shows the picture that the view reads (API-111).

### Requests of the server

The contract defines them, and this table lists them. Who may send each: `user`, a person's own sign-in; `agent`, the service token; `either`, both ([Sign-in](#sign-in)).

| API | Request | Code name | Who | Serves | Status |
| --- | --- | --- | --- | --- | --- |
| API-101 | `GET /` | `getHubPage` | either | SPEC-113, SPEC-122, SPEC-123, SPEC-124, SPEC-125 | active |
| API-102 | `GET /pictures/{project}/{part}/{stage}` | `getPictureViewPage` | either | SPEC-113, SPEC-119 | active |
| API-103 | `GET /overview/{project}/{part}/{stage}` | `getStageOverviewPage` | either | SPEC-113, SPEC-138, SPEC-139 | active |
| API-104 | `GET /code/{file}` | `getViewCode` | either | SPEC-113, SPEC-119 | active |
| API-105 | `POST /api/snapshots` | `pushSnapshot` | either | SPEC-111, SPEC-112, SPEC-113, SPEC-114, SPEC-117, SPEC-118, SPEC-120, SPEC-121, SPEC-140 | active |
| API-106 | `GET /api/snapshots` | `listSnapshots` | either | SPEC-113, SPEC-122 | built |
| API-107 | `GET /api/snapshots/{project}` | `getSnapshot` | either | SPEC-113, SPEC-122 | built |
| API-108 | `DELETE /api/snapshots/{project}` | `removeProject` | either | SPEC-113, SPEC-115 | active |
| API-109 | `GET /api/snapshots/{project}/held` | `getHeldCommit` | either | SPEC-111, SPEC-112, SPEC-113 | active |
| API-110 | `GET /api/snapshots/{project}/removal` | `getRemovalDryRun` | either | SPEC-113, SPEC-115 | active |
| API-111 | `GET /api/spaces/{project}/pictures/{part}/{stage}` | `getPicture` | either | SPEC-113, SPEC-118, SPEC-119, SPEC-141 | active |
| API-112 | `GET /api/spaces/{project}/overview/{part}/{stage}` | `getStageOverview` | either | SPEC-113, SPEC-138 | active |
| API-113 | `GET /api/spaces/{project}/todo` | `getAgentTodo` | either | SPEC-113, SPEC-135, SPEC-136 | active |
| API-114 | `GET /api/spaces/{project}/comments/{comment}` | `getComment` | either | SPEC-113, SPEC-127, SPEC-132, SPEC-135 | active |
| API-115 | `GET /api/spaces/{project}/proposals/{proposal}` | `getProposal` | either | SPEC-113, SPEC-130, SPEC-131 | active |
| API-116 | `GET /api/spaces/{project}/edits/{edit}` | `getEdit` | either | SPEC-113, SPEC-133 | active |
| API-117 | `GET /api/spaces/{project}/checkpoints/{checkpoint}` | `getCheckpoint` | either | SPEC-113, SPEC-140 | active |
| API-118 | `POST /api/spaces/{project}/comments` | `leaveComment` | either | SPEC-113, SPEC-116, SPEC-126, SPEC-128 | active |
| API-119 | `POST /api/spaces/{project}/comments/{comment}/replies` | `replyToComment` | either | SPEC-113, SPEC-116, SPEC-127, SPEC-128, SPEC-132 | active |
| API-120 | `POST /api/spaces/{project}/comments/{comment}/answered` | `markAnswered` | either | SPEC-113, SPEC-116, SPEC-127 | active |
| API-121 | `POST /api/spaces/{project}/comments/{comment}/decisions` | `recordDecision` | agent | SPEC-113, SPEC-116, SPEC-128, SPEC-132 | active |
| API-122 | `POST /api/spaces/{project}/proposals` | `makeProposal` | agent | SPEC-113, SPEC-116, SPEC-128, SPEC-130 | active |
| API-123 | `POST /api/spaces/{project}/proposals/{proposal}/withdraw` | `withdrawProposal` | agent | SPEC-113, SPEC-116, SPEC-130 | active |
| API-124 | `POST /api/spaces/{project}/proposals/{proposal}/accept` | `acceptProposal` | user | SPEC-113, SPEC-116, SPEC-131 | active |
| API-125 | `POST /api/spaces/{project}/proposals/{proposal}/dismiss` | `dismissProposal` | user | SPEC-113, SPEC-116, SPEC-131 | active |
| API-126 | `POST /api/spaces/{project}/edits/{edit}/report` | `reportEdit` | agent | SPEC-113, SPEC-116, SPEC-128, SPEC-133, SPEC-136 | active |
| API-127 | `POST /api/spaces/{project}/edits/{edit}/dismiss` | `dismissEdit` | user | SPEC-113, SPEC-116, SPEC-133 | active |
| API-128 | `POST /api/spaces/{project}/checkpoints` | `passCheckpoint` | user | SPEC-113, SPEC-116, SPEC-139 | active |
| API-129 | `POST /api/spaces/{project}/checkpoints/{checkpoint}/withdraw` | `withdrawCheckpoint` | user | SPEC-113, SPEC-116, SPEC-139 | active |
| API-130 | `POST /api/spaces/{project}/checkpoints/{checkpoint}/report` | `reportCheckpoint` | agent | SPEC-113, SPEC-116, SPEC-128, SPEC-136, SPEC-140 | active |
| API-131 | `POST /api/spaces/{project}/claims/{entry}` | `claimEntry` | agent | SPEC-113, SPEC-116, SPEC-136 | active |
| API-132 | `DELETE /api/spaces/{project}/claims/{entry}` | `releaseEntry` | agent | SPEC-113, SPEC-116, SPEC-136 | active |

### Commands of the hub

| ID | Name | Sends | Serves | Status |
| --- | --- | --- | --- | --- |
| API-133 | `snapshot` | nothing | SPEC-101, SPEC-102, SPEC-103, SPEC-104, SPEC-105, SPEC-106, SPEC-107, SPEC-108, SPEC-109, SPEC-110 | active |
| API-134 | `status` | nothing | SPEC-109, SPEC-137, SPEC-140 | active |
| API-135 | `build` | nothing | SPEC-122, SPEC-123, SPEC-125 | active |
| API-136 | `push` | API-109, API-105 | SPEC-111, SPEC-112, SPEC-129 | active |
| API-137 | `remove` | API-110, API-108 | SPEC-115 | active |
| API-138 | `todo` | API-113 | SPEC-135, SPEC-129 | active |
| API-139 | `comment` | API-118 | SPEC-128, SPEC-129, SPEC-135 | active |
| API-140 | `reply` | API-119 | SPEC-127, SPEC-128, SPEC-129, SPEC-132 | active |
| API-141 | `answered` | API-120 | SPEC-127, SPEC-128, SPEC-129 | active |
| API-142 | `decide` | API-121 | SPEC-132, SPEC-128, SPEC-129 | active |
| API-143 | `propose` | API-122 | SPEC-130, SPEC-128, SPEC-129 | active |
| API-144 | `withdraw` | API-123 | SPEC-130, SPEC-128, SPEC-129 | active |
| API-145 | `reflect` | API-126 | SPEC-133, SPEC-128, SPEC-129 | active |
| API-146 | `record` | API-130 | SPEC-140, SPEC-128, SPEC-129 | active |
| API-147 | `show` | API-114, API-115, API-116, API-117 | SPEC-132, SPEC-133, SPEC-140 | active |
| API-148 | `claim` | API-131 | SPEC-136 | active |
| API-149 | `release` | API-132 | SPEC-136 | active |
| API-150 | `outbox` | the requests of the writes that it holds | SPEC-129 | active |

## Common rules

### Addresses and paths

- The server answers only at the address that the user set, which `nexus.url` names, and at no `workers.dev` or preview address, as phase 1 does (SPEC-113). The pages are `/`, `/pictures/…` and `/overview/…`, the view's code is under `/code/`, and the rest under `/api/`.
- `{project}` is the registered name: lowercase letters and digits in words joined by hyphens, up to 100 characters. `{part}` is a part's name of the same form, or `_` for the project as a whole, which a JSON body writes as `""`. `{stage}` is a stage key; only `01-domain`, `05-erd` and `07-sitemap` have pictures.
- The server's own IDs are a prefix and 12 random characters of lowercase Crockford base32, the digits and the letters but `i`, `l`, `o` and `u`: `nc_` for comments, `nd_` discrepancies, `np_` proposals, `ne_` edits, `nk_` checkpoints and `nw_` writes. The server makes them, apart from write IDs, which the page and the hub make. They are not trace IDs, and the hub never reads them as items.
- A path value in another form gets the `404` that a value the server does not hold gets, as phase 1 answers a project name, and never `400` ([choice 1](#choices-this-stage-made)).

### Methods and bodies

- `GET` reads, and every `GET` also answers `HEAD`, with the same status and headers and no body. `POST` writes, and `DELETE` removes a project or ends a claim. A method that a path does not take gets `405` with an `Allow` header that names those it takes; an unknown path gets `404` `not_found`.
- A body is JSON, sent as `Content-Type: application/json` (otherwise `415` `json_required`) and in UTF-8 (otherwise `400`). A snapshot may have up to 1 MiB, and any other body up to 256 KiB (`413`). A request that takes no body reads none that is sent.
- A write's body holds only the fields that the contract names, and a field of another name is refused with `400`. A snapshot keeps the fields that the server does not know, as phase 1 does.
- A text that a write must have, such as a reply's, is refused with `400` when it is empty or white space only, and with `413` `text_too_long` when it is longer than its limit. Texts are stored as the client sent them; the hub redacts the agent's before it sends them (SPEC-128).

### Replies

- An answer is JSON, as `application/json; charset=utf-8`, with `200`, or `201` for a write that adds an entry. A page is `text/html; charset=utf-8`, and a file of the view's code has its own type.
- Every reply carries phase 1's headers: `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-Robots-Tag: noindex, nofollow` and `Cross-Origin-Resource-Policy: same-origin`, so that no reply is cached, shown in a frame of another site or indexed (SPEC-113). A JSON reply adds `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`.
- The hub page keeps phase 1's policy, which runs only its own inline script, by its digest, and sends no request: `default-src 'none'; script-src 'sha256-…'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, with `Cross-Origin-Opener-Policy: same-origin`.
- The picture view and the stage overview load their code from `/code/` and send their requests only to the server (REQ-147): `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, with `Cross-Origin-Opener-Policy: same-origin`. Their data is in a JSON script block, which the page reads as text and never runs.
- Only the files of the view's code may be kept by the browser, with `Cache-Control: private, max-age=31536000, immutable`: each name carries a digest of the file's content, and they hold no project data. SPEC-113 allows this, as this stage's checkpoint changed it ([Changes to earlier stages](#changes-to-earlier-stages)).

### Errors

Every refusal and error is Problem Details (RFC 9457), sent as `application/problem+json`, apart from the pages' answers to a browser below, with these members (the contract's `Problem`):

| Member | Value |
| --- | --- |
| `title` | The code's short title in English, the same in every reply with that code |
| `status` | The reply's status |
| `detail` | One line that says what was wrong with this request; it may name its values, such as a field or a commit, but never a stored text |
| `code` | One of the [error codes](#error-codes) |
| `traceId` | The request's Ray ID, which Cloudflare sends in the `Cf-Ray` header, such as `8f6c3b2a1d0e9f80-ICN`, or 16 random hexadecimal digits where there is none, as on a device. The server's log line for an error holds the same ID |
| `error` | The same as `detail`, for hubs of 0.1, which show a refusal's `error` and read at most 4,096 bytes of a reply |
| others | The members that the code adds, which [Error codes](#error-codes) names, such as `field` and `limit` |

NEXUS sends no `type`, which RFC 9457 reads as `about:blank`, and no `instance`. A client ignores the members that it does not know, as RFC 9457 says. The view shows the code's message in the user's language, never `detail`; the hub shows `detail`. The server's log holds only the kind of an error and its trace ID, never a stored text or a value of the request (SPEC-113).

The three pages, API-101 to API-103, answer a refusal or an error as `text/html; charset=utf-8` when the request's `Accept` header names `text/html`, as a browser's does when it opens a page, and as Problem Details otherwise, since a browser shows those as raw text. The page holds one message, the code's in the server's language, with the trace ID, Load again and a link to the hub page; it has the reply's status and the policy `default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, and stage 08's [rule 9](../08-screens/nexus/README.md#every-screen) draws it. The `/api/` requests and the view's code always answer Problem Details, and a view's own data holds them in `problem`.

### Which refusal comes first

A request that breaks several rules gets the refusal of the first in this order, which phase 1 keeps for its own checks:

1. Access: not checked, `403` `access_missing`; checked for another Access application, `403` `access_other_app`.
2. The path and the method: `404` `not_found`; `405` `method_not_allowed`; a path value in another form, the `404` of what it names.
3. A change that a browser sends from another site: `403` `cross_site`.
4. The kind of sign-in that a write needs: `403` `user_only`, `agent_only` or `no_kind`.
5. The headers: the write ID and the session label, `400` `invalid_request`.
6. The body's type, `415` `json_required`, and its size, `413` `snapshot_too_large` or `body_too_large`.
7. The body: not UTF-8, not JSON or not in its form, `400` `invalid_request` or `invalid_snapshot`; a snapshot dated ahead, `400` `clock_ahead`; a text over its limit, `413` `text_too_long`.
8. The write ID: a write that the server took already gets its first answer, and an ID that another request took, `409` `write_id_reused`.
9. What the request names: `404` for the project, the space, the part, the picture or the entry, and `400` `unknown_item` for items that the picture does not hold.
10. The claims, the state and the limits: `409`.

## Sign-in

Cloudflare Access checks every request before the Worker sees it, as in phase 1. A request without a valid sign-in never reaches the Worker: Access sends a browser to its login page and answers a refused service token with a redirect, `401` or `403`. So no request lists `401`, and the contract says why in each `x-corthex.omit`.

The Worker then checks, as phase 1 does, that Access checked the request (`ctx.access`, otherwise `403` `access_missing`) for its own application (an `aud` that `ACCESS_AUD` names, otherwise `403` `access_other_app`), and takes the kind of sign-in from the identity that Access checked (SPEC-116):

| Identity | Kind |
| --- | --- |
| A non-empty `sub`: a person signed in with Access's login | `user` |
| An empty `sub` and a `common_name`: the client ID of a service token | `agent` |
| Anything else | neither: `403` `no_kind` for every write |

- Reads, pushes and removals take any identity that Access let in, as in phase 1, and never answer `no_kind`. A write that only one kind may send answers the other with `user_only` or `agent_only`, whose `needs` names the kind that it takes.
- Nothing of the identity is kept or logged: an entry keeps only its author's kind, `user` or `agent` (REQ-163).
- A sign-in can expire while a view is open. The view sends its requests with `redirect: "manual"`, so Access's redirect to its login page reaches it as an `opaqueredirect` reply; the view then says that the sign-in expired, keeps the text and offers to load the page again (SPEC-126).
- Chosen on 2026-11-03 by the development Access trial: read the kind from `Cf-Access-Jwt-Assertion`, after requiring `ctx.access` and checking its audience. Verify RS256 with the matching `kid` from the configured team’s public `https://<ACCESS_TEAM_DOMAIN>/cdn-cgi/access/certs`, the exact team issuer, `ACCESS_AUD`, expiry and any not-before time. `ACCESS_TEAM_DOMAIN` is the configured host, never a host taken from a token. Keep public keys for at most one hour and refresh on an unknown key. Fetch the keys with manual redirects and refuse a non-200 response; the trial’s `redirect: error` request failed before an HTTP response, while manual mode returned the keys and both signatures verified. `getIdentity()` did not give `sub` for the person or `common_name` for the service token. No identity value, JWT, cookie or credential is kept or logged. The security schemes below and in OpenAPI use this selected method.

## Writes

The user's writes come from the view and the agent's through the hub (SPEC-128). Each is one batch in D1, so two writes at once are taken one after the other (stage 05, [The writes of the user and the agent](../05-erd/nexus.md#the-writes-of-the-user-and-the-agent)).

### Write IDs

- Every write but a claim carries the header `Idempotency-Key` with its write ID, an `nw_` ID that the page or the hub makes for that one write and sends with each try of it, in double quotes as the draft writes it: `Idempotency-Key: "nw_6t9w2z5c8f1j"`. Without it, or in another form, the write is refused with `400` `invalid_request`, whose `field` is `Idempotency-Key`.
- The server keeps the ID of each write that it took, with the request's name and its first answer, for 7 days (TBL-112). A write sent again with that ID gets that answer, with the same status, and changes nothing. A write that the server refused leaves no ID behind, so it is checked again when it is sent again.
- An ID that the server holds for another request is refused with `409` `write_id_reused`. NEXUS compares the request's name, which TBL-112 keeps, and not the body.
- Where NEXUS differs from the draft: it answers an ID of another request with `409` and not `422`, since a write ID that comes back for another request is a fault of the client, as `409` says for the other conflicts of a write; it keeps no write that is still being processed, since each write is one transaction, so a second try waits for the first and gets its answer; and it forgets an ID after 7 days, when the hub's outbox has dropped the write too.
- A push needs no write ID, since the commit rule tells a new snapshot from one sent again ([A push](#a-push)), and a removal needs none, since a second one gets `404`. A claim needs none, since claiming twice leaves one claim.

### Request names

The name that TBL-112 keeps for each write, and the outbox for the agent's:

| Name | Request | Who |
| --- | --- | --- |
| `comment` | API-118 | either |
| `reply` | API-119 | either |
| `answered` | API-120 | either |
| `decision` | API-121 | agent |
| `proposal` | API-122 | agent |
| `withdraw-proposal` | API-123 | agent |
| `accept` | API-124 | user |
| `dismiss-proposal` | API-125 | user |
| `report-edit` | API-126 | agent |
| `dismiss-edit` | API-127 | user |
| `checkpoint` | API-128 | user |
| `withdraw-checkpoint` | API-129 | user |
| `report-checkpoint` | API-130 | agent |

### Sessions

- The agent names its session in the header `Nexus-Session` with a label of 1 to 100 ASCII letters, digits, `.`, `_`, `:` and `-`, which it keeps for the session, such as the host's session ID or, without one, a label that it makes at the session's start, such as `claude-code-4f2a91`. The label holds nothing personal (SPEC-128). The hub takes it from `--session` or the environment variable `CORTHEX_NEXUS_SESSION`.
- Every write of the agent's carries it, and one without it is refused with `400` `invalid_request`, whose `field` is `Nexus-Session`. The agent to-do reads it to mark the session's own claims. The user's writes need none, since no claim holds the user back, and the server does not read one that they carry.

### Claims

- The agent claims an entry of its to-do, a comment, a discrepancy, an edit or a checkpoint, for its session (API-131, SPEC-136). The claim lasts until 60 minutes after the session's last write on the entry: each such write and each claim again moves its end on. It ends at that time, when the entry closes or when the session releases it (API-132). An entry is closed when the to-do no longer lists it: a closed comment, a resolved discrepancy, a closed or dismissed edit, a recorded checkpoint, or a withdrawn one that no open pull request and no stored record names.
- While a claim lasts, the agent's writes on the entry from other sessions are refused with `409` `claimed`, whose `ends_at` gives the claim's end, and the to-do shows the entry to them as taken until then. The user's writes are never refused for a claim.
- A claim of another session's entry, of a closed one or of one that a reported pull request holds is refused with `409` `claimed`, `entry_closed` or `pull_request_reported`. A report of an opened pull request ends the claim on the entry, since the pull request holds the entry from then on, for every session, until it is merged or closed (SPEC-133, SPEC-140).
- Which entry a write is on:

| The agent's write | The entry it is on |
| --- | --- |
| A reply, marking answered or a decision | The comment |
| A comment on a discrepancy | The discrepancy |
| A proposal in answer to a comment or a discrepancy, and its withdrawal | That comment or discrepancy |
| A report of a reflection | The edit |
| A report of a record's pull request | The checkpoint |
| A comment on an item, or a proposal of the agent's own | None |

### Answers that change nothing

A write whose outcome holds already changes nothing, and its answer says so with `changed: false`: marking answered a comment that is closed, whether as answered or as decided (SPEC-127); withdrawing a proposal or a checkpoint that is withdrawn already, or dismissing a reflection that is dismissed already; and a report that repeats the last one of its entry. A write that another outcome has closed is refused with `409` and the state that closed it: accepting or dismissing a proposal that is not open (`proposal_not_open`, SPEC-131), and a report that does not fit its entry's state. A write sent again with its write ID gets its first answer, whatever it said ([Write IDs](#write-ids)).

## A push

A push (API-136) brings the stored snapshot, the project space, its pictures, its discrepancies and its checkpoints to the default branch's latest commit that the device fetched (SPEC-111, SPEC-114):

1. The hub sends the project's outbox first ([The outbox](#the-outbox)).
2. It asks for the held commit (API-109): the stored snapshot's `revision` and `default_commit`. `404` `project_not_found` means that the server holds none. A `404` without a `code` comes from a server of phase 1, which needs the 0.2 release first; the hub then sends nothing.
3. It takes a fresh snapshot (API-133) and checks its default commit with Git, reading the repository as SPEC-105 does:

| The server holds | The snapshot's commit | The hub |
| --- | --- | --- |
| No snapshot, or none with a default commit | any | Sends it without `replaces` |
| Commit H | H | Sends it without `replaces` |
| Commit H | A descendant of H | Sends it with `replaces: H` |
| Commit H | H's ancestor, or the checkout does not have H | Sends nothing, and says to fetch the default branch and push again |
| Commit H | Not a descendant of H, as after the default branch was rewritten | Sends nothing, and names both commits; with `--replace-held`, which the agent uses only after the user agrees, sends it with `replaces: H` |
| Commit H | None, since the checkout has no default branch | Sends nothing, and says how to record the head (`git remote set-head origin --auto`) |

4. It sends the snapshot (API-105), compact JSON of at most 1 MiB.
5. The server stores it when it is the next version, by the commit rule, which compares commits by their names only:

| The server holds | The snapshot | The server |
| --- | --- | --- |
| Nothing of the project | any | Stores it as a new project, unless it holds 30: `409` `too_many_projects` |
| A snapshot without a default commit | any | Stores it when it was made no earlier than the stored one, otherwise `409` `older_snapshot` with `stored_at` |
| Commit H | Of H | Likewise |
| Commit H | Of another commit, with `replaces: H` | Stores it |
| Commit H | Of another commit without `replaces: H`, or of no commit | `409` `commit_not_replaced` with `held_commit` |
| Commit H, and another push stored first since this one read it | any | `409` `commit_not_replaced` with the new `held_commit` |

6. For a snapshot of 0.2, the same request creates the project's space when there is none, bound to the repository's address (SPEC-117), draws the pictures that changed and marks those that are not current (SPEC-118), cross-checks the parts whose pictures changed or became current again (SPEC-120, SPEC-121) and marks the checkpoints that the stage records name (SPEC-140), all of it or none (stage 05, [A push](../05-erd/nexus.md#a-push)). A snapshot whose address is not the one that the space is bound to, or that has none while the space has one, is refused with `409` `repository_mismatch`, with `bound`. A space bound to no address takes the first one that a snapshot names (stage 05's choice 9).
7. The server answers with the revision, the default commit that it now holds, the commit that it replaced, the pictures drawn, made current again or marked not current, the discrepancies opened and resolved, the checkpoints recorded and the counts of the agent to-do, each list up to 20 (`PushAnswer02`). A snapshot of 0.1 gets phase 1's answer, its `name` and `revision`, and changes nothing but the stored snapshot: a space, if the project has one, keeps its pictures and entries.

The address that a space is bound to is the `origin` remote's address in one form, which the hub writes into the snapshot and the server compares: without a user name or password; `git@example.com:owner/repo.git` and `ssh://git@example.com/owner/repo.git` as `https://example.com/owner/repo`; without a final `.git` or `/`; with the host in lowercase; and `https` for `http`.

A push that gets no answer within 30 seconds, or no network, is reported and nothing is kept, since the next push takes a fresh snapshot (SPEC-111).

## Reads

| Read | Holds | Up to |
| --- | --- | --- |
| The hub page (API-101) | Every stored snapshot and, for each project that has a space, its pictures, its counts of open comments, proposals and discrepancies, its checkpoints passed in NEXUS that wait for their records and its `checkpoint-withdrawn` warnings (SPEC-123) | 150 pictures, 100 checkpoints and 100 warnings for each project, with their totals |
| A picture (API-111) | The picture source with its document version and whether it is current; its open comments, the most recently active first, each with its count of replies and its last reply; its closed comments by ID; its open proposals, without their stage source text; its reflections that are not closed; and the open discrepancies of its part that concern it (SPEC-119) | 500 of each, and 1,000 discrepancies, with their totals |
| A stage's overview (API-112) | The stage's record and checks from the snapshot; its open discrepancies, open comments and pending reflections; and its checkpoints passed in NEXUS that no record names yet, or that a record names after their withdrawal (SPEC-138) | 50 of each, with their totals |
| The agent to-do (API-113) | In its order: the comments that wait for the agent, the open discrepancies, the pending reflections and the checkpoints ([The agent to-do](#the-agent-to-do)) | 50 of each, with their totals |
| One comment (API-114) | Its replies, decisions and proposals | All of them: 200 replies at most |
| One proposal (API-115), edit (API-116) or checkpoint (API-117) | The whole entry, with a proposal's stage source text | |
| The dry run of a removal (API-110) | What the removal deletes, with the open comments, open proposals, pending reflections and checkpoints that no record names yet by ID | 20 of each, with their totals |

Implementation clarification (2026-11-04): `CommentThread.proposals` has no lifetime array cap. The 500-proposal limit applies to open proposals in a space, not to a comment's historical proposals. The OpenAPI schema now agrees with API-114's existing promise to return all of them.

The view finds which comments, proposals and discrepancies are apart, those whose item the current picture no longer holds, since only it reads the picture source's items (SPEC-119). A project without a space, which only hubs of 0.1 pushed, has no pictures: its picture view and its to-do are `404` `space_not_found`, and its overview shows the record and checks only.

### The agent to-do

The to-do (API-113, SPEC-135) lists, in this order:

1. The open comments that wait for the agent ([How a comment waits](#how-a-comment-waits)), oldest first.
2. The open discrepancies, `warn` before `info`, oldest first.
3. The pending reflections, those without a pull request first, oldest first.
4. The checkpoints passed in NEXUS that no stored record names, oldest first, then the withdrawn ones that an open pull request or a stored record still names, each with `why`: `not-recorded`, `withdrawn-in-review` or `withdrawn-recorded`.

It also counts the comments that wait for the user (`waiting_for_user`) and the entries that other sessions claim (`taken`). An entry that a session claims carries the claim's end, marked `mine` when it is the session that `Nexus-Session` names; without the header, every claim counts as another session's. A reflection or checkpoint that a reported open pull request holds carries the pull request, so that other sessions skip it as in review.

## How a comment waits

A comment's entries are its text, its replies and the proposals that answer it, with their acceptance or dismissal; a withdrawn proposal does not count.

| The last entry | `waits` |
| --- | --- |
| The user's: the comment, a reply, or accepting or dismissing a proposal that answers it | `agent` |
| The agent's: the comment, a reply or an open proposal that answers it | `user` |
| The comment is closed | `null` |

- `settled` is `true` once a reply of the user's settles the comment, and the comment then waits for the agent to record the decision (SPEC-127, SPEC-132). A decision closes the comment as `decided`.
- `dismissed` is `true` while the last proposal that answered it was dismissed and the agent has not written on the comment since (SPEC-131).
- The user's reply to a closed comment opens it again, and it waits for the agent; the agent's is refused with `409` `comment_closed`. Opening a comment again is that reply, with no request of its own.

## Reports

### Reports of a reflection

The agent reports what became of a pending reflection (API-126, SPEC-133). `opened`, `merged` and `closed` carry the pull request, `reflected` the commit whose stage source already holds the change, and `needs-user` nothing:

| Event | The edit's state | Becomes |
| --- | --- | --- |
| `opened` | `pending` or `needs-user` | `in-review`, held by the pull request |
| `merged` | `in-review` with that pull request, or `pending` or `needs-user` | `closed`, with the pull request |
| `closed` | `in-review` with that pull request | `pending` |
| `reflected` | `pending` or `needs-user` | `closed`, with the commit as `closed_commit` |
| `needs-user` | `pending` | `needs-user`, which the user may dismiss (API-127) |

- A report that repeats the edit's last report changes nothing (`changed: false`).
- `opened` for an edit that another reported pull request holds is refused with `409` `pull_request_reported`, and `merged` or `closed` for another pull request than the held one with `409` `pull_request_mismatch`; both name the held pull request.
- Any other report that does not fit the edit's state is refused with `409` `edit_state`, whose `state` gives the state. An event without its field, or with a field that it does not take, is refused with `400`.

### Reports of a record's pull request

The agent reports the pull request that writes a checkpoint passed in NEXUS into its stage record (API-130, SPEC-140):

| Event | The checkpoint | Becomes |
| --- | --- | --- |
| `opened` | Passed, with no reported pull request open | `pr_state: open`, held by the pull request |
| `merged` | Its reported pull request is open | `pr_state: merged` |
| `closed` | Its reported pull request is open | `pr_state: closed`, free for any session to claim |

- `opened` for a withdrawn checkpoint is refused with `409` `checkpoint_withdrawn`, so no new record names it. `merged` and `closed` are still taken for a withdrawn checkpoint's open pull request, which the agent closes (SPEC-140).
- A merged pull request does not record the checkpoint: the next push whose stored records name it does, and sets its `recorded_commit`.
- Repeats and other pull requests are answered as for a reflection.

Implementation clarification (2026-11-04): API-130 returns `409 checkpoint_state` for `merged` or `closed` without a reported open pull request, and for a new `opened` after a stored record names the checkpoint. Repeating its last report still changes nothing. This fills an unspecified refusal without changing SPEC-140's state transitions.

## The hub's commands

### Running a command

- The hub is `hub.py` in the `scripts` folder of the hub skill, in standard-library Python 3.8 or later on Windows, macOS and Linux, as in phase 1. It keeps phase 1's options `--home` and `--version`, and its five commands with their options, which 0.2 extends as each command below says.
- The commands that reach the server, `push`, `remove`, `todo`, the agent's writes, `show`, `claim`, `release` and `outbox --send`, take its address from `--url`, then `CORTHEX_NEXUS_URL`, then `nexus.url` in the profile: `https`, or `http` only for the device itself. They send the service token from `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET`, which a server on the device does not need, and never write it to a file, a log or a message (REQ-109, REQ-110). They follow no redirect, and take a redirect, or a `401` or `403` without a JSON reason, as a refused token (REQ-111). They work only for the projects in `nexus.push`, apart from `remove`.
- The agent's writes, `claim` and `release` need the session label, from `--session` or `CORTHEX_NEXUS_SESSION`; `todo` reads it when it is given.
- A text comes from `--text TEXT`, or from `--text-file FILE`, where `-` is standard input, in UTF-8; likewise `--reason` and `--reason-file`, `--change` and `--change-file`, and `--source-file`. Before it sends a text, the hub redacts it as it redacts a snapshot: secrets and email addresses become `[redacted]`, and the user's home folder becomes `~` (SPEC-128).
- `--part PART` names a part; without it a command concerns the project as a whole.
- `--json` prints, for each project, one line with a JSON object: `command`; `project`; `outcome`, as below; `answer`, the server's answer; `problem`, the server's Problem Details of a refusal; `failure`, the kind of a failure or of the hub's own refusal, such as `no network`, `timeout`, `HTTP 503`, `no service token`, `refused token` or `not in nexus.push`; and `outbox`, how many of its writes were `sent`, `dropped` and are `waiting`. Without it, the hub prints the same in lines for a person.
  When a write is dropped, `outbox.notices` additionally names its write ID and reason (the Problem Details or the failure kind), never its body. This supplies the drop report below, including seven-day expiry, without exposing a kept text.
  Only when an agent write cannot be persisted, the failed result also has `recovery`: its original redacted OutboxFile, including its write ID and body. The command shows this once to the calling agent, as SPEC-129 requires; it does not save or log this copy. The agent keeps the text in its session and preserves that ID when recovering it. Ordinary results and outbox listings have no recovery text.

| Exit code | Outcome | When |
| --- | --- | --- |
| 0 | `done` | The command did what it asked, also for a write that changed nothing, one that the server had taken already, a removal of a project that the server does not hold, and an empty to-do |
| 1 | `refused` or `failed` | The server or the hub's own checks refused it, or it could not reach the server, and nothing waits to be sent again |
| 2 | | The command line is wrong: an unknown option, an ID or a label in another form, a text file that is not UTF-8, a missing session label, or a link or role that holds a secret or an email address |
| 3 | `kept` | The write waits in the outbox ([The outbox](#the-outbox)) |

### Snapshots and records

`snapshot` (API-133):

```txt
hub.py snapshot [PROJECT ...] [--path FOLDER] [--repo ALIAS=FOLDER ...] [--print]
```

As in phase 1, in the format `corthex-hub/0.2` ([Snapshot 0.2](#snapshot-02)): from 0.2 the snapshot also holds the parts, the picture sources from the default branch's commit, the stage records from the repository and the actions to ask about first (SPEC-104 to SPEC-110), and its checks include the [new rules](#check-rules).

`status` (API-134):

```txt
hub.py status PROJECT STAGE [--part PART] [--state STATE] [--next TEXT]
              [--checkpoint TEXT --by ROLE --date DATE [--where LINK] [--nexus CHECKPOINT]]
              [--check LEVEL MESSAGE ...] [--clear-checks] [--reset] [--repository]
```

- It writes the stage's record into the repository's working tree, `.corthex/stages/<part>.json`, or `.corthex/stages.json` for a project without parts, when the checkout holds stage records, or, for the first record, with `--repository` (SPEC-137). Otherwise it writes the device's status file, as in phase 1. The agent commits the record with the work, in its pull request; the hub never commits, pushes or opens a pull request.
- In the records, `--checkpoint` adds a checkpoint to the stage's list: what was approved, `--by` the role that approved it, such as `the maintainer`, `--date`, and `--where`, a link to where it was approved. `--nexus` names a checkpoint passed in NEXUS, whose link, by default, is its stage overview on the server, `<nexus.url>/overview/<project>/<part>/<stage>#<checkpoint>` (SPEC-140). `--state done` needs a checkpoint with its date in the record (REQ-085). In the status file, `--checkpoint` keeps phase 1's meaning.
- The file is written as TBL-115 says: JSON indented by two spaces, its fields in their order and a final LF, through a temporary file and a move. `updated` is the time of the write, with the device's zone.

`build` (API-135):

```txt
hub.py build [PROJECT ...] [--out FILE] [--no-scan]
```

As in phase 1, with the page data `corthex-hub-page/0.2` ([Page data](#page-data)): each part's stage records and the actions to ask about first. A page built on a device has no `spaces`, and says that the pictures and the counts are on the server (SPEC-123).

### Pushes and removals

`push` (API-136):

```txt
hub.py push [PROJECT ...] [--url URL] [--dry-run] [--replace-held]
```

- Without names it pushes every project in `nexus.push`, each as [A push](#a-push) says, and reports the answer: the revision, the pictures drawn again, made current again or marked not current, the discrepancies opened and resolved, the checkpoints recorded and what waits in the agent to-do (SPEC-111).
- `--dry-run` sends nothing, not even the outbox or the question for the held commit: it shows each snapshot's counts and size, the pictures that it would send and those that it leaves out, and says that the held commit is checked when it is sent.
- `--replace-held` sends a snapshot whose commit is not a descendant of the held one, naming the held one as the one it replaces. The agent uses it only after the user agrees.
- Outcomes: `done`; `refused`, for a project that is not in `nexus.push`, no address, no token's variables, which it names without a value, a commit that the table of [A push](#a-push) rules out, a server of phase 1, a refused token or a refusal of the server, with its reason; `failed`, for no network or no answer within 30 seconds. A push is never kept, since the next one takes a fresh snapshot.

`remove` (API-137):

```txt
hub.py remove PROJECT ... [--url URL] [--dry-run]
```

- `--dry-run` reads what the removal would delete (API-110) and shows it, with the open comments, open proposals, pending reflections and checkpoints not yet recorded, by ID, up to 20 of each with their totals. Unlike phase 1's, it reaches the server and needs the service token. The hub skill has the agent show it, offer to answer, reflect or record those entries first, and send the removal only once the user confirms (SPEC-115).
- Without `--dry-run`, it sends the removal (API-108). `404` `project_not_found` is reported as nothing to remove, with exit code 0, as in phase 1. After a removal the hub deletes the project's outbox, and when the project is still in `nexus.push` it says that the next push brings the project back with an empty space, and how to take it off the list.
- It takes projects whether `nexus.push` lists them or not, as in phase 1.

### The agent's work

`todo` (API-138):

```txt
hub.py todo PROJECT [--session LABEL]
```

It sends the project's outbox, reads the agent to-do with the session label and prints it in its order, with the counts of comments that wait for the user and of entries that other sessions took (SPEC-135). `404` `space_not_found` gives an empty to-do and exit code 0, and the agent says nothing about it. No service token, or no answer, is `failed`, and the agent goes on with its work (REQ-185).

The writes (API-139 to API-146):

```txt
hub.py comment  PROJECT --stage STAGE [--part PART] [--item ID] [--quote TEXT]
                [--discrepancy ID] [--commit COMMIT] (--text TEXT | --text-file FILE)
hub.py reply    PROJECT COMMENT (--text TEXT | --text-file FILE)
hub.py answered PROJECT COMMENT
hub.py decide   PROJECT COMMENT --link LINK [--text TEXT | --text-file FILE]
hub.py propose  PROJECT --stage STAGE [--part PART] --item ID [--item ID ...] [--adds ID ...]
                (--reason TEXT | --reason-file FILE) (--change TEXT | --change-file FILE)
                [--source-file FILE] [--comment ID | --discrepancy ID] [--commit COMMIT]
hub.py withdraw PROJECT PROPOSAL
hub.py reflect  PROJECT EDIT EVENT [--pr LINK] [--commit COMMIT]
hub.py record   PROJECT CHECKPOINT EVENT --pr LINK
```

- Each sends one write with a new write ID and the session label (API-118 to API-123, API-126 and API-130), after the project's outbox. `comment` without `--item` comments on the picture itself and needs `--quote`. `reflect` takes the events `opened`, `merged`, `closed`, `reflected` and `needs-user`, and `record` takes `opened`, `merged` and `closed` ([Reports](#reports)).
- `decide` refuses, before sending, a link that is not `https` or that holds a secret or an email address (SPEC-132).
- A write that cannot be sent waits in the outbox, with exit code 3; a refusal of the server is reported with its reason and is not sent again (SPEC-128, SPEC-129).

`show` (API-147):

```txt
hub.py show PROJECT ID
```

It reads one comment, proposal, edit or checkpoint by its `nc_`, `np_`, `ne_` or `nk_` ID (API-114 to API-117): a comment with all its replies, a proposal with its stage source text, and a checkpoint, which the agent reads before it merges the pull request of its record (SPEC-140). The to-do and the overview hold discrepancies whole, so an `nd_` ID is a wrong command line.

`claim` and `release` (API-148, API-149):

```txt
hub.py claim   PROJECT ENTRY
hub.py release PROJECT ENTRY
```

They claim an entry for the session, or end the session's claim (API-131, API-132). A claim is never kept in the outbox: one that cannot be sent leaves the entry untaken, and the hub says so (stage 05, [Outbox](../05-erd/nexus.md#outbox-tbl-117)).

### The outbox

`outbox` (API-150):

```txt
hub.py outbox [PROJECT ...] [--send]
```

It lists the writes that wait, by project, with their request, when they were made, their tries and their last failure, but no text; `--send` sends them.

- A write is kept when it cannot be sent: no network, no answer within 30 seconds, `429`, `500`, `502`, `503` or `504`, no service token on the device, a refused token, or `403` `access_missing` or `access_other_app`, which a fixed Access setup will let through (SPEC-129).
- A write is dropped, and reported with its reason, when the server refuses it for another reason, such as `409` or `404`, since sending it again changes nothing, and 7 days after it was made, since the to-do that it answered has moved on.
- At each contact with the server for a project, a push, `todo`, a write, `show`, `claim`, `release` or `outbox --send`, the hub first sends that project's outbox, oldest first, each write with its own write ID and session label. It stops at the first write that is kept again, so that the writes keep their order.
- Each write is one file, `outbox/<project>/<time>.<write>.json` under `~/.corthex/hub/` (TBL-117), in the form of the contract's `OutboxFile`. The hubs of one device take turns on a project's outbox with the lock `outbox/<project>.lock`, as stage 05 says.
- A fresh agent write enters that queue before its first send. The device-only ID ordering metadata preserves admission order at millisecond ties; neither a concurrent append nor a lost sender's lease makes a new direct send bypass it. Successful first sends remove their transient files too, so the reported drain counts include them.
- The outbox never holds the service token, and the hub never shows a kept write's text in a log.

## Formats

### Snapshot 0.2

The fields that `corthex-hub/0.2` adds to phase 1's format are those of TBL-114 in stage 05's [Snapshot](../05-erd/nexus.md#snapshot-tbl-114), and the contract's `Snapshot02` checks them. An excerpt, with lists cut short:

```json
{
  "schema": "corthex-hub/0.2",
  "generator": "corthex-nexus 0.2.0",
  "generated_at": "2026-11-03T10:00:00+09:00",
  "project": { "name": "acme-shop", "title": "Acme Shop", "parts": ["orders", "billing"] },
  "repos": {
    ".": {
      "commit": "<full commit id>", "branch": "work", "dirty": true,
      "web": "https://github.com/example/acme-shop", "url": "https://github.com/example/acme-shop",
      "default": { "branch": "main", "commit": "<full commit id>", "time": "2026-11-03T09:40:00+09:00" }
    }
  },
  "replaces": "<the held commit>",
  "records": { "from": "repository", "commit": "<full commit id>", "time": "2026-11-03T09:40:00+09:00" },
  "stages": {
    "05-erd": {
      "state": "in_progress", "source_state": "found",
      "parts": {
        "orders": { "state": "in_progress", "checkpoints": [], "next": "Index the orders by date", "updated": "2026-11-03T09:30:00+09:00" }
      }
    }
  },
  "items": [], "checks": [], "summary": {},
  "pictures": [
    { "part": "orders", "stage": "05-erd", "commit": "<full commit id>", "time": "2026-11-03T09:40:00+09:00",
      "source": { "format": 1, "tables": [], "without_table": [] } }
  ],
  "left_out": [{ "part": "billing", "stage": "07-sitemap", "why": "other-repository" }],
  "ask_before": { "entries": ["releases", "deletions"], "source": "project", "left_out": ["external messages", "deploys", "payments", "publishing"] }
}
```

- The hub sends it as compact JSON. It keeps phase 1's limits of 3,000 items, 2,000 checks and 1,000,000 bytes, under the server's 1 MiB. When the picture sources would take it over, whole pictures are left out, the largest first, each named in `left_out` with `why: size` and in a `picture-left-out` check (REQ-192).
- `repos.".".url` is the `origin` remote's address in the form of [A push](#a-push), and `repos.".".default` the default branch as SPEC-105 finds it. Without them, the snapshot has no picture sources and a `pictures-not-sent` check.
- `replaces` is the held commit that the push replaces ([A push](#a-push)); `hub.py snapshot` writes none.
- `records` says where the stage records came from: `repository`, with the commit and its time, or `status-file`.
- The server stores the snapshot without `pictures`, whose sources the pictures keep (stage 05's choice 3), so `API-107` returns the snapshot without them, the contract's `StoredSnapshot02`.

### Picture sources

Each picture source has `format: 1` and one of three shapes, the contract's `DomainSource`, `ErdSource` and `SitemapSource`. The hub takes them from the stage sources' documents of one part at the default branch's commit (SPEC-105 to SPEC-108):

- Each element has `where`, its file and line at the commit, relative to the repository, such as `docs/05-erd/nexus.sql:15`.
- An element's `id` is its trace ID, or `""` when it has none; `context` is a CTX ID, or `""`. Names are cut at 120 characters and other texts at 300, as titles are, and each list stops at the contract's limit for it.
- `removed` is `true` for an element whose status says that it is removed, as [reading.md](../../plugins/corthex-nexus/skills/corthex-hub/references/reading.md) reads statuses.
- Secrets and email addresses become `[redacted]` (REQ-191).
- A document that the forms below cannot fully read gives what could be read, with a `picture-partial` check that names the place.

**DDD board (`01-domain`).** The forms of the stage 01 template, [01-domain.md](../../plugins/corthex/skills/corthex-discover/references/01-domain.md), in English, and in Korean as its Korean documents write them, such as [docs/01-domain/nexus.ko.md](../01-domain/nexus.ko.md). The hub finds a table by its header row, reads the columns named here in any order, compares the names ignoring case and spacing, and ignores other columns.

| Element | English form | Korean form |
| --- | --- | --- |
| A context | A heading that starts with its CTX ID and then its name, such as `### CTX-001 Ordering`, with a line `Purpose: …` and a bullet `- External systems: …` under it | The same heading, with `목적: …` and `- 바깥 시스템: …` |
| Its type and aggregates | A table with the columns `Context`, `Type` and `Aggregates` | `컨텍스트`, `종류`, `애그리거트` |
| Its command rows | A table with the columns `Given by`, `Read model`, `Command`, `Aggregate` and `Events`, under the context's heading. A row whose `Given by` holds `Policy: when …`, alone or after who else gives it, is a policy | `주는 쪽`, `읽기 모델`, `명령`, `애그리거트`, `사건`; `정책: …` |
| The read models | The read models of the command rows, and a table with the columns `Read model` and `Shows` | `읽기 모델`, `보여 주는 것` |
| The dependencies | A table with the columns `From`, `To`, `Kind`, `Why` and `Data`. A kind that starts with `call` is `call`, one that starts with `event` is `event`, and any other `""` | `어디서`, `어디로`, `종류`, `까닭`, `오가는 것`; `바로 묻기` is `call`, `사건 알림` is `event` |
| The hotspots | A table with the columns `Hotspot`, `Context`, `State` and `Answer or next step`. A number at the start of the text, such as `1.`, is the hotspot's `number`, and the CTX IDs under `Context` its contexts | `핫스팟`, `컨텍스트`, `상태`, `답이나 다음 할 일` |
| The glossary | A table with an `ID` column of TERM IDs and a `Term` column | `ID`, `용어` |
| Removed contexts and terms | A table with an `ID` column and a `Status` column that says removed | `ID`, `상태`, with `삭제` |
| The timeline | A table with the columns `Lane` and `Events`, one row for each lane, in order. In `Events`, ` → ` separates the places, from left to right, and `, or ` the events stacked in one place | `흐름`, `사건`; ` 또는 `, with or without a comma before it |

An aggregate or read model takes the TERM ID written beside its name, as `Picture (TERM-085)`, or else that of the glossary row, in the same document, whose term is its name, ignoring case and spacing; with none, or with two such rows, it gets a `board-term-missing` warning (SPEC-106).

A command table outside a context's heading keeps its rows under the nearest context heading above it, with a `picture-partial` check. If none precedes it but the document has a context elsewhere, the rows stay in a context whose `id` and `name` are empty, and their aggregates and read models have `context: ""`. A document with no context contributes no DDD board, including none of its dependencies or timeline (SPEC-106).

In a command row's `Events`, commas separate the events, and a leading `or` (`또는`) is not part of a name, so `Payment taken, or Payment failed` gives two events. The timeline is optional: a document without one gives no `timeline`, and the view then shows the board only as a whole (SPEC-141). Each lane keeps its `where`, the line of its row.

**ERD (`05-erd`).** The SQL of [reading.md](../../plugins/corthex-nexus/skills/corthex-hub/references/reading.md) and the stage 05 template, [05-erd.md](../../plugins/corthex/skills/corthex-contract/references/05-erd.md):

```sql
-- without a table: TERM-122
-- TBL-101 snapshots (CTX-009, terms: none) ← SPEC-111, SPEC-114
CREATE TABLE snapshots (
  name TEXT PRIMARY KEY,
  revision INTEGER NOT NULL
);
-- TBL-103 pictures (CTX-012, TERM-085) ← SPEC-118
CREATE TABLE pictures (
  project TEXT NOT NULL REFERENCES snapshots (name) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  PRIMARY KEY (project, stage)
);
```

- A table is a `CREATE TABLE` that a TBL ID comment defines. The parentheses after its name give its context, a CTX ID, and either its TERM IDs or `terms: none`. A comment with neither leaves `terms` out, which SPEC-121 reports.
- A column has its name, its type as written and `null`, which is `false` for `NOT NULL` and for a column of the primary key. The primary key comes from `PRIMARY KEY` on a column or in the table; a unique rule from `UNIQUE` on a column or in the table, or from `CREATE UNIQUE INDEX … ON`, with `partial: true` for one with `WHERE`; a foreign key from `REFERENCES` on a column or in the table, or from `ALTER TABLE … ADD [CONSTRAINT …] FOREIGN KEY`, with `on_delete` in lowercase, or `""` without one.
- A comment line `-- without a table:` followed by TERM IDs, anywhere in the part's SQL, lists the aggregates that the part keeps outside tables.
- An index expression that cannot be represented as column names is omitted as a whole unique rule, with a `picture-partial` check; a function name is never drawn as a column. Removed status words in table comments use the same vocabulary as other stage items: an explicit `status:` (`상태:`) wins; otherwise a standalone metadata field in parentheses or after a `|` may mark removal. Words in a table name or descriptive title are not its status. Quoted identifier/title spans are excluded before metadata delimiters are read, including escaped quotes; a quoted status value remains a value.
- The markers `terms: none`, `without a table:` and `without a screen:` are the same in every language, as the code around them is.

**Sitemap (`07-sitemap`).** The YAML of the stage 07 template, [07-sitemap.md](../../plugins/corthex/skills/corthex-screen/references/07-sitemap.md), with `terms`, here two screens of NEXUS's own [nexus.yaml](../07-sitemap/nexus.yaml):

```yaml
- id: SCR-104
  name: Stage detail
  path: "/#p={project}&s={stage}"
  access: anyone Cloudflare Access lets in, or the device's user
  flows: [FL-105, FL-113]
  terms: none
  status: active
  children:
    - id: SCR-109
      name: Stage overview
      path: "/overview/{project}/{part}/{stage}"
      access: anyone Cloudflare Access lets in, on the server
      flows: [FL-113]
      terms: [CTX-007, TERM-120]
      status: active
# without a screen: TERM-121
```

- Each screen keeps `id`, `name`, `path`, `access`, `flows` and, from the nesting under `children`, `parent`, the place of its parent in `screens`. A parent that the part does not hold puts the screen at the top, with a `picture-partial` check.
- `terms` holds the screen's context, a CTX ID, and the TERM IDs that it stands for; `terms: none` and `terms: []` say that it stands for none, and a screen with neither leaves `terms` out.
- A comment line `# without a screen:` followed by TERM IDs lists the read models that the part shows on no screen ([Changes to earlier stages](#changes-to-earlier-stages)).

### Project settings

The project settings, `.corthex/project.json`, gain two fields, which the core plugin's [project.md](../../plugins/corthex/skills/corthex/references/project.md) adds with the 0.2 release:

| Field | Type | Meaning |
| --- | --- | --- |
| `parts` | array of strings | Optional. The project's parts, in the order in which the hub page shows them: 1 to 50 different names in lowercase letters and digits joined by hyphens, up to 100 characters each. A document belongs to the part whose name starts its path in the stage source, followed by `/`, `.` or `-`, and the longest such name wins: in a stage source `docs/01-domain/`, `nexus.md` and `nexus/board.md` belong to `nexus` |
| `ask_before` | array of strings | Optional. The actions to ask about first in this project, in place of the profile's list (SPEC-110) |

`parts` in another form counts as none, with a `parts-invalid` warning. The hub keeps a copy of the core plugin's default `ask_before` list, the one in its example profile, `["external messages", "deploys", "payments", "deletions", "publishing"]`, and a test compares the two, as memory's context does.

### Stage records

The stage records are the file of TBL-115 in stage 05's [Stage records](../05-erd/nexus.md#stage-records-tbl-115), which the contract's `StageRecords` checks: `.corthex/stages/<part>.json` for each part that `parts` names, or `.corthex/stages.json` for a project without parts. The hub reads them from the default branch's commit through Git's object reader and writes them in the working tree with `status` (API-134). A file that is not valid JSON, of another `format` or with a state that is not one of the four gets a `records-invalid` warning, and its stages show as `unknown` (SPEC-109).

`RecordCheckpoint.where` is optional: `status --where` is optional, and SPEC-109 leaves an unsafe link out of a snapshot while retaining the approval, role and date. The status-file fallback preserves phase 1's `checkpoint` and `checkpoint_date` without inventing a role or a NEXUS checkpoint. It never converts that legacy text into a repository checkpoint by itself. A legacy `done` without both a checkpoint and a valid calendar date is shown as `in_progress` with a warning (REQ-085).

### Outbox files

Each file of the outbox is TBL-117 of stage 05's [Outbox](../05-erd/nexus.md#outbox-tbl-117), whose `path`, the request's path, makes each try go where the first went; the contract's `OutboxFile` checks it:

```json
{
  "format": 1,
  "write": "nw_6t9w2z5c8f1j",
  "project": "corthex",
  "request": "reply",
  "path": "/api/spaces/corthex/comments/nc_3a6d9g2j5m8r/replies",
  "session": "claude-code-4f2a91",
  "made": "2026-11-03T07:00:00.000Z",
  "body": { "text": "The table keeps one row for each part." },
  "tries": 1,
  "failure": "no network"
}
```

`request` is one of the agent's [request names](#request-names). The file keeps the write ID without the quotes, which the hub adds to the header.

### Page data

- The hub page holds `corthex-hub-page/0.2` in `<script id="hub-data" type="application/json">`, the contract's `HubPageData`: phase 1's members and `spaces`, which holds for each project that has a space its pictures, open counts, checkpoints that wait for their records and warnings. `lang` comes from the server's `NEXUS_LANGUAGE`, as in phase 1, or from the profile on a device.
- The picture view and the stage overview hold `corthex-view-page/0.2` in `<script id="view-data" type="application/json">`, the contract's `ViewPageData`: `view`, `picture` or `overview`; `data`, the answer of API-111 or API-112; and `problem`, the Problem Details when the server could not read it, such as `picture_not_found`. After a write the view reads its data again with that request.

## Check rules

The hub's new rules, which its [reading.md](../../plugins/corthex-nexus/skills/corthex-hub/references/reading.md) gains with the 0.2 release:

| Rule | Level | Meaning |
| --- | --- | --- |
| `pictures-not-sent` | warn | The repository has no default branch that the hub can read: no `origin` remote, no head recorded for it, or no Git. The snapshot holds no picture sources, and the message says to run `git remote set-head origin --auto` (SPEC-105) |
| `picture-left-out` | warn | A whole picture is left out, for its size or because its stage source is in another repository, as `left_out` says (SPEC-105) |
| `picture-partial` | warn | A pictured document could not be fully read, so its picture holds what could be read: the check names the place and why, such as a table under no context heading, a document without a context, a screen whose parent is missing or YAML not in the template's form (SPEC-105, SPEC-106, SPEC-108) |
| `part-unknown` | info | A pictured document belongs to no part, so it is drawn into the picture of the project as a whole (SPEC-105) |
| `parts-invalid` | warn | The project settings' `parts` is not 1 to 50 different part names, so the project is read without parts |
| `board-term-missing` | warn | An aggregate or a read model has no glossary row of its name, or two, so it has no term, or the first (SPEC-106) |
| `records-invalid` | warn | A stage records file is not valid JSON or not in a known format, or a record has a state that is not one of the four, `done` without a checkpoint and its date, a stage key that is not one of the 13 or a part that the settings do not name; the check names the file and what was wrong (SPEC-109) |
| `records-in-status-file` | info | The repository holds no stage records at the default branch's commit, so they come from the device's status file and should move to the repository (SPEC-109) |
| `ask-before-invalid` | warn | The project's or the profile's `ask_before` is not a list of strings, or the profile cannot be read, so the next list applies (SPEC-110) |
| `ask-before-long` | info | The list has more than 30 entries, and the first 30 are kept (SPEC-110) |

The server adds one rule to a stage when it reads it, in the overview and the hub page, and never to the stored snapshot: `checkpoint-withdrawn`, `warn`, for a stored stage record that names a checkpoint withdrawn in NEXUS, shown beside the stage's recorded state until a push whose records no longer name it (SPEC-140).

## Limits

Stage 05's [limits](../05-erd/nexus.md#limits) hold, with these that this stage adds:

| Limit | Value |
| --- | --- |
| A write's body | 256 KiB |
| A snapshot dated ahead of the server's clock | 10 minutes, as in phase 1 |
| The lists of a read | As [Reads](#reads) gives them |
| The lists of a push's answer | 20 of each, with their counts |
| A request of the hub | An answer within 30 seconds |

## Kinds of cases

| Kind | What the contract lists |
| --- | --- |
| Access | Every request's security. `401` is never the Worker's, since Access answers it; `403` with `access_missing`, `access_other_app`, `cross_site`, `user_only`, `agent_only` and `no_kind` |
| Input | `400` with `invalid_request`, `invalid_snapshot`, `clock_ahead` and `unknown_item`, and `413` for texts and bodies, with each field's limits from stage 05 |
| Target | `404` with a code for each kind of entry; a path value in another form gets the same `404` |
| State changes | `409` with a code for each reason, such as `comment_closed`, `proposal_not_open`, `edit_state` and `checkpoint_recorded` |
| Repeats | The write ID: a write sent again gets its first answer, and an ID of another request `409` `write_id_reused`. A push by the commit rule, a removal sent twice `404` |
| Concurrency | Writes are taken one after the other; a push that another overtook gets `409` `commit_not_replaced`; another session's claim `409` `claimed` |
| Limits | `409` for a space's limits and `413` for sizes. No `429` of the server's own: Cloudflare's limits apply, and the hub keeps an agent's write that gets `429` in the outbox |
| Outside services | None: the server calls no other service. A failure of D1 is `500` `internal`, and the hub keeps an agent's write that gets it |
| Data exposure | Answers hold no identity but the author's kind, a stored snapshot holds no picture sources, and lists hold the length of a proposal's stage source text instead of the text |
| Empty and streamed answers | Empty lists with a total of 0, as each list's `nothing` or `empty` example shows. No `204` and no streams |
| Screen states | Nothing more; stage 08 leads each response to a state |
| AI answers | None: NEXUS calls no AI model (REQ-121) |

## Error codes

The codes of every request, as the contract's `components.x-corthex.errors` lists them; the `code` member takes no other. The members are those that the code adds to the [error shape](#errors). The messages are drafts in English, which stage 08 words in English and Korean for the view's states; the meanings and what the client does are this stage's.

| Code | Status | Meaning | Members | Message | What the client does |
| --- | --- | --- | --- | --- | --- |
| `invalid_request` | 400 | a field, a header or the body is not in its form; field names it | `field` | This is not valid: check the marked field | the view shows the message by the field; the hub reports the field and drops the write from its outbox |
| `invalid_snapshot` | 400 | the snapshot is not in the format corthex-hub/0.1 or 0.2; field names the first bad field | `field` | The snapshot is not valid | the hub reports the field and keeps nothing to send again |
| `clock_ahead` | 400 | the snapshot is dated more than 10 minutes ahead of the server's clock | none | The snapshot is dated in the future. Check the device's clock | the hub reports it |
| `unknown_item` | 400 | a proposal names items that its picture does not hold and that adds does not name; items names them | `items` | The proposal names items that are not in the picture | the hub reports the items, and the agent checks the stage source |
| `access_missing` | 403 | Cloudflare Access did not check the request | none | Cloudflare Access did not check this request. Protect the server with Access first | the hub reports a refused token; the view says that the sign-in is missing and offers to load again |
| `access_other_app` | 403 | another Access application than ACCESS_AUD names checked the request | none | This request was checked for another Access application | as for access_missing |
| `cross_site` | 403 | a browser sent a change from another site | none | A change from another site is refused | the view offers to open the page at the server's own address |
| `user_only` | 403 | the request needs a person's own sign-in; needs is user | `needs` | Only you can do this, signed in yourself | the hub reports that the user does this in the view |
| `agent_only` | 403 | the request needs the service token; needs is agent | `needs` | Only the agent does this, through the hub | the view never sends it; the hub reports a missing or refused service token |
| `no_kind` | 403 | Access let the request in, but its identity is neither a person's sign-in nor the service token | none | This sign-in cannot write here | the view and the hub report it, and the user checks the Access policy |
| `not_found` | 404 | no such path, or no such file of the view's code | none | Not found | the view links to the hub page |
| `project_not_found` | 404 | the server holds no snapshot of the project | none | This project is not on the server | the hub reports nothing to remove or read; a push stores the project as a new one |
| `space_not_found` | 404 | the project has no space, since only hubs of 0.1 pushed it | none | This project has no pictures on the server yet. Push it with corthex-nexus 0.2 | the hub says so and sends nothing |
| `part_not_found` | 404 | the stored snapshot does not hold the part | none | This part is not in the project's snapshot | the view links to the hub page |
| `picture_not_found` | 404 | the space holds no picture of the part and stage; why says whether none was drawn yet, the snapshot left it out for its size or its source is in another repository | `why` | No picture is drawn yet for this stage and part | the view shows the empty state with why |
| `comment_not_found` | 404 | the space holds no such comment | none | This comment is not on the server | the view loads the picture again; the hub reports it and drops the write |
| `discrepancy_not_found` | 404 | the part holds no such discrepancy | none | This discrepancy is not on the server | as for comment_not_found |
| `proposal_not_found` | 404 | the space holds no such proposal | none | This proposal is not on the server | as for comment_not_found |
| `edit_not_found` | 404 | the space holds no such edit | none | This reflection is not on the server | as for comment_not_found |
| `checkpoint_not_found` | 404 | the space holds no such checkpoint | none | This checkpoint is not on the server | the overview loads again; the hub reports it, and the agent writes no record of it |
| `entry_not_found` | 404 | the space holds no comment, discrepancy, edit or checkpoint with that ID | none | This entry is not on the server | the hub reports it and leaves the entry |
| `method_not_allowed` | 405 | the path does not take the method; Allow names those that it takes | none | This request is not allowed here | the hub reports it as a fault of its own |
| `older_snapshot` | 409 | a snapshot of the held commit, or of a project that holds none, made earlier than the stored one; stored_at says when that was made | `stored_at` | The server holds a newer snapshot | the hub takes a fresh snapshot and pushes again |
| `commit_not_replaced` | 409 | a snapshot of another commit than the held one that does not name the held one as the one it replaces, one without a commit where the stored snapshot has one, or a push that another push overtook; held_commit names the held commit | `held_commit` | The server holds another commit. Fetch the default branch and push again | the agent fetches and pushes again, once |
| `too_many_projects` | 409 | the server holds 30 projects, and the snapshot is of a new one | `limit` | The server holds 30 projects. Remove one first | the hub reports it |
| `repository_mismatch` | 409 | the snapshot's repository address is not the one that the space is bound to; bound names it | `bound` | This project's space is bound to another repository | the hub names both addresses and says that a removal unbinds the space |
| `comment_limit` | 409 | the space holds 2,000 comments | `limit` | This project holds as many comments as it may | the view keeps the text and says so |
| `reply_limit` | 409 | the comment holds 200 replies | `limit` | This comment holds as many replies as it may. Leave a new comment | the view keeps the text and offers a new comment |
| `proposal_limit` | 409 | the space holds 500 open proposals | `limit` | This project holds as many open proposals as it may | the hub reports it, and the agent withdraws proposals that the stage sources passed |
| `reflection_limit` | 409 | the space holds 500 pending reflections | `limit` | This project holds as many pending reflections as it may | the view says so, and the proposal stays open |
| `space_full` | 409 | the write would take the text of the space past 8 MiB | `limit` | This project's space is full | the view keeps the text; the hub reports it |
| `comment_closed` | 409 | the agent wrote on a closed comment, which only the user's reply opens again | none | This comment is closed | the hub reports it, and the agent leaves the comment |
| `proposal_not_open` | 409 | the proposal is accepted, dismissed or withdrawn already; state says which | `state` | This proposal is no longer open | the view shows its state |
| `edit_state` | 409 | the report or the dismissal does not fit the edit's state; state says which it is | `state` | This reflection is in another state | the view loads it again; the hub reports the state |
| `pull_request_reported` | 409 | another reported pull request still holds the reflection or the checkpoint; pull_request names it | `pull_request` | A pull request holds this already | the hub reports the pull request, and the agent leaves the entry |
| `pull_request_mismatch` | 409 | the report names another pull request than the one reported for the entry; pull_request names that one | `pull_request` | This is not the reported pull request | the hub reports both pull requests |
| `claimed` | 409 | another agent session claims the entry; ends_at says until when | `ends_at` | Another session holds this | the hub skips the entry until the claim ends |
| `entry_closed` | 409 | a claim on a closed entry | none | This entry is closed | the hub skips it |
| `checkpoint_recorded` | 409 | a stored stage record names the checkpoint, so withdrawing it would change a recorded decision | none | This checkpoint is recorded. Changing it is a new decision | the overview shows the record |
| `checkpoint_withdrawn` | 409 | the checkpoint was withdrawn, so no new record pull request may write it | none | This checkpoint was withdrawn | the hub reports it, and the agent writes no record |
| `checkpoint_state` | 409 | no matching open record, or already recorded | none | Read the checkpoint before reporting | read it again |
| `write_id_reused` | 409 | the write ID was taken by another request | none | This write could not be sent. Try again | the view makes a new ID; the hub reports it as a fault of its own |
| `snapshot_too_large` | 413 | the snapshot is larger than 1 MiB | `limit` | The snapshot is larger than the server takes | the hub reports it; its own limits keep snapshots smaller |
| `body_too_large` | 413 | a write's body is larger than 256 KiB | `limit` | This is larger than the server takes | the view and the hub report it |
| `text_too_long` | 413 | a text is longer than its limit; field and limit name them | `field`, `limit` | This text is too long | the view counts down by the field; the hub reports the field |
| `json_required` | 415 | a body that is not sent as application/json | none | This could not be sent | the hub reports it as a fault of its own |
| `internal` | 500 | an error inside the server; its log holds only the kind of error and the trace ID | none | Something went wrong. Try again | the view keeps what it holds and offers to send again; the hub keeps the write in its outbox |

## Breaking changes

Compared with phase 1, as the hub's [snapshot.md](../../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md) describes it:

1. Refusals are Problem Details, sent as `application/problem+json`, with more members. They keep `error`, so a hub of 0.1, which reads any JSON reply and shows `error`, still shows the reason, and the reasons are worded anew.
2. A hub of 0.1 cannot push a project that a hub of 0.2 pushed: its snapshot names no commit while the stored one has one, so the server refuses it with `409` `commit_not_replaced`. Every device's hub moves to 0.2 before it pushes such a project again.
3. A hub of 0.2 does not push to a server of phase 1, which refuses a snapshot of 0.2 with `400`: the hub stops at the question for the held commit, which a server of phase 1 answers with a `404` without a `code`. So the server of 0.2 is deployed before the hubs.
4. `push` takes a fresh snapshot instead of sending the saved one (SPEC-111), and `remove --dry-run` reads the server and needs the service token.
5. A removal deletes the project's space with the snapshot (SPEC-115), and `GET /api/snapshots/{project}` returns a snapshot of 0.2 without its picture sources.
6. The page data is `corthex-hub-page/0.2`, which the page of 0.2 reads; nothing else reads it.

The checkpoint accepted them on 2026-11-03, so 0.2 ships with them: the server first, then every device's hub.

## Changes to earlier stages

Applied on 2026-11-03, when the checkpoint passed: 1, 2 and 6 to the functional spec, and 3 to 5 and 7 to the server's data.

1. SPEC-113 says that no reply may be cached. The files of the view's code may be: they hold no project data, each name carries a digest of its content, and the view's speed on a phone needs them kept (REQ-149).
2. SPEC-108 names a top-level `without a screen` list. The stage 07 template's YAML is a list of screens, which has no place for a key, so the list is a comment line, `# without a screen:`, as the SQL's `-- without a table:` is.
3. TBL-117 gains `path`, so that each try of a kept write goes where the first went.
4. Stage 05's reads give a picture's open comments with their replies and decisions. The picture's answer gives each open comment with its count of replies and its last reply, and a comment's own read (API-114) gives all of them, so that a picture's answer stays small; the same for a proposal's stage source text (API-115).
5. Stage 05's picture sources give a hotspot's number. The template's hotspot table has no number column, so `number` is optional, taken from a number at the start of the text.
6. SPEC-116 counts opening a comment again from the view among the user's writes, and the functional spec's notes for stage 06 list it among the requests: it is the user's reply to the closed comment (SPEC-127), with no request of its own.
7. Stage 05's limits gain the 256 KiB of a write's body.

## Choices this stage made

1. A path value in another form gets the `404` of a value that the server does not hold, never `400`, as phase 1 answers a project name: every path has one refusal for what it names, and the form of a path tells nothing more.
2. Input that is not in its form gets `400`, never `422`, in every request, as phase 1 does. A text over its limit gets `413`, as SPEC-126 says, and a space at a limit `409`, since the request is in its form and the space is what is full.
3. A write whose outcome holds already changes nothing and succeeds with `changed: false`; one that another outcome closed is refused with `409` and the state ([Answers that change nothing](#answers-that-change-nothing)). The functional spec decides the cases that it names: marking answered a closed comment changes nothing (SPEC-127), and accepting a proposal dismissed in another tab is refused (SPEC-131).
4. The server sets no rate limit of its own. It serves one user and their agents behind Access, within Cloudflare's limits, and a `429` from Cloudflare keeps the agent's write in the outbox.
5. The write ID goes in the header of the Idempotency-Key draft, so that the page and the hub send it the same way for every write and the server reads it before the body, with the three differences that [Write IDs](#write-ids) gives.
6. No request lists `401`: Access answers it before the Worker. The Worker's refusals of a sign-in are `403` with a code, as phase 1's are.
7. Errors are Problem Details with phase 1's `error` kept, so that hubs of 0.1 still show the reason.
8. One comment, proposal, edit or checkpoint has a read of its own, so that the lists of a picture, an overview and the to-do stay small.
9. The hub's commands extend phase 1's `hub.py`, with exit codes 0 to 3 and `--json`, as MEMORY's commands give their results, instead of a second tool.
10. The contract is YAML, `nexus.openapi.yaml`, beside MEMORY's interfaces: the hub reads YAML as it reads JSON, and MEMORY's tests check the JSON files of this folder for a field named `id`, which an OpenAPI contract's examples hold.
11. The markers of the picture sources in SQL and YAML, `terms: none`, `without a table:` and `without a screen:`, are English in every language, as the code around them is; the DDD board's tables are read in English and in Korean, as people write them.

## Checks run

On 2026-11-02, on the contract and this file:

- openapi-spec-validator 0.7.1: the contract is valid OpenAPI 3.1.
- A check of this stage, in Python with PyYAML and jsonschema, which stays outside the repository: every operation has an API ID, its SPEC IDs and a status, and accounts for each response of the stage's table, by listing it or by naming it in `omit` with a reason; every response has a named example that its schema takes; every error example's code is in the list with the same status; and every write takes the write ID and answers `409` `write_id_reused` for an ID that another request took. No problems.
- Prism 5.16.0, `prism mock`: the contract loads, with its 32 operations. A write ID in double quotes passes, and one without them gets `400`.
- Schemathesis 3.39.16 against that mock, with `not_a_server_error`, `status_code_conformance`, `content_type_conformance` and `response_schema_conformance` and 25 examples for each operation: all 32 operations pass, in 858 requests. Two habits of the tool were set aside with hooks, which stay outside the repository and are counted in each run: it builds the `CF_Authorization` cookie from any characters, which Node's HTTP server refuses with a bare `400` before the mock sees it, so the hook gives the cookie a printable stand-in; and it fills a path value from a response example's member of the same name, such as the `edit` object for `{edit}`, so the hook puts back the parameter's own example. Its health check `data_too_large` was turned off, for the snapshot's large body.
- A mock passes most of these by design, so only a real server proves the contract: stage 11 runs the same tool against a development server behind Access, never against the user's own server.
- The repository's checks, with these files in place: `python -m unittest discover -s tests` (725 tests, 12 skipped), `claude plugin validate --strict` for the marketplace and its three plugins, and `node --test nexus/test/*.test.js` (15 tests) pass. The hub's snapshot of this repository reads API-101 to API-150 once each, with no checks, and every link of this file and its translation resolves.

On 2026-11-03, after the checkpoint's changes, with the same tools:

- The check of this stage and openapi-spec-validator find no problems; each of the contract's 72 examples is used, among them the pages' answers in HTML.
- Prism's mock answers API-101 to API-103 with a page of the code's message when the request's `Accept` names `text/html`, and with Problem Details otherwise.
- Schemathesis, with `--experimental=openapi-3.1`, which it asks for an OpenAPI 3.1 contract: all 32 operations pass, in 858 requests, and the four under Pages, the three pages and the view's code, in 103 of them. A third habit was set aside the same way: it builds the service token's two headers, `CF-Access-Client-Id` and `CF-Access-Client-Secret`, from any characters, which Node's HTTP server also refuses with a bare `400`, so the hook gives each a printable stand-in.
- The repository's checks pass, now with 727 tests (12 skipped), and the hub's snapshot of this repository reads 996 items with no checks.

Again on 2026-11-03, after the maintainer's choice to hold stage 01's event storming in NEXUS:

- openapi-spec-validator 0.7.1: the contract, with the optional `timeline` of `DomainSource`, is valid OpenAPI 3.1.
- The check of this stage finds no problems: the example `picture_data_domain`, which now holds a lane of the timeline, is taken by its schema, and each of the 72 examples is still used.
- Prism and Schemathesis were not run again: the change adds one optional field to one schema and a lane to one example, which the check of this stage validates.
- The repository's checks pass, now with 756 tests (12 skipped), and the hub's snapshot of this repository reads 1014 items with no checks.

### Development Access identity trial (2026-11-03)

TASK-201 deployed a temporary diagnostic Worker behind Access without static assets and used a service-token request (this host’s user environment) and a person’s signed-in browser through Aside CLI 1.26.1028.2335. Both returned 200; ctx.access audience and the JWT audience, issuer, expiry and RS256 signature matched. An anonymous browser received Access’s 302. Only field presence, empty and absent are recorded below, never their values.

| Source | Field | Person | Service token |
| --- | --- | --- | --- |
| ctx.access | aud | present | present |
| ctx.access | sub | absent | absent |
| ctx.access | email | absent | absent |
| ctx.access | common_name | absent | absent |
| getIdentity() | aud | absent | absent |
| getIdentity() | sub | absent | absent |
| getIdentity() | email | present | absent |
| getIdentity() | common_name | empty | absent |
| header JWT | aud | present | present |
| header JWT | sub | present | empty |
| header JWT | email | present | absent |
| header JWT | common_name | absent | present |

The selected header method distinguishes both kinds. Implementation checks of caching, expiry, rotation and refusal, and the full development API contract run are separate from this diagnostic and are not yet counted as complete. After the diagnostic, replace the development probe with the implemented server.

## For the checkpoint

The maintainer's choice of 2026-11-03, to hold stage 01's event storming in NEXUS, passed at 16:54 KST the same day, together with the changes that it made to the other stages: on a decision card in the project's thread the maintainer chose to pass the step view and the work board as drawn ("모두 그린 대로 통과", pass all as drawn). The checkpoint covered: the optional `timeline` of `DomainSource`, with its forms in [Picture sources](#picture-sources), which is a compatible change, since a picture source without it stays valid and a snapshot of the frozen form still passes; and the work board of phase ② (SPEC-142), which adds its requests then, beside those of editing (SPEC-134).

Passed on 2026-11-03 at 11:39 KST, together with stages 03 to 05, 07 and 08: on a decision card in the project's thread the maintainer chose all the recommendations ("모두 추천대로", all as recommended), so the requests, the commands and the formats stand as written, with the changes of stage 08. The sign-in (3) stays open until its trial. The checkpoint covered:

1. The [breaking changes](#breaking-changes), above all that every device's hub moves to 0.2 once one has pushed with it, and that the server is deployed first.
2. The [changes to earlier stages](#changes-to-earlier-stages), above all the cached code of the view (1) and the `# without a screen:` line (2).
3. The sign-in that stays open until a trial on a real Access setup ([Sign-in](#sign-in)), which comes before stage 11 builds the requests.
4. The write ID in the draft's header, with its three differences ([Write IDs](#write-ids)), and the answers that change nothing (choice 3).
5. The hub's 18 commands and their names ([The hub's commands](#the-hubs-commands)), which the stage skills will tell the agent to run.

## Notes for later stages

### Stages 07 and 08: screens

- The requests of each screen: the hub page, API-101; the picture view, API-102 and API-104 to load, API-111 to read again, API-114 and API-115 to open a comment or a proposal, API-116 to read a reflection that the picture no longer lists, closed or dismissed, so that the proposal's panel shows its pull request, and API-118 to API-120, API-124, API-125 and API-127 to write; and the stage overview, API-103 and API-104 to load, API-112 to read again, and API-128 and API-129 to write.
- The states that the errors lead to: `picture_not_found` with its `why` is empty; `access_missing`, `access_other_app`, `no_kind` and an `opaqueredirect` reply are permission or an expired sign-in; `cross_site` is an error that offers the server's own address; `comment_limit`, `reply_limit`, `space_full` and `text_too_long` keep the text; `proposal_not_open`, `edit_state` and `checkpoint_recorded` are stale, and the view reads again. The view keeps an unsent text with its write ID (SPEC-126).
- Each message of [Error codes](#error-codes) gets its final words, in English and Korean.

### Stage 10: work breakdown

- The server first: store.js's migrations, then the requests in the contract's order: the push with the held commit and the removal; the reads; the discussion; editing; stage progress with the claims. The hub follows: the snapshot 0.2 with its picture sources, stage records and settings, `status`, `push`, then the writes with the outbox. The views come last.
- The release carries this file's formats and rules into the hub's [snapshot.md](../../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md) and [reading.md](../../plugins/corthex-nexus/skills/corthex-hub/references/reading.md), and `parts` and `ask_before` into the core plugin's [project.md](../../plugins/corthex/skills/corthex/references/project.md), with the stage skills' steps that run the hub's commands.

### Stage 11: development

- The trial of both kinds of sign-in on a real Access setup comes first, and closes the open question of [Sign-in](#sign-in).
- Contract tests run Schemathesis against a development Worker behind Access, with the hooks of [Checks run](#checks-run) in the repository, and Prism's mock serves the views' work before the server is built.
- Tests that hold the parts together: the server's error codes against the contract's list; the hub's request names against the contract's `OutboxFile`; the hub's copy of the default `ask_before` list against the core plugin's example profile; and the order of refusals of [Which refusal comes first](#which-refusal-comes-first).

### Stage 12: QA

- A test case for each response of each request, from its named examples, written as `API-118#409`, and for each outcome of each command, on Linux, macOS and Windows.
- The kinds of cases above: a write sent twice and again after 7 days, a write ID of another request, two sessions on one entry, a push that another overtook, a 0.1 hub after a 0.2 push, a sign-in that expires in the view, and the outbox without a network, without a token and after 7 days.
