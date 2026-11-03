// Checks the NEXUS server with an in-memory database: run `node --test test/`
// in this folder (Node 22.13 or later).

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { MAX_PROJECTS, handle, render } from "../src/app.js";
import { MAX_BYTES } from "../src/snapshot.js";
import { fakeD1 } from "./fake-d1.js";
import { testAccess } from "./access-fixture.js";

const template = readFileSync(new URL("../src/hub.html", import.meta.url), "utf8");
const access = await testAccess();
const CHECKED = access.ctx;

function snapshot(fields = {}) {
  return {
    schema: "corthex-hub/0.1",
    generator: "corthex-nexus 0.1.0",
    generated_at: "2026-01-12T10:00:00+09:00",
    project: { name: "acme-shop", title: "Acme Shop", team: true, language: "en", records: { kind: "notion", link: "https://example.com/records" } },
    ids: { REQ: "requirement", SPEC: "spec" },
    repos: { ".": { commit: "0123456789abcdef0123456789abcdef01234567", branch: "main", dirty: false, web: "https://github.com/example/acme-shop" } },
    stages: {
      "02-prd": {
        name: "PRD", human: "notion", truth: "human", source: "docs/02-prd/", source_state: "found", read: true,
        files: 1, items: 1, copied: { oldest: "2026-01-11T09:00", newest: "2026-01-11T09:00" }, skipped: { binary: 1 },
        state: "done", checkpoint: "PRD approved in the kickoff review", checkpoint_date: "2026-01-12",
      },
    },
    items: [{ id: "REQ-001", kind: "requirement", stage: "02-prd", where: "docs/02-prd/requirements.md:3", title: "Send an order confirmation", priority: "Must", links: ["SPEC-001"] }],
    checks: [{ rule: "unknown-ref", level: "warn", by: "scan", stage: "02-prd", message: "SPEC-001 is mentioned but not defined", refs: ["SPEC-001"], args: { id: "SPEC-001" } }],
    summary: { items: 1, kinds: { requirement: 1 }, checks: { error: 0, warn: 1, info: 0 }, states: { done: 1, unknown: 12 } },
    truncated: false,
    ...fields,
  };
}

function server(env = {}) {
  const settings = { DB: fakeD1(), NEXUS_LANGUAGE: "en", ...access.env, ...env };
  return async function call(method, path, options = {}) {
    const { body, headers = {} } = options;
    const ctx = "ctx" in options ? options.ctx : CHECKED;
    const init = { method, headers: { ...access.headers(), ...headers } };
    if (body !== undefined) {
      init.body = typeof body === "string" || body instanceof Uint8Array ? body : JSON.stringify(body);
      if (!("Content-Type" in init.headers)) init.headers["Content-Type"] = "application/json";
    }
    const response = await handle(new Request("https://nexus.example.com" + path, init), settings, ctx, template);
    const text = await response.text();
    return { status: response.status, headers: response.headers, text, data: () => JSON.parse(text) };
  };
}

function pageData(html) {
  const open = '<script id="hub-data" type="application/json">';
  const start = html.indexOf(open) + open.length;
  return JSON.parse(html.slice(start, html.indexOf("</script>", start)));
}

test("refuses every request that Cloudflare Access did not check", async () => {
  const call = server();
  for (const [method, path] of [["GET", "/"], ["GET", "/api/snapshots"], ["POST", "/api/snapshots"], ["DELETE", "/api/snapshots/acme-shop"], ["GET", "/nothing"]]) {
    for (const ctx of [{}, undefined]) {
      const reply = await call(method, path, { ctx, body: method === "POST" ? snapshot() : undefined });
      assert.equal(reply.status, 403, `${method} ${path}`);
      assert.match(reply.data().error, /Cloudflare Access did not check this request/);
    }
  }
  assert.equal((await call("GET", "/api/snapshots")).data().projects.length, 0);
});

test("ACCESS_AUD pins the Access application", async () => {
  assert.equal((await server({ ACCESS_AUD: "other-aud, test-aud" })("GET", "/")).status, 200);
  const refused = await server({ ACCESS_AUD: "other-aud" })("GET", "/");
  assert.equal(refused.status, 403);
  assert.match(refused.data().error, /ACCESS_AUD/);
});

test("stores snapshots and counts revisions", async () => {
  const call = server();
  let reply = await call("POST", "/api/snapshots", { body: snapshot() });
  assert.equal(reply.status, 200, reply.text);
  assert.deepEqual(reply.data(), { name: "acme-shop", revision: 1 });
  reply = await call("POST", "/api/snapshots", { body: snapshot() });
  assert.deepEqual(reply.data(), { name: "acme-shop", revision: 2 });
  const [entry] = (await call("GET", "/api/snapshots")).data().projects;
  assert.equal(entry.name, "acme-shop");
  assert.equal(entry.revision, 2);
  assert.equal(entry.generated_at, "2026-01-12T10:00:00+09:00");
  assert.equal(entry.bytes, Buffer.byteLength(JSON.stringify(snapshot())));
  assert.ok(Date.parse(entry.received_at) > 0);
  assert.deepEqual((await call("GET", "/api/snapshots/acme-shop")).data(), snapshot());
  assert.equal((await call("GET", "/api/snapshots/blog")).status, 404);
});

