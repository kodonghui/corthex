// NEXUS: checked Access requests, contract ordering, and D1 transactions.
import { Refused, readSnapshot } from "./snapshot.js";
import { readSnapshot02 } from "./snapshot02.js";
import { Store } from "./store.js";
import { preflight } from "./preflight.js";
import { jsonBody } from "./body.js";
import { COMMON_HEADERS, Problem, problemDocument, problemResponse } from "./problem.js";

export const MAX_PROJECTS = 30;
const PLACEHOLDER = "__CORTHEX_HUB_DATA__";
const INPUTS = Object.freeze({comment:"NewComment",reply:"NewReply",decision:"NewDecision",proposal:"NewProposal",
  "report-edit":"EditReport",checkpoint:"NewCheckpoint","report-checkpoint":"CheckpointReport"});
const lang = (env) => String(env.NEXUS_LANGUAGE || "").toLowerCase().startsWith("ko") ? "ko" : "en";
const escaped = (value) => String(value).replace(/[&<>"']/g,(ch)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const dataText = (value) => JSON.stringify(value).replace(/[<>&]/g,(ch)=>({"<":"\\u003c",">":"\\u003e","&":"\\u0026"}[ch]));
export const VIEW_POLICY = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

export async function handle(request,env,ctx,template,views={}) {
  env ||= {};
  try {
    const route=await preflight(request,env,ctx);
    if(!env.DB)throw new Problem("internal","the Worker has no D1 database bound as DB");
    const store=new Store(env.DB),p=route.params,head=request.method==="HEAD";
    switch(route.operation) {
      case "pushSnapshot": {
        const {data,text}=await jsonBody(request,null,true);
        let sent;
        if(data?.schema==="corthex-hub/0.2")sent=readSnapshot02(data,Date.now());
        else {
          try {sent=readSnapshot(text,Date.now());}
          catch(error) {
            if(!(error instanceof Refused))throw error;
            const code=error.status===413?"snapshot_too_large":/dated in the future/.test(error.message)?"clock_ahead":"invalid_snapshot";
            throw new Problem(code,error.message,code==="invalid_snapshot"?{field:"body"}:{});
          }
        }
        return json(await store.push(sent));
      }
      case "listSnapshots": return json({projects:await store.list()},200,head);
      case "getSnapshot": {
        const body=await store.body(p.project);
        if(body==null)throw new Problem("project_not_found","no such project");
        return new Response(head?null:body,{headers:jsonHeaders()});
      }
      case "removeProject": {
        if(!await store.remove(p.project))throw new Problem("project_not_found","no such project");
        return json({name:p.project,removed:true});
      }
      case "getHeldCommit": return json(await store.heldCommit(p.project),200,head);
      case "getRemovalDryRun": return json(await store.removalDryRun(p.project),200,head);
      case "getPicture": return json(await store.readPicture(p.project,p.part,p.stage),200,head);
      case "getStageOverview": return json(await store.readOverview(p.project,p.part,p.stage),200,head);
      case "getAgentTodo": return json(await store.readTodo(p.project,route.session),200,head);
      case "getComment": return json(await store.readEntry(p.project,"comment",p.comment),200,head);
      case "getProposal": return json(await store.readEntry(p.project,"proposal",p.proposal),200,head);
      case "getEdit": return json(await store.readEntry(p.project,"edit",p.edit),200,head);
      case "getCheckpoint": return json(await store.readEntry(p.project,"checkpoint",p.checkpoint),200,head);
      case "claimEntry": return json(await store.claimEntry(p.project,p.entry,route.session));
      case "releaseEntry": return json(await store.claimEntry(p.project,p.entry,route.session,true));
      case "getHubPage": {
        const [bodies,spaces]=await Promise.all([store.bodies(),store.readSpaces()]);
        const data={schema:"corthex-hub-page/0.2",generated_at:new Date().toISOString(),lang:lang(env),origin:"server",projects:bodies.map(JSON.parse),spaces,missing:[]};
        return html(head?null:render(template,JSON.stringify(data)),await pagePolicy(template));
      }
      case "getViewCode": {
        const file=views.code?.[p.file];
        if(!file)throw new Problem("not_found","no such file of the view's code");
        return new Response(head?null:file.body,{headers:{...COMMON_HEADERS,"Content-Type":file.type,"Cache-Control":"private, max-age=31536000, immutable","Content-Security-Policy":"default-src 'none'; frame-ancestors 'none'"}});
      }
      case "getPictureViewPage":
      case "getStageOverviewPage": {
        const view=route.operation==="getPictureViewPage"?"picture":"overview";
        const data=await(view==="picture"?store.readPicture(p.project,p.part,p.stage):store.readOverview(p.project,p.part,p.stage));
        const payload={schema:"corthex-view-page/0.2",lang:lang(env),view,data,problem:null};
        const viewTemplate=views.template || '<!doctype html><html><head><meta charset="utf-8"><title>NEXUS</title></head><body><main id="view"></main><script id="view-data" type="application/json">__CORTHEX_VIEW_DATA__</script></body></html>';
        return html(head?null:renderView(viewTemplate,payload),VIEW_POLICY);
      }
      default: {
        if(!route.writeName)throw new Error("unhandled operation");
        const body=INPUTS[route.writeName]?(await jsonBody(request,INPUTS[route.writeName])).data:{};
        const id=p.comment||p.proposal||p.edit||p.checkpoint||null;
        const result=await store.writeEntry(route.writeName,p.project,id,body,{kind:route.kind,session:route.session,write:route.write});
        return json(result.body,result.status);
      }
    }
  } catch(error) {
    const path=new URL(request.url).pathname;
    if((path==="/"||path.startsWith("/pictures/")||path.startsWith("/overview/")) && /(?:^|[,;\s])text\/html(?:[,;\s]|$)/i.test(request.headers.get("Accept")||""))return refusalPage(request,env,error);
    return problemResponse(request,error);
  }
}

function refusalPage(request,env,error) {
  const p=problemDocument(request,error),ko=lang(env)==="ko";
  console.error("nexus",{kind:p.code,traceId:p.traceId});
  const messages={project_not_found:"이 프로젝트는 서버에 없습니다.",space_not_found:"아직 그림을 서버에 보내지 않았습니다.",part_not_found:"이 프로젝트에 없는 부분입니다.",picture_not_found:"이 단계와 부분의 그림이 아직 없습니다.",access_missing:"로그인을 확인하지 못했습니다.",access_other_app:"이 서버의 로그인으로 확인되지 않았습니다.",not_found:"페이지를 찾지 못했습니다.",method_not_allowed:"이 요청 방법으로 열 수 없습니다.",internal:"페이지를 불러오지 못했습니다."};
  const message=ko?(messages[p.code]||"요청을 처리하지 못했습니다."):p.title;
  const body=`<!doctype html><html lang="${ko?"ko":"en"}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NEXUS</title></head><body><main><h1>${escaped(message)}</h1><p>${ko?"확인 번호":"Trace ID"}: ${escaped(p.traceId)}</p><p><a href="">${ko?"다시 불러오기":"Load again"}</a> · <a href="/">${ko?"허브로":"Hub"}</a></p></main></body></html>`;
  return new Response(request.method==="HEAD"?null:body,{status:p.status,headers:{...COMMON_HEADERS,"Content-Type":"text/html; charset=utf-8","Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",...(error instanceof Problem?error.headers:{})}});
}

export function render(template,data) {
  const at=template.indexOf(PLACEHOLDER);
  if(at<0||template.indexOf(PLACEHOLDER,at+1)>=0)throw new Error("the hub template must hold its placeholder once");
  const payload=data.replace(/</g,"\\u003c").replace(/>/g,"\\u003e").replace(/&/g,"\\u0026");
  return template.slice(0,at)+payload+template.slice(at+PLACEHOLDER.length);
}
export function renderView(template,data) {
  const marker="__CORTHEX_VIEW_DATA__",at=template.indexOf(marker);
  if(at<0 || template.indexOf(marker,at+1)>=0)throw new Error("the view template must hold its placeholder once");
  // A replacement string interprets $', $` and $$ even after HTML escaping.
  // A callback inserts the exact JSON characters without template expansion.
  return template.replace(marker,()=>dataText(data));
}
const policies=new Map();
export async function pagePolicy(template) {
  if(!policies.has(template)) {
    const start=template.lastIndexOf("<script>")+"<script>".length;
    const script=template.slice(start,template.indexOf("</script>",start));
    const digest=new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(script)));
    policies.set(template,`default-src 'none'; script-src 'sha256-${btoa(String.fromCharCode(...digest))}'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`);
  }
  return policies.get(template);
}
function html(body,policy) {return new Response(body,{headers:{...COMMON_HEADERS,"Content-Type":"text/html; charset=utf-8","Content-Security-Policy":policy,"Cross-Origin-Opener-Policy":"same-origin"}});}
function jsonHeaders() {return {...COMMON_HEADERS,"Content-Type":"application/json; charset=utf-8","Content-Security-Policy":"default-src 'none'; frame-ancestors 'none'"};}
function json(data,status=200,head=false) {return new Response(head?null:JSON.stringify(data),{status,headers:jsonHeaders()});}
