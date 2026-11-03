import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { Store } from "../src/store.js";
import { fakeD1 } from "./fake-d1.js";
import { readSnapshot02 } from "../src/snapshot02.js";

const NOW="2026-11-03T12:00:00.000Z";
async function fixture() {
  const db=new DatabaseSync(":memory:");const store=new Store(fakeD1(db));
  const data=JSON.parse(readFileSync(new URL("./snapshot-02-example.json",import.meta.url)));
  await store.push(readSnapshot02(data,Date.parse(NOW)),NOW);
  return {db,store,data};
}

test("held, picture and overview reads keep exact sources and separate record origins",async()=>{
  const {store,data}=await fixture();
  const held=await store.heldCommit("corthex");assert.equal(held.project,"corthex");assert.equal(held.default_commit,data.repos["."].default.commit);
  const picture=await store.readPicture("corthex","nexus","05-erd");
  assert.deepEqual(picture.picture.source,data.pictures[0].source);assert.deepEqual(picture.comments,{total:0,entries:[]});
  const overview=await store.readOverview("corthex","memory","05-erd");
  assert.equal(overview.record.state,"done");assert.equal(overview.record.from,"repository");assert.equal(overview.record.checkpoints[0].date,"2026-10-27");
  assert.equal(overview.source_state,"found");assert.equal(overview.read,true);
  await assert.rejects(store.readPicture("corthex","unknown","05-erd"),(error)=>error.code==="part_not_found");
  await assert.rejects(store.readPicture("corthex","memory","01-domain"),(error)=>error.code==="picture_not_found");
  await assert.rejects(store.readOverview("missing","","02-prd"),(error)=>error.code==="project_not_found");
});

test("the dry run is read-only and removal cascades through every project table",async()=>{
  const {db,store}=await fixture();
  const before=db.prepare("SELECT total_changes() AS n").get().n;
  const dry=await store.removalDryRun("corthex");
  assert.deepEqual(dry.deletes,{snapshot:true,space:true,pictures:1,discrepancies:0,comments:0,proposals:0,edits:0,checkpoints:0,replies:0,decisions:0});
  assert.equal(db.prepare("SELECT total_changes() AS n").get().n,before);
  assert.equal(await store.remove("corthex"),true);
  for(const table of ["snapshots","project_spaces","pictures","discrepancies","comments","replies","decisions","proposals","edits","checkpoints","claims","writes"])assert.equal(db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n,0);
});

test("one entry read is scoped to the named project and missing IDs get their own refusal",async()=>{
  const {store}=await fixture();
  for(const type of ["comment","proposal","edit","checkpoint"])await assert.rejects(store.readEntry("corthex",type,"missing"),(error)=>error.code===`${type}_not_found`);
});