test("keeps the newer snapshot of a project", async () => {
  const call = server();
  await call("POST", "/api/snapshots", { body: snapshot({ generated_at: "2026-01-12T11:00:00+09:00", truncated: true }) });
  const older = await call("POST", "/api/snapshots", { body: snapshot({ generated_at: "2026-01-12T01:30:00Z" }) });
  assert.equal(older.status, 409);
  assert.equal(older.data().code, "older_snapshot");
  assert.equal(older.data().stored_at, "2026-01-12T11:00:00+09:00");
  assert.equal((await call("GET", "/api/snapshots/acme-shop")).data().truncated, true);
  const ahead = new Date(Date.now() + 60 * 60 * 1000).toISOString();
  const future = await call("POST", "/api/snapshots", { body: snapshot({ generated_at: ahead }) });
  assert.equal(future.status, 400);
  assert.match(future.data().error, /dated in the future/);
});

test("refuses snapshots that the page could not show", async () => {
  const call = server();
  const many = Array.from({ length: 3001 }, (_, index) => ({ id: `REQ-${index}`, kind: "requirement", stage: "02-prd" }));
  const cases = [
    ["{", /not JSON/],
    ["[]", /not a JSON object/],
    [snapshot({ schema: "corthex-hub/9.9" }), /corthex-hub\/0\.1 format/],
    [snapshot({ project: { name: "Acme Shop" } }), /project\.name/],
    [snapshot({ project: { name: "acme-shop", team: "yes" } }), /bad project\.team/],
    [snapshot({ generated_at: "2026-01-12T10:00:00" }), /time zone/],
    [snapshot({ generated_at: undefined }), /time zone/],
    [snapshot({ stages: [] }), /bad stages/],
    [snapshot({ stages: { "02-prd": { files: "1" } } }), /bad stages\.02-prd\.files/],
    [snapshot({ repos: { ".": { commit: 7 } } }), /bad repos\.\.\.commit/],
    [snapshot({ ids: { REQ: 1 } }), /bad ids\.REQ/],
    [snapshot({ items: {} }), /bad items/],
    [snapshot({ items: many }), /bad items/],
    [snapshot({ items: [{ kind: "requirement", stage: "02-prd" }] }), /bad items\[0\]\.id/],
    [snapshot({ items: [{ id: "REQ-001", kind: "requirement", stage: "02-prd", links: [7] }] }), /bad items\[0\]\.links/],
    [snapshot({ checks: [{ rule: "review", level: "fatal", message: "x" }] }), /bad checks\[0\]\.level/],
    [snapshot({ checks: [{ rule: "review", level: "warn", message: "x", refs: "REQ-001" }] }), /bad checks\[0\]\.refs/],
    [snapshot({ summary: { items: "1" } }), /bad summary\.items/],
    [snapshot({ summary: undefined }), /bad summary/],
  ];
  for (const [body, message] of cases) {
    const reply = await call("POST", "/api/snapshots", { body });
    assert.equal(reply.status, 400, String(message));
    assert.match(reply.data().error, message);
  }
  assert.deepEqual((await call("GET", "/api/snapshots")).data().projects, []);
});

test("limits the size, the type and the origin of a write", async () => {
  const call = server();
  const big = snapshot({ items: [{ id: "REQ-001", kind: "requirement", stage: "02-prd", title: "x".repeat(MAX_BYTES) }] });
  assert.equal((await call("POST", "/api/snapshots", { body: big })).status, 413);
  const text = await call("POST", "/api/snapshots", { body: snapshot(), headers: { "Content-Type": "text/plain" } });
  assert.equal(text.status, 415);
  for (const site of ["cross-site", "same-site"]) {
    const reply = await call("POST", "/api/snapshots", { body: snapshot(), headers: { "Sec-Fetch-Site": site } });
    assert.equal(reply.status, 403, site);
    assert.match(reply.data().error, /another site/);
  }
  const bytes = new Uint8Array([0x7b, 0xff, 0x7d]);
  assert.match((await call("POST", "/api/snapshots", { body: bytes })).data().error, /not UTF-8/);
  const same = await call("POST", "/api/snapshots", { body: snapshot(), headers: { "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json; charset=utf-8" } });
  assert.equal(same.status, 200, same.text);
});

test("limits the number of projects", async () => {
  const call = server();
  for (let index = 0; index < MAX_PROJECTS; index += 1) {
    const reply = await call("POST", "/api/snapshots", { body: snapshot({ project: { name: `project-${index}` } }) });
    assert.equal(reply.status, 200, reply.text);
  }
  const full = await call("POST", "/api/snapshots", { body: snapshot() });
  assert.equal(full.status, 409);
  assert.equal(full.data().code, "too_many_projects");
  assert.equal((await call("POST", "/api/snapshots", { body: snapshot({ project: { name: "project-0" } }) })).data().revision, 2);
});

