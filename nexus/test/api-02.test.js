import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { handle, renderView } from "../src/app.js";
import { fakeD1 } from "./fake-d1.js";
import { testAccess } from "./access-fixture.js";

const access=await testAccess();
const template=readFileSync(new URL("../src/hub.html",import.meta.url),"utf8");
const snapshot=JSON.parse(readFileSync(new URL("./snapshot-02-example.json",import.meta.url),"utf8"));
function server() {
  const env={...access.env,DB:fakeD1(),NEXUS_LANGUAGE:"ko"};let seq=0;
  return async(method,path,{body,kind="user",headers={},ctx=access.ctx,views={}}={})=>{
    const h={...access.headers(kind),...(method==="POST"?{"Idempotency-Key":'"nw_'+(++seq).toString().padStart(12,"0")+'"'}:{}),...(kind==="agent"?{"Nexus-Session":"session-a"}:{}),...headers};
    if(body!==undefined && !Object.hasOwn(h,"Content-Type"))h["Content-Type"]="application/json";
    const request=new Request("https://nexus.example.com"+path,{method,headers:h,...(body===undefined?{}:{body:typeof body==="string"?body:JSON.stringify(body)})});
    const response=await handle(request,env,ctx,template,views);const text=await response.text();
    return {status:response.status,headers:response.headers,text,...(response.headers.get("Content-Type")?.includes("json")&&text?{data:JSON.parse(text)}:{})};
  };
}

test("the actual handler provides a complete discussion, reflection and checkpoint round trip",async()=>{
  const call=server(),base="/api/spaces/corthex";
  assert.equal((await call("POST","/api/snapshots",{body:snapshot,kind:"agent"})).status,200);
  assert.equal((await call("GET","/api/snapshots/corthex/held")).data.default_commit,snapshot.repos["."].default.commit);
  const first=await call("POST",base+"/comments",{body:{part:"nexus",stage:"05-erd",item:"TBL-111",text:"Question"}});
  assert.equal(first.status,201,first.text);const id=first.data.id;
  assert.equal((await call("GET",base+"/todo",{kind:"agent"})).data.comments.total,1);
  const claimed=await call("POST",base+"/claims/"+id,{kind:"agent"});assert.equal(claimed.status,200,claimed.text);
  assert.equal((await call("DELETE",base+"/claims/"+id,{kind:"agent"})).data.released,true);
  const replied=await call("POST",base+"/comments/"+id+"/replies",{kind:"agent",body:{text:"A proposal follows"}});
  assert.equal(replied.status,201,replied.text);
  const proposed=await call("POST",base+"/proposals",{kind:"agent",body:{part:"nexus",stage:"05-erd",items:["TBL-111"],reason:"Question",change:"Answer",source_text:"CREATE TABLE safe (id TEXT)",comment:id}});
  assert.equal(proposed.status,201,proposed.text);const pid=proposed.data.id;
  assert.equal((await call("GET",base+"/proposals/"+pid)).data.source_text,"CREATE TABLE safe (id TEXT)");
  const accepted=await call("POST",base+"/proposals/"+pid+"/accept");assert.equal(accepted.status,200,accepted.text);
  const eid=accepted.data.edit.id;
  const report=await call("POST",base+"/edits/"+eid+"/report",{kind:"agent",body:{event:"reflected",commit:"a".repeat(40)}});
  assert.equal(report.status,200,report.text);assert.equal(report.data.edit.state,"closed");
  assert.equal((await call("GET",base+"/edits/"+eid)).data.proposal.source_text,"CREATE TABLE safe (id TEXT)");
  const decision=await call("POST",base+"/comments/"+id+"/decisions",{kind:"agent",body:{link:"https://example.com/record"}});
  assert.equal(decision.status,201,decision.text);
  const thread=await call("GET",base+"/comments/"+id);assert.equal(thread.data.replies.length,1);assert.equal(thread.data.decisions.length,1);
  const checkpoint=await call("POST",base+"/checkpoints",{body:{part:"nexus",stage:"05-erd"}});assert.equal(checkpoint.status,201,checkpoint.text);
  const kid=checkpoint.data.id;
  assert.equal((await call("GET",base+"/checkpoints/"+kid)).data.state,"passed");
  assert.equal((await call("GET",base+"/overview/nexus/05-erd")).data.checkpoints.length,1);
  const picture=await call("GET",base+"/pictures/nexus/05-erd");assert.equal(picture.status,200,picture.text);
  assert.equal(picture.data.proposals.length,0);assert.equal(picture.data.reflections.length,0);
  const dry=await call("GET","/api/snapshots/corthex/removal");assert.equal(dry.data.deletes.comments,1);
  assert.equal(dry.data.deletes.replies,1);assert.equal(dry.data.deletes.decisions,1);assert.equal(dry.data.deletes.checkpoints,1);
  assert.equal((await call("DELETE","/api/snapshots/corthex")).status,200);
  assert.equal((await call("GET",base+"/comments/"+id)).data.code,"project_not_found");
});

