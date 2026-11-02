-- NEXUS server, schema 2: the D1 database that nexus/src/store.js keeps, from NEXUS 0.2.
-- Stage 05 of CORTHEX's own project. nexus.md beside this file explains each table and
-- column, the migrations that bring a database of phase 1 to this schema, and the files on
-- devices and in repositories that go with it.
-- This file is the schema of an empty database, in SQL that SQLite, which D1 runs, and
-- Postgres share, but for one column: Postgres's INTEGER has 32 bits, so a copy for Postgres
-- declares snapshots.generated_ms BIGINT. Only store.js runs SQL (REQ-123). D1 enforces
-- foreign keys, so deleting a project's snapshot deletes its space and everything in it.
-- Each table's comment names its context, and the terms of the DDD board's aggregates that
-- the table keeps, or terms: none for a table that keeps none of them. The limits of the
-- functional spec are checked by the code, not by constraints here, so that changing one
-- needs no migration.
-- without a table: TERM-122

-- TBL-101 snapshots (CTX-009, terms: none) ← SPEC-111, SPEC-112, SPEC-114, SPEC-115, SPEC-122, SPEC-123, SPEC-124, SPEC-125, SPEC-138, SPEC-139
-- The newest snapshot of each project, as phase 1 keeps it. From schema 2 the body is the
-- snapshot without its picture sources, which pictures keeps, and default_commit is the
-- default branch commit that its pictures and stage records came from: the held commit, which
-- a snapshot of another commit must name as the one it replaces.
CREATE TABLE snapshots (
  name           TEXT    PRIMARY KEY,
  revision       INTEGER NOT NULL,
  generated_ms   INTEGER NOT NULL,
  generated_at   TEXT    NOT NULL,
  received_at    TEXT    NOT NULL,
  bytes          INTEGER NOT NULL,
  body           TEXT    NOT NULL,
  default_commit TEXT
);

-- TBL-102 project_spaces (CTX-012, TERM-109) ← SPEC-114, SPEC-115, SPEC-117, SPEC-121, SPEC-126, SPEC-127, SPEC-130, SPEC-132, SPEC-133, SPEC-134
-- One space for each stored snapshot, made with the project's first snapshot of 0.2 and bound
-- to the address of the repository that holds the project settings. text_bytes counts the
-- UTF-8 bytes of the text in the space's comments, replies, decisions, proposals and edits;
-- unopened is a JSON object of how many discrepancies each part's last cross-check could not
-- open, because the space held as many open ones as it may.
CREATE TABLE project_spaces (
  project     TEXT    PRIMARY KEY REFERENCES snapshots (name) ON DELETE CASCADE,
  repo_url    TEXT,
  created_at  TEXT    NOT NULL,
  text_bytes  INTEGER NOT NULL DEFAULT 0 CHECK (text_bytes >= 0),
  unopened    TEXT    NOT NULL DEFAULT '{}'
);

-- TBL-103 pictures (CTX-012, TERM-085) ← SPEC-114, SPEC-115, SPEC-118, SPEC-119, SPEC-120, SPEC-123, SPEC-126, SPEC-130, SPEC-134
-- The last picture of each part and pictured stage, current or not: its picture source as the
-- snapshot carried it, the document version that it was drawn from, and why it is not current.
-- part is empty for the project as a whole. digest is the SHA-256 of source, by which a push
-- finds a picture source unchanged without reading the stored one.
CREATE TABLE pictures (
  project      TEXT NOT NULL REFERENCES project_spaces (project) ON DELETE CASCADE,
  part         TEXT NOT NULL,
  stage        TEXT NOT NULL CHECK (stage IN ('01-domain', '05-erd', '07-sitemap')),
  commit_id    TEXT NOT NULL,
  committed_at TEXT NOT NULL,
  source       TEXT NOT NULL,
  digest       TEXT NOT NULL,
  drawn_at     TEXT NOT NULL,
  not_current  TEXT CHECK (not_current IN ('size', 'source-gone', 'other-repository')),
  PRIMARY KEY (project, part, stage)
);

