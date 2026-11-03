// Actual default responses: synthetic Access, no account or database/network.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {handle} from "../src/app.js";
import {ROUTES} from "../src/preflight.js";
import {testAccess} from "./access-fixture.js";

const manifest=JSON.parse(readFileSync(0,"utf8")),access=await testAccess();
const env={...access.env,NEXUS_LANGUAGE:"en"}; // Missing DB deliberately exercises internal/500.
const template=readFileSync(new URL("../src/hub.html",import.meta.url),"utf8");
// Stage 06's common headers, independently asserted rather than importing
// the implementation's header constant as its own expected value.
const common={"Cache-Control":"no-store","Referrer-Policy":"no-referrer",
  "X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY",
  "X-Robots-Tag":"noindex, nofollow","Cross-Origin-Resource-Policy":"same-origin"};
const values={project:"qa-offline-default",part:"nexus",stage:"05-erd",comment:"nc_aaaaaaaaaaaa",
  proposal:"np_bbbbbbbbbbbb",edit:"ne_cccccccccccc",checkpoint:"nk_dddddddddddd",
  entry:"nc_aaaaaaaaaaaa",file:"view.deadbeef.js"};
const records=[],originalError=console.error;
try {
  for(const selected of manifest) {
    const route=ROUTES.find(row=>row.operation===selected.operation);assert.ok(route);
    const kind=route.role==="user"?"user":"agent",trace="1234567890abcdef-ICN";
    const path=selected.path.replace(/\{(\w+)\}/g,(_,name)=>values[name]);
    const method=selected.status===405?"PATCH":selected.method.toUpperCase();
    const headers={...access.headers(kind),Accept:selected.media,"Cf-Ray":trace,
      "Nexus-Session":"offline-default-session","Idempotency-Key":'"nw_aaaaaaaaaaaa"'};
    const logs=[];console.error=(...args)=>logs.push(args);
    const response=await handle(new Request("https://nexus.example.com"+path,{method,headers}),env,access.ctx,template);
    const text=await response.text();
    assert.equal(response.status,selected.status);
    assert.equal(response.headers.get("Content-Type").split(";")[0],selected.media);
    for(const [name,value]of Object.entries(common))assert.equal(response.headers.get(name),value,name);
    const policy=selected.media.includes("json")?"default-src 'none'; frame-ancestors 'none'":
      "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
    assert.equal(response.headers.get("Content-Security-Policy"),policy);
    assert.equal(response.headers.get("Allow"),selected.status===405?selected.allow:null);
    const value=selected.media.includes("json")?JSON.parse(text):text;
    if(typeof value==="object") {
      assert.equal(value.code,selected.status===500?"internal":"method_not_allowed");
      assert.equal(value.traceId,trace);
    } else {
      assert.ok(value.includes(trace));
      assert.ok(value.includes("<h1>"+(selected.status===500?"Something went wrong":"Method not allowed")+"</h1>"));
    }
    assert.equal(logs.length,1);assert.equal(logs[0][1].traceId,trace);
    records.push({operation:selected.operation,media:selected.media,example:selected.example,value});
  }
} finally {console.error=originalError;}
process.stdout.write(JSON.stringify(records));
