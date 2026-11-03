// Everything that touches the database is in this file. The SQL is the part
// SQLite (D1) and Postgres share, apart from the `?` placeholders, so moving
// to another database changes this file only.

// All SQL, including released migrations, stays in this module (REQ-123).
// SQLite reads row lists with json_each; Postgres uses json_array_elements.
// Postgres also needs BIGINT for generated_ms, since its INTEGER is 32-bit.
// Changed-row comparisons use IS NOT, SQLite's null-safe equivalent of
// IS DISTINCT FROM, so that two NULL values compare equal on older SQLite.
// Never edit a released migration: add a new version instead.
export const MIGRATIONS = [
  {
    "version": 1,
    "statements": [
      "CREATE TABLE IF NOT EXISTS snapshots (\n  name TEXT PRIMARY KEY,\n  revision INTEGER NOT NULL,\n  generated_ms INTEGER NOT NULL,\n  generated_at TEXT NOT NULL,\n  received_at TEXT NOT NULL,\n  bytes INTEGER NOT NULL,\n  body TEXT NOT NULL\n)"
    ]
  },
  {
    "version": 2,
    "statements": [
      "ALTER TABLE snapshots ADD COLUMN default_commit TEXT",
      "ALTER TABLE snapshots ADD COLUMN push_id TEXT",
      "CREATE TABLE project_spaces (\n  project     TEXT    PRIMARY KEY REFERENCES snapshots (name) ON DELETE CASCADE,\n  repo_url    TEXT,\n  created_at  TEXT    NOT NULL,\n  text_bytes  INTEGER NOT NULL DEFAULT 0 CHECK (text_bytes >= 0),\n  unopened    TEXT    NOT NULL DEFAULT '{}'\n)",
      "CREATE TABLE pictures (\n  project      TEXT NOT NULL REFERENCES project_spaces (project) ON DELETE CASCADE,\n  part         TEXT NOT NULL,\n  stage        TEXT NOT NULL CHECK (stage IN ('01-domain', '05-erd', '07-sitemap')),\n  commit_id    TEXT NOT NULL,\n  committed_at TEXT NOT NULL,\n  source       TEXT NOT NULL,\n  digest       TEXT NOT NULL,\n  drawn_at     TEXT NOT NULL,\n  not_current  TEXT CHECK (not_current IN ('size', 'source-gone', 'other-repository')),\n  PRIMARY KEY (project, part, stage)\n)",
      "CREATE TABLE discrepancies (\n  id              TEXT    PRIMARY KEY,\n  project         TEXT    NOT NULL REFERENCES project_spaces (project) ON DELETE CASCADE,\n  part            TEXT    NOT NULL,\n  compares        TEXT    NOT NULL CHECK (compares IN ('aggregate-table', 'read-model-screen')),\n  term            TEXT    NOT NULL,\n  item            TEXT    NOT NULL,\n  reasons         TEXT    NOT NULL,\n  level           TEXT    NOT NULL CHECK (level IN ('warn', 'info')),\n  state           TEXT    NOT NULL CHECK (state IN ('open', 'resolved')),\n  waiting         INTEGER NOT NULL DEFAULT 0 CHECK (waiting IN (0, 1)),\n  opened_commit   TEXT    NOT NULL,\n  opened_at       TEXT    NOT NULL,\n  resolved_commit TEXT,\n  resolved_at     TEXT,\n  earlier         TEXT    REFERENCES discrepancies (id) ON DELETE SET NULL,\n  CHECK ((state = 'open' AND resolved_commit IS NULL AND resolved_at IS NULL)\n      OR (state = 'resolved' AND resolved_commit IS NOT NULL AND resolved_at IS NOT NULL)),\n  CHECK (waiting = 0 OR state = 'open')\n)",
      "CREATE UNIQUE INDEX discrepancies_pair ON discrepancies (project, part, compares, term, item) WHERE state = 'open'",
      "CREATE INDEX discrepancies_state ON discrepancies (project, state, level)",
      "CREATE TABLE comments (\n  id           TEXT    PRIMARY KEY,\n  project      TEXT    NOT NULL,\n  part         TEXT    NOT NULL,\n  stage        TEXT    NOT NULL,\n  item         TEXT    NOT NULL,\n  quote        TEXT,\n  discrepancy  TEXT    REFERENCES discrepancies (id) ON DELETE SET NULL,\n  commit_id    TEXT    NOT NULL,\n  author       TEXT    NOT NULL CHECK (author IN ('user', 'agent')),\n  text         TEXT    NOT NULL,\n  state        TEXT    NOT NULL CHECK (state IN ('open', 'closed')),\n  closed_as    TEXT    CHECK (closed_as IN ('answered', 'decided')),\n  waits        TEXT    CHECK (waits IN ('user', 'agent')),\n  settled      INTEGER NOT NULL DEFAULT 0 CHECK (settled IN (0, 1)),\n  dismissed    INTEGER NOT NULL DEFAULT 0 CHECK (dismissed IN (0, 1)),\n  made_at      TEXT    NOT NULL,\n  last_at      TEXT    NOT NULL,\n  FOREIGN KEY (project, part, stage) REFERENCES pictures (project, part, stage) ON DELETE CASCADE,\n  CHECK ((state = 'open' AND closed_as IS NULL AND waits IS NOT NULL)\n      OR (state = 'closed' AND closed_as IS NOT NULL AND waits IS NULL)),\n  CHECK ((settled = 0 AND dismissed = 0) OR state = 'open')\n)",
      "CREATE INDEX comments_waiting ON comments (project, state, waits, last_at)",
      "CREATE INDEX comments_picture ON comments (project, part, stage, state)",
      "CREATE TABLE replies (\n  comment  TEXT    NOT NULL REFERENCES comments (id) ON DELETE CASCADE,\n  seq      INTEGER NOT NULL CHECK (seq > 0),\n  author   TEXT    NOT NULL CHECK (author IN ('user', 'agent')),\n  text     TEXT    NOT NULL,\n  settles  INTEGER NOT NULL DEFAULT 0 CHECK (settles IN (0, 1)),\n  made_at  TEXT    NOT NULL,\n  PRIMARY KEY (comment, seq),\n  CHECK (settles = 0 OR author = 'user')\n)",
      "CREATE TABLE decisions (\n  comment  TEXT    NOT NULL REFERENCES comments (id) ON DELETE CASCADE,\n  seq      INTEGER NOT NULL CHECK (seq > 0),\n  link     TEXT    NOT NULL,\n  text     TEXT,\n  made_at  TEXT    NOT NULL,\n  PRIMARY KEY (comment, seq)\n)",
      "CREATE TABLE proposals (\n  id           TEXT PRIMARY KEY,\n  project      TEXT NOT NULL,\n  part         TEXT NOT NULL,\n  stage        TEXT NOT NULL,\n  commit_id    TEXT NOT NULL,\n  items        TEXT NOT NULL,\n  reason       TEXT NOT NULL,\n  change       TEXT NOT NULL,\n  source_text  TEXT,\n  comment      TEXT REFERENCES comments (id) ON DELETE SET NULL,\n  discrepancy  TEXT REFERENCES discrepancies (id) ON DELETE SET NULL,\n  state        TEXT NOT NULL CHECK (state IN ('open', 'accepted', 'dismissed', 'withdrawn')),\n  made_at      TEXT NOT NULL,\n  closed_at    TEXT,\n  FOREIGN KEY (project, part, stage) REFERENCES pictures (project, part, stage) ON DELETE CASCADE,\n  CHECK ((state = 'open') = (closed_at IS NULL))\n)",
      "CREATE INDEX proposals_state ON proposals (project, state)",
      "CREATE INDEX proposals_comment ON proposals (comment)",
      "CREATE TABLE edits (\n  id            TEXT PRIMARY KEY,\n  project       TEXT NOT NULL,\n  part          TEXT NOT NULL,\n  stage         TEXT NOT NULL,\n  commit_id     TEXT NOT NULL,\n  proposal      TEXT UNIQUE REFERENCES proposals (id) ON DELETE CASCADE,\n  content       TEXT,\n  state         TEXT NOT NULL CHECK (state IN ('pending', 'in-review', 'needs-user', 'closed', 'dismissed')),\n  pull_request  TEXT,\n  closed_commit TEXT,\n  made_at       TEXT NOT NULL,\n  changed_at    TEXT NOT NULL,\n  FOREIGN KEY (project, part, stage) REFERENCES pictures (project, part, stage) ON DELETE CASCADE,\n  CHECK (proposal IS NOT NULL OR content IS NOT NULL),\n  CHECK (state <> 'in-review' OR pull_request IS NOT NULL)\n)",
      "CREATE INDEX edits_state ON edits (project, state, made_at)",
      "CREATE TABLE checkpoints (\n  id              TEXT PRIMARY KEY,\n  project         TEXT NOT NULL REFERENCES project_spaces (project) ON DELETE CASCADE,\n  part            TEXT NOT NULL,\n  stage           TEXT NOT NULL,\n  commit_id       TEXT,\n  words           TEXT,\n  state           TEXT NOT NULL CHECK (state IN ('passed', 'withdrawn')),\n  passed_at       TEXT NOT NULL,\n  withdrawn_at    TEXT,\n  pull_request    TEXT,\n  pr_state        TEXT CHECK (pr_state IN ('open', 'merged', 'closed')),\n  recorded_commit TEXT,\n  CHECK ((state = 'withdrawn') = (withdrawn_at IS NOT NULL)),\n  CHECK ((pull_request IS NULL) = (pr_state IS NULL))\n)",
      "CREATE INDEX checkpoints_state ON checkpoints (project, state)",
      "CREATE TABLE claims (\n  entry      TEXT PRIMARY KEY,\n  project    TEXT NOT NULL REFERENCES project_spaces (project) ON DELETE CASCADE,\n  session    TEXT NOT NULL,\n  claimed_at TEXT NOT NULL,\n  ends_at    TEXT NOT NULL\n)",
      "CREATE INDEX claims_ends ON claims (project, ends_at)",
      "CREATE TABLE writes (\n  project     TEXT NOT NULL REFERENCES project_spaces (project) ON DELETE CASCADE,\n  id          TEXT NOT NULL,\n  request     TEXT NOT NULL,\n  result      TEXT NOT NULL,\n  received_at TEXT NOT NULL,\n  PRIMARY KEY (project, id)\n)",
      "CREATE INDEX writes_received ON writes (received_at)"
    ]
  }
];

