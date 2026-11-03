import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { readSnapshot02 } from "../src/snapshot02.js";
import { inputFailure } from "../src/input-check.js";

const NOW = Date.parse("2026-11-03T12:00:00Z");
const example = JSON.parse(readFileSync(new URL("./snapshot-02-example.json", import.meta.url)));
const fixture = () => structuredClone(example);
const bad = (change, field) => {
  const data = fixture(); change(data);
  assert.throws(() => readSnapshot02(data, NOW), (error) => error.code === "invalid_snapshot" && error.status === 400 && (!field || error.fields.field.includes(field)));
};
const picture = (stage, source) => ({ part: "nexus", stage, commit: example.repos["."].default.commit, time: example.repos["."].default.time, source });

test("the frozen complete 0.2 example validates and separates pictures without losing unknown fields", () => {
  const data = fixture();
  data.future = { nested: [1, false, "한글 😀"] };
  const before = JSON.stringify(data);
  const parsed = readSnapshot02(data, NOW);
  assert.equal(JSON.stringify(data), before);
  const stored = JSON.parse(parsed.body);
  assert.equal(stored.schema, "corthex-hub/0.2");
  assert.deepEqual(stored.future, data.future);
  assert.equal(Object.hasOwn(stored, "pictures"), false);
  assert.deepEqual(parsed.pictures, data.pictures);
  assert.equal(parsed.defaultCommit, data.repos["."].default.commit);
  assert.equal(parsed.repository, data.repos["."].url);
});

test("0.2 requires its own fields and strict known field types", () => {
  for (const key of ["records", "ask_before", "pictures", "project", "items", "checks", "stages", "summary"]) bad((d) => { delete d[key]; });
  bad((d) => { d.ask_before.extra = true; });
  bad((d) => { d.ask_before.entries = [""]; });
  bad((d) => { d.records.from = "device"; });
  bad((d) => { d.project.parts = ["a", "a"]; });
  bad((d) => { d.project.parts = []; });
  bad((d) => { d.project.parts = ["Bad-part"]; });
  bad((d) => { d.items[0].title = false; });
  bad((d) => { d.checks = [{ rule: "test", level: "fatal", message: "test" }]; });
  bad((d) => { d.stages["05-erd"].parts.nexus.state = "finished"; });
});

test("times require real dates and explicit zones; the ten-minute boundary is exact", () => {
  for (const date of ["2026-11-03T12:00:00", "2026-02-30T12:00:00Z", "2026-13-01T12:00:00Z", "2026-11-03T24:00:00Z"]) bad((d) => { d.generated_at = date; });
  const data = fixture();
  data.generated_at = new Date(NOW + 600000).toISOString();
  assert.equal(readSnapshot02(data, NOW).generatedMs, NOW + 600000);
  data.generated_at = new Date(NOW + 600001).toISOString();
  assert.throws(() => readSnapshot02(data, NOW), (error) => error.code === "clock_ahead");
  assert.equal(inputFailure("2000-02-29", "Date"), null);
  assert.ok(inputFailure("1900-02-29", "Date"));
});

test("snapshot list caps, parts and checkpoint records are enforced without trimming input", () => {
  bad((d) => { d.items = Array.from({ length: 3001 }, () => d.items[0]); }, "items");
  bad((d) => { d.checks = Array.from({ length: 10001 }, () => ({ rule: "test", level: "warn", message: "test" })); }, "checks");
  bad((d) => { d.project.parts = Array.from({ length: 51 }, (_, i) => `part-${i}`); }, "parts");
  bad((d) => { d.ask_before.entries = Array(31).fill("test"); });
  bad((d) => { d.stages["05-erd"].parts.memory.checkpoints[0].where = "http://example.com"; });
  bad((d) => { d.stages["05-erd"].parts.memory.checkpoints[0].date = "2026-02-30"; });
});

