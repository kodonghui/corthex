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
  vm.runInNewContext(script.replace("  render();\n", "  globalThis.hubTest = {traceView:traceView,stageDetail:stageDetail,checkList:checkList,checkText:checkText,spaceSummary:spaceSummary,projects:projects,render:render};\n"), sandbox, {timeout: 2000});
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
  // Checks start folded unless one is an error, and the summary counts each level.
  const folded = api.checkList(p, [{level: "warn", message: "Synthetic warning"}, {level: "warn", message: "Another warning"}, {level: "info", message: "Synthetic note"}], true);
  assert.equal(folded.tagName, "DETAILS");
  assert.ok(!("open" in folded.attributes));
  assert.equal(folded.children[0].textContent, lang === "ko" ? "점검 (3) · 경고 2 · 참고 1" : "Checks (3) · 2 warnings · 1 note");
  const opened = api.checkList(p, [{level: "error", message: "Synthetic error"}, {level: "warn", message: "Synthetic warning"}], true);
  assert.equal(opened.attributes.open, "");
  assert.equal(opened.children[0].textContent, lang === "ko" ? "점검 (2) · 오류 1 · 경고 1" : "Checks (2) · 1 error · 1 warning");
  // Korean texts for the checks whose snapshot message is English only; English shows the message itself.
  const samples = [
    [{rule: "records-in-status-file", level: "info", message: "stage records come from this device's status file; move them to the repository"},
      "단계 기록을 저장소가 아니라 스냅샷을 만든 기기의 상태 파일에서 읽었습니다. 기록을 저장소로 옮겨 주세요"],
    [{rule: "records-invalid", level: "warn", stage: "05-erd", message: "device status file: done needs a checkpoint and its date", args: {source: "device status file"}},
      "05 ERD: 기기의 상태 파일: ‘완료’에는 확인 지점과 그 날짜가 있어야 해서 ‘진행 중’으로 보입니다"],
    [{rule: "records-invalid", level: "warn", message: ".corthex/stages.json: a reason added later", args: {source: ".corthex/stages.json"}},
      ".corthex/stages.json: 단계 기록에 고칠 곳이 있습니다 (원문: a reason added later)"],
    [{rule: "picture-partial", level: "warn", stage: "05-erd", message: "docs/05-erd/erd.json:3: synthetic detail"},
      "05 ERD: 그림 원본의 일부를 읽지 못했거나 그림 한도를 넘었습니다 (원문: docs/05-erd/erd.json:3: synthetic detail)"],
    [{rule: "picture-left-out", level: "warn", stage: "07-sitemap", message: "a whole picture is left out to keep the snapshot under 1 MB", args: {part: "", stage: "07-sitemap", why: "size"}},
      "07 사이트맵: 스냅샷을 1MB 안에 담으려고 이 그림을 통째로 뺐습니다"],
    [{rule: "files-skipped", level: "info", message: "Synthetic skipped files", args: {stage: "05-erd", count: 3, reasons: {size: 1, format: 2}}},
      "05 ERD: 읽지 않은 파일 3개 (1MB 넘음 1개, 읽지 않는 형식 2개)"],
    [{rule: "board-term-missing", level: "warn", message: "Order placed has multiple glossary terms", args: {name: "Order placed", context: "CTX-001"}},
      "Order placed: 용어집에 맞는 용어가 여럿이라 첫 번째를 씁니다"],
    [{rule: "records-in-status-file", level: "info", by: "review", message: "A reviewer's own words"}, "A reviewer's own words"],
    [{rule: "invented-rule", level: "info", message: "Synthetic unknown rule"}, "Synthetic unknown rule"],
  ];
  for (const [check, korean] of samples) {
    assert.equal(api.checkText(check), lang === "ko" ? korean : check.message);
  }
  // The default ask-before words are translated; the user's own words are kept and marked in Korean.
  const askNotes = ask => walk(api.spaceSummary({project: {name: "synthetic"}, ask_before: ask})).filter(node => node.className === "note");
  const own = askNotes({entries: ["deletions (repositories, data)", "payments"], source: "project", left_out: ["deploys"]});
  assert.equal(own[1].textContent, lang === "ko" ? "원문 deletions (repositories, data) · 결제" : "deletions (repositories, data) · payments");
  assert.equal(own[1].children.filter(node => node.className === "tag").length, lang === "ko" ? 1 : 0);
  assert.equal(own[2].textContent, lang === "ko" ? "이 프로젝트에서 먼저 묻지 않는 것: 배포" : "Not asked in this project: deploys");
  assert.equal(own[2].children.filter(node => node.className === "tag").length, 0);
  const none = askNotes({entries: [], source: "project", left_out: []});
  assert.equal(none[1].textContent, lang === "ko" ? "되돌릴 수 없는 일만 먼저 묻습니다." : "Only what cannot be undone is asked.");
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
