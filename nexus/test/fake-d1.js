// The part of the D1 binding the store uses, over an in-memory SQLite
// database from Node (22.5 or later). For tests only.

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

export function fakeD1() {
  const db = new DatabaseSync(":memory:");
  return { prepare: (sql) => new Statement(db, sql) };
}
