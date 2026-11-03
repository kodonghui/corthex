import { Problem } from "./problem.js";
import { crosscheckParts } from "./crosscheck.js";

export function entryId(prefix) {
  const alphabet = "0123456789abcdefghjkmnpqrstvwxyz";
  return prefix + Array.from(crypto.getRandomValues(new Uint8Array(12)), (value) => alphabet[value & 31]).join("");
}

export function checkCommit(sent, held) {
  if (!held) return;
  const current = held.default_commit;
  if (current && (!sent.defaultCommit || (sent.defaultCommit !== current && sent.data?.replaces !== current))) throw new Problem("commit_not_replaced", "fetch the held default branch commit and push again", { held_commit: current });
  if ((!current || current === sent.defaultCommit) && sent.generatedMs < held.generated_ms) throw new Problem("older_snapshot", `the server holds a newer snapshot of ${sent.name}, made at ${held.generated_at}; build it again and send that`, { stored_at: held.generated_at });
}

export function repositoryAddress(value) {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname === "/") throw new Error();
    url.protocol = "https:";
    url.pathname = url.pathname.replace(/\/+$/, "").replace(/\.git$/, "");
    return url.href.replace(/\/$/, "");
  } catch { throw new Problem("invalid_snapshot", "the repository address is not in its canonical HTTPS form", { field: "repos...url" }); }
}

const place = (picture) => ({ part: picture.part, stage: picture.stage });
const pictureKey = (picture) => JSON.stringify([picture.part, picture.stage]);
const hash = async (text) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))), (value) => value.toString(16).padStart(2, "0")).join("");

// A plan contains only changes; sending an identical snapshot writes one row.
export async function planPush(sent, state, now) {
  checkCommit(sent, state.held);
  const repository = repositoryAddress(sent.repository);
  if (state.space?.repo_url && state.space.repo_url !== repository) throw new Problem("repository_mismatch", "this space is bound to another repository", { bound: state.space.repo_url });
  const old = new Map(state.pictures.map((picture) => [pictureKey(picture), picture]));
  const absent = new Map((sent.data.left_out || []).map((entry) => [pictureKey(entry), entry.why]));
  const changes = [];
  const supplied = [];
  const changedParts = new Set();
  const pictures = { drawn: [], current_again: [], not_current: [], unchanged: 0 };
  for (const entry of sent.pictures) {
    const source = JSON.stringify(entry.source);
    const digest = await hash(source);
    const held = old.get(pictureKey(entry));
    old.delete(pictureKey(entry));
    supplied.push({ ...entry, not_current: null });
    if (!held || held.digest !== digest) {
      changes.push({ ...entry, source, digest, drawn_at: now, not_current: null });
      pictures.drawn.push(place(entry));
      changedParts.add(entry.part);
    } else if (held.not_current) {
      changes.push({ ...held, not_current: null });
      pictures.current_again.push(place(entry));
      changedParts.add(entry.part);
    } else pictures.unchanged++;
  }
  for (const held of old.values()) {
    const why = absent.get(pictureKey(held)) || "source-gone";
    supplied.push({ ...held, not_current: why });
    if (held.not_current !== why) {
      changes.push({ ...held, not_current: why });
      pictures.not_current.push({ ...place(held), why });
      changedParts.add(held.part);
    }
  }
  const reconciled = crosscheckParts(supplied, state.discrepancies, changedParts);
  const retained = state.discrepancies.length - reconciled.resolve.length;
  const candidates = reconciled.open.map((entry) => ({ ...entry, id: entryId("nd_") }));
  candidates.sort((a, b) => (a.level === "warn" ? 0 : 1) - (b.level === "warn" ? 0 : 1) || a.id.localeCompare(b.id, "en"));
  const opened = candidates.slice(0, Math.max(0, 1000 - retained));
  const unopened = Object.assign(Object.create(null),state.space ? JSON.parse(state.space.unopened) : {});
  for (const part of changedParts) delete unopened[part];
  for (const entry of candidates.slice(opened.length)) unopened[entry.part] = (unopened[entry.part] || 0) + 1;
  const records = new Set();
  for (const [stage, row] of Object.entries(sent.data.records.from === "repository" ? sent.data.stages : {})) {
    for (const checkpoint of row.checkpoints || []) if (checkpoint.nexus) records.add(JSON.stringify(["", stage, checkpoint.nexus]));
    for (const [part, record] of Object.entries(row.parts || {})) for (const checkpoint of record.checkpoints || []) if (checkpoint.nexus) records.add(JSON.stringify([part, stage, checkpoint.nexus]));
  }
  const checkpointChanges = [];
  const withdrawnRecorded = [];
  let recorded = 0;
  for (const checkpoint of state.checkpoints) {
    const named = records.has(JSON.stringify([checkpoint.part, checkpoint.stage, checkpoint.id]));
    // recorded_commit describes the current stored records, not an archive.
    // An omitted ID becomes actionable again whether passed or withdrawn.
    const commit = named ? sent.defaultCommit : null;
    if (named && sent.defaultCommit && !checkpoint.recorded_commit) recorded++;
    if (commit !== checkpoint.recorded_commit) checkpointChanges.push({ id: checkpoint.id, recorded_commit: commit });
    if (checkpoint.state === "withdrawn" && named) withdrawnRecorded.push(checkpoint.id);
  }
  return {
    repository, pictures: changes, discrepancies: { ...reconciled, open: opened }, checkpoints: checkpointChanges, unopened,
    answer: {
      name: sent.name, revision: (state.held?.revision || 0) + 1, default_commit: sent.defaultCommit,
      replaced: state.held?.default_commit !== sent.defaultCommit ? state.held?.default_commit || null : null,
      pictures: { ...pictures, drawn: pictures.drawn.slice(0, 20), current_again: pictures.current_again.slice(0, 20), not_current: pictures.not_current.slice(0, 20) },
      discrepancies: { opened: opened.length, resolved: reconciled.resolve.length, open: retained + opened.length, not_opened: Object.values(unopened).reduce((a, b) => a + b, 0) },
      checkpoints: { recorded, withdrawn_recorded: withdrawnRecorded.sort().slice(0, 20) },
    },
  };
}
