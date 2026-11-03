import { Problem } from "./problem.js";
import { planPush, checkCommit } from "./push-plan.js";
import * as E from "./entries.js";
import { checkWriteBody, planEntryWrite, entryDisposition } from "./entry-plan.js";
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

// Schema 2 has no way to distinguish a repeated closed report after its PR
// field was cleared. Preserve the last event internally without changing APIs.
MIGRATIONS.push({ version: 3, statements: ["ALTER TABLE edits ADD COLUMN last_report TEXT"] });

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
const CHECKPOINT_BASIS = `SELECT json_group_array(json_object('id',id,'state',state,'recorded_commit',recorded_commit))
  FROM (SELECT id,state,recorded_commit FROM checkpoints WHERE project=? ORDER BY id)`;

// Identifiers below are fixed by the schema, never taken from a request.
const ENTRY_COLUMNS = Object.freeze({
  comments: "id project part stage item quote discrepancy commit_id author text state closed_as waits settled dismissed made_at last_at".split(" "),
  replies: "comment seq author text settles made_at".split(" "),
  decisions: "comment seq link text made_at".split(" "),
  proposals: "id project part stage commit_id items reason change source_text comment discrepancy state made_at closed_at".split(" "),
  edits: "id project part stage commit_id proposal content state pull_request closed_commit made_at changed_at last_report".split(" "),
  checkpoints: "id project part stage commit_id words state passed_at withdrawn_at pull_request pr_state recorded_commit".split(" "),
  discrepancies: "id project part compares term item reasons level state waiting opened_commit opened_at resolved_commit resolved_at earlier".split(" "),
  claims: "entry project session claimed_at ends_at".split(" "),
});
const rowJSON = (table, where) => `(SELECT json_object(${ENTRY_COLUMNS[table].map((name) => `'${name}',${name}`).join(",")}) FROM ${table} WHERE ${where})`;
const activeEntry = `EXISTS(SELECT 1 FROM comments WHERE id=entry AND project=claims.project AND state='open')
 OR EXISTS(SELECT 1 FROM discrepancies WHERE id=entry AND project=claims.project AND state='open')
 OR EXISTS(SELECT 1 FROM edits WHERE id=entry AND project=claims.project AND state IN ('pending','needs-user'))
 OR EXISTS(SELECT 1 FROM checkpoints WHERE id=entry AND project=claims.project AND pr_state IS NOT 'open' AND
   ((state='passed' AND recorded_commit IS NULL) OR (state='withdrawn' AND recorded_commit IS NOT NULL)))`;

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
  async pushState(name) {
    await this.ensure();
    const read = (sql) => this.db.prepare(sql).bind(name);
    const rows = await this.db.batch([
      read("SELECT name, revision, generated_ms, generated_at, default_commit, push_id FROM snapshots WHERE name = ?"),
      read("SELECT * FROM project_spaces WHERE project = ?"),
      read("SELECT part, stage, commit_id, committed_at, digest, drawn_at, not_current FROM pictures WHERE project = ?"),
      read("SELECT * FROM discrepancies WHERE project = ? AND state = 'open'"),
      read("SELECT * FROM checkpoints WHERE project = ?"),
      this.db.prepare("SELECT COUNT(*) AS projects FROM snapshots"),
      read(CHECKPOINT_BASIS),
    ]);
    return {
      held: rows[0].results[0] || null, space: rows[1].results[0] || null,
      pictures: rows[2].results, discrepancies: rows[3].results, checkpoints: rows[4].results,
      projectCount: rows[5].results[0].projects,
      checkpointBasis: Object.values(rows[6].results[0])[0],
    };
  }

  async push(sent, now = new Date().toISOString(), retry = 0) {
    const state = await this.pushState(sent.name);
    checkCommit(sent, state.held);
    if (!state.held && state.projectCount >= 30) throw new Problem("too_many_projects", "remove a stored project before adding another", { limit: 30 });
    const phase2 = sent.data?.schema === "corthex-hub/0.2";
    const plan = phase2 ? await planPush(sent, state, now) : null;
    const token = crypto.randomUUID();
    const held = state.held;
    const revision = (held?.revision || 0) + 1;
    const bytes = new TextEncoder().encode(sent.body).byteLength;
    const gate = "EXISTS (SELECT 1 FROM snapshots WHERE name = ? AND push_id = ?)";
    const gated = (sql, ...params) => this.db.prepare(sql).bind(...params, sent.name, token);
    const first = this.db.prepare(`INSERT INTO snapshots
      (name, revision, generated_ms, generated_at, received_at, bytes, body, default_commit, push_id)
      SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
      WHERE ((? IS NULL AND NOT EXISTS (SELECT 1 FROM snapshots WHERE name = ?) AND (SELECT COUNT(*) FROM snapshots) < 30)
         OR EXISTS (SELECT 1 FROM snapshots WHERE name = ? AND revision = ? AND default_commit IS NOT DISTINCT FROM ? AND push_id IS NOT DISTINCT FROM ?))
        AND (${CHECKPOINT_BASIS})=?
      ON CONFLICT (name) DO UPDATE SET
        revision = excluded.revision, generated_ms = excluded.generated_ms, generated_at = excluded.generated_at,
        received_at = excluded.received_at, bytes = excluded.bytes, body = excluded.body,
        default_commit = excluded.default_commit, push_id = excluded.push_id
      WHERE snapshots.revision = ? AND snapshots.default_commit IS NOT DISTINCT FROM ? AND snapshots.push_id IS NOT DISTINCT FROM ?
        AND (${CHECKPOINT_BASIS})=?
      RETURNING revision`).bind(sent.name, revision, sent.generatedMs, sent.generatedAt, now, bytes, sent.body,
        sent.defaultCommit || null, token, held?.revision || null, sent.name, sent.name, held?.revision || null,
        held?.default_commit || null, held?.push_id || null, sent.name, state.checkpointBasis,
        held?.revision || null, held?.default_commit || null, held?.push_id || null, sent.name, state.checkpointBasis);
    const statements = [first];
    if (plan) {
      statements.push(gated(`INSERT INTO project_spaces (project, repo_url, created_at)
        SELECT ?, ?, ? WHERE ${gate}
        ON CONFLICT (project) DO UPDATE SET repo_url = excluded.repo_url
        WHERE project_spaces.repo_url IS NULL AND excluded.repo_url IS NOT NULL`, sent.name, plan.repository, now));
      const drawn = plan.pictures.filter((row) => row.source !== undefined).map((row) => ({ ...row, commit_id: row.commit, committed_at: row.time }));
      const marks = plan.pictures.filter((row) => row.source === undefined);
      statements.push(gated(`INSERT INTO pictures (project, part, stage, commit_id, committed_at, source, digest, drawn_at, not_current)
        SELECT ?, json_extract(value,'$.part'), json_extract(value,'$.stage'), json_extract(value,'$.commit_id'),
          json_extract(value,'$.committed_at'), json_extract(value,'$.source'), json_extract(value,'$.digest'),
          json_extract(value,'$.drawn_at'), NULL FROM json_each(?) WHERE ${gate}
        ON CONFLICT (project, part, stage) DO UPDATE SET commit_id=excluded.commit_id, committed_at=excluded.committed_at,
          source=excluded.source, digest=excluded.digest, drawn_at=excluded.drawn_at, not_current=NULL`, sent.name, JSON.stringify(drawn)));
      statements.push(gated(`UPDATE pictures AS p SET not_current=json_extract(j.value,'$.not_current')
        FROM json_each(?) AS j WHERE p.project=? AND p.part=json_extract(j.value,'$.part') AND p.stage=json_extract(j.value,'$.stage')
        AND p.not_current IS DISTINCT FROM json_extract(j.value,'$.not_current') AND ${gate}`, JSON.stringify(marks), sent.name));
      statements.push(gated(`UPDATE discrepancies SET state='resolved', waiting=0, resolved_commit=?, resolved_at=?
        WHERE project=? AND id IN (SELECT value FROM json_each(?)) AND ${gate}`, sent.defaultCommit, now, sent.name, JSON.stringify(plan.discrepancies.resolve)));
      const updates = plan.discrepancies.updates.map((row) => ({ ...row, reasons: JSON.stringify(row.reasons) }));
      statements.push(gated(`UPDATE discrepancies AS d SET reasons=json_extract(j.value,'$.reasons'), level=json_extract(j.value,'$.level'), waiting=json_extract(j.value,'$.waiting')
        FROM json_each(?) AS j WHERE d.project=? AND d.id=json_extract(j.value,'$.id') AND ${gate}`, JSON.stringify(updates), sent.name));
      const opened = plan.discrepancies.open.map((row) => ({ ...row, reasons: JSON.stringify(row.reasons) }));
      statements.push(gated(`INSERT INTO discrepancies (id, project, part, compares, term, item, reasons, level, state, waiting, opened_commit, opened_at, earlier)
        SELECT json_extract(j.value,'$.id'), ?, json_extract(j.value,'$.part'), json_extract(j.value,'$.compares'),
          json_extract(j.value,'$.term'), json_extract(j.value,'$.item'), json_extract(j.value,'$.reasons'), json_extract(j.value,'$.level'), 'open', 0, ?, ?,
          (SELECT d.id FROM discrepancies AS d WHERE d.project=? AND d.part=json_extract(j.value,'$.part')
            AND d.compares=json_extract(j.value,'$.compares') AND d.term=json_extract(j.value,'$.term') AND d.item=json_extract(j.value,'$.item')
            AND d.state='resolved' ORDER BY d.resolved_at DESC, d.id LIMIT 1)
        FROM json_each(?) AS j WHERE ${gate}`, sent.name, sent.defaultCommit, now, sent.name, JSON.stringify(opened)));
      statements.push(gated(`UPDATE checkpoints AS c SET recorded_commit=json_extract(j.value,'$.recorded_commit')
        FROM json_each(?) AS j WHERE c.project=? AND c.id=json_extract(j.value,'$.id') AND c.recorded_commit IS DISTINCT FROM json_extract(j.value,'$.recorded_commit') AND ${gate}`,
        JSON.stringify(plan.checkpoints), sent.name));
      const ended = [...plan.discrepancies.resolve, ...plan.checkpoints.filter((row) => row.recorded_commit).map((row) => row.id)];
      statements.push(gated(`DELETE FROM claims WHERE project=? AND entry IN (SELECT value FROM json_each(?)) AND ${gate}`, sent.name, JSON.stringify(ended)));
      const unopened = JSON.stringify(plan.unopened);
      statements.push(gated(`UPDATE project_spaces SET unopened=? WHERE project=? AND unopened<>? AND ${gate}`, unopened, sent.name, unopened));
      statements.push(this.db.prepare(`SELECT
        (SELECT COUNT(*) FROM comments WHERE project=? AND state='open' AND waits='agent') AS comments,
        (SELECT COUNT(*) FROM discrepancies WHERE project=? AND state='open') AS discrepancies,
        (SELECT COUNT(*) FROM edits WHERE project=? AND state NOT IN ('closed','dismissed')) AS reflections,
        (SELECT COUNT(*) FROM checkpoints WHERE project=? AND
          ((state='passed' AND recorded_commit IS NULL) OR (state='withdrawn' AND (pr_state='open' OR recorded_commit IS NOT NULL)))) AS checkpoints`).bind(sent.name, sent.name, sent.name, sent.name));
    }
    const results = await this.db.batch(statements);
    if (!results[0].results.length) {
      const latest = await this.pushState(sent.name);
      // A checkpoint may be withdrawn after planning but before this batch.
      // Replan against it when no other snapshot overtook the push. Never
      // acknowledge the old checkpoint state or hide its withdrawal warning.
      if (retry < 1 && latest.held?.push_id === held?.push_id && latest.held?.revision === held?.revision && latest.checkpointBasis !== state.checkpointBasis) return this.push(sent,now,retry+1);
      if (!latest.held && latest.projectCount >= 30) throw new Problem("too_many_projects", "remove a stored project before adding another", { limit: 30 });
      if (latest.held?.default_commit) throw new Problem("commit_not_replaced", "another push stored first; fetch the held commit and push again", { held_commit: latest.held.default_commit });
      if (latest.held) throw new Problem("older_snapshot", "another push stored first; build a fresh snapshot and push again", { stored_at: latest.held.generated_at });
      throw new Problem("internal", "the project changed during this push; try again");
    }
    return plan ? { ...plan.answer, todo: results[results.length - 1].results[0] } : { name: sent.name, revision };
  }

  async readContext(project, needsSpace = false) {
    await this.ensure();
    const [snapshots, spaces] = await this.db.batch([
      this.db.prepare("SELECT * FROM snapshots WHERE name=?").bind(project),
      this.db.prepare("SELECT * FROM project_spaces WHERE project=?").bind(project),
    ]);
    const held = snapshots.results[0];
    if (!held) throw new Problem("project_not_found", "no such project");
    const space = spaces.results[0] || null;
    if (needsSpace && !space) throw new Problem("space_not_found", "this project has no space; push a 0.2 snapshot first");
    return { held, snapshot: JSON.parse(held.body), space };
  }

  validPart(snapshot, part) {
    if (part && (!Array.isArray(snapshot.project.parts) || !snapshot.project.parts.includes(part))) throw new Problem("part_not_found", "no such part");
  }

  commentStatement(project, mode, part, stage, limit) {
    let where = "c.project=?";
    const params = [project];
    if (part !== undefined) { where += " AND c.part=?"; params.push(part); }
    if (stage !== undefined) { where += " AND c.stage=?"; params.push(stage); }
    where += mode === "todo" ? " AND c.state='open' AND c.waits='agent'" : " AND c.state='open'";
    return this.db.prepare(`SELECT c.*, COUNT(*) OVER() AS _total,
      (SELECT COUNT(*) FROM replies AS r WHERE r.comment=c.id) AS reply_count,
      (SELECT json_object('seq',r.seq,'author',r.author,'text',r.text,'settles',r.settles,'made_at',r.made_at)
       FROM replies AS r WHERE r.comment=c.id ORDER BY r.seq DESC LIMIT 1) AS last_reply_json,
      (SELECT json_group_array(id) FROM (SELECT id FROM proposals WHERE comment=c.id ORDER BY made_at DESC,id LIMIT 500)) AS proposal_ids_json
      FROM comments AS c WHERE ${where} ORDER BY c.last_at ${mode === "todo" ? "ASC" : "DESC"}, c.id LIMIT ?`).bind(...params, limit);
  }

  proposalStatement(project, part, stage) {
    let where = "p.project=? AND p.state='open'";
    const params = [project];
    if (part !== undefined) { where += " AND p.part=?"; params.push(part); }
    if (stage !== undefined) { where += " AND p.stage=?"; params.push(stage); }
    return this.db.prepare(`SELECT p.*,e.id AS edit FROM proposals AS p LEFT JOIN edits AS e ON e.proposal=p.id
      WHERE ${where} ORDER BY p.made_at,p.id LIMIT 500`).bind(...params);
  }

  editStatement(project, mode, part, stage, limit) {
    let where = "e.project=? AND e.state NOT IN ('closed','dismissed')";
    const params = [project];
    if (part !== undefined) { where += " AND e.part=?"; params.push(part); }
    if (stage !== undefined) { where += " AND e.stage=?"; params.push(stage); }
    return this.db.prepare(`SELECT e.*,COUNT(*) OVER() AS _total,
      json_object('id',p.id,'part',p.part,'stage',p.stage,'commit_id',p.commit_id,'items',p.items,'reason',p.reason,
       'change',p.change,'source_text',p.source_text,'comment',p.comment,'discrepancy',p.discrepancy,'state',p.state,
       'made_at',p.made_at,'closed_at',p.closed_at,'edit',e.id) AS proposal_json
      FROM edits AS e LEFT JOIN proposals AS p ON e.proposal=p.id WHERE ${where}
      ORDER BY ${mode === "todo" ? "CASE WHEN e.pull_request IS NULL THEN 0 ELSE 1 END," : ""} e.made_at,e.id LIMIT ?`).bind(...params, limit);
  }

  discrepancyStatement(project, part, stage, limit) {
    let where = "project=? AND state='open'";
    const params = [project];
    if (part !== undefined) { where += " AND part=?"; params.push(part); }
    if (stage === "05-erd") where += " AND compares='aggregate-table'";
    else if (stage === "07-sitemap") where += " AND compares='read-model-screen'";
    else if (stage && stage !== "01-domain") where += " AND 0";
    return this.db.prepare(`SELECT *,COUNT(*) OVER() AS _total FROM discrepancies WHERE ${where}
      ORDER BY CASE WHEN level='warn' THEN 0 ELSE 1 END, opened_at,id LIMIT ?`).bind(...params, limit);
  }

  async heldCommit(project) {
    const { held } = await this.readContext(project);
    return { project, revision: held.revision, default_commit: held.default_commit,
      generated_at: held.generated_at, received_at: held.received_at };
  }

  async readPicture(project, part, stage) {
    const { snapshot } = await this.readContext(project, true);
    this.validPart(snapshot, part);
    const rows = await this.db.batch([
      this.db.prepare("SELECT * FROM pictures WHERE project=? AND part=? AND stage=?").bind(project, part, stage),
      this.commentStatement(project, "picture", part, stage, 500),
      this.db.prepare("SELECT id,item,closed_as,last_at,COUNT(*) OVER() AS _total FROM comments WHERE project=? AND part=? AND stage=? AND state='closed' ORDER BY last_at DESC,id LIMIT 500").bind(project, part, stage),
      this.proposalStatement(project, part, stage), this.editStatement(project, "picture", part, stage, 500),
      this.discrepancyStatement(project, part, stage, 1000),
    ]);
    const picture = rows[0].results[0];
    if (!picture) {
      const omitted=(snapshot.left_out||[]).find((row)=>row.part===part&&row.stage===stage);
      throw new Problem("picture_not_found", "this part and stage have no picture yet", {why:omitted?.why||"not-drawn"});
    }
    const comments = rows[1].results, closed = rows[2].results;
    return { project, part, stage,
      picture: { commit: picture.commit_id, committed_at: picture.committed_at, drawn_at: picture.drawn_at, not_current: picture.not_current, source: JSON.parse(picture.source) },
      comments: { total: comments[0]?._total || 0, entries: comments.map((row) => E.commentListRow(row)) },
      closed_comments: { total: closed[0]?._total || 0, entries: closed.map(({ id,item,closed_as,last_at }) => ({ id,item,closed_as,last_at })) },
      proposals: rows[3].results.map((row) => E.proposal(row)), reflections: rows[4].results.map((row) => E.editListRow(row)),
      discrepancies: rows[5].results.map((row) => E.discrepancy(row)),
    };
  }

  async readOverview(project, part, stage) {
    const { snapshot, space } = await this.readContext(project);
    this.validPart(snapshot, part);
    const [comments, edits, discrepancies, checkpoints, pictures] = await this.db.batch([
      this.commentStatement(project,"overview",part,stage,50), this.editStatement(project,"overview",part,stage,50),
      this.discrepancyStatement(project,part,stage,50),
      this.db.prepare(`SELECT * FROM checkpoints WHERE project=? AND part=? AND stage=?
        AND ((state='passed' AND recorded_commit IS NULL) OR (state='withdrawn' AND recorded_commit IS NOT NULL))
        ORDER BY passed_at,id LIMIT 50`).bind(project,part,stage),
      this.db.prepare("SELECT stage,commit_id,not_current FROM pictures WHERE project=? AND part=? ORDER BY stage").bind(project,part),
    ]);
    const source = snapshot.stages?.[stage] || {};
    const notOpened = space ? JSON.parse(space.unopened) : {};
    const warnings = checkpoints.results.filter((row) => row.state==='withdrawn').map((row) => ({ rule:"checkpoint-withdrawn", checkpoint:row.id }));
    const checks = (snapshot.checks || []).filter((check) => check.stage===stage && (!check.part || check.part===part));
    for (const warning of warnings) checks.push({ rule:warning.rule,level:"warn",by:"server",stage,part,message:"A withdrawn checkpoint is named by the stored stage record",refs:[],args:{checkpoint:warning.checkpoint} });
    const envelope = (rows, mapper) => ({ total:rows[0]?._total || 0,entries:rows.map(mapper) });
    return { project,part,stage,record:E.stageRecord(snapshot,part,stage),
      source_state:["found","missing","none","no-checkout","skipped","invalid"].includes(source.source_state)?source.source_state:"none", read:Boolean(source.read),checks:checks.slice(0,2000),
      pictures:["01-domain","05-erd","07-sitemap"].includes(stage)?pictures.results.slice(0,3).map((row)=>({stage:row.stage,commit:row.commit_id,not_current:row.not_current})):[],
      comments:envelope(comments.results,(row)=>E.commentListRow(row)), reflections:envelope(edits.results,(row)=>E.editListRow(row)),
      discrepancies:envelope(discrepancies.results,(row)=>E.discrepancy(row)), checkpoints:checkpoints.results.map((row)=>E.checkpoint(row)), warnings,
      not_opened:Object.hasOwn(notOpened,part)?notOpened[part]:0 };
  }

  async readEntry(project, kind, id) {
    await this.readContext(project);
    if (kind === "comment") {
      const [comments,replies,decisions,proposals] = await this.db.batch([
        this.db.prepare("SELECT * FROM comments WHERE project=? AND id=?").bind(project,id),
        this.db.prepare("SELECT r.* FROM replies AS r JOIN comments AS c ON c.id=r.comment WHERE c.project=? AND c.id=? ORDER BY r.seq").bind(project,id),
        this.db.prepare("SELECT d.* FROM decisions AS d JOIN comments AS c ON c.id=d.comment WHERE c.project=? AND c.id=? ORDER BY d.seq").bind(project,id),
        this.db.prepare("SELECT p.*,e.id AS edit FROM proposals AS p LEFT JOIN edits AS e ON e.proposal=p.id WHERE p.project=? AND p.comment=? ORDER BY p.made_at DESC,p.id").bind(project,id),
      ]);
      const row=comments.results[0]; if(!row)throw new Problem("comment_not_found","no such comment");
      return {...E.comment(row),replies:replies.results.map(E.reply),decisions:decisions.results.map(E.decision),proposals:proposals.results.map((row)=>E.proposal(row))};
    }
    if (kind === "proposal") {
      const row=await this.db.prepare("SELECT p.*,e.id AS edit FROM proposals AS p LEFT JOIN edits AS e ON e.proposal=p.id WHERE p.project=? AND p.id=?").bind(project,id).first();
      if(!row)throw new Problem("proposal_not_found","no such proposal"); return E.proposal(row,true);
    }
    if (kind === "edit") {
      const row=await this.db.prepare(`SELECT e.*,json_object('id',p.id,'part',p.part,'stage',p.stage,'commit_id',p.commit_id,'items',p.items,'reason',p.reason,
        'change',p.change,'source_text',p.source_text,'comment',p.comment,'discrepancy',p.discrepancy,'state',p.state,'made_at',p.made_at,'closed_at',p.closed_at,'edit',e.id) AS proposal_json
        FROM edits AS e LEFT JOIN proposals AS p ON e.proposal=p.id WHERE e.project=? AND e.id=?`).bind(project,id).first();
      if(!row)throw new Problem("edit_not_found","no such reflection"); return E.editListRow(row,true);
    }
    if(kind === "checkpoint") {
      const row=await this.db.prepare("SELECT * FROM checkpoints WHERE project=? AND id=?").bind(project,id).first();
      if(!row)throw new Problem("checkpoint_not_found","no such checkpoint"); return E.checkpoint(row);
    }
    throw new Error("unimplemented entry kind");
  }

  async removalDryRun(project) {
    const {space}=await this.readContext(project);
    const tables=["pictures","discrepancies","comments","proposals","edits","checkpoints"];
    const statements=tables.map((table)=>this.db.prepare(`SELECT COUNT(*) AS n FROM ${table} WHERE project=?`).bind(project));
    statements.push(this.db.prepare("SELECT COUNT(*) AS n FROM replies AS r JOIN comments AS c ON c.id=r.comment WHERE c.project=?").bind(project));
    statements.push(this.db.prepare("SELECT COUNT(*) AS n FROM decisions AS d JOIN comments AS c ON c.id=d.comment WHERE c.project=?").bind(project));
    const open=[ ["comments","state='open'"],["proposals","state='open'"],["edits","state NOT IN ('closed','dismissed')"],["checkpoints","state='passed' AND recorded_commit IS NULL"] ];
    for(const [table,where] of open)statements.push(this.db.prepare(`SELECT id,COUNT(*) OVER() AS _total FROM ${table} WHERE project=? AND ${where} ORDER BY id LIMIT 20`).bind(project));
    const rows=await this.db.batch(statements);
    const deletes={snapshot:true,space:Boolean(space)};
    tables.forEach((table,i)=>{deletes[table]=rows[i].results[0].n;});
    deletes.replies=rows[6].results[0].n;deletes.decisions=rows[7].results[0].n;
    const lists={}; ["comments","proposals","reflections","checkpoints"].forEach((name,i)=>{const entries=rows[i+8].results;lists[name]={total:entries[0]?._total||0,ids:entries.map((row)=>row.id)};});
    return {project,deletes,open:lists};
  }

  // Read only the target rows and counters needed by this transition. The
  // exact same SQL is evaluated inside the receipt INSERT, so a concurrent
  // push, claim or write invalidates the plan before any business row changes.
  entryBasis(project, id, body, write, cutoff) {
    const sql = `WITH q AS (SELECT ? AS project,? AS target,? AS body_comment,? AS body_discrepancy,
      ? AS part,? AS stage,? AS write,? AS cutoff),
      t AS (SELECT q.*,COALESCE(body_comment,(SELECT comment FROM proposals WHERE id=q.target AND project=q.project),target) AS thread,
        COALESCE(body_discrepancy,(SELECT discrepancy FROM proposals WHERE id=q.target AND project=q.project),target) AS diff FROM q)
      SELECT json_object(
        'held',(SELECT json_object('revision',revision,'default_commit',default_commit) FROM snapshots WHERE name=t.project),
        'parts',json(COALESCE((SELECT json_extract(body,'$.project.parts') FROM snapshots WHERE name=t.project),'[]')),
        'leftOut',json(COALESCE((SELECT json_extract(body,'$.left_out') FROM snapshots WHERE name=t.project),'[]')),
        'space',(SELECT json_object('text_bytes',text_bytes,'repo_url',repo_url) FROM project_spaces WHERE project=t.project),
        'picture',(SELECT json_object('commit_id',commit_id,'source',source) FROM pictures WHERE project=t.project AND part=t.part AND stage=t.stage),
        'comment',${rowJSON("comments", "project=t.project AND id=t.thread")},
        'proposal',${rowJSON("proposals", "project=t.project AND id=t.target")},
        'edit',${rowJSON("edits", "project=t.project AND id=t.target")},
        'checkpoint',${rowJSON("checkpoints", "project=t.project AND id=t.target")},
        'discrepancy',${rowJSON("discrepancies", "project=t.project AND id=t.diff")},
        'counts',json_object('comments',(SELECT COUNT(*) FROM comments WHERE project=t.project),
          'proposals',(SELECT COUNT(*) FROM proposals WHERE project=t.project AND state='open'),
          'edits',(SELECT COUNT(*) FROM edits WHERE project=t.project AND state NOT IN ('closed','dismissed'))),
        'replyCount',(SELECT COUNT(*) FROM replies WHERE comment=t.thread),
        'decisionCount',(SELECT COUNT(*) FROM decisions WHERE comment=t.thread),
        'lastReply',(SELECT json_object('author',author,'made_at',made_at) FROM replies WHERE comment=t.thread ORDER BY seq DESC LIMIT 1),
        'threadProposals',json((SELECT json_group_array(json_object('id',id,'state',state,'made_at',made_at,'closed_at',closed_at)) FROM proposals WHERE project=t.project AND comment=t.thread)),
        'claims',json((SELECT json_group_array(json_object('entry',entry,'session',session,'claimed_at',claimed_at,'ends_at',ends_at)) FROM claims WHERE project=t.project AND entry IN(t.target,t.thread,t.diff))),
        'prior',(SELECT json_object('request',request,'result',result) FROM writes WHERE project=t.project AND id=t.write AND received_at>t.cutoff)
      ) AS basis FROM t`;
    return { sql, params: [project,id || null,body.comment || null,body.discrepancy || null,body.part ?? null,body.stage || null,write || null,cutoff] };
  }

  async writeEntry(name, project, id, body, { kind, session = null, write, now = new Date().toISOString() }) {
    checkWriteBody(name, body, kind);
    await this.ensure();
    const cutoff = new Date(Date.parse(now)-7*86400000).toISOString();
    const basisQuery = this.entryBasis(project,id,body,write,cutoff);
    for (let attempt=0; attempt<8; attempt++) {
      const basis = await this.db.prepare(basisQuery.sql).bind(...basisQuery.params).first("basis");
      const state = JSON.parse(basis);
      if (state.prior) {
        if (state.prior.request!==name) throw new Problem("write_id_reused","this ID was used for another request");
        const { status,body: answer }=JSON.parse(state.prior.result);
        return { status,body:answer };
      }
      const plan=planEntryWrite(name,body,state,{project,kind,session,now});
      const nonce=crypto.randomUUID();
      const result=JSON.stringify({status:plan.status,body:plan.body,nonce});
      const gate="EXISTS(SELECT 1 FROM writes WHERE project=? AND id=? AND json_extract(result,'$.nonce')=?)";
      const guard=[project,write,nonce];
      const statements=[
        this.db.prepare("DELETE FROM writes WHERE project=? AND received_at<=?").bind(project,cutoff),
        this.db.prepare(`INSERT OR IGNORE INTO writes(project,id,request,result,received_at)
          SELECT ?,?,?,?,? WHERE (${basisQuery.sql})=?`).bind(project,write,name,result,now,...basisQuery.params,basis),
      ];
      for(const change of plan.changes) {
        const columns=ENTRY_COLUMNS[change.table];
        if(!columns)throw new Error("unknown transition table");
        const keys=change.table==="replies"||change.table==="decisions"?["comment","seq"]:["id","project"];
        const fields=columns.filter((column)=>Object.hasOwn(change.row,column));
        if(change.fresh)statements.push(this.db.prepare(`INSERT INTO ${change.table}(${fields.join(",")})
          SELECT ${fields.map(()=>"?").join(",")} WHERE ${gate}`).bind(...fields.map((key)=>change.row[key]),...guard));
        else statements.push(this.db.prepare(`UPDATE ${change.table} SET ${fields.filter((key)=>!keys.includes(key)).map((key)=>key+"=?").join(",")}
          WHERE ${keys.map((key)=>key+"=?").join(" AND ")} AND ${gate}`)
          .bind(...fields.filter((key)=>!keys.includes(key)).map((key)=>change.row[key]),...keys.map((key)=>change.row[key]),...guard));
      }
      if(plan.textBytes)statements.push(this.db.prepare(`UPDATE project_spaces SET text_bytes=text_bytes+? WHERE project=? AND ${gate}`).bind(plan.textBytes,project,...guard));
      if(plan.on && kind==="agent")statements.push(this.db.prepare(`UPDATE claims SET ends_at=? WHERE project=? AND entry=? AND session=? AND ${gate}`)
        .bind(new Date(Date.parse(now)+3600000).toISOString(),project,plan.on,session,...guard));
      statements.push(this.db.prepare(`DELETE FROM claims WHERE project=? AND (ends_at<=? OR NOT (${activeEntry})) AND ${gate}`).bind(project,now,...guard));
      statements.push(this.db.prepare("SELECT request,result FROM writes WHERE project=? AND id=?").bind(project,write));
      const results=await this.db.batch(statements);
      const receipt=results[results.length-1].results[0];
      if(!receipt)continue; // another write changed the basis; plan afresh
      if(receipt.request!==name)throw new Problem("write_id_reused","this ID was used for another request");
      const {status,body:answer}=JSON.parse(receipt.result);
      return {status,body:answer};
    }
    throw new Error("the entry kept changing during this write");
  }

  async claimEntry(project,id,session,release=false,now=new Date().toISOString()) {
    await this.ensure();
    const query=this.entryBasis(project,id,{},null,now);
    for(let attempt=0;attempt<8;attempt++) {
      const basis=await this.db.prepare(query.sql).bind(...query.params).first("basis");
      const state=JSON.parse(basis);
      if(!state.held)throw new Problem("project_not_found","no such project");
      if(!state.space)throw new Problem("space_not_found","this project has no space");
      const type={nc_:"comment",nd_:"discrepancy",ne_:"edit",nk_:"checkpoint"}[id.slice(0,3)];
      const row=state[type];
      if(!row)throw new Problem("entry_not_found","no such entry");
      const held=state.claims.find((claim)=>claim.entry===id && claim.ends_at>now);
      if(held && held.session!==session)throw new Problem("claimed","another session holds this entry",{ends_at:held.ends_at});
      if(release) {
        const result=await this.db.prepare(`DELETE FROM claims WHERE project=? AND entry=? AND session=? AND ends_at>? AND (${query.sql})=? RETURNING entry`)
          .bind(project,id,session,now,...query.params,basis).all();
        if(result.results.length)return {entry:id,released:true};
        // A missing own claim is an idempotent release. If it changed under
        // us, reread before returning or refusing another session's claim.
        if(!held)return {entry:id,released:false};
      } else {
        const disposition=entryDisposition(row,type);
        if(disposition.held)throw new Problem("pull_request_reported","a pull request holds this entry",{pull_request:disposition.held});
        if(disposition.closed)throw new Problem("entry_closed","this entry is closed");
        const result=await this.db.prepare(`INSERT INTO claims(entry,project,session,claimed_at,ends_at)
          SELECT ?,?,?,?,? WHERE (${query.sql})=? ON CONFLICT(entry) DO UPDATE SET
          session=excluded.session,claimed_at=excluded.claimed_at,ends_at=excluded.ends_at RETURNING *`)
          .bind(id,project,session,held?.claimed_at||now,new Date(Date.parse(now)+3600000).toISOString(),...query.params,basis).all();
        if(result.results.length)return E.claim(result.results[0]);
      }
    }
    throw new Error("the claim kept changing");
  }

  async readTodo(project,session=null,now=new Date().toISOString()) {
    const {held}=await this.readContext(project,true);
    const [comments,discrepancies,edits,checkpoints,claims,counts]=await this.db.batch([
      this.commentStatement(project,"todo",undefined,undefined,50),this.discrepancyStatement(project,undefined,undefined,50),this.editStatement(project,"todo",undefined,undefined,50),
      this.db.prepare(`SELECT *,COUNT(*) OVER() AS _total FROM checkpoints WHERE project=? AND
        ((state='passed' AND recorded_commit IS NULL) OR (state='withdrawn' AND (recorded_commit IS NOT NULL OR pr_state='open')))
        ORDER BY CASE WHEN state='passed' THEN 0 ELSE 1 END,passed_at,id LIMIT 50`).bind(project),
      this.db.prepare(`SELECT * FROM claims WHERE project=? AND ends_at>? AND (${activeEntry})`).bind(project,now),
      this.db.prepare(`SELECT (SELECT COUNT(*) FROM comments WHERE project=? AND state='open' AND waits='user') AS waiting,
        (SELECT COUNT(*) FROM claims WHERE project=? AND ends_at>? AND session IS NOT ? AND (${activeEntry})
        AND (EXISTS(SELECT 1 FROM comments WHERE id=entry AND waits='agent') OR substr(entry,1,3)<>'nc_')) AS taken`).bind(project,project,now,session),
    ]);
    const rows=claims.results;
    const wrap=(result,mapper)=>({total:result.results[0]?._total||0,entries:result.results.map(mapper)});
    return {project,default_commit:held.default_commit,session,
      comments:wrap(comments,(row)=>E.commentListRow(row,rows,session,now)),
      discrepancies:wrap(discrepancies,(row)=>E.withClaim(E.discrepancy(row),rows,session,now)),
      reflections:wrap(edits,(row)=>E.withClaim(E.editListRow(row),rows,session,now)),
      checkpoints:wrap(checkpoints,(row)=>E.withClaim({...E.checkpoint(row),why:E.listedCheckpoint(row)},rows,session,now)),
      waiting_for_user:counts.results[0].waiting,taken:counts.results[0].taken};
  }

  async readSpaces() {
    await this.ensure();
    const [spaces,pictures,counts,checkpoints,warnings]=await this.db.batch([
      this.db.prepare("SELECT project,unopened FROM project_spaces ORDER BY project"),
      this.db.prepare("SELECT project,part,stage,commit_id,committed_at,not_current FROM pictures ORDER BY project,part,stage"),
      this.db.prepare(`SELECT project,'comments' AS kind,COUNT(*) AS n FROM comments WHERE state='open' GROUP BY project
        UNION ALL SELECT project,'proposals',COUNT(*) FROM proposals WHERE state='open' GROUP BY project
        UNION ALL SELECT project,'discrepancies',COUNT(*) FROM discrepancies WHERE state='open' GROUP BY project`),
      this.db.prepare(`SELECT project,id,part,stage,passed_at,COUNT(*) OVER(PARTITION BY project) AS _total,
        ROW_NUMBER() OVER(PARTITION BY project ORDER BY passed_at,id) AS place FROM checkpoints WHERE state='passed' AND recorded_commit IS NULL`),
      this.db.prepare("SELECT project,id,part,stage FROM checkpoints WHERE state='withdrawn' AND recorded_commit IS NOT NULL ORDER BY passed_at,id"),
    ]);
    const result=Object.fromEntries(spaces.results.map((row)=>[row.project,{pictures:[],open:{comments:0,proposals:0,discrepancies:0},checkpoints:{total:0,entries:[]},warnings:[],not_opened:JSON.parse(row.unopened)}]));
    for(const row of pictures.results)result[row.project].pictures.push({part:row.part,stage:row.stage,commit:row.commit_id,committed_at:row.committed_at,not_current:row.not_current});
    for(const row of counts.results)result[row.project].open[row.kind]=row.n;
    for(const row of checkpoints.results) {
      result[row.project].checkpoints.total=row._total;
      if(row.place<=100)result[row.project].checkpoints.entries.push({id:row.id,part:row.part,stage:row.stage,passed_at:row.passed_at});
    }
    for(const row of warnings.results)if(result[row.project].warnings.length<100)result[row.project].warnings.push({part:row.part,stage:row.stage,rule:"checkpoint-withdrawn",checkpoint:row.id});
    return result;
  }

}
