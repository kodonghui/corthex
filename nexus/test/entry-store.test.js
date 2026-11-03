import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { Store, MIGRATIONS } from "../src/store.js";
import { readSnapshot02 } from "../src/snapshot02.js";
import { fakeD1 } from "./fake-d1.js";

const NOW="2026-11-03T12:00:00.000Z";
const PR="https://example.com/repo/pull/1";
async function fixture() {
  const db=new DatabaseSync(":memory:");const binding=fakeD1(db),store=new Store(binding);
  const data=JSON.parse(readFileSync(new URL("./snapshot-02-example.json",import.meta.url)));
  await store.push(readSnapshot02(data,Date.parse(NOW)),NOW);
  let next=0;
  const write=(name,id,body={},extra={})=>store.writeEntry(name,"corthex",id,body,{kind:"agent",session:"session-a",write:"nw_"+(++next).toString().padStart(12,"0"),now:NOW,...extra});
  const comment=(extra={})=>write("comment",null,{part:"nexus",stage:"05-erd",item:"TBL-111",text:"A synthetic comment",...extra},{kind:"user"});
  const proposal=(extra={})=>write("proposal",null,{part:"nexus",stage:"05-erd",items:["TBL-111"],reason:"Reason",change:"A synthetic change",...extra});
  return {db,binding,store,data,write,comment,proposal};
}
const code=(name)=>(e)=>e.code===name;

test("comments, settling, decisions on a closed comment and reopening preserve the conversation",async()=>{
  const {db,store,write,comment}=await fixture();
  const c=(await comment()).body;
  assert.equal(c.waits,"agent");
  await write("reply",c.id,{text:"Settled",settles:true},{kind:"user"});
  assert.equal((await store.readEntry("corthex","comment",c.id)).settled,true);
  await write("decision",c.id,{link:"https://example.com/decision",text:"Decision"});
  assert.equal((await write("answered",c.id)).body.changed,false);
  await write("decision",c.id,{link:"https://example.com/decision-2"});
  await assert.rejects(write("reply",c.id,{text:"Agent cannot reopen"}),code("comment_closed"));
  await write("reply",c.id,{text:"Continue",settles:false},{kind:"user"});
  const result=await store.readEntry("corthex","comment",c.id);
  assert.equal(result.decisions.length,2);assert.equal(result.state,"open");assert.equal(result.waits,"agent");assert.equal(result.settled,false);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM writes").get().n,6);
});

test("write IDs replay the first answer across a different target/body and reject another request",async()=>{
  const {db,write,comment}=await fixture();
  const c=(await comment()).body;
  const opts={write:"nw_aaaaaaaaaaaa"};
  const first=await write("reply",c.id,{text:"First"},opts);
  const replay=await write("reply","nc_bbbbbbbbbbbb",{text:"Different"},opts);
  assert.deepEqual(replay,first);
  await assert.rejects(write("answered",c.id,{},opts),code("write_id_reused"));
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM replies").get().n,1);
  assert.equal(db.prepare("SELECT text_bytes AS n FROM project_spaces").get().n,Buffer.byteLength("A synthetic commentFirst"));
});

test("a proposal can add an item; withdrawn proposals stop determining waits",async()=>{
  const {store,write,comment,proposal}=await fixture();
  const c=(await comment()).body;
  await assert.rejects(proposal({items:["TBL-999"]}),code("unknown_item"));
  const p=(await proposal({comment:c.id,items:["TBL-999"],adds:["TBL-999"]})).body;
  assert.equal((await store.readEntry("corthex","comment",c.id)).waits,"user");
  assert.equal((await write("withdraw-proposal",p.id)).body.changed,true);
  assert.equal((await write("withdraw-proposal",p.id)).body.changed,false);
  assert.equal((await store.readEntry("corthex","comment",c.id)).waits,"agent");
});

test("board proposals recognize defined aggregate and read-model terms",async()=>{
  const {store,data,write}=await fixture();
  const where="docs/01-domain/board.md:1";
  data.pictures[0]={...data.pictures[0],stage:"01-domain",source:{format:1,
    contexts:[{id:"CTX-001",name:"Orders",type:"core",purpose:"Orders",removed:false,external:"",rows:[],where}],
    aggregates:[{name:"Order",context:"CTX-001",term:"TERM-001",removed:false,where}],
    read_models:[{name:"Summary",context:"CTX-001",term:"TERM-002",removed:false,where}],dependencies:[],hotspots:[]}};
  await store.push(readSnapshot02(data,Date.parse(NOW)),NOW);
  const body={part:"nexus",stage:"01-domain",items:["CTX-001","TERM-001","TERM-002"],reason:"Reason",change:"Change"};
  assert.deepEqual((await write("proposal",null,body)).body.items,body.items);
  await assert.rejects(write("proposal",null,{...body,items:["TERM-003"]}),code("unknown_item"));
});