test("refusal order is enforced through the handler, including body shape before receipt replay",async()=>{
  const call=server(),path="/api/spaces/corthex/proposals";
  const req={kind:"user",headers:{"Sec-Fetch-Site":"cross-site","Idempotency-Key":"invalid"},body:"{"};
  assert.equal((await call("POST",path,{...req,ctx:{}})).data.code,"access_missing");
  assert.equal((await call("POST","/nothing",req)).data.code,"not_found");
  assert.equal((await call("PUT",path,req)).data.code,"method_not_allowed");
  assert.equal((await call("POST",path,req)).data.code,"cross_site");
  assert.equal((await call("POST",path,{...req,headers:{}})).data.code,"agent_only");
  assert.equal((await call("POST",path,{...req,kind:"agent",headers:{"Idempotency-Key":"invalid"}})).data.field,"Idempotency-Key");
  assert.equal((await call("POST",path,{kind:"agent",headers:{"Nexus-Session":""},body:{}})).data.field,"Nexus-Session");
  assert.equal((await call("POST",path,{kind:"agent",body:"{}",headers:{"Content-Type":"text/plain"}})).data.code,"json_required");
  assert.equal((await call("POST",path,{kind:"agent",body:{reason:"x"}})).data.code,"invalid_request");
  const valid={part:"nexus",stage:"05-erd",items:["TBL-111"],reason:"x",change:"y"};
  assert.equal((await call("POST",path,{kind:"agent",body:valid})).data.code,"project_not_found");
  await call("POST","/api/snapshots",{body:snapshot});
  const headers={"Idempotency-Key":'"nw_aaaaaaaaaaaa"'};
  assert.equal((await call("POST",path,{kind:"agent",body:valid,headers})).status,201);
  const malformed=await call("POST",path,{kind:"agent",body:{...valid,reason:""},headers});
  assert.equal(malformed.data.code,"invalid_request");
  const long=await call("POST",path,{kind:"agent",body:{...valid,reason:"😀".repeat(2001)}});
  assert.equal(long.status,413);assert.equal(long.data.field,"reason");assert.equal(long.data.limit,2000);
  const invalid=structuredClone(snapshot);invalid.stages["한".repeat(5000)]={files:"invalid"};
  const bounded=await call("POST","/api/snapshots",{body:invalid});
  assert.equal(bounded.data.code,"invalid_snapshot");assert.equal(Array.from(bounded.data.field).length,120);assert.ok(Buffer.byteLength(bounded.text)<4096);
});

test("HEAD, the protected code endpoint and browser refusals keep their distinct headers and bodies",async()=>{
  const call=server();
  await call("POST","/api/snapshots",{body:snapshot});
  for(const path of ["/","/api/snapshots","/api/snapshots/corthex","/api/snapshots/corthex/held","/api/snapshots/corthex/removal","/api/spaces/corthex/todo","/api/spaces/corthex/pictures/nexus/05-erd","/api/spaces/corthex/overview/nexus/05-erd"]) {
    const get=await call("GET",path),head=await call("HEAD",path);
    assert.equal(head.status,get.status,path);assert.equal(head.text,"");
    for(const key of ["Content-Type","Content-Security-Policy","Cache-Control","X-Frame-Options"])assert.equal(head.headers.get(key),get.headers.get(key),path);
  }
  const code="view.1234abcd.js",views={code:{[code]:{body:"export const version=2;",type:"application/javascript; charset=utf-8"}}};
  assert.equal((await call("GET","/code/"+code,{views,ctx:{}})).status,403);
  const file=await call("GET","/code/"+code,{views});assert.equal(file.text,"export const version=2;");assert.match(file.headers.get("Cache-Control"),/private.*immutable/);
  assert.equal((await call("GET","/code/view.ffffffff.js",{views})).data.code,"not_found");
  const browser=await call("GET","/pictures/missing/_/05-erd",{headers:{Accept:"text/html"}});
  assert.equal(browser.status,404);assert.equal(browser.headers.get("Content-Type"),"text/html; charset=utf-8");assert.match(browser.text,/이 프로젝트는 서버에 없습니다/);assert.match(browser.text,/확인 번호/);
  const api=await call("GET","/api/spaces/missing/todo",{headers:{Accept:"text/html"}});assert.equal(api.headers.get("Content-Type"),"application/problem+json");
});

test("picture and overview bootstrap JSON preserve literal replacement characters and inert HTML",async()=>{
  const call=server(),data=structuredClone(snapshot);
  const literal="literal $' $` $$ </script><script>unsafe</script> & tail";
  data.pictures[0].source.tables[0].name=literal;
  await call("POST","/api/snapshots",{body:data});
  await call("POST","/api/spaces/corthex/comments",{body:{part:"nexus",stage:"05-erd",item:"TBL-111",text:literal}});
  for(const path of ["/pictures/corthex/nexus/05-erd","/overview/corthex/nexus/05-erd"]) {
    const response=await call("GET",path);
    assert.equal(response.status,200,response.text);
    assert.equal(response.text.split("</script>").length,2);
    const payload=JSON.parse(response.text.match(/<script id="view-data" type="application\/json">(.*?)<\/script>/s)[1]);
    assert.equal(payload.data.comments.entries[0].text,literal);
    if(payload.view==="picture")assert.equal(payload.data.picture.source.tables[0].name,literal);
  }
  assert.throws(()=>renderView("no marker",{}),/placeholder/);
  assert.throws(()=>renderView("__CORTHEX_VIEW_DATA____CORTHEX_VIEW_DATA__",{}),/placeholder/);
});