-- TBL-104 discrepancies (CTX-013, TERM-112) ← SPEC-114, SPEC-115, SPEC-119, SPEC-120, SPEC-121, SPEC-123, SPEC-126, SPEC-130, SPEC-135, SPEC-136, SPEC-138
-- What a cross-check of one part found for one pair, or for one item without its pair.
-- compares names the kind of pair, term and item what it concerns, each empty when there is
-- none, and reasons, a JSON list, what disagrees. Only one discrepancy of a pair is open,
-- which the partial unique index keeps; one found again after it was resolved names the
-- earlier one.
CREATE TABLE discrepancies (
  id              TEXT    PRIMARY KEY,
  project         TEXT    NOT NULL REFERENCES project_spaces (project) ON DELETE CASCADE,
  part            TEXT    NOT NULL,
  compares        TEXT    NOT NULL CHECK (compares IN ('aggregate-table', 'read-model-screen')),
  term            TEXT    NOT NULL,
  item            TEXT    NOT NULL,
  reasons         TEXT    NOT NULL,
  level           TEXT    NOT NULL CHECK (level IN ('warn', 'info')),
  state           TEXT    NOT NULL CHECK (state IN ('open', 'resolved')),
  waiting         INTEGER NOT NULL DEFAULT 0 CHECK (waiting IN (0, 1)),
  opened_commit   TEXT    NOT NULL,
  opened_at       TEXT    NOT NULL,
  resolved_commit TEXT,
  resolved_at     TEXT,
  earlier         TEXT    REFERENCES discrepancies (id) ON DELETE SET NULL,
  CHECK ((state = 'open' AND resolved_commit IS NULL AND resolved_at IS NULL)
      OR (state = 'resolved' AND resolved_commit IS NOT NULL AND resolved_at IS NOT NULL)),
  CHECK (waiting = 0 OR state = 'open')
);
CREATE UNIQUE INDEX discrepancies_pair ON discrepancies (project, part, compares, term, item) WHERE state = 'open';
CREATE INDEX discrepancies_state ON discrepancies (project, state, level);

-- TBL-105 comments (CTX-014, TERM-114) ← SPEC-115, SPEC-116, SPEC-119, SPEC-123, SPEC-126, SPEC-127, SPEC-128, SPEC-130, SPEC-131, SPEC-132, SPEC-135, SPEC-136, SPEC-138
-- A comment on an item of a picture, by its trace ID, or on the picture itself, with a quote of
-- the part that it was left on. commit_id is the document version of the picture when the
-- comment was left. waits says whom an open comment waits for; settled marks a user's last
-- reply that settles it, and dismissed a proposal for it that the user dismissed since the
-- agent's last entry.
CREATE TABLE comments (
  id           TEXT    PRIMARY KEY,
  project      TEXT    NOT NULL,
  part         TEXT    NOT NULL,
  stage        TEXT    NOT NULL,
  item         TEXT    NOT NULL,
  quote        TEXT,
  discrepancy  TEXT    REFERENCES discrepancies (id) ON DELETE SET NULL,
  commit_id    TEXT    NOT NULL,
  author       TEXT    NOT NULL CHECK (author IN ('user', 'agent')),
  text         TEXT    NOT NULL,
  state        TEXT    NOT NULL CHECK (state IN ('open', 'closed')),
  closed_as    TEXT    CHECK (closed_as IN ('answered', 'decided')),
  waits        TEXT    CHECK (waits IN ('user', 'agent')),
  settled      INTEGER NOT NULL DEFAULT 0 CHECK (settled IN (0, 1)),
  dismissed    INTEGER NOT NULL DEFAULT 0 CHECK (dismissed IN (0, 1)),
  made_at      TEXT    NOT NULL,
  last_at      TEXT    NOT NULL,
  FOREIGN KEY (project, part, stage) REFERENCES pictures (project, part, stage) ON DELETE CASCADE,
  CHECK ((state = 'open' AND closed_as IS NULL AND waits IS NOT NULL)
      OR (state = 'closed' AND closed_as IS NOT NULL AND waits IS NULL)),
  CHECK ((settled = 0 AND dismissed = 0) OR state = 'open')
);
CREATE INDEX comments_waiting ON comments (project, state, waits, last_at);
CREATE INDEX comments_picture ON comments (project, part, stage, state);

