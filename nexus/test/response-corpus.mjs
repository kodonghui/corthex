// Offline actual-handler responses for the external OpenAPI schema check.
// No network or real credentials. stdout is synthetic JSON only.
import { readFileSync } from "node:fs";
import { handle } from "../src/app.js";
import { fakeD1 } from "./fake-d1.js";
import { testAccess } from "./access-fixture.js";

const access=await testAccess(),env={...access.env,DB:fakeD1(),NEXUS_LANGUAGE:"en"};
const template=readFileSync(new URL("../src/hub.html",import.meta.url),"utf8");
let serial=0;
async function call(method,path,body) {
  const headers={...access.headers("agent"),"Nexus-Session":"qa-offline-contract"};
  if(method==="POST")headers["Idempotency-Key"]='"nw_'+(++serial).toString().padStart(12,"0")+'"';
  if(body!==undefined)headers["Content-Type"]="application/json";
  const response=await handle(new Request("https://nexus.example.com"+path,{method,headers,...(body===undefined?{}:{body:JSON.stringify(body)})}),env,access.ctx,template);
  const text=await response.text();
  if(response.status>=400)throw new Error("offline corpus request failed: "+response.status+" "+path);
  return response.headers.get("Content-Type").includes("json")?JSON.parse(text):text;
}
const snapshot=JSON.parse(readFileSync(new URL("./snapshot-02-example.json",import.meta.url),"utf8"));
snapshot.project.parts.push("constructor");
await call("POST","/api/snapshots",snapshot);
const cases=[];
for(const path of ["/pictures/corthex/nexus/05-erd","/overview/corthex/nexus/05-erd","/pictures/corthex/constructor/05-erd"]){
  const page=await call("GET",path);
  const value=JSON.parse(page.match(/<script id="view-data" type="application\/json">(.*?)<\/script>/s)[1]);
  cases.push({name:path,schema:"ViewPageData",value});
}
cases.push({name:"constructor part overview",schema:"Overview",value:await call("GET","/api/spaces/corthex/overview/constructor/05-erd")});
const comment=await call("POST","/api/spaces/corthex/comments",{part:"nexus",stage:"05-erd",item:"TBL-111",text:"Synthetic history"});
for(let index=0;index<501;index++){
  const proposal=await call("POST","/api/spaces/corthex/proposals",{part:"nexus",stage:"05-erd",items:["TBL-111"],reason:"Synthetic",change:"Synthetic",comment:comment.id});
  await call("POST","/api/spaces/corthex/proposals/"+proposal.id+"/withdraw",{});
}
const history=await call("GET","/api/spaces/corthex/comments/"+comment.id);
if(history.proposals.length!==501)throw new Error("history was truncated");
cases.push({name:"501 historical proposals",schema:"CommentThread",value:history});
process.stdout.write(JSON.stringify(cases));
