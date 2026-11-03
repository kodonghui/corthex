import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { planPush, checkCommit, repositoryAddress } from "../src/push-plan.js";
import { readSnapshot02 } from "../src/snapshot02.js";

const NOW = "2026-11-03T12:00:00.000Z";
const data = () => JSON.parse(readFileSync(new URL("./snapshot-02-example.json", import.meta.url)));
const sent = () => readSnapshot02(data(), Date.parse(NOW));
const empty = () => ({ held: null, space: null, pictures: [], discrepancies: [], checkpoints: [] });

test("held commits gate replacement by name rather than clock time", () => {
  const s = sent();
  const held = { default_commit: "a".repeat(40), generated_ms: s.generatedMs + 1, generated_at: NOW };
  assert.throws(() => checkCommit(s, held), (error) => error.code === "commit_not_replaced");
  s.data.replaces = held.default_commit;
  assert.doesNotThrow(() => checkCommit(s, held));
  held.default_commit = s.defaultCommit;
  assert.throws(() => checkCommit(s, held), (error) => error.code === "older_snapshot");
  held.generated_ms = s.generatedMs;
  assert.doesNotThrow(() => checkCommit(s, held));
});

test("repository binding uses canonical addresses and rejects credential-bearing URLs", async () => {
  assert.equal(repositoryAddress("http://Example.COM/owner/repo.git/"), "https://example.com/owner/repo");
  for (const url of ["not a URL", "https://user:password@example.com/repo", "file:///repo", "https://example.com/repo?token=synthetic"]) assert.throws(() => repositoryAddress(url), (error) => error.code === "invalid_snapshot");
  const state = empty(); state.space = { repo_url: "https://example.com/another/repo", unopened: "{}" };
  await assert.rejects(planPush(sent(), state, NOW), (error) => error.code === "repository_mismatch");
});

test("an identical source is neither redrawn nor rewritten", async () => {
  const s = sent();
  const first = await planPush(s, empty(), NOW);
  assert.equal(first.answer.pictures.drawn.length, 1);
  const held = { ...first.pictures[0], commit_id: first.pictures[0].commit, committed_at: first.pictures[0].time };
  delete held.source;
  const state = { ...empty(), held: { revision: 1, default_commit: s.defaultCommit, generated_ms: s.generatedMs }, pictures: [held] };
  const again = await planPush(s, state, NOW);
  assert.deepEqual(again.pictures, []);
  assert.equal(again.answer.pictures.unchanged, 1);
  assert.equal(again.answer.revision, 2);
  const oldCommit = held.commit_id;
  held.not_current = "size";
  const resumed = await planPush(s, state, NOW);
  assert.equal(resumed.answer.pictures.current_again.length, 1);
  assert.equal(resumed.pictures[0].commit_id, oldCommit);
  assert.equal(resumed.pictures[0].not_current, null);
});

test("omitted pictures keep their old version and acquire the correct current mark", async () => {
  const s = sent();
  const state = empty(); state.pictures = [{ part: "nexus", stage: "05-erd", commit_id: "b".repeat(40), digest: "old", not_current: null }];
  s.pictures = [];
  s.data.left_out = [{ part: "nexus", stage: "05-erd", why: "other-repository" }];
  const plan = await planPush(s, state, NOW);
  assert.equal(plan.pictures[0].commit_id, "b".repeat(40));
  assert.equal(plan.answer.pictures.not_current[0].why, "other-repository");
  s.data.left_out = [];
  assert.equal((await planPush(s, state, NOW)).answer.pictures.not_current[0].why, "source-gone");
});

test("only committed repository records acknowledge known checkpoints of the same part/stage", async () => {
  const s = sent(); const state = empty();
  const checkpoint = { id: "nk_0123456789ab", part: "memory", stage: "05-erd", state: "passed", recorded_commit: null };
  state.checkpoints = [checkpoint];
  s.data.stages["05-erd"].parts.memory.checkpoints[0].nexus = checkpoint.id;
  const plan = await planPush(s, state, NOW);
  assert.equal(plan.answer.checkpoints.recorded, 1);
  assert.equal(plan.checkpoints[0].recorded_commit, s.defaultCommit);
  checkpoint.state = "withdrawn";
  assert.deepEqual((await planPush(s, state, NOW)).answer.checkpoints.withdrawn_recorded, [checkpoint.id]);
  checkpoint.recorded_commit = s.defaultCommit;
  s.data.stages["05-erd"].parts.memory.checkpoints = [];
  assert.equal((await planPush(s, state, NOW)).checkpoints[0].recorded_commit, null);
  s.data.records.from = "status-file";
  s.data.stages["05-erd"].parts.memory.checkpoints = [{ nexus: checkpoint.id }];
  assert.equal((await planPush(s, state, NOW)).answer.checkpoints.recorded, 0);
});