-- TBL-106 replies (CTX-014, TERM-114) ← SPEC-115, SPEC-116, SPEC-119, SPEC-127, SPEC-128, SPEC-132, SPEC-133
-- The replies under a comment, in order, each by the user or the agent. settles marks a user's
-- reply that settles the comment.
CREATE TABLE replies (
  comment  TEXT    NOT NULL REFERENCES comments (id) ON DELETE CASCADE,
  seq      INTEGER NOT NULL CHECK (seq > 0),
  author   TEXT    NOT NULL CHECK (author IN ('user', 'agent')),
  text     TEXT    NOT NULL,
  settles  INTEGER NOT NULL DEFAULT 0 CHECK (settles IN (0, 1)),
  made_at  TEXT    NOT NULL,
  PRIMARY KEY (comment, seq),
  CHECK (settles = 0 OR author = 'user')
);

-- TBL-107 decisions (CTX-014, TERM-114) ← SPEC-115, SPEC-119, SPEC-128, SPEC-132
-- The decisions that the agent recorded on a comment, each with the link to where it was
-- written, in the project's records or in a merged pull request, and the decision in words.
CREATE TABLE decisions (
  comment  TEXT    NOT NULL REFERENCES comments (id) ON DELETE CASCADE,
  seq      INTEGER NOT NULL CHECK (seq > 0),
  link     TEXT    NOT NULL,
  text     TEXT,
  made_at  TEXT    NOT NULL,
  PRIMARY KEY (comment, seq)
);

-- TBL-108 proposals (CTX-014, TERM-088) ← SPEC-115, SPEC-119, SPEC-123, SPEC-128, SPEC-130, SPEC-131, SPEC-133
-- A change that the agent proposes on a picture, made on the document version commit_id: the
-- items that it concerns, a JSON list of trace IDs, its reason, the change in words and the
-- text of the stage source that it would write, in answer to a comment or a discrepancy, or
-- on its own.
CREATE TABLE proposals (
  id           TEXT PRIMARY KEY,
  project      TEXT NOT NULL,
  part         TEXT NOT NULL,
  stage        TEXT NOT NULL,
  commit_id    TEXT NOT NULL,
  items        TEXT NOT NULL,
  reason       TEXT NOT NULL,
  change       TEXT NOT NULL,
  source_text  TEXT,
  comment      TEXT REFERENCES comments (id) ON DELETE SET NULL,
  discrepancy  TEXT REFERENCES discrepancies (id) ON DELETE SET NULL,
  state        TEXT NOT NULL CHECK (state IN ('open', 'accepted', 'dismissed', 'withdrawn')),
  made_at      TEXT NOT NULL,
  closed_at    TEXT,
  FOREIGN KEY (project, part, stage) REFERENCES pictures (project, part, stage) ON DELETE CASCADE,
  CHECK ((state = 'open') = (closed_at IS NULL))
);
CREATE INDEX proposals_state ON proposals (project, state);
CREATE INDEX proposals_comment ON proposals (comment);

-- TBL-109 edits (CTX-010, TERM-116) ← SPEC-115, SPEC-119, SPEC-128, SPEC-131, SPEC-133, SPEC-134, SPEC-135, SPEC-136, SPEC-138
-- An edit, bound to the document version commit_id of its picture: an accepted proposal, or in
-- phase ② a change that the user made in the editor, kept in content as JSON. Until it is
-- closed or dismissed it is a pending reflection. pull_request is the pull request that the
-- agent reported, and closed_commit the commit whose stage source already held the change.
CREATE TABLE edits (
  id            TEXT PRIMARY KEY,
  project       TEXT NOT NULL,
  part          TEXT NOT NULL,
  stage         TEXT NOT NULL,
  commit_id     TEXT NOT NULL,
  proposal      TEXT UNIQUE REFERENCES proposals (id) ON DELETE CASCADE,
  content       TEXT,
  state         TEXT NOT NULL CHECK (state IN ('pending', 'in-review', 'needs-user', 'closed', 'dismissed')),
  pull_request  TEXT,
  closed_commit TEXT,
  made_at       TEXT NOT NULL,
  changed_at    TEXT NOT NULL,
  FOREIGN KEY (project, part, stage) REFERENCES pictures (project, part, stage) ON DELETE CASCADE,
  CHECK (proposal IS NOT NULL OR content IS NOT NULL),
  CHECK (state <> 'in-review' OR pull_request IS NOT NULL)
);
CREATE INDEX edits_state ON edits (project, state, made_at);