test("comment details retain more than 500 historical proposals",async()=>{
  const {store,write,comment,proposal}=await fixture();
  const c=(await comment()).body;
  const ids=new Set();
  for(let i=0;i<501;i++){
    const p=(await proposal({comment:c.id})).body;ids.add(p.id);
    await write("withdraw-proposal",p.id);
  }
  const history=(await store.readEntry("corthex","comment",c.id)).proposals;
  assert.equal(history.length,501);
  assert.deepEqual(new Set(history.map((row)=>row.id)),ids);
  assert.ok(history.every((row)=>row.state==="withdrawn" && !Object.hasOwn(row,"source_text")));
});

test("acceptance is atomic; reports preserve PR identity even after the receipt expires",async()=>{
  const {db,store,write,proposal}=await fixture();
  const p=(await proposal()).body;
  const accepted=(await write("accept",p.id,{}, {kind:"user"})).body;
  assert.equal(accepted.edit.commit,p.commit);
  await assert.rejects(write("accept",p.id,{}, {kind:"user"}),code("proposal_not_open"));
  const id=accepted.edit.id;
  await assert.rejects(write("report-edit",id,{event:"closed",pull_request:PR}),code("edit_state"));
  await write("report-edit",id,{event:"opened",pull_request:PR});
  await assert.rejects(write("report-edit",id,{event:"opened",pull_request:PR+"2"}),code("pull_request_reported"));
  await assert.rejects(write("report-edit",id,{event:"merged",pull_request:PR+"2"}),code("pull_request_mismatch"));
  await write("report-edit",id,{event:"closed",pull_request:PR});
  db.exec("DELETE FROM writes");
  assert.equal((await write("report-edit",id,{event:"closed",pull_request:PR})).body.changed,false);
  assert.equal((await store.readEntry("corthex","edit",id)).state,"pending");
  assert.equal(Object.hasOwn(await store.readEntry("corthex","edit",id),"last_report"),false);
  await write("report-edit",id,{event:"reflected",commit:"a".repeat(40)});
  assert.equal((await store.readEntry("corthex","edit",id)).closed_commit,"a".repeat(40));
});

test("claims exclude other agents, allow user writes, extend and end on closure or a reported PR",async()=>{
  const {store,write,comment,proposal}=await fixture();
  const c=(await comment()).body;
  const claim=await store.claimEntry("corthex",c.id,"session-a",false,NOW);
  await assert.rejects(store.claimEntry("corthex",c.id,"session-b",false,NOW),code("claimed"));
  await assert.rejects(write("reply",c.id,{text:"Other agent"},{session:"session-b"}),code("claimed"));
  await write("reply",c.id,{text:"User can write"},{kind:"user"});
  const later="2026-11-03T12:30:00.000Z";
  await write("reply",c.id,{text:"Owner"},{now:later});
  assert.equal((await store.claimEntry("corthex",c.id,"session-a",false,later)).ends_at,"2026-11-03T13:30:00.000Z");
  assert.equal(claim.ends_at,"2026-11-03T13:00:00.000Z");
  await write("answered",c.id);
  await assert.rejects(store.claimEntry("corthex",c.id,"session-b",false,NOW),code("entry_closed"));
  const p=(await proposal()).body;
  const e=(await write("accept",p.id,{}, {kind:"user"})).body.edit;
  await store.claimEntry("corthex",e.id,"session-a",false,NOW);
  await write("report-edit",e.id,{event:"opened",pull_request:PR});
  await assert.rejects(store.claimEntry("corthex",e.id,"session-b",false,NOW),code("pull_request_reported"));
});

test("checkpoint withdrawal while a PR is open stays in the to-do until it closes",async()=>{
  const {store,write}=await fixture();
  const c=(await write("checkpoint",null,{part:"nexus",stage:"04-functional-spec",words:"Approved"},{kind:"user"})).body;
  for(const event of ["merged","closed"])await assert.rejects(write("report-checkpoint",c.id,{event,pull_request:PR}),code("checkpoint_state"));
  await write("report-checkpoint",c.id,{event:"opened",pull_request:PR});
  await write("withdraw-checkpoint",c.id,{}, {kind:"user"});
  const todo=await store.readTodo("corthex","session-b",NOW);
  assert.equal(todo.checkpoints.entries[0].why,"withdrawn-in-review");
  await assert.rejects(write("report-checkpoint",c.id,{event:"opened",pull_request:PR+"2"}),code("checkpoint_withdrawn"));
  await write("report-checkpoint",c.id,{event:"closed",pull_request:PR});
  assert.equal((await store.readTodo("corthex",null,NOW)).checkpoints.total,0);
});

