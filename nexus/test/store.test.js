// Checks the database statements on their own, over the in-memory stand-in.

import assert from "node:assert/strict";
import { test } from "node:test";

import { Store } from "../src/store.js";
import { fakeD1 } from "./fake-d1.js";

test("adds a project only below the limit and keeps updating stored ones", async () => {
  const db = new Store(fakeD1());
  const put = (name, generatedMs) => db.put(name, generatedMs, "2026-01-12T10:00:00+09:00", "2026-01-12T01:00:00.000Z", "{}", 2, 2);
  assert.equal(await put("one", 1), 1);
  assert.equal(await put("two", 1), 1);
  assert.equal(await put("three", 1), null);
  assert.equal(await put("one", 2), 2);
  assert.equal(await put("two", 0), null);
  assert.deepEqual((await db.list()).map((row) => [row.name, row.revision]), [["one", 2], ["two", 1]]);
});
