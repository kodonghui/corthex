// TASK-201/209: real synthetic RSA signatures, with no external requests.
import assert from "node:assert/strict";
import { test } from "node:test";
import { AccessVerifier, requireAccessContext, requireKind } from "../src/access.js";

const NOW = 1800000000000;
const TEAM = "https://access.example.com";
const env = { ACCESS_AUD: "this-app", ACCESS_TEAM_DOMAIN: "access.example.com" };
const ctx = { access: { aud: ["this-app"] } };
const pair = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const second = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const jwk = { ...await crypto.subtle.exportKey("jwk", pair.publicKey), kid: "key-one", alg: "RS256", use: "sig" };
const nextJwk = { ...await crypto.subtle.exportKey("jwk", second.publicKey), kid: "key-two", alg: "RS256", use: "sig" };
const b64 = (value) => Buffer.from(typeof value === "string" ? value : JSON.stringify(value)).toString("base64url");

async function token(changes = {}, header = {}, signing = pair.privateKey) {
  const parts = [b64({ alg: "RS256", kid: "key-one", ...header }), b64({ iss: TEAM, aud: ["this-app"], exp: NOW / 1000 + 300, sub: "synthetic-user", ...changes })];
  parts.push(Buffer.from(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", signing, new TextEncoder().encode(parts.join(".")))).toString("base64url"));
  return parts.join(".");
}
const request = (jwt) => new Request("https://nexus.example.com/", { headers: jwt ? { "Cf-Access-Jwt-Assertion": jwt } : {} });
const refusal = (code) => (error) => error.code === code && error.status === (code === "internal" ? 500 : 403);

function fixture(answer = () => ({ keys: [jwk] })) {
  const calls = [];
  let time = NOW;
  const verifier = new AccessVerifier({ now: () => time, fetcher: async (url, options) => {
    calls.push({ url, options });
    assert.equal(url, TEAM + "/cdn-cgi/access/certs");
    assert.equal(options.redirect, "manual");
    assert.deepEqual(options.headers, { Accept: "application/json" });
    const value = answer(calls.length);
    return value instanceof Response ? value : Response.json(value);
  } });
  return { verifier, calls, advance: (ms) => { time += ms; } };
}

test("Access context and audience refusal comes before token parsing or I/O", async () => {
  const { verifier, calls } = fixture();
  await assert.rejects(verifier.verify(request("not.a.token"), env, {}), refusal("access_missing"));
  await assert.rejects(verifier.verify(request("not.a.token"), env, { access: { aud: "another-app" } }), refusal("access_other_app"));
  assert.throws(() => requireAccessContext({}, ctx), refusal("access_other_app"));
  assert.equal(calls.length, 0);
});

test("verified user, agent and neither return only the kind, never identity", async () => {
  const { verifier } = fixture();
  assert.equal(await verifier.verify(request(await token({ email: "synthetic@example.com" })), env, ctx), "user");
  assert.equal(await verifier.verify(request(await token({ sub: "", common_name: "synthetic-client" })), env, ctx), "agent");
  assert.equal(await verifier.verify(request(await token({ sub: "" })), env, ctx), null);
  assert.equal(await verifier.verify(request(await token({ sub: 42, common_name: "synthetic-client" })), env, ctx), null);
  assert.equal(await verifier.verify(request(await token({ sub: null, common_name: "synthetic-client" })), env, ctx), null);
  assert.equal(await verifier.verify(request(await token({ sub: undefined, common_name: "synthetic-client" })), env, ctx), null);
});

test("missing, malformed, unsigned and unsupported critical headers are refused without keys", async () => {
  const { verifier, calls } = fixture();
  for (const jwt of [undefined, "one", "a.b.c.d", "!.e30.e30", await token({}, { alg: "none" }), await token({}, { crit: ["unknown"] }), await token({}, { b64: false })]) {
    await assert.rejects(verifier.verify(request(jwt), env, ctx), refusal("access_missing"));
  }
  assert.equal(calls.length, 0);
});

test("a forged signature, wrong issuer, expiry and future not-before fail closed", async () => {
  const { verifier } = fixture();
  const invalid = [
    await token({}, {}, second.privateKey),
    await token({ iss: "https://attacker.example.com" }),
    await token({ exp: NOW / 1000 }),
    await token({ exp: "later" }),
    await token({ nbf: NOW / 1000 + 1 }),
    await token({ nbf: "tomorrow" }),
  ];
  for (const jwt of invalid) await assert.rejects(verifier.verify(request(jwt), env, ctx), refusal("access_missing"));
  await assert.rejects(verifier.verify(request(await token({ aud: ["another-app"] })), env, ctx), refusal("access_other_app"));
});

test("the team host is configured and token jku/iss cannot choose an endpoint", async () => {
  const { verifier, calls } = fixture();
  const jwt = await token({}, { jku: "http://127.0.0.1/private", x5u: "https://attacker.example.com/keys" });
  assert.equal(await verifier.verify(request(jwt), env, ctx), "user");
  assert.equal(calls[0].url, TEAM + "/cdn-cgi/access/certs");
  for (const domain of ["", "http://access.example.com", "https://name:password@example.com", "access.example.com/private", "access.example.com:444"]) {
    await assert.rejects(verifier.verify(request(jwt), { ...env, ACCESS_TEAM_DOMAIN: domain }, ctx), refusal("internal"));
  }
  assert.equal(calls.length, 1);
});

test("public keys are shared across concurrent requests, expire within an hour and refresh on rotation", async () => {
  const { verifier, calls, advance } = fixture((n) => ({ keys: n < 3 ? [jwk] : [jwk, nextJwk] }));
  const jwt = await token({ exp: NOW / 1000 + 7200 });
  assert.deepEqual(await Promise.all(Array.from({ length: 20 }, () => verifier.verify(request(jwt), env, ctx))), Array(20).fill("user"));
  assert.equal(calls.length, 1);
  advance(3600001);
  assert.equal(await verifier.verify(request(jwt), env, ctx), "user");
  assert.equal(calls.length, 2);
  assert.equal(await verifier.verify(request(await token({ exp: NOW / 1000 + 7200 }, { kid: "key-two" }, second.privateKey)), env, ctx), "user");
  assert.equal(calls.length, 3);
});

test("unknown key, redirected keys and bad keys never authenticate", async () => {
  const first = fixture();
  await assert.rejects(first.verifier.verify(request(await token({}, { kid: "unknown" })), env, ctx), refusal("access_missing"));
  assert.equal(first.calls.length, 2);
  for (const answer of [() => new Response(null, { status: 302, headers: { Location: "https://attacker.example.com" } }), () => ({ keys: [] }), () => ({ keys: [jwk, jwk] }), () => ({ keys: [{ ...jwk, n: "bad" }] })]) {
    const { verifier } = fixture(answer);
    await assert.rejects(verifier.verify(request(await token()), env, ctx), refusal("internal"));
  }
});

test("a failed rotation request does not hide or discard still-valid known keys", async () => {
  let rejectRefresh;
  let calls = 0;
  let time = NOW;
  const verifier = new AccessVerifier({ now: () => time, fetcher: () => {
    if (++calls === 1) return Promise.resolve(Response.json({ keys: [jwk] }));
    return new Promise((_, reject) => { rejectRefresh = reject; });
  } });
  const known = request(await token({ exp: NOW / 1000 + 7200 }));
  assert.equal(await verifier.verify(known, env, ctx), "user");
  const rotated = verifier.verify(request(await token({}, { kid: "unknown" })), env, ctx);
  const refused = assert.rejects(rotated, refusal("internal"));
  while (!rejectRefresh) await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(await verifier.verify(known, env, ctx), "user");
  rejectRefresh(new Error("synthetic key endpoint outage"));
  await refused;
  assert.equal(await verifier.verify(known, env, ctx), "user");
  assert.equal(calls, 2);
  time += 3600001;
  const expired = verifier.verify(known, env, ctx);
  const expiredRefusal = assert.rejects(expired, refusal("internal"));
  while (calls < 3) await new Promise((resolve) => setTimeout(resolve, 0));
  rejectRefresh(new Error("synthetic outage after cache expiry"));
  await expiredRefusal;
});

test("failed key retrieval is retryable even when the injected fetcher throws synchronously", async () => {
  let calls = 0;
  const verifier = new AccessVerifier({ now: () => NOW, fetcher: () => {
    if (++calls === 1) throw new Error("synthetic network outage");
    return Promise.resolve(Response.json({ keys: [jwk] }));
  } });
  const jwt = await token();
  await assert.rejects(verifier.verify(request(jwt), env, ctx), refusal("internal"));
  assert.equal(await verifier.verify(request(jwt), env, ctx), "user");
  assert.equal(calls, 2);
});

test("the default host fetch is called without a verifier receiver", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = function () {
    assert.ok(this === undefined || this === globalThis, "host fetch cannot receive a class instance");
    calls++;
    return Promise.resolve(Response.json({ keys: [jwk] }));
  };
  try {
    const verifier = new AccessVerifier({ now: () => NOW });
    assert.equal(await verifier.verify(request(await token()), env, ctx), "user");
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});

test("write roles distinguish user-only, agent-only and neither", () => {
  assert.doesNotThrow(() => requireKind("user", "either"));
  assert.doesNotThrow(() => requireKind("agent", "agent"));
  assert.throws(() => requireKind(null, "either"), refusal("no_kind"));
  assert.throws(() => requireKind("agent", "user"), (e) => e.code === "user_only" && e.fields.needs === "user");
  assert.throws(() => requireKind("user", "agent"), (e) => e.code === "agent_only" && e.fields.needs === "agent");
});