test("concurrent same-ID writes with the same clock commit once, and a failed batch leaves no receipt",async()=>{
  const {db,binding,write,comment}=await fixture();
  const c=(await comment()).body;
  const original=binding.batch;
  let arrived=0,release;const barrier=new Promise((r)=>{release=r;});
  binding.batch=async(statements)=>{
    if(statements.some((s)=>s.sql.startsWith("INSERT OR IGNORE INTO writes"))) {if(++arrived===2)release();await barrier;}
    return original(statements);
  };
  const answers=await Promise.all([write("reply",c.id,{text:"One"},{write:"nw_aaaaaaaaaaaa"}),write("reply",c.id,{text:"Two"},{write:"nw_aaaaaaaaaaaa"})]);
  assert.deepEqual(answers[0],answers[1]);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM replies").get().n,1);
  binding.batch=async(statements)=>original([...statements,binding.prepare("INSERT INTO nonexistent VALUES(1)")]);
  await assert.rejects(write("reply",c.id,{text:"Rollback"}));
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM replies").get().n,1);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM writes").get().n,2);
});

test("migration 3 preserves a populated schema 2 reflection and adds no public field",async()=>{
  const db=new DatabaseSync(":memory:");db.exec("PRAGMA foreign_keys=ON");
  db.exec("CREATE TABLE migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)");
  for(const m of MIGRATIONS.slice(0,2)){for(const sql of m.statements)db.exec(sql);db.prepare("INSERT INTO migrations VALUES(?,?)").run(m.version,NOW);}
  db.prepare("INSERT INTO snapshots VALUES(?,1,1,?, ?,1,'{}',NULL,NULL)").run("synthetic",NOW,NOW);
  db.prepare("INSERT INTO project_spaces(project,created_at) VALUES(?,?)").run("synthetic",NOW);
  db.prepare("INSERT INTO pictures VALUES('synthetic','','05-erd',?,?,'{}','digest',?,NULL)").run("a".repeat(40),NOW,NOW);
  db.prepare("INSERT INTO edits VALUES('ne_aaaaaaaaaaaa','synthetic','','05-erd',?,NULL,?,'pending',NULL,NULL,?,?)").run("a".repeat(40),'{"text":"保つ"}',NOW,NOW);
  const before={...db.prepare("SELECT * FROM edits").get()};
  await new Store(fakeD1(db)).ensure();
  const after={...db.prepare("SELECT * FROM edits").get()};
  assert.equal(after.last_report,null);delete after.last_report;assert.deepEqual(after,before);
});

test("a checkpoint withdrawal racing a push is replanned before acknowledging the record",async()=>{
  const {store,binding,write,data}=await fixture();
  const k=(await write("checkpoint",null,{part:"nexus",stage:"05-erd"},{kind:"user"})).body;
  const record=data.stages["05-erd"].parts.memory;
  data.stages["05-erd"].parts.nexus={...record,checkpoints:[{...record.checkpoints[0],nexus:k.id}]};
  const batch=binding.batch;let withdraw=true;
  binding.batch=async(statements)=>{
    if(withdraw && statements[0].sql.startsWith("INSERT INTO snapshots")) {
      withdraw=false;await write("withdraw-checkpoint",k.id,{}, {kind:"user"});
    }
    return batch(statements);
  };
  const answer=await store.push(readSnapshot02(data,Date.parse(NOW)),NOW);
  assert.deepEqual(answer.checkpoints.withdrawn_recorded,[k.id]);
  assert.equal((await store.readEntry("corthex","checkpoint",k.id)).state,"withdrawn");
  assert.equal((await store.readOverview("corthex","nexus","05-erd")).warnings[0].checkpoint,k.id);
});

