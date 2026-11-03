import { AccessVerifier, requireKind } from "./access.js";
import { Problem } from "./problem.js";

export const STAGES = Object.freeze(["01-domain", "02-prd", "03-user-flow", "04-functional-spec", "05-erd", "06-api", "07-sitemap", "08-screen-states", "09-mockup", "10-wbs", "11-development", "12-qa", "13-presentation"]);
const NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const ID = /^[0-9a-hjkmnp-tv-z]{12}$/;
const SESSION = /^[A-Za-z0-9._:-]{1,100}$/;
const rules = [
  ["getHubPage", "GET", "/"],
  ["getPictureViewPage", "GET", "/pictures/{project}/{part}/{pictureStage}"],
  ["getStageOverviewPage", "GET", "/overview/{project}/{part}/{stage}"],
  ["getViewCode", "GET", "/code/{file}"],
  ["pushSnapshot", "POST", "/api/snapshots"],
  ["listSnapshots", "GET", "/api/snapshots"],
  ["getSnapshot", "GET", "/api/snapshots/{project}"],
  ["removeProject", "DELETE", "/api/snapshots/{project}"],
  ["getHeldCommit", "GET", "/api/snapshots/{project}/held"],
  ["getRemovalDryRun", "GET", "/api/snapshots/{project}/removal"],
  ["getPicture", "GET", "/api/spaces/{project}/pictures/{part}/{pictureStage}"],
  ["getStageOverview", "GET", "/api/spaces/{project}/overview/{part}/{stage}"],
  ["getAgentTodo", "GET", "/api/spaces/{project}/todo"],
  ["leaveComment", "POST", "/api/spaces/{project}/comments", "either", "comment"],
  ["getComment", "GET", "/api/spaces/{project}/comments/{comment}"],
  ["replyToComment", "POST", "/api/spaces/{project}/comments/{comment}/replies", "either", "reply"],
  ["markAnswered", "POST", "/api/spaces/{project}/comments/{comment}/answered", "either", "answered"],
  ["recordDecision", "POST", "/api/spaces/{project}/comments/{comment}/decisions", "agent", "decision"],
  ["makeProposal", "POST", "/api/spaces/{project}/proposals", "agent", "proposal"],
  ["getProposal", "GET", "/api/spaces/{project}/proposals/{proposal}"],
  ["withdrawProposal", "POST", "/api/spaces/{project}/proposals/{proposal}/withdraw", "agent", "withdraw-proposal"],
  ["acceptProposal", "POST", "/api/spaces/{project}/proposals/{proposal}/accept", "user", "accept"],
  ["dismissProposal", "POST", "/api/spaces/{project}/proposals/{proposal}/dismiss", "user", "dismiss-proposal"],
  ["getEdit", "GET", "/api/spaces/{project}/edits/{edit}"],
  ["reportEdit", "POST", "/api/spaces/{project}/edits/{edit}/report", "agent", "report-edit"],
  ["dismissEdit", "POST", "/api/spaces/{project}/edits/{edit}/dismiss", "user", "dismiss-edit"],
  ["passCheckpoint", "POST", "/api/spaces/{project}/checkpoints", "user", "checkpoint"],
  ["getCheckpoint", "GET", "/api/spaces/{project}/checkpoints/{checkpoint}"],
  ["withdrawCheckpoint", "POST", "/api/spaces/{project}/checkpoints/{checkpoint}/withdraw", "user", "withdraw-checkpoint"],
  ["reportCheckpoint", "POST", "/api/spaces/{project}/checkpoints/{checkpoint}/report", "agent", "report-checkpoint"],
  ["claimEntry", "POST", "/api/spaces/{project}/claims/{entry}", "agent"],
  ["releaseEntry", "DELETE", "/api/spaces/{project}/claims/{entry}", "agent"],
];

export const ROUTES = Object.freeze(rules.map(([operation, method, path, role, writeName]) => ({
  operation, method, path, role, writeName,
  names: [...path.matchAll(/\{(\w+)\}/g)].map((match) => match[1]),
  pattern: new RegExp("^" + path.replace(/\{\w+\}/g, "([^/]+)") + "$"),
})));

function validate(name, value) {
  if (name === "project" && (!NAME.test(value) || value.length > 100)) return "project_not_found";
  if (name === "part" && value !== "_" && (!NAME.test(value) || value.length > 100)) return "part_not_found";
  if ((name === "stage" && !STAGES.includes(value)) || (name === "pictureStage" && !["01-domain", "05-erd", "07-sitemap"].includes(value))) return "not_found";
  if (name === "file" && !/^[a-z0-9][a-z0-9-]{0,63}\.[0-9a-f]{8}\.(?:js|css|woff2)$/.test(value)) return "not_found";
  const prefix = { comment: "nc_", proposal: "np_", edit: "ne_", checkpoint: "nk_" }[name];
  if (prefix && (!value.startsWith(prefix) || !ID.test(value.slice(3)))) return name + "_not_found";
  if (name === "entry" && (!/^n[cdek]_/.test(value) || !ID.test(value.slice(3)))) return "entry_not_found";
  return null;
}

export function pathRoute(request) {
  const pathname = new URL(request.url).pathname;
  const matches = ROUTES.map((route) => ({ route, values: route.pattern.exec(pathname)?.slice(1) })).filter((match) => match.values);
  if (!matches.length) throw new Problem("not_found", "no such path");
  const parsed = {};
  const first = matches[0];
  for (let i = 0; i < first.route.names.length; i++) {
    const name = first.route.names[i];
    let value;
    try { value = decodeURIComponent(first.values[i]); }
    catch { throw new Problem("not_found", "no such path"); }
    const failure = validate(name, value);
    if (failure) throw new Problem(failure, "no such path value");
    parsed[name === "pictureStage" ? "stage" : name] = name === "part" && value === "_" ? "" : value;
  }
  const selected = matches.find(({ route }) => route.method === request.method || (route.method === "GET" && request.method === "HEAD"));
  if (!selected) {
    const allowed = ["GET", "HEAD", "POST", "DELETE"].filter((method) => matches.some(({ route }) => route.method === method || (method === "HEAD" && route.method === "GET")));
    throw new Problem("method_not_allowed", "method not allowed", {}, { Allow: allowed.join(", ") });
  }
  return { ...selected.route, params: parsed };
}

export function requestHeaders(request, route, kind) {
  const change = request.method !== "GET" && request.method !== "HEAD";
  const site = request.headers.get("Sec-Fetch-Site");
  if (change && site && site !== "same-origin" && site !== "none") throw new Problem("cross_site", "a request from another site cannot change NEXUS");
  if (route.role) requireKind(kind, route.role);
  let write = null;
  if (route.writeName) {
    const match = /^"(nw_[0-9a-hjkmnp-tv-z]{12})"$/.exec(request.headers.get("Idempotency-Key") || "");
    if (!match) throw new Problem("invalid_request", "send the quoted write ID in Idempotency-Key", { field: "Idempotency-Key" });
    write = match[1];
  }
  let session = null;
  if ((route.role && kind === "agent") || route.operation === "getAgentTodo") {
    session = request.headers.get("Nexus-Session");
    if ((route.role && !session) || (session !== null && !SESSION.test(session))) throw new Problem("invalid_request", "send a session label of 1 to 100 ASCII letters, digits, dot, underscore, colon or hyphen", { field: "Nexus-Session" });
  }
  return { write, session };
}

const verifier = new AccessVerifier();
export async function preflight(request, env, ctx) {
  const kind = await verifier.verify(request, env, ctx);
  const route = pathRoute(request);
  return { ...route, kind, ...requestHeaders(request, route, kind) };
}