const MIGRATION_TABLE = "CREATE TABLE IF NOT EXISTS migrations (\n  version    INTEGER PRIMARY KEY,\n  applied_at TEXT    NOT NULL\n)";

// The newer of two snapshots of a project wins: the update runs only when
// the incoming snapshot was generated at the same time or later. A new name
// is added only while the hub holds fewer projects than the limit. SQLite,
// which D1 runs, makes the statement one serializable transaction, so two
// uploads cannot both take the last place; Postgres would need a lock for that.
const PUT = `INSERT INTO snapshots (name, revision, generated_ms, generated_at, received_at, bytes, body)
SELECT ?, 1, ?, ?, ?, ?, ?
WHERE EXISTS (SELECT 1 FROM snapshots WHERE name = ?) OR (SELECT COUNT(*) FROM snapshots) < ?
ON CONFLICT (name) DO UPDATE SET
  revision = snapshots.revision + 1,
  generated_ms = excluded.generated_ms,
  generated_at = excluded.generated_at,
  received_at = excluded.received_at,
  bytes = excluded.bytes,
  body = excluded.body
WHERE excluded.generated_ms >= snapshots.generated_ms
RETURNING revision`;

const ready = new WeakMap();

export class Store {
  constructor(db) {
    this.db = db;
  }

