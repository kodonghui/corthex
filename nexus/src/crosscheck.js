// SPEC-120/121: compare only one part's current sources. The store applies the
// resulting pair changes in the same guarded transaction as its snapshot.
const word = (value) => String(value).normalize("NFC").replace(/\s+/gu, "").toLowerCase();
export const pairKey = ({ part, compares, term, item }) => JSON.stringify([part, compares, term, item]);

export function pairPictures(part, board, other, compares) {
  const aggregate = compares === "aggregate-table";
  const terms = aggregate ? board.aggregates : board.read_models;
  const items = aggregate ? other.tables : other.screens;
  const exempt = new Set(aggregate ? other.without_table : other.without_screen);
  const readingContexts = new Map();
  if (!aggregate) for (const context of board.contexts) for (const row of context.rows) {
    const name = word(row.read_model);
    if (!readingContexts.has(name)) readingContexts.set(name, new Set());
    readingContexts.get(name).add(context.id);
  }
  const byTerm = new Map();
  for (const term of terms) if (term.term && !exempt.has(term.term)) {
    if (!byTerm.has(term.term)) byTerm.set(term.term, []);
    byTerm.get(term.term).push(term);
  }
  const found = new Map();
  const named = new Set();
  function add(term, item, reasons) {
    if (!reasons.length) return;
    const entry = { part, compares, term, item, reasons: [], level: "info" };
    const key = pairKey(entry);
    const held = found.get(key) || entry;
    for (const reason of reasons) if (!held.reasons.some((value) => JSON.stringify(value) === JSON.stringify(reason))) held.reasons.push(reason);
    // One pair has at most the five reason kinds in stage 04. Multiple board
    // rows can name the same term; keep one context mismatch with both sides.
    held.reasons = held.reasons.filter((reason, index, all) => reason.kind !== "other-context" || all.findIndex((entry) => entry.kind === "other-context") === index);
    held.level = held.reasons.some((reason) => !["no-table", "no-screen"].includes(reason.kind)) ? "warn" : "info";
    found.set(key, held);
  }
  for (const item of items) {
    const ref = item.id || item.name;
    if (item.terms === undefined) {
      add("", ref, [{ kind: "no-term" }]);
      continue;
    }
    for (const id of new Set(item.terms)) {
      if (exempt.has(id)) continue;
      named.add(id);
      const matches = byTerm.get(id);
      if (!matches) {
        add(id, ref, [{ kind: "not-on-board" }]);
        continue;
      }
      for (const term of matches) {
        const reasons = [];
        const contexts = aggregate ? null : readingContexts.get(word(term.name));
        if (contexts?.size ? !contexts.has(item.context) : item.context !== term.context) reasons.push({ kind: "other-context", contexts: [term.context, item.context] });
        if (term.removed) reasons.push({ kind: "removed", side: "term" });
        if (item.removed) reasons.push({ kind: "removed", side: "item" });
        add(id, ref, reasons);
      }
    }
  }
  for (const id of byTerm.keys()) if (!named.has(id)) add(id, "", [{ kind: aggregate ? "no-table" : "no-screen" }]);
  return [...found.values()].sort((a, b) => pairKey(a).localeCompare(pairKey(b), "en"));
}

// With a missing/not-current source, keep each old discrepancy and mark it as
// waiting. Resolution only follows an actual cross-check of both current sides.
export function crosscheckParts(pictures, previous, changedParts) {
  const found = new Map();
  const checked = new Set();
  for (const part of changedParts) {
    const sources = new Map(pictures.filter((picture) => picture.part === part && !picture.not_current).map((picture) => [picture.stage, picture.source]));
    const board = sources.get("01-domain");
    if (!board) continue;
    for (const [stage, compares] of [["05-erd", "aggregate-table"], ["07-sitemap", "read-model-screen"]]) {
      const other = sources.get(stage);
      if (!other) continue;
      checked.add(JSON.stringify([part, compares]));
      for (const entry of pairPictures(part, board, other, compares)) found.set(pairKey(entry), entry);
    }
  }
  const updates = [];
  const resolve = [];
  for (const old of previous) {
    if (!changedParts.has(old.part)) continue;
    const match = found.get(pairKey(old));
    if (match) {
      const oldReasons = typeof old.reasons === "string" ? JSON.parse(old.reasons) : old.reasons;
      if (old.waiting || old.level !== match.level || JSON.stringify(oldReasons) !== JSON.stringify(match.reasons)) updates.push({ ...match, id: old.id, waiting: false });
      found.delete(pairKey(old));
    } else if (checked.has(JSON.stringify([old.part, old.compares]))) resolve.push(old.id);
    else if (!old.waiting) updates.push({ ...old, reasons: typeof old.reasons === "string" ? JSON.parse(old.reasons) : old.reasons, waiting: true });
  }
  return { open: [...found.values()], updates, resolve };
}
