// Execute the actual template functions with DOM doubles. No network or writes.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const template = fs.readFileSync(process.argv[2], "utf8");
const script = template.slice(template.lastIndexOf("<script>") + 8, template.lastIndexOf("</script>"));
class Element {
  constructor(tag, text = "") { this.tagName = tag.toUpperCase(); this.children = []; this._text = text; this.attributes = {}; }
  appendChild(child) { this.children.push(child); return child; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener() {}
  querySelector() { return null; }
}
const walk = node => [node, ...node.children.flatMap(walk)];
function runtime(lang, projects = [], missing = []) {
  const data = {schema: "corthex-hub-page/0.2", origin: "local", lang, projects, missing};
  const nodes = {"hub-data": new Element("script", JSON.stringify(data))};
  const document = {
    documentElement: {},
    createElement: tag => new Element(tag), createTextNode: text => new Element("#text", text),
    getElementById: id => nodes[id] || (nodes[id] = new Element("div")), addEventListener() {},
  };
  const sandbox = {document, URLSearchParams, location: {hash: ""}, window: {addEventListener() {}}};
  assert.ok(script.includes("  render();\n"));
  vm.runInNewContext(script.replace("  render();\n", "  globalThis.hubTest = {traceView:traceView,stageDetail:stageDetail,projects:projects,render:render};\n"), sandbox, {timeout: 2000});
  return {api: sandbox.hubTest, nodes};
}
for (const lang of ["en", "ko"]) {
  const project = {project: {name: "synthetic"}, stages: {"04-functional-spec": {state: "in_progress"}}, checks: [{stage: "05-erd", level: "warn", message: "Synthetic warning elsewhere"}], items: [
    {id: "SPEC-001", kind: "spec", title: "Synthetic spec", stage: "04-functional-spec", links: ["SCR-001"]},
    {id: "REQ-001", kind: "requirement", stage: "02-prd", where: "docs/qa-source.md:1", links: ["SPEC-001", "REQ-999"]},
    {id: "FL-001", kind: "flow", stage: "03-user-flow", links: ["SPEC-001"]},
    {id: "SCR-001", kind: "screen", stage: "08-screen-states", links: []},
    {id: "SPEC-002", kind: "spec", stage: "04-functional-spec", links: []},
    {id: "DEC-001", kind: "decision", stage: "04-functional-spec", links: []},
  ], ids: {REQ: "requirement"}};
  const {api} = runtime(lang, [project]);
  const p = api.projects[0], before = JSON.stringify(p);
  const empty = api.traceView(p, "SPEC-002");
  assert.ok(walk(empty).some(node => node.className === "note" && node.textContent === (lang === "ko" ? "없음" : "none")));
  const trace = api.traceView(p, "SPEC-001");
  const up = walk(trace).find(node => node.className === "group" && node.children[0].textContent.startsWith(lang === "ko" ? "앞 단계" : "Comes from"));
  const groups = up.children.filter(node => node.className === "trace-stage");
  assert.equal(groups.length, 2);
  assert.ok(groups[0].children[0].textContent.startsWith("02 "));
  assert.ok(groups[0].textContent.includes("REQ-001"));
  assert.ok(!groups[0].textContent.includes("FL-001"));
  assert.ok(groups[1].children[0].textContent.startsWith("03 "));
  assert.ok(groups[1].textContent.includes("FL-001"));
  const undefinedId = api.traceView(p, "REQ-999");
  assert.ok(undefinedId.textContent.includes(lang === "ko" ? "함께 언급한 항목" : "Mentioned with it"));
  assert.ok(undefinedId.textContent.includes("docs/qa-source.md:1"));
  const stage = api.stageDetail(p, "01-domain");
  assert.ok(stage.some(node => node.textContent === (lang === "ko" ? "점검에서 찾은 것이 없습니다." : "No checks found anything.")));
  assert.ok(!stage.some(node => node.textContent.includes("Synthetic warning elsewhere")));
  const withItems = api.stageDetail(p, "04-functional-spec");
  assert.equal(withItems[0].textContent, lang === "ko" ? "04 기능 명세 · 진행 중" : "04 Functional spec · In progress");
  const kinds = withItems.filter(node => node.className === "item-kind");
  assert.equal(kinds.length, 2);
  assert.equal(kinds[0].attributes["data-kind"], "spec");
  assert.ok(kinds[0].textContent.includes("SPEC-001"));
  assert.ok(!kinds[0].textContent.includes("DEC-001"));
  assert.equal(kinds[1].attributes["data-kind"], "decision");
  assert.ok(kinds[1].textContent.includes("DEC-001"));
  assert.equal(JSON.stringify(p), before, "rendering changes no project data");
  const missing = runtime(lang, [], [{name: "qa-missing-snapshot", reason: "no snapshot"}]);
  missing.api.render();
  assert.ok(missing.nodes.missing.textContent.includes("qa-missing-snapshot (no snapshot)"));
  const hostile = runtime(lang, [], [{name: "synthetic", reason: "<script>synthetic</script>"}]);
  hostile.api.render();
  assert.ok(hostile.nodes.missing.textContent.includes("<script>synthetic</script>"));
  assert.equal(walk(hostile.nodes.missing).filter(node => node.tagName === "SCRIPT").length, 0);
}
process.stdout.write(JSON.stringify({passed: true, locales: 2, source: "actual template with DOM doubles"}));
