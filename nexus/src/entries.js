const only = (row, names) => Object.fromEntries(names.map((name) => [name, row[name] ?? null]));
const json = (value, fallback) => value == null ? fallback : typeof value === "string" ? JSON.parse(value) : value;

export function comment(row) {
  return { ...only(row, ["id", "part", "stage", "item", "quote", "discrepancy", "author", "text", "state", "closed_as", "waits", "made_at", "last_at"]), commit: row.commit_id, settled: Boolean(row.settled), dismissed: Boolean(row.dismissed) };
}
export function commentState(row) {
  return { ...only(row, ["id", "state", "closed_as", "waits", "last_at"]), settled: Boolean(row.settled), dismissed: Boolean(row.dismissed) };
}
export const reply = (row) => ({ ...only(row, ["seq", "author", "text", "made_at"]), settles: Boolean(row.settles) });
export const decision = (row) => only(row, ["seq", "link", "text", "made_at"]);

export function proposal(row, full = false) {
  const result = { ...only(row, ["id", "part", "stage", "reason", "change", "comment", "discrepancy", "state", "made_at", "closed_at", "edit"]), commit: row.commit_id, items: json(row.items, []) };
  if (full) result.source_text = row.source_text;
  else result.source_text_chars = Array.from(row.source_text || "").length;
  return result;
}
export const proposalState = (row) => only(row, ["id", "state", "closed_at"]);
export const edit = (row) => ({ ...only(row, ["id", "part", "stage", "proposal", "state", "pull_request", "closed_commit", "made_at", "changed_at"]), commit: row.commit_id });
export const checkpoint = (row) => ({ ...only(row, ["id", "part", "stage", "words", "state", "passed_at", "withdrawn_at", "pull_request", "pr_state", "recorded_commit"]), commit: row.commit_id ?? null });
export const discrepancy = (row) => ({ ...only(row, ["id", "part", "compares", "term", "item", "level", "state", "opened_commit", "opened_at", "resolved_commit", "resolved_at", "earlier"]), reasons: json(row.reasons, []), waiting: Boolean(row.waiting) });
export const claim = (row) => only(row, ["entry", "session", "claimed_at", "ends_at"]);

export function withClaim(entry, claims, session, now) {
  const held = claims.find((row) => row.entry === entry.id && row.ends_at > now);
  return held ? { ...entry, claim: { ends_at: held.ends_at, mine: held.session === session } } : entry;
}

export function commentEntry(row, replies, proposals, claims = [], session = null, now = "") {
  const thread = replies.filter((entry) => entry.comment === row.id).sort((a, b) => a.seq - b.seq);
  return withClaim({ ...comment(row), replies: thread.length, last_reply: thread.length ? reply(thread[thread.length - 1]) : null,
    proposals: proposals.filter((entry) => entry.comment === row.id).map((entry) => entry.id) }, claims, session, now);
}

export function commentListRow(row, claims = [], session = null, now = "") {
  return withClaim({ ...comment(row), replies: row.reply_count,
    last_reply: row.last_reply_json ? reply(json(row.last_reply_json, null)) : null,
    proposals: json(row.proposal_ids_json, []) }, claims, session, now);
}

export function editListRow(row, full = false) {
  const source = json(row.proposal_json, null);
  return { ...edit(row), proposal: source?.id ? proposal(source, full) : null };
}

export function editEntry(row, proposals, full = false) {
  const source = proposals.find((entry) => entry.id === row.proposal);
  return { ...edit(row), proposal: source ? proposal(source, full) : null };
}

export function listedCheckpoint(row) {
  if (row.state === "passed" && !row.recorded_commit) return "not-recorded";
  if (row.state === "withdrawn" && row.recorded_commit) return "withdrawn-recorded";
  if (row.state === "withdrawn" && row.pr_state === "open") return "withdrawn-in-review";
  return null;
}

export function stageRecord(snapshot, part, stage) {
  const entry = snapshot.stages?.[stage] || {};
  const record = part ? entry.parts?.[part] || {} : entry;
  return {
    state: ["done", "in_progress", "not_started", "skipped", "unknown"].includes(record.state) ? record.state : "unknown",
    checkpoints: record.checkpoints || [], next: record.next || "",
    ...(record.updated ? { updated: record.updated } : {}), from: snapshot.records?.from || "status-file",
  };
}

export const list = (entries, limit) => ({ total: entries.length, entries: entries.slice(0, limit) });
export const compareTime = (field, descending = false) => (a, b) =>
  (String(a[field]).localeCompare(String(b[field]), "en") * (descending ? -1 : 1)) || a.id.localeCompare(b.id, "en");
