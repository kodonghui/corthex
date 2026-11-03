import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { Store } from "../src/store.js";
import { fakeD1 } from "./fake-d1.js";
import { readSnapshot02 } from "../src/snapshot02.js";

const NOW = "2026-11-03T12:00:00.000Z";
const fixture = () => JSON.parse(readFileSync(new URL("./snapshot-02-example.json", import.meta.url)));
const parse = (data) => readSnapshot02(data, Date.parse(NOW));
const context = () => { const db = new DatabaseSync(":memory:"); const binding = fakeD1(db); return { db, binding, store: new Store(binding) }; };

test("a 0.2 push creates the space and source once; an identical repeat writes only its snapshot", async () => {
  const { db, store } = context();
  const data = fixture(); data.future = { text: "한글 😀" };
  const sent = parse(data);
  const first = await store.push(sent, NOW);
  assert.equal(first.revision, 1);
  assert.equal(first.pictures.drawn.length, 1);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM project_spaces").get().n, 1);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM pictures").get().n, 1);
  assert.equal(Object.hasOwn(JSON.parse(await store.body(sent.name)), "pictures"), false);
  assert.deepEqual(JSON.parse(await store.body(sent.name)).future, data.future);
  const before = db.prepare("SELECT total_changes() AS n").get().n;
  const second = await store.push(sent, NOW);
  assert.equal(second.revision, 2);
  assert.equal(second.pictures.unchanged, 1);
  assert.equal(db.prepare("SELECT total_changes() AS n").get().n - before, 1);
});

test("commit and address refusals preserve every row", async () => {
  const { db, store } = context(); const data = fixture();
  await store.push(parse(data), NOW);
  const before = db.prepare("SELECT total_changes() AS n").get().n;
  data.repos["."].default.commit = "b".repeat(40); data.records.commit = "b".repeat(40); data.pictures[0].commit = "b".repeat(40);
  await assert.rejects(store.push(parse(data), NOW), (error) => error.code === "commit_not_replaced");
  data.replaces = fixture().repos["."].default.commit;
  data.repos["."].url = "https://example.com/other/repo";
  await assert.rejects(store.push(parse(data), NOW), (error) => error.code === "repository_mismatch");
  assert.equal(db.prepare("SELECT total_changes() AS n").get().n, before);
});

test("a matching replaces cannot clear a held default commit", async () => {
  const { db, store } = context(); const data = fixture();
  await store.push(parse(data), NOW);
  const before = db.prepare("SELECT total_changes() AS n").get().n;
  const held = data.repos["."].default.commit;
  data.replaces = held;
  delete data.repos["."].default;
  data.records = { from: "status-file" };
  data.pictures = [];
  await assert.rejects(store.push(parse(data), NOW), (error) => error.code === "commit_not_replaced" && error.fields.held_commit === held);
  assert.equal(db.prepare("SELECT total_changes() AS n").get().n, before);
  assert.equal(db.prepare("SELECT default_commit FROM snapshots").get().default_commit, held);
  assert.equal(db.prepare("SELECT not_current FROM pictures").get().not_current, null);
});

test("the write batch rolls back its snapshot if a picture statement fails", async () => {
  const { db, binding, store } = context(); await store.ensure();
  const faulty = { prepare: binding.prepare, batch(statements) {
    if (statements[0].sql.startsWith("INSERT INTO snapshots")) {
      return binding.batch([...statements.slice(0, 2), binding.prepare("INSERT INTO table_that_does_not_exist VALUES (1)"), ...statements.slice(2)]);
    }
    return binding.batch(statements);
  } };
  const failing = new Store(faulty); await failing.ensure();
  await assert.rejects(failing.push(parse(fixture()), NOW));
  for (const table of ["snapshots", "project_spaces", "pictures"]) assert.equal(db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n, 0);
});

test("two interleaved pushes that read one revision cannot both change any row", async () => {
  const { db, binding, store } = context(); const data = fixture();
  await store.push(parse(data), NOW);
  let readers = 0; let release;
  const barrier = new Promise((resolve) => { release = resolve; });
  let race = true;
  const shared = { prepare: binding.prepare, async batch(statements) {
    const result = await binding.batch(statements);
    if (race && statements[0].sql.startsWith("SELECT name, revision, generated_ms")) {
      if (++readers === 2) { race = false; release(); }
      await barrier;
    }
    return result;
  } };
  const a = new Store(shared); const b = new Store(shared); await a.ensure();
  const left = structuredClone(data), right = structuredClone(data);
  for (const [entry, commit] of [[left, "a".repeat(40)], [right, "b".repeat(40)]]) {
    entry.replaces = data.repos["."].default.commit;
    entry.repos["."].default.commit = commit; entry.records.commit = commit; entry.pictures[0].commit = commit;
    entry.pictures[0].source.tables[0].name = commit[0] + "_claims";
  }
  const before = db.prepare("SELECT total_changes() AS n").get().n;
  const results = await Promise.allSettled([a.push(parse(left), NOW), b.push(parse(right), NOW)]);
  assert.equal(results.filter((entry) => entry.status === "fulfilled").length, 1);
  assert.equal(results.find((entry) => entry.status === "rejected").reason.code, "commit_not_replaced");
  const held = db.prepare("SELECT revision, default_commit FROM snapshots").get();
  assert.equal(held.revision, 2);
  assert.equal(db.prepare("SELECT commit_id FROM pictures").get().commit_id, held.default_commit);
  assert.equal(db.prepare("SELECT total_changes() AS n").get().n - before, 2);
});
