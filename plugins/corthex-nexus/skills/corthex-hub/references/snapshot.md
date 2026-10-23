# Hub files and formats

Everything the hub writes is under `~/.corthex/hub/` (on Windows, `%USERPROFILE%\.corthex\hub\`):

| File | Written by | Holds |
| --- | --- | --- |
| `snapshots/<project>.json` | `snapshot`, `build` | what the project's stage sources define and link, and the checks |
| `status/<project>.json` | `status` | each stage's recorded state, checkpoint, next action and review findings |
| `status/<project>.json.bak` | `status` | the status file as it was before the last write |
| `index.html` | `build` | the hub page |

Files are written through a temporary file, so a failed write keeps the old one. To start over, delete the folder; the next `build` makes the snapshots and the page again, but recorded progress is only in `status/`.

## Snapshot: `corthex-hub/0.1`

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
- `repos` has `.` for the project's own repository and one entry per alias in the project's `repos`. `checkout: false` means this machine has no local copy. `web` is set for GitHub repositories and lets the page link each `where` to the file at that commit.
- Each stage has `source_state`: `found`, `missing`, `none` (no text source), `no-checkout`, `skipped` or `invalid`. `default_source: true` marks the contract's default path. `read` and `files` are set for stages that were read, `skipped` counts the files that were not.
- `state` is `done`, `in_progress`, `not_started` or `skipped` as recorded, and `unknown` when nothing is recorded. A stage with `skip: true` and no record shows as `skipped`.
- Items are in stage order, then by ID. `where` is `file:line`, with the repository alias in front for another repository. Optional fields: `title`, `status`, `type`, `priority`, `link`, `parent`, `screen_doc`, `states` and `links`.
- Checks are ordered by level, then stage. `by` is `scan` for the rules in [reading.md](reading.md) and `review` for findings recorded with `status --check`. `args` holds the values of the message, so the page can show it in another language.

### What a snapshot leaves out

- File contents, other than IDs, titles and the status, type, priority and link fields.
- Local paths: `where` and `source` are relative to their repository.
- Secrets and email addresses in titles and fields, which become `[redacted]`, and user names and passwords in links. A link that holds a secret or an email address, even percent-encoded, is left out whole, since it would not work with the secret taken out.

Limits: 3,000 items, 2,000 checks and 1,000,000 bytes per snapshot. Items are dropped from the end first, then checks, and a `truncated` check gives how many of each were kept. A project whose settings alone are over the limit gets no snapshot. Titles have up to 120 characters, and an item up to 60 links.

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
{ "schema": "corthex-hub-page/0.1", "generated_at": "…", "lang": "en", "origin": "local", "projects": [], "missing": [] }
```

`projects` holds the snapshots. `lang` is `ko` when the profile's `language` starts with `ko`, otherwise `en`. A NEXUS server serves the same page with `origin` set to `server`. The page loads nothing from the network: its Content Security Policy allows no requests, and it shows text only as text.

## NEXUS push

Settings in `~/.corthex/profile.json`:

```json
{ "nexus": { "url": "https://nexus.example.com", "push": ["acme-shop"] } }
```

- `url`: the server. `--url` and the environment variable `CORTHEX_NEXUS_URL` take precedence. It must use `https`; `http` works only for `localhost`, `127.0.0.1` and `::1`, for testing.
- `push`: the projects that may be sent. `hub.py push` with no names sends these; a name that is not listed is refused.
- The service token is read from `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET` and sent as the Cloudflare Access headers `CF-Access-Client-Id` and `CF-Access-Client-Secret`. A server on this machine may be used without a token.

Each project is one request: `POST <url>/api/snapshots` with the snapshot as the JSON body. Any `2xx` reply means it was stored; the reply may hold `{"revision": <number>}`. Redirects are not followed: a redirect, `401` or `403` means the token was refused, because Cloudflare Access sends a refused request to its login page.