-- TBL-110 checkpoints (CTX-007, TERM-119) ← SPEC-114, SPEC-115, SPEC-123, SPEC-128, SPEC-135, SPEC-136, SPEC-138, SPEC-139, SPEC-140
-- A checkpoint that the user passed in NEXUS for one stage of one part, with the user's words,
-- on the default branch commit commit_id of the stored snapshot. pull_request and pr_state
-- are the record's pull request that the agent reported; recorded_commit is the default
-- branch commit of the stored snapshot whose stage record names the checkpoint, which each
-- push sets.
CREATE TABLE checkpoints (
  id              TEXT PRIMARY KEY,
  project         TEXT NOT NULL REFERENCES project_spaces (project) ON DELETE CASCADE,
  part            TEXT NOT NULL,
  stage           TEXT NOT NULL,
  commit_id       TEXT,
  words           TEXT,
  state           TEXT NOT NULL CHECK (state IN ('passed', 'withdrawn')),
  passed_at       TEXT NOT NULL,
  withdrawn_at    TEXT,
  pull_request    TEXT,
  pr_state        TEXT CHECK (pr_state IN ('open', 'merged', 'closed')),
  recorded_commit TEXT,
  CHECK ((state = 'withdrawn') = (withdrawn_at IS NOT NULL)),
  CHECK ((pull_request IS NULL) = (pr_state IS NULL))
);
CREATE INDEX checkpoints_state ON checkpoints (project, state);

-- TBL-111 claims (CTX-007, terms: none) ← SPEC-115, SPEC-127, SPEC-128, SPEC-130, SPEC-132, SPEC-133, SPEC-135, SPEC-136, SPEC-140
-- The hold of one entry of the agent to-do, a comment, a discrepancy, an edit or a checkpoint,
-- by its ID, for one agent session, named by its label. Each of the session's writes on the
-- entry moves ends_at on; a claim past ends_at counts as none and is deleted by the space's
-- next write.
CREATE TABLE claims (
  entry      TEXT PRIMARY KEY,
  project    TEXT NOT NULL REFERENCES project_spaces (project) ON DELETE CASCADE,
  session    TEXT NOT NULL,
  claimed_at TEXT NOT NULL,
  ends_at    TEXT NOT NULL
);
CREATE INDEX claims_ends ON claims (project, ends_at);

-- TBL-112 writes (CTX-014, terms: none) ← SPEC-115, SPEC-126, SPEC-127, SPEC-128, SPEC-129, SPEC-130, SPEC-131, SPEC-132, SPEC-133, SPEC-139, SPEC-140
-- The IDs that the page or the hub gave the writes that the server took, with the first
-- answer, so that a write sent again changes nothing and gets the same answer. Kept 7 days.
CREATE TABLE writes (
  project     TEXT NOT NULL REFERENCES project_spaces (project) ON DELETE CASCADE,
  id          TEXT NOT NULL,
  request     TEXT NOT NULL,
  result      TEXT NOT NULL,
  received_at TEXT NOT NULL,
  PRIMARY KEY (project, id)
);
CREATE INDEX writes_received ON writes (received_at);

-- TBL-113 migrations (CTX-009, terms: none) ← SPEC-114
-- The schema versions that store.js applied to the database, one row each; 1 and 2 give the
-- schema of this file. This file records none, so the server's database is always set up by
-- store.js, and one made from this file alone serves only to compare the schemas.
CREATE TABLE migrations (
  version    INTEGER PRIMARY KEY,
  applied_at TEXT    NOT NULL
);
