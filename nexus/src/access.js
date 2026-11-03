// The real Access trial selected a verified assertion header, not getIdentity.
// This module returns only the author's kind. It never retains or logs a JWT,
// user identity, service client ID, cookie or request header.
import { Problem } from "./problem.js";

const HOUR = 60 * 60 * 1000;
const denied = () => new Problem("access_missing", "the Access assertion could not be verified");
const nonempty = (value) => typeof value === "string" && value.length > 0;
const audiences = (value) => typeof value === "string" ? [value] : Array.isArray(value) ? value : [];
const wanted = (env) => String(env.ACCESS_AUD || "").split(",").map((v) => v.trim()).filter(Boolean);

function decode(part) {
  if (!/^[A-Za-z0-9_-]+$/.test(part)) throw denied();
  try {
    return Uint8Array.from(atob(part.replaceAll("-", "+").replaceAll("_", "/")), (c) => c.charCodeAt(0));
  } catch { throw denied(); }
}

function object(part) {
  try {
    const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(decode(part)));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw denied();
    return value;
  } catch { throw denied(); }
}

function issuer(env) {
  // The host is configured by the operator, never copied from JWT iss/jku/x5u.
  const value = String(env.ACCESS_TEAM_DOMAIN || "").trim();
  try {
    const url = new URL(value.startsWith("https://") ? value : "https://" + value);
    if (url.protocol !== "https:" || url.username || url.password || url.port || url.pathname !== "/" || url.search || url.hash ||
      !/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$/i.test(url.hostname)) throw new Error();
    return url.origin;
  } catch { throw new Problem("internal", "the Access team domain is not configured correctly"); }
}

export function requireAccessContext(env, ctx) {
  if (!ctx?.access) throw new Problem("access_missing", "Cloudflare Access did not check this request; protect this Worker with Access first");
  const allowed = wanted(env);
  if (!allowed.length || !audiences(ctx.access.aud).some((aud) => allowed.includes(aud))) {
    throw new Problem("access_other_app", "another Access application than ACCESS_AUD names checked this request");
  }
}

export class AccessVerifier {
  // Workers' host fetch must be called as a global, with no verifier receiver.
  constructor({ fetcher = (...args) => fetch(...args), now = Date.now } = {}) {
    this.fetcher = fetcher;
    this.now = now;
    this.keys = new Map();
  }

  async publicKeys(team, refresh = false) {
    const cached = this.keys.get(team);
    // A request with a known key may use its unexpired cache while a rotated
    // (or unrecognized) kid is being checked by another request.
    if (!refresh && cached?.publicKeys && cached.expires > this.now()) return cached;
    if (cached?.pending) return cached.pending;
    const holder = cached || {};
    const pending = Promise.resolve().then(async () => {
      let response;
      try {
        response = await this.fetcher(team + "/cdn-cgi/access/certs", {
          redirect: "manual", headers: { Accept: "application/json" },
        });
        if (response.status !== 200) {
          await response.body?.cancel();
          throw new Error();
        }
        const data = await response.json();
        if (!Array.isArray(data.keys)) throw new Error();
        const publicKeys = new Map();
        for (const key of data.keys) {
          if (!key || !nonempty(key.kid) || key.kty !== "RSA" || (key.alg && key.alg !== "RS256") || (key.use && key.use !== "sig")) continue;
          if (publicKeys.has(key.kid)) throw new Error();
          // Keep public components only, even if an endpoint is misconfigured.
          publicKeys.set(key.kid, { kty: "RSA", n: key.n, e: key.e, alg: "RS256", ext: true });
        }
        if (!publicKeys.size) throw new Error();
        const entry = { publicKeys, imported: new Map(), expires: this.now() + HOUR };
        this.keys.set(team, entry);
        return entry;
      } catch {
        if (this.keys.get(team) === holder) {
          delete holder.pending;
          if (!holder.publicKeys || holder.expires <= this.now()) this.keys.delete(team);
        }
        throw new Problem("internal", "the Access signing keys could not be read");
      }
    });
    holder.pending = pending;
    this.keys.set(team, holder);
    return pending;
  }

  async verify(request, env, ctx) {
    // This first refusal is independent of path, method, body and token text.
    requireAccessContext(env, ctx);
    const token = request.headers.get("Cf-Access-Jwt-Assertion");
    if (!token) throw denied();
    const parts = token.split(".");
    if (parts.length !== 3) throw denied();
    const header = object(parts[0]);
    const claims = object(parts[1]);
    if (header.alg !== "RS256" || !nonempty(header.kid) || header.crit !== undefined || header.b64 === false) throw denied();
    const signature = decode(parts[2]);
    const team = issuer(env);
    let entry = await this.publicKeys(team);
    if (!entry.publicKeys.has(header.kid)) entry = await this.publicKeys(team, true);
    const jwk = entry.publicKeys.get(header.kid);
    if (!jwk) throw denied();
    let importing = entry.imported.get(header.kid);
    if (!importing) {
      importing = crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
      entry.imported.set(header.kid, importing);
    }
    let key;
    try {
      key = await importing;
      if (key.algorithm.modulusLength < 2048) throw new Error();
    }
    catch {
      entry.imported.delete(header.kid);
      this.keys.delete(team);
      throw new Problem("internal", "the Access signing key could not be used");
    }
    let valid;
    try {
      valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, signature, new TextEncoder().encode(parts[0] + "." + parts[1]));
    } catch { throw denied(); }
    if (!valid) throw denied();
    const seconds = this.now() / 1000;
    if (claims.iss !== team || typeof claims.exp !== "number" || !Number.isFinite(claims.exp) || claims.exp <= seconds ||
      (claims.nbf !== undefined && (typeof claims.nbf !== "number" || !Number.isFinite(claims.nbf) || claims.nbf > seconds))) throw denied();
    if (!audiences(claims.aud).some((aud) => wanted(env).includes(aud))) {
      throw new Problem("access_other_app", "the Access assertion is for another application");
    }
    if (nonempty(claims.sub)) return "user";
    if (claims.sub === "" && nonempty(claims.common_name)) return "agent";
    return null;
  }
}

export function requireKind(kind, needs) {
  if (kind !== "user" && kind !== "agent") throw new Problem("no_kind", "the checked sign-in has neither kind of author");
  if (needs !== "either" && kind !== needs) throw new Problem(needs === "user" ? "user_only" : "agent_only", "this write requires another kind of sign-in", { needs });
}
