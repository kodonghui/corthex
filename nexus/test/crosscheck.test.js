import assert from "node:assert/strict";
import { test } from "node:test";
import { pairPictures, crosscheckParts, pairKey } from "../src/crosscheck.js";

const term = (id, fields = {}) => ({ term: id, name: "Order", context: "CTX-001", removed: false, ...fields });
const table = (terms, fields = {}) => ({ id: "TBL-001", name: "orders", context: "CTX-001", removed: false, ...(terms === undefined ? {} : { terms }), ...fields });
const board = (fields = {}) => ({ aggregates: [term("TERM-001")], read_models: [term("TERM-002", { name: "Summary" })], contexts: [], ...fields });
const erd = (tables = []) => ({ tables, without_table: [] });
const sitemap = (screens = []) => ({ screens, without_screen: [] });

test("same-term aggregate/table pairs do not create false discrepancies", () => {
  assert.deepEqual(pairPictures("orders", board(), erd([table(["TERM-001"])]), "aggregate-table"), []);
  const noTerms = erd([table([])]); noTerms.without_table = ["TERM-001"];
  assert.deepEqual(pairPictures("orders", board(), noTerms, "aggregate-table"), []);
  assert.deepEqual(pairPictures("", board({ aggregates: [term(undefined)] }), erd(), "aggregate-table"), []);
});

test("missing terms, wrong side and missing pairs have exact warning/info reasons", () => {
  const missing = pairPictures("", board(), erd([table(undefined)]), "aggregate-table");
  assert.deepEqual(missing.map((entry) => [entry.term, entry.item, entry.level, entry.reasons[0].kind]), [["", "TBL-001", "warn", "no-term"], ["TERM-001", "", "info", "no-table"]]);
  const wrongSide = pairPictures("", board(), erd([table(["TERM-002"])]), "aggregate-table");
  assert.equal(wrongSide.find((entry) => entry.term === "TERM-002").reasons[0].kind, "not-on-board");
  const noScreen = pairPictures("", board(), sitemap(), "read-model-screen");
  assert.deepEqual(noScreen.map((entry) => [entry.term, entry.reasons[0].kind]), [["TERM-002", "no-screen"]]);
});

test("a pair merges context and removed reasons, with a stable composite key", () => {
  const result = pairPictures("orders", board({ aggregates: [term("TERM-001", { removed: true })] }), erd([table(["TERM-001"], { context: "CTX-002", removed: true })]), "aggregate-table");
  assert.equal(result.length, 1);
  assert.deepEqual(result[0].reasons, [{ kind: "other-context", contexts: ["CTX-001", "CTX-002"] }, { kind: "removed", side: "term" }, { kind: "removed", side: "item" }]);
  assert.equal(result[0].level, "warn");
  assert.notEqual(pairKey(result[0]), pairKey({ ...result[0], part: "other" }));
});

test("SPEC-120 excludes explicitly exempt terms from pairs, including removed contexts", () => {
  const b=board({aggregates:[term("TERM-001",{removed:true})]});
  const e=erd([table(["TERM-001"],{context:"CTX-002",removed:true})]);e.without_table=["TERM-001"];
  assert.deepEqual(pairPictures("",b,e,"aggregate-table"),[]);
  const s=sitemap([table(["TERM-002"],{id:"SCR-001",context:"CTX-002",removed:true})]);s.without_screen=["TERM-002"];
  assert.deepEqual(pairPictures("",b,s,"read-model-screen"),[]);
});

test("every context that reads a read model is a valid screen context", () => {
  const b = board({ contexts: [{ id: "CTX-001", rows: [{ read_model: "Summary" }] }, { id: "CTX-002", rows: [{ read_model: "summary" }] }] });
  assert.deepEqual(pairPictures("", b, sitemap([table(["TERM-002"], { id: "SCR-001", context: "CTX-002" })]), "read-model-screen"), []);
});

test("two aggregates naming one term each participate without duplicate open pairs", () => {
  const b = board({ aggregates: [term("TERM-001"), term("TERM-001", { context: "CTX-002", removed: true })] });
  const result = pairPictures("", b, erd([table(["TERM-001"])]), "aggregate-table");
  assert.equal(result.length, 1);
  assert.equal(result[0].reasons.filter((entry) => entry.kind === "other-context").length, 1);
  assert.equal(new Set(result.map(pairKey)).size, result.length);
});

test("noncurrent pictures leave old pairs waiting; a current copy resumes resolution", () => {
  const old = { id: "nd_0123456789ab", part: "", compares: "aggregate-table", term: "TERM-001", item: "", level: "info", reasons: [{ kind: "no-table" }], waiting: false };
  const pictures = [{ part: "", stage: "01-domain", source: board() }, { part: "", stage: "05-erd", source: erd([table(["TERM-001"])]), not_current: "size" }];
  const waiting = crosscheckParts(pictures, [old], new Set([""]));
  assert.equal(waiting.updates[0].waiting, true);
  assert.deepEqual(waiting.resolve, []);
  pictures[1].not_current = null;
  const resumed = crosscheckParts(pictures, [{ ...old, waiting: true }], new Set([""]));
  assert.deepEqual(resumed.resolve, [old.id]);
  assert.deepEqual(resumed.open, []);
});

test("unchanged pair IDs remain open, changed reasons update and removed pairs resolve", () => {
  const pictures = [{ part: "", stage: "01-domain", source: board() }, { part: "", stage: "05-erd", source: erd() }];
  const existing = { id: "nd_0123456789ab", ...pairPictures("", board(), erd(), "aggregate-table")[0], waiting: false };
  assert.deepEqual(crosscheckParts(pictures, [existing], new Set([""])), { open: [], updates: [], resolve: [] });
  const old = { ...existing, reasons: [{ kind: "other-context", contexts: ["CTX-001", "CTX-002"] }], level: "warn" };
  assert.equal(crosscheckParts(pictures, [old], new Set([""])).updates[0].id, old.id);
  pictures[0].source = board({ aggregates: [] });
  assert.deepEqual(crosscheckParts(pictures, [existing], new Set([""])).resolve, [existing.id]);
});

test("cross-checking is isolated by changed part and comparison side", () => {
  const pictures = [{ part: "orders", stage: "01-domain", source: board() }, { part: "orders", stage: "05-erd", source: erd() }];
  const result = crosscheckParts(pictures, [], new Set(["orders"]));
  assert.equal(result.open.length, 1);
  assert.equal(result.open[0].compares, "aggregate-table");
  assert.equal(result.open[0].part, "orders");
  assert.deepEqual(crosscheckParts(pictures, [], new Set(["other"])), { open: [], updates: [], resolve: [] });
});