  // Each version is one D1 transaction with its version marker. Separate
  // Worker isolates may race: a loser rereads the committed versions rather
  // than attempting to continue after a partially applied migration.
  async migrate() {
    await this.db.prepare(MIGRATION_TABLE).run();
    const versions = async () => {
      const { results } = await this.db.prepare("SELECT version FROM migrations").all();
      return new Set((results || []).map((row) => row.version));
    };
    let applied = await versions();
    for (const migration of MIGRATIONS) {
      if (applied.has(migration.version)) continue;
      const statements = migration.statements.map((sql) => this.db.prepare(sql));
      statements.push(this.db.prepare("INSERT INTO migrations (version, applied_at) VALUES (?, ?)")
        .bind(migration.version, new Date().toISOString()));
      try {
        await this.db.batch(statements);
      } catch (error) {
        // A failure is recoverable only if another isolate committed this
        // exact version. Other failures remain failures and are retryable.
        applied = await versions();
        if (!applied.has(migration.version)) throw error;
      }
    }
  }

  // Share startup work within an isolate, but never cache a rejected attempt.
  async ensure() {
    let pending = ready.get(this.db);
    if (!pending) {
      pending = this.migrate();
      ready.set(this.db, pending);
      pending.catch(() => ready.delete(this.db));
    }
    await pending;
  }

  async meta(name) {
    await this.ensure();
    return this.db
      .prepare("SELECT name, revision, generated_at, received_at, bytes FROM snapshots WHERE name = ?")
      .bind(name)
      .first();
  }

  async list() {
    await this.ensure();
    const { results } = await this.db
      .prepare("SELECT name, revision, generated_at, received_at, bytes FROM snapshots ORDER BY name")
      .all();
    return results || [];
  }

  async bodies() {
    await this.ensure();
    const { results } = await this.db.prepare("SELECT body FROM snapshots ORDER BY name").all();
    return (results || []).map((row) => row.body);
  }

  async body(name) {
    await this.ensure();
    return this.db.prepare("SELECT body FROM snapshots WHERE name = ?").bind(name).first("body");
  }

  // Returns the new revision, or null when nothing was stored: the stored
  // snapshot is newer, or the name is new and the hub holds `limit` projects.
  async put(name, generatedMs, generatedAt, receivedAt, body, bytes, limit) {
    await this.ensure();
    const row = await this.db
      .prepare(PUT)
      .bind(name, generatedMs, generatedAt, receivedAt, bytes, body, name, limit)
      .first();
    return row ? row.revision : null;
  }

  async remove(name) {
    await this.ensure();
    const result = await this.db.prepare("DELETE FROM snapshots WHERE name = ?").bind(name).run();
    return Boolean(result && result.meta && result.meta.changes);
  }
}