test("a write ID expires at seven days and a claim expires at sixty minutes",async()=>{
  const {db,store,write,comment}=await fixture();const c=(await comment()).body;
  const key={write:"nw_aaaaaaaaaaaa"};
  await write("reply",c.id,{text:"First"},key);
  const before="2026-11-10T11:59:59.999Z",after="2026-11-10T12:00:00.000Z";
  assert.equal((await write("reply",c.id,{text:"Second"},{...key,now:before})).body.reply.text,"First");
  assert.equal((await write("reply",c.id,{text:"Second"},{...key,now:after})).body.reply.seq,2);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM replies").get().n,2);
  await store.claimEntry("corthex",c.id,"session-a",false,NOW);
  await assert.rejects(store.claimEntry("corthex",c.id,"session-b",false,"2026-11-03T12:59:59.999Z"),code("claimed"));
  assert.equal((await store.claimEntry("corthex",c.id,"session-b",false,"2026-11-03T13:00:00.000Z")).session,"session-b");
});

test("two distinct writes cannot both take a final comment place or the last UTF-8 text byte",async()=>{
  const {db,binding,write,comment}=await fixture();const c=(await comment()).body;
  const row={...db.prepare("SELECT * FROM comments WHERE id=?").get(c.id)};
  const names=Object.keys(row),insert=db.prepare(`INSERT INTO comments(${names.join(",")}) VALUES(${names.map(()=>"?").join(",")})`);
  for(let i=1;i<1999;i++)insert.run(...names.map((key)=>key==="id"?"seed-"+i:row[key]));
  const batch=binding.batch;let arrivals=0,release;
  const barrier=new Promise((r)=>{release=r;});
  binding.batch=async(statements)=>{
    if(statements.some((s)=>s.sql.startsWith("INSERT OR IGNORE INTO writes")) && arrivals<2) {if(++arrivals===2)release();await barrier;}
    return batch(statements);
  };
  const results=await Promise.allSettled([comment({text:"Last A"}),comment({text:"Last B"})]);
  assert.equal(results.filter((row)=>row.status==="fulfilled").length,1);
  assert.equal(results.find((row)=>row.status==="rejected").reason.code,"comment_limit");
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM comments").get().n,2000);
  binding.batch=batch;
  db.prepare("UPDATE project_spaces SET text_bytes=?").run(8*1024*1024-3);
  const failures=await Promise.allSettled([write("reply",c.id,{text:"가"}),write("reply",c.id,{text:"나"})]);
  assert.equal(failures.filter((row)=>row.status==="fulfilled").length,1);
  assert.equal(failures.find((row)=>row.status==="rejected").reason.code,"space_full");
  assert.equal(db.prepare("SELECT text_bytes FROM project_spaces").get().text_bytes,8*1024*1024);
});

test("two sessions racing a claim give one owner and releasing an absent own claim changes nothing",async()=>{
  const {store,comment}=await fixture();const c=(await comment()).body;
  assert.deepEqual(await store.claimEntry("corthex",c.id,"session-a",true,NOW),{entry:c.id,released:false});
  const results=await Promise.allSettled([store.claimEntry("corthex",c.id,"session-a",false,NOW),store.claimEntry("corthex",c.id,"session-b",false,NOW)]);
  assert.equal(results.filter((row)=>row.status==="fulfilled").length,1);
  assert.equal(results.find((row)=>row.status==="rejected").reason.code,"claimed");
  const winner=results.find((row)=>row.status==="fulfilled").value.session;
  assert.equal((await store.claimEntry("corthex",c.id,winner,true,NOW)).released,true);
  assert.equal((await store.claimEntry("corthex",c.id,winner,true,NOW)).released,false);
});

test("a passed checkpoint omitted by a later record returns to the to-do and may be withdrawn",async()=>{
  const {store,write,data}=await fixture();
  const k=(await write("checkpoint",null,{part:"nexus",stage:"05-erd"},{kind:"user"})).body;
  const record=data.stages["05-erd"].parts.memory;
  data.stages["05-erd"].parts.nexus={...record,checkpoints:[{...record.checkpoints[0],nexus:k.id}]};
  await store.push(readSnapshot02(data,Date.parse(NOW)),NOW);
  assert.equal((await store.readTodo("corthex",null,NOW)).checkpoints.total,0);
  assert.equal((await store.readEntry("corthex","checkpoint",k.id)).recorded_commit,data.repos["."].default.commit);
  data.stages["05-erd"].parts.nexus.checkpoints=[];
  await store.push(readSnapshot02(data,Date.parse(NOW)),NOW);
  assert.equal((await store.readEntry("corthex","checkpoint",k.id)).recorded_commit,null);
  assert.equal((await store.readTodo("corthex",null,NOW)).checkpoints.entries[0].id,k.id);
  assert.equal((await write("withdraw-checkpoint",k.id,{}, {kind:"user"})).body.checkpoint.state,"withdrawn");
});
