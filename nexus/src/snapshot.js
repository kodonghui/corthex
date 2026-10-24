// Checks a snapshot that `hub.py push` sent. The format is described in
// plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md. Fields the
// page reads must have the type it expects; other fields are kept as sent.

export const SCHEMA = "corthex-hub/0.1";
export const MAX_BYTES = 1024 * 1024;
export const NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

const MAX_NAME = 100;
const MAX_ITEMS = 3000;
const MAX_CHECKS = 10000;
const MAX_STAGES = 100;
const MAX_AHEAD_MS = 10 * 60 * 1000;
const STAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/;
const LEVELS = new Set(["error", "warn", "info"]);

// Field types: a JavaScript type name, "strings" for a list of strings,
// "numbers" for an object of numbers, or an object for nested fields.
const PROJECT = { name: "string", title: "string", team: "boolean", language: "string", records: { kind: "string", link: "string" } };
const REPO = { commit: "string", branch: "string", url: "string", web: "string", dirty: "boolean", checkout: "boolean" };
const STAGE = {
  name: "string", human: "string", link: "string", truth: "string", note: "string", source: "string",
  repo: "string", source_state: "string", state: "string", checkpoint: "string", checkpoint_date: "string",
  next: "string", updated: "string", read: "boolean", skip: "boolean", default_source: "boolean",
  files: "number", items: "number", copied: { oldest: "string", newest: "string" }, skipped: "numbers",
};
const ITEM = {
  id: "string", kind: "string", stage: "string", where: "string", title: "string", status: "string",
  type: "string", priority: "string", link: "string", parent: "string", screen_doc: "string",
  states: "strings", links: "strings",
};
const CHECK = { rule: "string", level: "string", message: "string", by: "string", stage: "string", at: "string", refs: "strings", args: "object" };
const SUMMARY = { items: "number", kinds: "numbers", checks: "numbers", states: "numbers" };

export class Refused extends Error {
  constructor(status, message, headers) {
    super(message);
    this.status = status;
    this.headers = headers || {};
  }
}

function bad(what) {
  return new Refused(400, `the snapshot has a bad ${what}`);
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function fits(value, type, path) {
  if (type === "strings") {
    if (!Array.isArray(value) || !value.every((entry) => typeof entry === "string")) throw bad(path);
  } else if (type === "numbers") {
    if (!isObject(value) || !Object.values(value).every(Number.isFinite)) throw bad(path);
  } else if (type === "number") {
    if (!Number.isFinite(value)) throw bad(path);
  } else if (type === "object") {
    if (!isObject(value)) throw bad(path);
  } else if (typeof type === "object") {
    if (!isObject(value)) throw bad(path);
    for (const [key, inner] of Object.entries(type)) {
      if (value[key] !== undefined) fits(value[key], inner, `${path}.${key}`);
    }
  } else if (typeof value !== type) {
    throw bad(path);
  }
}

function needs(value, keys, path) {
  for (const key of keys) {
    if (typeof value[key] !== "string" || !value[key]) throw bad(`${path}.${key}`);
  }
}

function eachOf(value, path, check) {
  if (!isObject(value)) throw bad(path);
  for (const [key, entry] of Object.entries(value)) check(entry, `${path}.${key}`);
}

// Returns what the store needs, or throws Refused with the reason.
export function readSnapshot(text, nowMs) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Refused(400, "the body is not JSON");
  }
  if (!isObject(data)) throw new Refused(400, "the body is not a JSON object");
  if (data.schema !== SCHEMA) throw new Refused(400, `the snapshot is not in the ${SCHEMA} format`);

  fits(data.project, PROJECT, "project");
  const name = data.project.name;
  if (typeof name !== "string" || !NAME.test(name) || name.length > MAX_NAME) {
    throw new Refused(400, "the snapshot needs project.name in lowercase letters, digits and hyphens");
  }
  const generatedMs = typeof data.generated_at === "string" && STAMP.test(data.generated_at) ? Date.parse(data.generated_at) : NaN;
  if (!Number.isFinite(generatedMs)) throw new Refused(400, "the snapshot needs generated_at as a time with its time zone");
  if (generatedMs > nowMs + MAX_AHEAD_MS) {
    throw new Refused(400, "the snapshot is dated in the future; check the clock of the machine that made it");
  }

  if (data.generator !== undefined) fits(data.generator, "string", "generator");
  if (data.truncated !== undefined) fits(data.truncated, "boolean", "truncated");
  if (data.ids !== undefined) eachOf(data.ids, "ids", (kind, path) => fits(kind, "string", path));
  if (data.repos !== undefined) eachOf(data.repos, "repos", (repo, path) => fits(repo, REPO, path));
  if (!isObject(data.stages) || Object.keys(data.stages).length > MAX_STAGES) throw bad("stages");
  eachOf(data.stages, "stages", (stage, path) => fits(stage, STAGE, path));
  fits(data.summary, SUMMARY, "summary");

  if (!Array.isArray(data.items) || data.items.length > MAX_ITEMS) throw bad("items");
  data.items.forEach((item, index) => {
    const path = `items[${index}]`;
    fits(item, ITEM, path);
    needs(item, ["id", "kind", "stage"], path);
  });
  if (!Array.isArray(data.checks) || data.checks.length > MAX_CHECKS) throw bad("checks");
  data.checks.forEach((check, index) => {
    const path = `checks[${index}]`;
    fits(check, CHECK, path);
    needs(check, ["rule", "message"], path);
    if (!LEVELS.has(check.level)) throw bad(`${path}.level`);
  });

  return { name, generatedMs, generatedAt: data.generated_at, body: JSON.stringify(data) };
}
