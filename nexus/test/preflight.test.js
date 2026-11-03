import assert from "node:assert/strict";
import { test } from "node:test";
import { ROUTES, pathRoute, requestHeaders } from "../src/preflight.js";

const request = (method, path, headers) => new Request("https://nexus.example.com" + path, { method, headers });
const ID = "0123456789ab";
const values = { project: "acme-shop", part: "_", stage: "02-prd", pictureStage: "05-erd", file: "view.01234567.js", comment: "nc_" + ID, proposal: "np_" + ID, edit: "ne_" + ID, checkpoint: "nk_" + ID, entry: "nd_" + ID };
const path = (route) => route.path.replace(/\{(\w+)\}/g, (_, name) => values[name]);
const code = (value) => (error) => error.code === value;
const headers = { "Idempotency-Key": '"nw_' + ID + '"', "Nexus-Session": "agent-one" };

test("all 32 contracted operations dispatch, and every GET also takes HEAD", () => {
  assert.equal(ROUTES.length, 32);
  assert.equal(new Set(ROUTES.map((route) => route.operation)).size, 32);
  for (const route of ROUTES) {
    assert.equal(pathRoute(request(route.method, path(route))).operation, route.operation);
    if (route.method === "GET") assert.equal(pathRoute(request("HEAD", path(route))).operation, route.operation);
  }
});

test("invalid path values get resource-specific 404s and never reach a handler", () => {
  for (const [path, error] of [
    ["/api/snapshots/Bad", "project_not_found"], ["/api/spaces/acme/pictures/Bad/05-erd", "part_not_found"],
    ["/api/spaces/acme/pictures/_/02-prd", "not_found"], ["/api/spaces/acme/overview/_/other", "not_found"],
    ["/api/spaces/acme/comments/nc_iiiiiiiiiiii", "comment_not_found"], ["/api/spaces/acme/proposals/nc_" + ID, "proposal_not_found"],
    ["/api/spaces/acme/edits/wrong", "edit_not_found"], ["/api/spaces/acme/checkpoints/wrong", "checkpoint_not_found"],
    ["/api/spaces/acme/claims/np_" + ID, "entry_not_found"], ["/api/snapshots/a%2fb", "project_not_found"],
    ["/code/private.js", "not_found"], ["/api/snapshots/%ZZ", "not_found"], ["/nothing", "not_found"],
  ]) assert.throws(() => pathRoute(request("GET", path)), code(error), path);
});

test("known paths reject methods with all supported methods in Allow", () => {
  assert.throws(() => pathRoute(request("PATCH", "/api/snapshots")), (error) => error.code === "method_not_allowed" && error.headers.Allow === "GET, HEAD, POST");
  assert.throws(() => pathRoute(request("OPTIONS", "/api/snapshots/acme")), (error) => error.code === "method_not_allowed" && error.headers.Allow === "GET, HEAD, DELETE");
});

test("cross-site refusal precedes kind, then write ID precedes the agent session", () => {
  const route = pathRoute(request("POST", "/api/spaces/acme/proposals"));
  assert.throws(() => requestHeaders(request("POST", "/api/spaces/acme/proposals", { "Sec-Fetch-Site": "same-site" }), route, "user"), code("cross_site"));
  assert.throws(() => requestHeaders(request("POST", "/api/spaces/acme/proposals"), route, "user"), code("agent_only"));
  assert.throws(() => requestHeaders(request("POST", "/api/spaces/acme/proposals"), route, null), code("no_kind"));
  assert.throws(() => requestHeaders(request("POST", "/api/spaces/acme/proposals"), route, "agent"), (error) => error.fields.field === "Idempotency-Key");
  assert.throws(() => requestHeaders(request("POST", "/api/spaces/acme/proposals", { "Idempotency-Key": headers["Idempotency-Key"] }), route, "agent"), (error) => error.fields.field === "Nexus-Session");
});

test("every write role and header policy agrees with the request-name table", () => {
  for (const route of ROUTES.filter((route) => route.role)) {
    const kind = route.role === "either" ? "agent" : route.role;
    const result = requestHeaders(request(route.method, path(route), headers), route, kind);
    assert.equal(result.write, route.writeName ? "nw_" + ID : null);
    assert.equal(result.session, kind === "agent" ? "agent-one" : null);
    assert.throws(() => requestHeaders(request(route.method, path(route), headers), route, null), code("no_kind"));
    if (route.role !== "either") assert.throws(() => requestHeaders(request(route.method, path(route), headers), route, kind === "user" ? "agent" : "user"), code(kind === "user" ? "user_only" : "agent_only"));
  }
});

test("reads, pushes and removals accept a checked identity with neither kind", () => {
  for (const route of ROUTES.filter((route) => !route.role)) assert.doesNotThrow(() => requestHeaders(request(route.method, path(route)), route, null));
});

test("session labels are required only where specified and user's session header is ignored", () => {
  const comment = pathRoute(request("POST", "/api/spaces/acme/comments"));
  assert.equal(requestHeaders(request("POST", "/api/spaces/acme/comments", { ...headers, "Nexus-Session": "bad session" }), comment, "user").session, null);
  for (const key of ["nw_" + ID, '"nw_iiiiiiiiiiii"', '"nw_' + ID + '" extra']) assert.throws(() => requestHeaders(request("POST", "/api/spaces/acme/comments", { ...headers, "Idempotency-Key": key }), comment, "agent"), (error) => error.fields.field === "Idempotency-Key");
  const todo = pathRoute(request("GET", "/api/spaces/acme/todo"));
  assert.equal(requestHeaders(request("GET", "/api/spaces/acme/todo"), todo, "user").session, null);
  assert.throws(() => requestHeaders(request("GET", "/api/spaces/acme/todo", { "Nexus-Session": "bad session" }), todo, "user"), (error) => error.fields.field === "Nexus-Session");
});