test("a repository checkpoint retains approval without an absent or unsafe link", () => {
  const data = fixture();
  const checkpoint = data.stages["05-erd"].parts.memory.checkpoints[0];
  delete checkpoint.where;
  const parsed = readSnapshot02(data, NOW);
  const stored = JSON.parse(parsed.body).stages["05-erd"].parts.memory.checkpoints[0];
  assert.equal(stored.approved, checkpoint.approved);
  assert.equal(stored.date, checkpoint.date);
  assert.equal(Object.hasOwn(stored, "where"), false);
  bad((d) => { d.stages["05-erd"].parts.memory.checkpoints[0].where = "file:///private"; });
});

test("names count Unicode code points and preserve exact code and source text", () => {
  const data = fixture();
  data.items[0].title = "😀".repeat(120);
  data.pictures[0].source.tables[0].name = "가".repeat(120);
  assert.equal(JSON.parse(readSnapshot02(data, NOW).body).items[0].title, data.items[0].title);
  bad((d) => { d.items[0].title = "😀".repeat(121); });
  bad((d) => { d.pictures[0].source.tables[0].name = "가".repeat(121); });
});

test("each picture is unique, in its declared part and bound to the default commit", () => {
  bad((d) => { d.pictures.push(structuredClone(d.pictures[0])); });
  bad((d) => { d.pictures[0].part = "unknown"; });
  bad((d) => { d.pictures[0].commit = "b".repeat(40); });
  bad((d) => { delete d.repos["."].default; });
  bad((d) => { d.left_out.push({ part: "nexus", stage: "05-erd", why: "size" }); });
  bad((d) => { d.records.commit = "b".repeat(40); });
  const data = fixture();
  data.pictures = []; delete data.repos; data.records = { from: "status-file" };
  assert.equal(readSnapshot02(data, NOW).defaultCommit, null);
});

test("domain rows, terms, timeline and ERD structure retain their complete shape", () => {
  const data = fixture();
  const domain = {
    format: 1, contexts: [{ id: "CTX-001", name: "Orders", type: "core", purpose: "Take orders", removed: false, external: "", where: "board.md:1", rows: [{ given_by: "Buyer", policy: false, read_model: "Cart", command: "Order", aggregate: "Order", events: ["Ordered"], where: "board.md:3" }] }],
    aggregates: [{ name: "Order", context: "CTX-001", term: "TERM-001", removed: false, where: "board.md:3" }], read_models: [], dependencies: [], hotspots: [],
    timeline: [{ lane: "Buyer", places: [["Ordered"], ["Paid", "Payment failed"]], where: "board.md:6" }],
  };
  data.pictures.push(picture("01-domain", domain));
  assert.equal(readSnapshot02(data, NOW).pictures.length, 2);
  domain.contexts[0].rows[0].policy = "yes";
  assert.throws(() => readSnapshot02(data, NOW), (error) => error.code === "invalid_snapshot");
  bad((d) => { d.pictures[0].source.tables[0].columns[0].null = "false"; });
  bad((d) => { d.pictures[0].stage = "01-domain"; });
  bad((d) => { d.pictures[0].source.tables[0].unknown = "test"; });
});

test("sitemap parents are bounded and cannot cycle; unknown and empty term lists differ", () => {
  const data = fixture();
  const screen = { id: "SCR-001", name: "Home", path: "/", access: "user", flows: [], context: "", removed: false, where: "sitemap.yaml:1" };
  data.pictures.push(picture("07-sitemap", { format: 1, screens: [screen, { ...screen, id: "SCR-002", parent: 0, terms: [] }], without_screen: [] }));
  const parsed = readSnapshot02(data, NOW);
  assert.equal(Object.hasOwn(parsed.pictures[1].source.screens[0], "terms"), false);
  assert.deepEqual(parsed.pictures[1].source.screens[1].terms, []);
  screen.parent = 1;
  assert.throws(() => readSnapshot02(data, NOW), (error) => error.code === "invalid_snapshot");
  screen.parent = 99;
  assert.throws(() => readSnapshot02(data, NOW), (error) => error.code === "invalid_snapshot");
});