test("keeps the limit when new projects arrive together", async () => {
  const call = server();
  for (let index = 0; index < MAX_PROJECTS - 1; index += 1) {
    await call("POST", "/api/snapshots", { body: snapshot({ project: { name: `project-${index}` } }) });
  }
  const replies = await Promise.all(["late-a", "late-b"].map((name) => call("POST", "/api/snapshots", { body: snapshot({ project: { name } }) })));
  assert.deepEqual(replies.map((reply) => reply.status).sort(), [200, 409]);
  assert.equal((await call("GET", "/api/snapshots")).data().projects.length, MAX_PROJECTS);
});

test("removes a project", async () => {
  const call = server();
  await call("POST", "/api/snapshots", { body: snapshot() });
  assert.equal((await call("DELETE", "/api/snapshots/acme-shop", { headers: { "Sec-Fetch-Site": "cross-site" } })).status, 403);
  assert.deepEqual((await call("DELETE", "/api/snapshots/acme-shop")).data(), { name: "acme-shop", removed: true });
  assert.equal((await call("GET", "/api/snapshots/acme-shop")).status, 404);
  assert.equal((await call("DELETE", "/api/snapshots/acme-shop")).status, 404);
});

test("serves the hub page with the stored snapshots", async () => {
  const call = server();
  await call("POST", "/api/snapshots", { body: snapshot({ project: { name: "zoo", title: "Zoo" } }) });
  await call("POST", "/api/snapshots", { body: snapshot() });
  const reply = await call("GET", "/");
  assert.equal(reply.status, 200);
  assert.equal(reply.headers.get("Content-Type"), "text/html; charset=utf-8");
  assert.equal(reply.headers.get("Cache-Control"), "no-store");
  const data = pageData(reply.text);
  assert.equal(data.schema, "corthex-hub-page/0.2");
  assert.deepEqual(data.spaces, {});
  assert.equal(data.origin, "server");
  assert.equal(data.lang, "en");
  assert.ok(Date.parse(data.generated_at) > 0);
  assert.deepEqual(data.projects.map((p) => p.project.name), ["acme-shop", "zoo"]);
  assert.deepEqual(data.projects[0], snapshot());
  assert.deepEqual(data.missing, []);
  assert.equal(pageData((await server({ NEXUS_LANGUAGE: "ko" })("GET", "/")).text).lang, "ko");
  const head = await call("HEAD", "/");
  assert.equal(head.status, 200);
  assert.equal(head.text, "");
});

test("the page allows only its own script and cannot be framed", async () => {
  const reply = await server()("GET", "/");
  const policy = reply.headers.get("Content-Security-Policy");
  const start = reply.text.lastIndexOf("<script>") + "<script>".length;
  const script = reply.text.slice(start, reply.text.indexOf("</script>", start));
  const hash = createHash("sha256").update(script, "utf8").digest("base64");
  assert.match(policy, /^default-src 'none'; /);
  assert.ok(policy.includes(`script-src 'sha256-${hash}'`), policy);
  assert.ok(policy.includes("frame-ancestors 'none'"));
  assert.ok(!policy.includes("unsafe-eval"));
  assert.equal(reply.headers.get("X-Frame-Options"), "DENY");
});

test("stored text cannot close the page's data block", async () => {
  const call = server();
  const title = "Shop </script><script>alert(1)</script> & <b>";
  await call("POST", "/api/snapshots", { body: snapshot({ project: { name: "acme-shop", title } }) });
  const html = (await call("GET", "/")).text;
  assert.equal(html.split("</script>").length, template.split("</script>").length);
  assert.equal(pageData(html).projects[0].project.title, title);
  assert.throws(() => render("<html></html>", "{}"), /placeholder/);
});

test("answers unknown paths and methods without data", async () => {
  const call = server();
  assert.equal((await call("GET", "/admin")).status, 404);
  assert.equal((await call("GET", "/api/snapshots/Acme_Shop")).status, 404);
  const put = await call("PUT", "/api/snapshots", { body: snapshot() });
  assert.equal(put.status, 405);
  assert.equal(put.headers.get("Allow"), "GET, HEAD, POST");
  assert.equal((await call("POST", "/", { body: snapshot() })).status, 405);
});

test("a failure shows no stored text", async () => {
  const broken = { prepare() { throw new Error("SELECT body FROM snapshots: secret project text"); } };
  const reply = await server({ DB: broken })("GET", "/");
  assert.equal(reply.status, 500);
  assert.equal(reply.data().error, "the server could not finish the request");
  const unbound = await server({ DB: undefined })("GET", "/");
  assert.equal(unbound.status, 500);
  assert.match(unbound.data().error, /no D1 database bound as DB/);
});
