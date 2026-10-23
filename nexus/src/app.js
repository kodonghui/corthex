// The NEXUS server: it stores the snapshots that `hub.py push` sends and
// serves the same hub page the plugin builds on the user's machine.
// Cloudflare Access protects the whole Worker; a request that Access did not
// check is refused, so a missing or broken Access setup shows no data.

import { MAX_BYTES, NAME, Refused, readSnapshot } from "./snapshot.js";
import { Store } from "./store.js";

const PAGE_SCHEMA = "corthex-hub-page/0.1";
const PLACEHOLDER = "__CORTHEX_HUB_DATA__";
export const MAX_PROJECTS = 30;

const COMMON = {
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "X-Robots-Tag": "noindex, nofollow",
  "Cross-Origin-Resource-Policy": "same-origin",
};

export async function handle(request, env, ctx, template) {
  try {
    return await route(request, env || {}, ctx, template);
  } catch (error) {
    if (error instanceof Refused) return json({ error: error.message }, error.status, error.headers);
    // The message may hold stored text, so only the kind of error is logged.
    console.error("nexus: request failed", error && error.name);
    return json({ error: "the server could not finish the request" }, 500);
  }
}

async function route(request, env, ctx, template) {
  checkAccess(ctx, env);
  const { pathname } = new URL(request.url);
  const method = request.method;
  if (pathname === "/") {
    allow(method, ["GET", "HEAD"]);
    return page(request, env, template);
  }
  if (pathname === "/api/snapshots") {
    allow(method, ["GET", "HEAD", "POST"]);
    return method === "POST" ? receive(request, env) : listing(request, env);
  }
  const match = /^\/api\/snapshots\/([^/]+)$/.exec(pathname);
  if (match) {
    allow(method, ["GET", "HEAD", "DELETE"]);
    const name = match[1];
    if (!NAME.test(name)) throw new Refused(404, "no such project");
    return method === "DELETE" ? remove(request, env, name) : snapshot(request, env, name);
  }
  throw new Refused(404, "not found");
}

function checkAccess(ctx, env) {
  const access = ctx && ctx.access;
  if (!access) {
    throw new Refused(403, "Cloudflare Access did not check this request; protect this Worker with Access first");
  }
  const wanted = String(env.ACCESS_AUD || "").split(",").map((aud) => aud.trim()).filter(Boolean);
  const audiences = [].concat(access.aud || []);
  if (wanted.length && !audiences.some((aud) => wanted.includes(aud))) {
    throw new Refused(403, "another Access application than ACCESS_AUD names checked this request");
  }
}

function allow(method, methods) {
  if (!methods.includes(method)) throw new Refused(405, "method not allowed", { Allow: methods.join(", ") });
}

function store(env) {
  if (!env.DB) throw new Refused(500, "the Worker has no D1 database bound as DB");
  return new Store(env.DB);
}

// Browsers mark requests from other sites; only the user's own tools may change data.
function checkSameOrigin(request) {
  const site = request.headers.get("Sec-Fetch-Site");
  if (site && site !== "same-origin" && site !== "none") {
    throw new Refused(403, "a request from another site cannot change the hub");
  }
}

async function readBody(request) {
  const declared = Number(request.headers.get("Content-Length"));
  if (declared > MAX_BYTES) throw new Refused(413, `the snapshot is larger than ${MAX_BYTES} bytes`);
  const chunks = [];
  let size = 0;
  if (request.body) {
    const reader = request.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) {
        await reader.cancel();
        throw new Refused(413, `the snapshot is larger than ${MAX_BYTES} bytes`);
      }
      chunks.push(value);
    }
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return { text: new TextDecoder("utf-8", { fatal: true }).decode(bytes), size };
  } catch {
    throw new Refused(400, "the body is not UTF-8 text");
  }
}

async function receive(request, env) {
  checkSameOrigin(request);
  const type = request.headers.get("Content-Type") || "";
  if (!/^application\/json\s*(?:;|$)/i.test(type)) throw new Refused(415, "send the snapshot as application/json");
  const { text } = await readBody(request);
  const now = Date.now();
  const sent = readSnapshot(text, now);
  const db = store(env);
  const bytes = new TextEncoder().encode(sent.body).byteLength;
  const revision = await db.put(sent.name, sent.generatedMs, sent.generatedAt, new Date(now).toISOString(), sent.body, bytes, MAX_PROJECTS);
  if (revision === null) {
    const stored = await db.meta(sent.name);
    if (!stored) throw new Refused(409, `the hub already holds ${MAX_PROJECTS} projects; remove one with hub.py remove first`);
    throw new Refused(409, `the server holds a newer snapshot of ${sent.name}, made at ${stored.generated_at}; build it again and send that`);
  }
  return json({ name: sent.name, revision });
}

async function listing(request, env) {
  return json({ projects: await store(env).list() }, 200, {}, request.method === "HEAD");
}

async function snapshot(request, env, name) {
  const body = await store(env).body(name);
  if (body === null || body === undefined) throw new Refused(404, "no such project");
  return new Response(request.method === "HEAD" ? null : body, { headers: jsonHeaders() });
}

async function remove(request, env, name) {
  checkSameOrigin(request);
  if (!(await store(env).remove(name))) throw new Refused(404, "no such project");
  return json({ name, removed: true });
}

async function page(request, env, template) {
  const bodies = await store(env).bodies();
  const lang = String(env.NEXUS_LANGUAGE || "").toLowerCase().startsWith("ko") ? "ko" : "en";
  // The stored snapshots are already JSON, so the page data is put together as text.
  const data = `{"schema":"${PAGE_SCHEMA}","generated_at":"${new Date().toISOString()}","lang":"${lang}",` +
    `"origin":"server","projects":[${bodies.join(",")}],"missing":[]}`;
  const headers = {
    ...COMMON,
    "Content-Type": "text/html; charset=utf-8",
    "Content-Security-Policy": await pagePolicy(template),
    "Cross-Origin-Opener-Policy": "same-origin",
  };
  return new Response(request.method === "HEAD" ? null : render(template, data), { headers });
}

// The page template with the data in its JSON script block, as hub.py writes it.
export function render(template, data) {
  const at = template.indexOf(PLACEHOLDER);
  if (at < 0 || template.indexOf(PLACEHOLDER, at + 1) >= 0) throw new Error("the hub template must hold its placeholder once");
  // Inside <script>, "<" could end the block; JSON allows these escapes.
  const payload = data.replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");
  return template.slice(0, at) + payload + template.slice(at + PLACEHOLDER.length);
}

// Like the page's own policy, but the script is allowed by its hash instead of
// as any inline script, and no site may frame the page.
const policies = new Map();

export async function pagePolicy(template) {
  if (!policies.has(template)) {
    const start = template.lastIndexOf("<script>") + "<script>".length;
    const script = template.slice(start, template.indexOf("</script>", start));
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(script)));
    const hash = btoa(String.fromCharCode(...digest));
    policies.set(template, `default-src 'none'; script-src 'sha256-${hash}'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`);
  }
  return policies.get(template);
}

function jsonHeaders(extra) {
  return {
    ...COMMON,
    "Content-Type": "application/json; charset=utf-8",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    ...extra,
  };
}

function json(data, status = 200, extra = {}, headOnly = false) {
  return new Response(headOnly ? null : JSON.stringify(data), { status, headers: jsonHeaders(extra) });
}
