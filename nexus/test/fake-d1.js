// The part of the D1 binding the store uses, over an in-memory SQLite
// database from Node (22.13 or later). For tests only.

import { DatabaseSync } from "node:sqlite";

class Statement {
  constructor(db, sql, params = []) {
    this.db = db;
    this.sql = sql;
    this.params = params;
  }

  bind(...params) {
    return new Statement(this.db, this.sql, params);
  }

  async first(column) {
    const row = this.db.prepare(this.sql).get(...this.params);
    if (row === undefined) return null;
    return column === undefined ? { ...row } : row[column];
  }

  async all() {
    const results = this.db.prepare(this.sql).all(...this.params).map((row) => ({ ...row }));
    return { success: true, results, meta: {} };
  }

  async run() {
    const info = this.db.prepare(this.sql).run(...this.params);
    return { success: true, results: [], meta: { changes: Number(info.changes) } };
  }
}

export function fakeD1(db = new DatabaseSync(":memory:")) {
  db.exec("PRAGMA foreign_keys = ON");
  return {
    prepare: (sql) => new Statement(db, sql),
    async batch(statements) {
      db.exec("BEGIN IMMEDIATE");
      try {
        const results = [];
        for (const statement of statements) {
          const before = Number(db.prepare("SELECT total_changes() AS n").get().n);
          const prepared = db.prepare(statement.sql);
          const rows = prepared.columns().length
            ? prepared.all(...statement.params).map((row) => ({ ...row }))
            : (prepared.run(...statement.params), []);
          const after = Number(db.prepare("SELECT total_changes() AS n").get().n);
          results.push({ success: true, results: rows, meta: { changes: after - before } });
        }
        db.exec("COMMIT");
        return results;
      } catch (error) {
        db.exec("ROLLBACK");
        throw error;
      }
    },
  };
}
