import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ERRORS, COMMON_HEADERS, Problem, problemDocument, problemResponse } from "../src/problem.js";

test("server error names equal the frozen OpenAPI error list", () => {
  const contract = readFileSync(new URL("../../docs/06-api/nexus.openapi.yaml", import.meta.url), "utf8");
  const list = /    ErrorCode:\s*\n\s*type: string\s*\n\s*enum: \[([^\]]+)\]/.exec(contract)[1].split(",").map((v) => v.trim());
  assert.deepEqual(Object.keys(ERRORS).sort(), list.sort());
  assert.throws(() => new Problem("not_a_contract_code", "invalid"));
  assert.throws(() => new Problem("internal", "invalid", { stored_text: "never expose" }));
});

test("Problem Details preserves the legacy error and one-line Unicode-safe limits", () => {
  const request = new Request("https://nexus.example.com/", { headers: { "Cf-Ray": "8f6c3b2a1d0e9f80-ICN" } });
  const document = problemDocument(request, new Problem("text_too_long", "line one\n" + "😀".repeat(400), { field: "text", limit: 2000 }));
  assert.equal(document.code, "text_too_long");
  assert.equal(document.status, 413);
  assert.equal(document.error, document.detail);
  assert.equal(document.traceId, "8f6c3b2a1d0e9f80-ICN");
  assert.equal(Array.from(document.detail).length, 300);
  assert.ok(!document.detail.includes("\n"));
  assert.equal(document.limit, 2000);
  assert.equal(Object.hasOwn(document, "type"), false);
  assert.equal(Object.hasOwn(document, "instance"), false);
  const fallback = problemDocument(new Request("https://nexus.example.com/", { headers: { "Cf-Ray": "untrusted-text" } }), new Error("stored text must never be returned"));
  assert.match(fallback.traceId, /^[0-9a-f]{16}$/);
  assert.equal(fallback.code, "internal");
  assert.ok(!JSON.stringify(fallback).includes("stored text"));
});

test("error responses have exact security headers, shared trace logs and body-free HEAD", async () => {
  const logs = [];
  const original = console.error;
  console.error = (...values) => logs.push(values);
  try {
    const request = new Request("https://nexus.example.com/");
    const response = problemResponse(request, new Problem("method_not_allowed", "not allowed", {}, { Allow: "GET, HEAD" }));
    const body = await response.json();
    assert.equal(response.status, 405);
    assert.equal(response.headers.get("Content-Type"), "application/problem+json");
    assert.equal(response.headers.get("Allow"), "GET, HEAD");
    for (const [name, value] of Object.entries(COMMON_HEADERS)) assert.equal(response.headers.get(name), value);
    assert.deepEqual(logs[0], ["nexus", { kind: "method_not_allowed", traceId: body.traceId }]);
    const head = problemResponse(new Request("https://nexus.example.com/", { method: "HEAD" }), new Error("private stored text"));
    assert.equal(await head.text(), "");
    assert.equal(head.status, 500);
    assert.ok(!JSON.stringify(logs).includes("private stored text"));
  } finally { console.error = original; }
});
