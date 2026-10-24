// Everything that touches the database is in this file. The SQL is the part
// SQLite (D1) and Postgres share, apart from the `?` placeholders, so moving
// to another database changes this file only.

const SCHEMA = `CREATE TABLE IF NOT EXISTS snapshots (
  name TEXT PRIMARY KEY,
  revision INTEGER NOT NULL,
  generated_ms INTEGER NOT NULL,
  generated_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  body TEXT NOT NULL
)`;

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

  // Creates the table on first use, once per database binding.
  async ensure() {
    let pending = ready.get(this.db);
    if (!pending) {
      pending = this.db.prepare(SCHEMA).run();
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
