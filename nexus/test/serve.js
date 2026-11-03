// Serves the Worker on this machine over an in-memory database, with a
// stand-in for the Cloudflare Access check. For tests only: tests/test_nexus.py
// runs it, reads the address it prints and closes its input to stop it.
//   node test/serve.js [--no-access]

import { readFileSync } from "node:fs";
import { createServer } from "node:http";

import { handle } from "../src/app.js";
import { fakeD1 } from "./fake-d1.js";
import { testAccess } from "./access-fixture.js";

const template = readFileSync(new URL("../src/hub.html", import.meta.url), "utf8");
const access = await testAccess();
const env = { DB: fakeD1(), NEXUS_LANGUAGE: "en", ...access.env };
const ctx = process.argv.includes("--no-access") ? {} : access.ctx;

const server = createServer(async (incoming, outgoing) => {
  const headers = new Headers();
  for (const [name, value] of Object.entries(incoming.headers)) {
    if (typeof value === "string") headers.set(name, value);
  }
  headers.set("Cf-Access-Jwt-Assertion", access.headers()["Cf-Access-Jwt-Assertion"]);
  // Read the whole body before the Worker answers. The Worker refuses some
  // requests without reading their body, and a socket closed with unread data
  // can reset the connection before the client reads the answer.
  const reads = incoming.method !== "GET" && incoming.method !== "HEAD";
  const chunks = [];
  if (reads) for await (const chunk of incoming) chunks.push(chunk);
  const request = new Request(`http://${incoming.headers.host}${incoming.url}`, {
    method: incoming.method,
    headers,
    body: reads ? Buffer.concat(chunks) : undefined,
  });
  const response = await handle(request, env, ctx, template);
  outgoing.writeHead(response.status, Object.fromEntries(response.headers));
  outgoing.end(Buffer.from(await response.arrayBuffer()));
});

server.listen(0, "127.0.0.1", () => {
  process.stdout.write(`http://127.0.0.1:${server.address().port}\n`);
});
process.stdin.on("end", () => process.exit(0));
process.stdin.resume();
