// TASK-202/203: compare real SQLite metadata, not a second copy of the schema.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { DatabaseSync } from "node:sqlite";

import { MIGRATIONS, Store } from "../src/store.js";
import { fakeD1 } from "./fake-d1.js";

const schema = readFileSync(new URL("../../docs/05-erd/nexus.sql", import.meta.url), "utf8");
const plain = (rows) => rows.map((row) => ({ ...row }));
const quoted = (name) => '"' + name.replaceAll('"', '""') + '"';

function checks(sql) {
  const found = [];
  const pattern = /\bCHECK\s*\(/gi;
  let match;
  while ((match = pattern.exec(sql))) {
    let depth = 1;
    let end = pattern.lastIndex;
    let quote = "";
    for (; end < sql.length && depth; end++) {
      const ch = sql[end];
      if (quote) {
        if (ch === quote && sql[end + 1] === quote) end++;
        else if (ch === quote) quote = "";
      } else if (ch === "'" || ch === '"') quote = ch;
      else if (ch === "(") depth++;
      else if (ch === ")") depth--;
    }
    assert.equal(depth, 0, "balanced CHECK expression");
    found.push(sql.slice(pattern.lastIndex, end - 1).replace(/\s+/g, " ").trim());
    pattern.lastIndex = end;
  }
  return found.sort();
}

function describe(db) {
  return plain(db.prepare("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all())
    .map(({ name, sql }) => ({
      name,
      columns: plain(db.prepare(`PRAGMA table_info(${quoted(name)})`).all()),
      foreignKeys: plain(db.prepare(`PRAGMA foreign_key_list(${quoted(name)})`).all()),
      indexes: plain(db.prepare(`PRAGMA index_list(${quoted(name)})`).all())
        .map(({ name: index, unique, origin, partial }) => ({
          name: index, unique, origin, partial,
          columns: plain(db.prepare(`PRAGMA index_info(${quoted(index)})`).all()),
          where: (db.prepare("SELECT sql FROM sqlite_master WHERE name=?").get(index)?.sql || "")
            .match(/\bWHERE\s+(.+)$/i)?.[1] || "",
        })).sort((a, b) => a.name.localeCompare(b.name)),
      checks: checks(sql),
    }));
}

test("TASK-202/203: migration output has exactly the stage-05 tables, columns, keys, indexes and constraints", async () => {
  const expected = new DatabaseSync(":memory:");
  expected.exec(schema);
  const actual = new DatabaseSync(":memory:");
  await new Store(fakeD1(actual)).ensure();
  assert.deepEqual(describe(actual), describe(expected));
  assert.deepEqual(plain(actual.prepare("SELECT version FROM migrations ORDER BY version").all()), [{ version: 1 }, { version: 2 }]);
  assert.equal(actual.prepare("SELECT COUNT(*) AS n FROM migrations WHERE applied_at IS NOT NULL").get().n, 2);
  actual.close(); expected.close();
});

test("TASK-202/203: a phase-1 snapshot survives migration byte for byte with its revision", async () => {
  const raw = new DatabaseSync(":memory:");
  raw.exec(MIGRATIONS[0].statements[0]);
  const body = '{"schema":"corthex-hub/0.1","title":"그림 \\u003cscript>"}\n';
  const values = ["synthetic", 7, 1762135200123, "2026-11-03T10:00:00+09:00", "2026-11-03T01:00:00Z", Buffer.byteLength(body), body];
  raw.prepare("INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?)").run(...values);
  const store = new Store(fakeD1(raw));
  await store.ensure();
  assert.deepEqual(Object.values({ ...raw.prepare("SELECT name, revision, generated_ms, generated_at, received_at, bytes, body FROM snapshots").get() }), values);
  assert.deepEqual({ ...raw.prepare("SELECT default_commit, push_id FROM snapshots").get() }, { default_commit: null, push_id: null });
  assert.equal(await store.body("synthetic"), body);
  const timestamps = plain(raw.prepare("SELECT * FROM migrations ORDER BY version").all());
  await new Store(fakeD1(raw)).ensure();
  assert.deepEqual(plain(raw.prepare("SELECT * FROM migrations ORDER BY version").all()), timestamps);
  raw.close();
});

test("TASK-203: a failed schema-2 transaction rolls back and a later attempt retries it", async () => {
  const raw = new DatabaseSync(":memory:");
  const binding = fakeD1(raw);
  const batch = binding.batch;
  let fail = true;
  binding.batch = (statements) => {
    if (fail && statements.some((s) => s.sql.startsWith("ALTER TABLE"))) {
      fail = false;
      // Fail inside the transaction, after both ALTERs have run.
      return batch([...statements.slice(0, 2), binding.prepare("INSERT INTO table_that_does_not_exist VALUES (1)")]);
    }
    return batch(statements);
  };
  const store = new Store(binding);
  await assert.rejects(store.ensure());
  assert.equal(raw.prepare("PRAGMA table_info(snapshots)").all().length, 7);
  assert.deepEqual(plain(raw.prepare("SELECT version FROM migrations").all()), [{ version: 1 }]);
  await store.ensure();
  assert.equal(raw.prepare("PRAGMA table_info(snapshots)").all().length, 9);
  assert.equal(raw.prepare("SELECT COUNT(*) AS n FROM migrations").get().n, 2);
  raw.close();
});

test("TASK-202/203: two Worker isolates applying the same migrations converge without partial schema", async () => {
  const raw = new DatabaseSync(":memory:");
  let arrivals = 0;
  let release;
  const barrier = new Promise((resolve) => { release = resolve; });
  const bindings = [fakeD1(raw), fakeD1(raw)];
  for (const binding of bindings) {
    const batch = binding.batch;
    binding.batch = async (statements) => {
      if (statements.some((s) => s.sql === MIGRATIONS[0].statements[0])) {
        if (++arrivals === 2) release();
        await barrier;
      }
      return batch(statements);
    };
  }
  await Promise.all(bindings.map((binding) => new Store(binding).ensure()));
  assert.equal(arrivals, 2);
  assert.deepEqual(plain(raw.prepare("SELECT version FROM migrations ORDER BY version").all()), [{ version: 1 }, { version: 2 }]);
  const expected = new DatabaseSync(":memory:"); expected.exec(schema);
  assert.deepEqual(describe(raw), describe(expected));
  raw.close(); expected.close();
});
