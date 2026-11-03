"""Checks the corthex-nexus plugin: the hub script, its page and the push client."""

import http.server
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from _common import PLUGINS, read_text

SKILL = PLUGINS / "corthex-nexus" / "skills" / "corthex-hub"
SCRIPT = SKILL / "scripts" / "hub.py"
TEMPLATE = SKILL / "assets" / "hub.html"
CORE = PLUGINS / "corthex" / "skills"
CONTRACT = CORE / "corthex" / "references" / "stage-contract.md"
NOW = "2026-01-12T10:00:00+09:00"
FENCE = re.compile(r"^(`{3,})[\w-]*\s*$")

# Where each stage skill's output template is written: (path, skill, reference, block).
TEMPLATES = (
    ("docs/01-domain/domain.md", "corthex-discover", "01-domain", 0),
    ("docs/02-prd/requirements.md", "corthex-define", "02-prd", 0),
    ("docs/03-user-flow/FL-001.md", "corthex-define", "03-user-flow", 0),
    ("docs/04-functional-spec/spec.md", "corthex-define", "04-functional-spec", 0),
    ("db/schema.sql", "corthex-contract", "05-erd", 0),
    ("api/openapi.yaml", "corthex-contract", "06-api", 0),
    ("docs/07-sitemap/sitemap.yaml", "corthex-screen", "07-sitemap", 0),
    ("docs/08-screens/SCR-002.md", "corthex-screen", "08-screen-states", 0),
    ("docs/10-wbs/wbs.md", "corthex-build", "10-wbs", 0),
    ("docs/12-qa/test-plan.md", "corthex-build", "12-qa", None),
    ("docs/13-presentation/script.md", "corthex-present", "13-presentation", 0),
)


def load_script():
    spec = importlib.util.spec_from_file_location("corthex_hub", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hub = load_script()


def output_blocks(skill, stage):
    """The fenced blocks under "## Output template" in a stage's reference file."""
    text = read_text(CORE / skill / "references" / (stage + ".md"))
    lines = text[text.index("## Output template"):].splitlines()
    blocks = []
    index = 0
    while index < len(lines):
        match = FENCE.match(lines[index])
        if not match:
            index += 1
            continue
        end = next(i for i in range(index + 1, len(lines)) if lines[i].strip() == match.group(1))
        blocks.append("\n".join(lines[index + 1:end]) + "\n")
        index = end + 1
    return blocks


def contract_rows():
    rows = {}
    for line in read_text(CONTRACT).splitlines():
        match = re.match(r"^\| `([0-9]{2}-[a-z-]+|record)` \|", line)
        if match:
            rows[match.group(1)] = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return rows


class HubCase(unittest.TestCase):
    """A home folder and a project repository in a temporary folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.repo = self.base / "work" / "acme-shop"
        (self.home / ".corthex").mkdir(parents=True)
        self.repo.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        path.write_text(text, encoding="utf-8")

    def project(self, **fields):
        settings = {"name": "acme-shop", "title": "Acme Shop", "team": True}
        settings.update(fields)
        self.write(self.repo / ".corthex" / "project.json", settings)

    def register(self, **entry):
        project = {"name": "acme-shop", "path": str(self.repo)}
        project.update(entry)
        self.write(self.home / ".corthex" / "projects.json", {"projects": [project]})

    def snapshot(self, extra=None):
        ((_, project, reason),) = hub.select_projects(self.home, [], self.repo, extra)
        self.assertIsNotNone(project, reason)
        return hub.make_snapshot(project, hub.load_status(self.home, project.name), NOW)

    def items(self, snapshot):
        return {item["id"]: item for item in snapshot["items"]}

    def found(self, snapshot, rule):
        return [check for check in snapshot["checks"] if check["rule"] == rule]

    def refs(self, snapshot, rule):
        return sorted(ref for check in self.found(snapshot, rule) for ref in check.get("refs", ()))


class StageTableTest(unittest.TestCase):
    def test_stages_match_the_contract(self):
        rows = contract_rows()
        prefixes = dict(hub.KINDS)
        self.assertEqual(list(hub.STAGE_KEYS), [key for key in rows if key != "record"])
        for key, name, default, kinds, _ in hub.STAGES:
            with self.subTest(stage=key):
                _, stage, _, creates, source = rows[key]
                self.assertEqual(name, stage)
                listed = creates.split(", ") if re.fullmatch(r"[A-Z]+(?:, [A-Z]+)*", creates) else []
                self.assertEqual([prefixes[kind] for kind in kinds], listed)
                self.assertEqual(default, source.strip("`") if source.startswith("`") else None)
        self.assertEqual(rows["record"][3], prefixes["decision"])

    def test_kinds_match_the_contract(self):
        line = next(line for line in read_text(CONTRACT).splitlines() if "with these keys:" in line)
        self.assertEqual(list(hub.KIND_NAMES), re.findall(r"`([a-z]+)`", line.split("with these keys:")[1]))


class IdFormatTest(unittest.TestCase):
    def test_ids_are_found_only_as_whole_words(self):
        ids = hub.IdFormat({})
        text = "REQ-001, XREQ-002, REQ-003a, REQ-1234567, SPEC-4이며 (TC-12)"
        self.assertEqual([found[0] for found in ids.find(text)], ["REQ-001", "SPEC-4", "TC-12"])

    def test_project_prefixes(self):
        ids = hub.IdFormat({"spec": {"prefix": ["AUTH", "CHAT"], "digits": 3}, "requirement": "FR", "flow": "FR"})
        self.assertEqual(ids.kind("AUTH-001"), "spec")
        self.assertEqual(ids.kind("FR-01"), "requirement")
        self.assertIsNone(ids.kind("REQ-001"))
        self.assertEqual(ids.clashes, [("FR", "requirement", "flow")])
        self.assertEqual(ids.whole("SCR-002#empty"), ("SCR-002", "screen", "empty"))
        self.assertIsNone(ids.whole("SCR-002 empty"))


class TemplateTest(HubCase):
    """The hub reads what the stage skills' own templates write."""

    def setUp(self):
        super().setUp()
        for path, skill, stage, block in TEMPLATES:
            blocks = output_blocks(skill, stage)
            self.write(self.repo / path, "\n".join(blocks) if block is None else blocks[block])
        self.project()

    def test_domain_template_keeps_nested_mermaid_and_later_sections(self):
        (domain,) = output_blocks("corthex-discover", "01-domain")
        lines = domain.splitlines()
        start = lines.index("```mermaid")
        end = lines.index("```", start + 1)
        self.assertGreater(end, start + 1, "the nested diagram has content")
        self.assertGreater(lines.index("## 6. Hotspots"), end)
        self.assertGreater(lines.index("## 7. Glossary"), end)
        self.assertIn("| TERM-002 | Payment |", domain)
        self.assertNotIn("````", domain, "the outer fence is removed, not copied into the document")

    def test_every_template_defines_its_items(self):
        expected = {
            "CTX-001": ("context", "01-domain", "Ordering"),
            "CTX-002": ("context", "01-domain", "Payment"),
            "TERM-001": ("term", "01-domain", "Order"),
            "TERM-002": ("term", "01-domain", "Payment"),
            "REQ-001": ("requirement", "02-prd", None),
            "REQ-002": ("requirement", "02-prd", None),
            "REQ-003": ("requirement", "02-prd", None),
            "FL-001": ("flow", "03-user-flow", "Place an order"),
            "SPEC-001": ("spec", "04-functional-spec", "Place order"),
            "TBL-001": ("table", "05-erd", "orders"),
            "API-001": ("api", "06-api", "POST /orders"),
            "SCR-001": ("screen", "07-sitemap", "Home"),
            "SCR-002": ("screen", "07-sitemap", "Order detail"),
            "TASK-001": ("task", "10-wbs", "Create order endpoint"),
            "TC-001": ("test", "12-qa", "Order with a failing payment"),
            "TC-002": ("test", "12-qa", "Open another account's order"),
            "BUG-001": ("bug", "12-qa", "Cancel button stays enabled after payment"),
            "SCENE-001": ("scene", "13-presentation", "Ordering takes three taps"),
        }
        items = self.items(self.snapshot())
        self.assertEqual(set(items), set(expected))
        for ident, (kind, stage, title) in expected.items():
            with self.subTest(item=ident):
                self.assertEqual((items[ident]["kind"], items[ident]["stage"]), (kind, stage))
                if title:
                    self.assertEqual(items[ident]["title"], title)
        self.assertEqual(items["REQ-003"]["type"], "non-functional")
        self.assertEqual(items["REQ-001"]["priority"], "Must")
        self.assertEqual(items["SPEC-001"]["status"], "active")

    def test_links_follow_the_templates(self):
        items = self.items(self.snapshot())
        expected = {
            "CTX-001": {"CTX-002"},
            "CTX-002": {"CTX-001"},
            "TERM-001": {"CTX-001"},
            "TERM-002": {"CTX-002"},
            "FL-001": {"REQ-001", "REQ-002", "REQ-004"},
            "SPEC-001": {"REQ-001", "REQ-002", "FL-001"},
            "TBL-001": {"CTX-001", "SPEC-001", "SPEC-002"},
            "API-001": {"SPEC-001"},
            "SCR-001": {"FL-001", "FL-002"},
            "TASK-001": {"SPEC-001", "API-001", "TBL-001"},
            "TC-001": {"FL-001", "SPEC-001", "API-001"},
            "TC-002": {"FL-002", "API-002", "SCR-002"},
            "BUG-001": {"TC-004", "SCR-002", "SPEC-005"},
            "SCENE-001": {"FL-001"},
        }
        for ident, links in expected.items():
            with self.subTest(item=ident):
                self.assertEqual(set(items[ident].get("links", ())), links)
        screen = items["SCR-002"]
        self.assertEqual(screen["parent"], "SCR-001")
        self.assertEqual(screen["screen_doc"], "docs/08-screens/SCR-002.md:1")
        self.assertEqual(screen["states"], ["error", "loading", "permission"])
        self.assertNotIn("status", screen, "a table header is not a field")
        self.assertEqual(items["FL-001"]["where"], "docs/03-user-flow/FL-001.md:1")

    def test_checks_on_the_templates(self):
        snapshot = self.snapshot()
        self.assertEqual(self.refs(snapshot, "unknown-ref"), ["API-002", "FL-002", "REQ-004", "SPEC-002", "SPEC-005", "TC-004"])
        self.assertEqual(self.refs(snapshot, "screen-without-states"), ["SCR-001"])
        self.assertEqual(snapshot["summary"]["checks"], {"error": 0, "warn": 6, "info": 1})
        stages = snapshot["stages"]
        self.assertEqual(stages["01-domain"]["copied"]["newest"], "2026-01-12T10:00+09:00", "the board's read time")
        self.assertTrue(stages["02-prd"]["default_source"])
        self.assertEqual((stages["02-prd"]["files"], stages["02-prd"]["items"]), (1, 3))
        self.assertEqual(stages["08-screen-states"]["items"], 1)
        self.assertEqual(stages["09-mockup"]["source_state"], "missing")
        self.assertNotIn("read", stages["09-mockup"])
        self.assertEqual(stages["11-development"]["source_state"], "none")

    def test_requirement_rules(self):
        path = self.repo / "docs/02-prd/requirements.md"
        text = read_text(path).rstrip("\n")
        self.write(path, text + "\n| REQ-004 | The system shall keep an address book. | functional | Must | CTX-001 | Review | active |"
                   "\n| REQ-005 | The system shall export orders. | functional | | none | Review | active |\n")
        snapshot = self.snapshot()
        self.assertEqual(self.refs(snapshot, "req-without-spec"), ["REQ-004"])
        self.assertEqual(self.refs(snapshot, "req-without-priority"), ["REQ-005"])
        self.assertNotIn("REQ-004", self.refs(snapshot, "unknown-ref"))


# The same schema as the ERD Editor MCP server 1.1.0 writes it for each database, with the line
# of each table ID.
# A column comment of `customers` names SPEC-003 and one of `orders` names TBL-001 and SPEC-004;
# `shipments` has no ID, so its SPEC-005 links from nothing.
ERD_EXPORTS = {
    "mysql": ("""\
CREATE TABLE customers
(
  id    BIGINT       NOT NULL AUTO_INCREMENT COMMENT 'Customer id',
  email VARCHAR(255) NOT NULL COMMENT 'Sign-in email; see SPEC-003',
  PRIMARY KEY (id)
) COMMENT 'TBL-001 customers (CTX-001) <- SPEC-001';

CREATE TABLE orders
(
  id          BIGINT NOT NULL AUTO_INCREMENT,
  customer_id BIGINT NOT NULL COMMENT 'TBL-001 buyer -- see SPEC-004',
  PRIMARY KEY (id)
) COMMENT 'TBL-002 orders (CTX-001) <- SPEC-001, SPEC-002';

CREATE TABLE shipments
(
  id    BIGINT NOT NULL AUTO_INCREMENT,
  label TEXT   NOT NULL COMMENT 'Printed for SPEC-005',
  PRIMARY KEY (id)
);

ALTER TABLE orders
  ADD CONSTRAINT FK_customers_TO_orders
    FOREIGN KEY (customer_id)
    REFERENCES customers (id)
    ON DELETE RESTRICT;
""", 6, 13),
    "postgresql": ("""\
CREATE TABLE "customers"
(
  id    BIGINT       NOT NULL GENERATED ALWAYS AS IDENTITY,
  email VARCHAR(255) NOT NULL UNIQUE,
  PRIMARY KEY (id)
);

COMMENT ON TABLE "customers" IS 'TBL-001 customers (CTX-001) <- SPEC-001';

COMMENT ON COLUMN "customers".email IS 'Sign-in email; see SPEC-003';

CREATE TABLE orders
(
  id          BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
  customer_id BIGINT NOT NULL,
  PRIMARY KEY (id)
);

COMMENT ON TABLE orders IS 'TBL-002 orders (CTX-001)
<- SPEC-001, SPEC-002';

COMMENT ON COLUMN orders.customer_id IS 'TBL-001 buyer''s id -- see SPEC-004';

CREATE TABLE shipments
(
  id    BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
  label TEXT   NOT NULL,
  PRIMARY KEY (id)
);

COMMENT ON COLUMN shipments.label IS 'Printed for SPEC-005';
""", 8, 19),
    "oracle": ("""\
CREATE TABLE customers
(
  id    NUMBER(19)    NOT NULL,
  email VARCHAR2(255) NOT NULL,
  CONSTRAINT PK_customers PRIMARY KEY (id)
);

CREATE SEQUENCE SEQ_customers
START WITH 1
INCREMENT BY 1;

CREATE OR REPLACE TRIGGER SEQ_TRG_customers
BEFORE INSERT ON customers
REFERENCING NEW AS NEW FOR EACH ROW
BEGIN
  SELECT SEQ_customers.NEXTVAL
  INTO :NEW.id
  FROM DUAL;
END;
/

COMMENT ON TABLE customers IS 'TBL-001 customers (CTX-001) <- SPEC-001';

COMMENT ON COLUMN customers.email IS 'Sign-in email; see SPEC-003';

CREATE TABLE orders
(
  id          NUMBER(19) NOT NULL,
  customer_id NUMBER(19) NOT NULL,
  CONSTRAINT PK_orders PRIMARY KEY (id)
);

COMMENT ON TABLE orders IS 'TBL-002 orders (CTX-001) <- SPEC-001, SPEC-002';

COMMENT ON COLUMN orders.customer_id IS 'TBL-001 buyer -- see SPEC-004';

CREATE TABLE shipments
(
  id    NUMBER(19)    NOT NULL,
  label VARCHAR2(255) NOT NULL,
  CONSTRAINT PK_shipments PRIMARY KEY (id)
);

COMMENT ON COLUMN shipments.label IS 'Printed for SPEC-005';
""", 22, 33),
    "sql server": ("""\
CREATE TABLE [customers]
(
  [id]    bigint       NOT NULL IDENTITY(1,1),
  [email] varchar(255) NOT NULL,
  CONSTRAINT [PK_customers] PRIMARY KEY ([id])
)
GO

EXECUTE sys.sp_addextendedproperty 'MS_Description',
  N'TBL-001 customers (CTX-001) <- SPEC-001', 'schema', 'dbo', 'table', 'customers'
GO

EXECUTE sys.sp_addextendedproperty 'MS_Description',
  N'Sign-in email; see SPEC-003', 'schema', 'dbo', 'table', 'customers', 'column', 'email'
GO

CREATE TABLE [orders]
(
  [id]          bigint NOT NULL IDENTITY(1,1),
  [customer_id] bigint NOT NULL,
  CONSTRAINT [PK_orders] PRIMARY KEY ([id])
)
GO

EXEC sp_addextendedproperty @name = N'MS_Description', @value = N'TBL-002 orders (CTX-001) <- SPEC-001, SPEC-002',
  @level0type = N'SCHEMA', @level0name = N'dbo', @level1type = N'TABLE', @level1name = N'orders';

EXEC sp_addextendedproperty @name = N'MS_Description', @value = N'TBL-001 buyer -- see SPEC-004',
  @level0type = N'SCHEMA', @level0name = N'dbo', @level1type = N'TABLE', @level1name = N'orders',
  @level2type = N'COLUMN', @level2name = N'customer_id';

CREATE TABLE [shipments]
(
  [id]    bigint NOT NULL IDENTITY(1,1),
  [label] text   NOT NULL,
  CONSTRAINT [PK_shipments] PRIMARY KEY ([id])
)
GO

EXECUTE sys.sp_addextendedproperty 'MS_Description',
  N'Printed for SPEC-005', 'schema', 'dbo', 'table', 'shipments', 'column', 'label'
GO
""", 10, 25),
    "snowflake and databricks": ("""\
CREATE TABLE customers
(
  id    NUMBER  NOT NULL COMMENT 'Customer id',
  email VARCHAR NOT NULL COMMENT 'Sign-in email; see SPEC-003',
  CONSTRAINT PK_customers PRIMARY KEY (id)
)
COMMENT = 'TBL-001 customers (CTX-001) <- SPEC-001';

CREATE TABLE orders
(
  id          BIGINT NOT NULL,
  customer_id BIGINT NOT NULL COMMENT 'TBL-001 buyer -- see SPEC-004'
)
USING DELTA
COMMENT 'TBL-002 orders (CTX-001) <- SPEC-001, SPEC-002';

CREATE TABLE shipments
(
  id    NUMBER  NOT NULL,
  label VARCHAR NOT NULL COMMENT 'Printed for SPEC-005'
);
""", 7, 15),
    "sqlite": ("""\
-- TBL-001 customers (CTX-001) <- SPEC-001
CREATE TABLE customers
(
  -- Sign-in email; see SPEC-003
  email TEXT    NOT NULL,
  id    INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT
);

-- TBL-002 orders (CTX-001) <- SPEC-001, SPEC-002
CREATE TABLE orders
(
  -- TBL-001 buyer's id -- see SPEC-004
  customer_id INTEGER NOT NULL,
  id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
  FOREIGN KEY (customer_id) REFERENCES customers (id)
);

CREATE TABLE shipments
(
  -- Printed for SPEC-005
  label TEXT    NOT NULL,
  id    INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT
);
""", 1, 9),
}


class FormsTest(HubCase):
    def test_item_files_and_listings(self):
        self.project(ids={"requirement": {"prefix": "REQ", "digits": 2}}, stages={"02-prd": {"human": "notion", "source": "prd/", "truth": "human"}})
        self.write(self.repo / "prd/REQ-01.md", "---\nid: REQ-01\ntitle: Sign up\nexported_at: 2026-01-10T09:00\n---\n# REQ-01 Sign up (draft)\n\nLeads to ~~SPEC-009~~ SPEC-001.\n")
        self.write(self.repo / "prd/REQ-02 Sign in.md", "# REQ-02 Sign in\n\n| Status | Draft |\n| --- | --- |\n| Priority | Must |\n")
        self.write(self.repo / "prd/_index.md", "| ID | 요구사항 | 우선순위 |\n| --- | --- | --- |\n| REQ-01 | Sign up | Should |\n| REQ-02 | Sign in | Must |\n")
        snapshot = self.snapshot()
        items = self.items(snapshot)
        self.assertEqual(items["REQ-01"]["title"], "Sign up")
        self.assertEqual(items["REQ-01"]["where"], "prd/REQ-01.md:1")
        self.assertEqual(items["REQ-01"]["priority"], "Should", "a listing fills in missing fields")
        self.assertEqual(items["REQ-01"]["links"], ["SPEC-001"], "struck-through text is ignored")
        self.assertEqual((items["REQ-02"]["title"], items["REQ-02"]["priority"]), ("Sign in", "Must"))
        self.assertEqual(self.found(snapshot, "duplicate-id"), [])
        self.assertEqual(snapshot["stages"]["02-prd"]["copied"], {"oldest": "2026-01-10T09:00", "newest": "2026-01-10T09:00"})

    def test_duplicate_definitions(self):
        self.project(stages={"02-prd": {"human": "notion", "source": "prd/", "truth": "source"}})
        self.write(self.repo / "prd/a.md", "## REQ-001 Sign up\n")
        self.write(self.repo / "prd/b.md", "## REQ-001 Sign up again\n")
        (check,) = self.found(self.snapshot(), "duplicate-id")
        self.assertEqual((check["level"], check["refs"]), ("error", ["REQ-001"]))
        self.assertEqual(check["args"]["places"], ["prd/a.md:1", "prd/b.md:1"])

    def test_id_formats_and_upstream_links(self):
        self.project(ids={"spec": {"prefix": ["AUTH", "CHAT"], "digits": 3}, "test": "TASK"}, stages={
            "02-prd": {"human": "notion", "source": "prd.md", "truth": "source"},
            "04-functional-spec": {"human": "notion", "source": "spec.md", "truth": "source"},
        })
        self.write(self.repo / "prd.md", "| ID | Requirement | Type | Priority |\n| --- | --- | --- | --- |\n| REQ-001 | Sign in | functional | Must |\n")
        self.write(self.repo / "spec.md", "| ID | Behaviour | From | Status |\n| --- | --- | --- | --- |\n"
                   "| AUTH-001 | Sign in | REQ-001 | active |\n| CHAT-01 | Ask a question | | active |\n| AUTH-002 | Old sign in | | removed |\n")
        snapshot = self.snapshot()
        self.assertEqual(self.refs(snapshot, "id-format"), ["CHAT-01"])
        self.assertEqual(self.found(snapshot, "id-config")[0]["args"], {"prefix": "TASK", "kinds": ["task", "test"]})
        self.assertEqual(self.refs(snapshot, "missing-upstream"), ["CHAT-01"], "removed items are left out")
        self.assertEqual(self.found(snapshot, "req-without-spec"), [])

    def test_links_to_removed_or_undefined_items_do_not_count(self):
        self.project(stages={
            "02-prd": {"human": "notion", "source": "prd.md", "truth": "source"},
            "04-functional-spec": {"human": "notion", "source": "spec.md", "truth": "source"},
        })
        self.write(self.repo / "prd.md", "| ID | Requirement | Type | Priority | Status | Spec |\n| --- | --- | --- | --- | --- | --- |\n"
                   "| REQ-001 | Check out | functional | Must | active | |\n| REQ-002 | Old sign in | functional | Must | removed | |\n"
                   "| REQ-003 | Pay | functional | Must | active | SPEC-009 |\n| REQ-004 | Sign in | functional | Must | active | |\n")
        self.write(self.repo / "spec.md", "| ID | Behaviour | From | Status |\n| --- | --- | --- | --- |\n"
                   "| SPEC-001 | Old checkout | REQ-001 | removed |\n| SPEC-002 | Sign in again | REQ-002 | active |\n"
                   "| SPEC-003 | Sign in | REQ-004 | active |\n")
        snapshot = self.snapshot()
        self.assertEqual(self.refs(snapshot, "req-without-spec"), ["REQ-001", "REQ-003"], "a removed or undefined spec covers nothing")
        self.assertEqual(self.refs(snapshot, "missing-upstream"), ["SPEC-002"], "a removed requirement is not an upstream")

    def test_a_heading_without_an_id_closes_the_item(self):
        self.project(stages={"02-prd": {"human": "notion", "source": "prd.md", "truth": "source"}})
        self.write(self.repo / "prd.md", "# Requirements\n\n## REQ-001 One\n\nLeads to SPEC-001.\n\n## References for SPEC-002\n\nAnd SPEC-003.\n\n"
                   "## REQ-002 Two\n\n### Notes on SPEC-004\n")
        items = self.items(self.snapshot())
        self.assertEqual(items["REQ-001"]["links"], ["SPEC-001"])
        self.assertEqual(items["REQ-002"]["links"], ["SPEC-004"], "a lower heading stays in the item")

    def test_fields_are_cleaned(self):
        self.project(stages={"02-prd": {"human": "notion", "source": "prd.md", "truth": "human"}})
        self.write(self.repo / "prd.md", "| ID | Title | Status | Link |\n| --- | --- | --- | --- |\n"
                   "| REQ-001 | **Sign** [in](https://example.com/a) | - | https://someone:pw@example.com/req-1 |\n")
        item = self.items(self.snapshot())["REQ-001"]
        self.assertEqual(item["title"], "Sign in")
        self.assertNotIn("status", item)
        self.assertEqual(item["link"], "https://example.com/req-1")

    def test_screens(self):
        self.project(stages={
            "07-sitemap": {"human": "board", "source": "sitemap.yaml", "truth": "source"},
            "08-screen-states": {"human": "wireframes", "source": "screens/", "truth": "source"},
        })
        self.write(self.repo / "sitemap.yaml", "- id: SCR-001\n  name: Home\n- id: SCR-002\n  name: Cart\n")
        self.write(self.repo / "screens/SCR-001.md", "# SCR-001 Home\n\n| State | Shows |\n| --- | --- |\n| SCR-001#empty | A hint |\n")
        self.write(self.repo / "screens/SCR-009.md", "# SCR-009 Settings\n")
        self.write(self.repo / "screens/responses.md", "| Response | Shows |\n| --- | --- |\n| API-001#default | A retry button |\n")
        self.write(self.repo / "api/openapi.yaml", "paths:\n  /home:\n    get:\n      x-corthex:\n        id: API-001\n")
        snapshot = self.snapshot()
        items = self.items(snapshot)
        self.assertEqual(items["SCR-001"]["states"], ["empty"])
        self.assertNotIn("states", items["API-001"], "a response is not a screen state")
        self.assertEqual(self.refs(snapshot, "screen-not-in-sitemap"), ["SCR-009"])
        self.assertEqual(self.refs(snapshot, "screen-without-states"), ["SCR-002"])

    def test_yaml_comments(self):
        self.project(stages={"07-sitemap": {"human": "board", "source": "sitemap.yaml", "truth": "source"}})
        self.write(self.repo / "sitemap.yaml", "# Screens\n- id: SCR-001 # Home\n  name: Home # the first screen\n  status: \"live\" # since January\n")
        snapshot = self.snapshot()
        item = self.items(snapshot)["SCR-001"]
        self.assertEqual((item["title"], item["status"], item["where"]), ("Home", "live", "sitemap.yaml:2"))
        self.assertEqual(self.found(snapshot, "unknown-ref"), [])

    def test_json_definitions_keep_their_own_lines(self):
        self.project(stages={"07-sitemap": {"human": "board", "source": "sitemap.json", "truth": "source"}})
        self.write(self.repo / "sitemap.json", json.dumps({
            "intro": "Start at SCR-002.",
            "screens": [{"id": "SCR-001", "name": "Home"}, {"id": "SCR-002", "name": "Cart"}, {"id": "SCR-001", "name": "Home again"}],
        }, indent=1))
        snapshot = self.snapshot()
        self.assertEqual(self.items(snapshot)["SCR-002"]["where"], "sitemap.json:9", "the definition, not the earlier mention")
        (check,) = self.found(snapshot, "duplicate-id")
        self.assertEqual(check["args"]["places"], ["sitemap.json:5", "sitemap.json:13"])

    def test_large_table_fields(self):
        self.project(stages={"02-prd": {"human": "notion", "source": "requirements.csv", "truth": "human"}})
        self.write(self.repo / "requirements.csv", "ID,Title,Notes\nREQ-001,Sign in,%s\n" % ("x" * 200000))
        self.assertEqual(self.items(self.snapshot())["REQ-001"]["title"], "Sign in")

    def test_table_records_over_several_lines(self):
        self.project(stages={"02-prd": {"human": "notion", "source": "requirements.csv", "truth": "human"}})
        self.write(self.repo / "requirements.csv", 'ID,Title,Notes\nREQ-001,"Access is not\nallowed",See SPEC-001\nREQ-002,Sign in,"Two\nlines"\nREQ-003,Sign out,\n')
        items = self.items(self.snapshot())
        self.assertEqual(items["REQ-001"].get("title"), "Access is not allowed")
        self.assertEqual([items[ident]["where"] for ident in ("REQ-001", "REQ-002", "REQ-003")],
                         ["requirements.csv:2", "requirements.csv:4", "requirements.csv:6"], "the line each record starts on")

    def test_yaml_keys_in_any_order(self):
        self.project(stages={"07-sitemap": {"human": "board", "source": "sitemap.yaml", "truth": "source"}})
        self.write(self.repo / "sitemap.yaml", "- name: Home\n  flows: [FL-001]\n  children:\n    - name: Cart\n      id: SCR-002\n  id: SCR-001\n")
        items = self.items(self.snapshot())
        home, cart = items["SCR-001"], items["SCR-002"]
        self.assertEqual((home.get("title"), home.get("links"), home["where"]), ("Home", ["FL-001"], "sitemap.yaml:6"))
        self.assertEqual((cart.get("title"), cart.get("parent"), cart["where"]), ("Cart", "SCR-001", "sitemap.yaml:5"))

    def test_table_comments_as_erd_editor_writes_them(self):
        self.project(stages={"05-erd": {"human": "erd-editor", "source": "db/schema.sql", "truth": "human"}})
        for database, (sql, first, second) in ERD_EXPORTS.items():
            with self.subTest(database=database):
                self.write(self.repo / "db/schema.sql", sql)
                snapshot = self.snapshot()
                items = self.items(snapshot)
                self.assertEqual({ident: (item["kind"], item["title"], item["where"]) for ident, item in items.items()}, {
                    "TBL-001": ("table", "customers", "db/schema.sql:%d" % first),
                    "TBL-002": ("table", "orders", "db/schema.sql:%d" % second),
                })
                self.assertEqual(set(items["TBL-001"]["links"]), {"CTX-001", "SPEC-001", "SPEC-003"})
                self.assertEqual(set(items["TBL-002"]["links"]), {"CTX-001", "SPEC-001", "SPEC-002", "SPEC-004", "TBL-001"},
                                 "a column comment links from its own table, even one that starts with an ID")
                self.assertEqual(self.found(snapshot, "duplicate-id"), [])

    def test_sql_strings_and_trailing_comments(self):
        self.project(stages={"05-erd": {"human": "erd-editor", "source": "db/schema.sql", "truth": "source"}})
        self.write(self.repo / "db/schema.sql", "-- Schema for the shop; TBL-009 is planned.\n"
                   "-- TBL-001 customers (CTX-001) ← SPEC-001\n-- One row per account.\nCREATE TABLE IF NOT EXISTS customers (\n"
                   "  id   BIGINT PRIMARY KEY,\n  note TEXT DEFAULT '-- TBL-003 is a value; not a comment'\n);\n"
                   "CREATE INDEX customers_note ON customers (note); -- for SPEC-003\n\n"
                   "CREATE TABLE orders (id BIGINT PRIMARY KEY) ENGINE=InnoDB COMMENT='TBL-002 <- SPEC-002';\n")
        items = self.items(self.snapshot())
        self.assertEqual({ident: (item["title"], item["where"]) for ident, item in items.items()}, {
            "TBL-001": ("customers", "db/schema.sql:2"),
            "TBL-002": ("orders", "db/schema.sql:10"),
        }, "an ID in a string is not a definition, and a table comment without a name takes the table's")
        self.assertEqual(set(items["TBL-001"]["links"]), {"CTX-001", "SPEC-001", "SPEC-003", "TBL-003"})
        self.assertEqual(items["TBL-002"]["links"], ["SPEC-002"])

    def test_sql_backslashes_in_strings(self):
        self.project(stages={"05-erd": {"human": "erd-editor", "source": "db/", "truth": "source"}})
        # MySQL reads \' as a quote, and ERD Editor writes an apostrophe that way for Databricks.
        self.write(self.repo / "db/mysql.sql", "CREATE TABLE notes (body TEXT DEFAULT 'buyer\\'s account');\n"
                   "-- TBL-001 customers ← SPEC-001\nCREATE TABLE customers (id BIGINT PRIMARY KEY);\n")
        self.write(self.repo / "db/databricks.sql", "CREATE TABLE `orders`\n(\n  `id` BIGINT NOT NULL COMMENT 'buyer\\'s id, see SPEC-003'\n)\n"
                   "USING DELTA\nCOMMENT 'TBL-002 buyer\\'s orders <- SPEC-002';\n")
        # PostgreSQL reads the backslash as a character.
        self.write(self.repo / "db/postgres.sql", "CREATE TABLE files (path TEXT DEFAULT 'C:\\');\n"
                   "-- TBL-003 folders ← SPEC-004\nCREATE TABLE folders (path TEXT DEFAULT 'D:\\');\n")
        items = self.items(self.snapshot())
        self.assertEqual({ident: item["title"] for ident, item in items.items()},
                         {"TBL-001": "customers", "TBL-002": "buyer's orders", "TBL-003": "folders"})
        self.assertEqual(set(items["TBL-002"]["links"]), {"SPEC-002", "SPEC-003"})
        self.assertEqual(items["TBL-003"]["links"], ["SPEC-004"])

    def test_sql_server_batches_with_a_count(self):
        self.project(stages={"05-erd": {"human": "erd-editor", "source": "db/schema.sql", "truth": "source"}})
        self.write(self.repo / "db/schema.sql", "PRINT 'prelude'\nGO 2\n-- TBL-001 customers\nCREATE TABLE customers (id INT)\nGO\n"
                   "ALTER TABLE customers ADD note INT -- SPEC-002\nGO 3\n"
                   "EXECUTE sp_addextendedproperty 'MS_Description', N'TBL-002 orders', 'schema', 'dbo', 'table', 'orders'\nGO\n")
        items = self.items(self.snapshot())
        self.assertEqual(sorted(items), ["TBL-001", "TBL-002"])
        self.assertEqual(items["TBL-001"]["links"], ["SPEC-002"])

    def test_sql_tables_in_schemas(self):
        self.project(stages={"05-erd": {"human": "erd-editor", "source": "db/", "truth": "source"}})
        self.write(self.repo / "db/shop.sql", "-- TBL-001 sales orders\nCREATE TABLE sales.orders (\n  id INT\n);\n"
                   "-- TBL-002 archived orders\nCREATE TABLE archive.orders (\n  id INT -- kept for SPEC-004\n);\n"
                   "COMMENT ON COLUMN sales.orders.id IS 'SPEC-005';\nALTER TABLE orders ADD note INT; -- SPEC-006\n"
                   "-- TBL-003 customers\nCREATE TABLE crm.customers (id INT);\nALTER TABLE customers ADD note INT; -- SPEC-007\n")
        self.write(self.repo / "db/stock.sql", "-- TBL-004 items\nCREATE TABLE items (id INT);\n"
                   "-- TBL-005 archived items\nCREATE TABLE archive.items (\n  id INT -- kept for SPEC-008\n);\n")
        items = self.items(self.snapshot())
        self.assertEqual(items["TBL-001"]["links"], ["SPEC-005"])
        self.assertEqual(items["TBL-002"]["links"], ["SPEC-004"], "a name in two schemas links from neither table")
        self.assertEqual(items["TBL-003"]["links"], ["SPEC-007"], "a name without its schema means the only table of that name")
        self.assertEqual(items["TBL-005"]["links"], ["SPEC-008"])
        self.assertNotIn("links", items["TBL-004"], "a table created without a schema is a table of its own")


class SourcesTest(HubCase):
    def test_other_repository(self):
        design = self.base / "work" / "acme-design"
        self.write(design / "prd/requirements.md", "| ID | Requirement |\n| --- | --- |\n| REQ-001 | Sign in |\n")
        self.project(repos={"design": "https://github.com/example/acme-design.git"}, stages={"02-prd": {"human": "notion", "source": "design:prd/", "truth": "human"}})
        self.register(repos={"design": str(design)})
        snapshot = self.snapshot()
        self.assertEqual(self.items(snapshot)["REQ-001"]["where"], "design:prd/requirements.md:3")
        self.assertEqual(snapshot["stages"]["02-prd"]["repo"], "design")
        self.assertEqual(snapshot["repos"]["design"]["web"], "https://github.com/example/acme-design")

    def test_repository_without_a_checkout(self):
        self.project(repos={"design": "https://github.com/example/acme-design"}, stages={"02-prd": {"human": "notion", "source": "design:prd/", "truth": "human"}})
        snapshot = self.snapshot()
        self.assertEqual(snapshot["stages"]["02-prd"]["source_state"], "no-checkout")
        self.assertEqual(snapshot["repos"]["design"], {"checkout": False, "url": "https://github.com/example/acme-design", "web": "https://github.com/example/acme-design"})
        self.assertEqual(self.found(snapshot, "no-checkout")[0]["level"], "warn")

    def test_sources_that_need_a_fix(self):
        elsewhere = str(self.base / "elsewhere")
        self.project(stages={
            "01-domain": {"human": "miro", "source": "wiki:domain/", "truth": "human"},
            "02-prd": {"human": "notion", "source": elsewhere, "truth": "human"},
            "03-user-flow": {"human": "notion", "source": "../acme-design/flows/", "truth": "human"},
            "04-functional-spec": {"human": "notion", "source": "spec/", "truth": "human"},
            "05-erd": {"skip": True},
        })
        snapshot = self.snapshot()
        rules = {check["stage"]: (check["rule"], check["level"]) for check in snapshot["checks"]}
        self.assertEqual(rules["01-domain"], ("unknown-alias", "error"))
        self.assertEqual(rules["02-prd"], ("source-invalid", "error"))
        self.assertEqual(rules["03-user-flow"], ("source-outside", "error"))
        self.assertEqual(rules["04-functional-spec"], ("source-missing", "warn"))
        self.assertEqual(snapshot["stages"]["02-prd"]["source"], "[absolute path]")
        self.assertEqual(snapshot["stages"]["05-erd"]["state"], "skipped")
        text = json.dumps(snapshot, ensure_ascii=False)
        for form in (str(self.base), json.dumps(str(self.base))[1:-1], self.base.as_posix()):
            self.assertNotIn(form, text)

    def test_an_entry_without_a_source_is_not_read(self):
        self.project(stages={"02-prd": {}, "03-user-flow": {"human": "notion"}})
        self.write(self.repo / "docs/02-prd/requirements.md", "## REQ-001 Sign in\n")
        self.write(self.repo / "docs/03-user-flow/FL-001.md", "# FL-001 Sign in\n")
        self.write(self.repo / "docs/04-functional-spec/spec.md", "## SPEC-001 Sign in\n")
        snapshot = self.snapshot()
        stages = snapshot["stages"]
        self.assertEqual(set(self.items(snapshot)), {"SPEC-001"}, "only the stage without an entry uses its default path")
        self.assertEqual([stages[key]["source_state"] for key in ("02-prd", "03-user-flow")], ["none", "none"])
        self.assertNotIn("default_source", stages["02-prd"])
        self.assertTrue(stages["04-functional-spec"]["default_source"])

    def test_skipped_files(self):
        self.project(stages={"02-prd": {"human": "notion", "source": "prd/", "truth": "source"}})
        self.write(self.repo / "prd/requirements.md", "## REQ-001 Sign in\n")
        self.write(self.repo / "prd/api-keys.md", "## REQ-002 Hidden\n")
        self.write(self.repo / "prd/.drafts/notes.md", "## REQ-003 Hidden\n")
        self.write(self.repo / "prd/board.png", "not text")
        snapshot = self.snapshot()
        self.assertEqual(set(self.items(snapshot)), {"REQ-001"})
        self.assertEqual(snapshot["stages"]["02-prd"]["skipped"], {"secret": 1, "format": 1})
        self.assertEqual(self.found(snapshot, "files-skipped")[0]["args"]["reasons"], {"secret": 1})

    def test_translations_beside_their_originals_are_skipped(self):
        self.project(stages={
            "01-domain": {"human": "github", "source": "docs/01-domain/", "truth": "source"},
            "02-prd": {"human": "github", "source": "docs/02-prd/memory.ko.md", "truth": "source"},
        })
        self.write(self.repo / "docs/01-domain/memory.md", "## CTX-001 Capture\n")
        self.write(self.repo / "docs/01-domain/memory.ko.md", "## CTX-001 기록\n")
        self.write(self.repo / "docs/01-domain/hub.md", "## CTX-002 Hub\n")
        self.write(self.repo / "docs/01-domain/hub.pt-BR.md", "## CTX-002 Central\n")
        self.write(self.repo / "docs/01-domain/sync.zh-Hans.md", "## CTX-003 同步\n")
        self.write(self.repo / "docs/01-domain/plan.md", "## CTX-004 Plan\n")
        self.write(self.repo / "docs/01-domain/plan.v2.md", "## CTX-005 Plan again\n")
        self.write(self.repo / "docs/02-prd/memory.md", "## REQ-001 Record prompts\n")
        self.write(self.repo / "docs/02-prd/memory.ko.md", "## REQ-001 프롬프트 기록\n")
        snapshot = self.snapshot()
        items = self.items(snapshot)
        self.assertEqual((items["CTX-001"]["title"], items["CTX-001"]["where"]), ("Capture", "docs/01-domain/memory.md:1"))
        self.assertEqual(items["CTX-002"]["where"], "docs/01-domain/hub.md:1")
        self.assertEqual(items["CTX-003"]["where"], "docs/01-domain/sync.zh-Hans.md:1", "a translation without its original is read")
        self.assertIn("CTX-005", items, "v2 is not a language tag")
        self.assertEqual(items["REQ-001"]["where"], "docs/02-prd/memory.ko.md:1", "a source may name a translation")
        self.assertEqual(self.found(snapshot, "duplicate-id"), [])
        self.assertEqual(snapshot["stages"]["01-domain"]["files"], 5)
        self.assertEqual(snapshot["stages"]["01-domain"]["skipped"], {"translation": 2})
        self.assertEqual(self.found(snapshot, "files-skipped"), [], "translations are expected, not a finding")

    def test_a_file_with_ids_of_its_own_is_read(self):
        self.project(stages={"02-prd": {"human": "github", "source": "prd/", "truth": "source"}})
        self.write(self.repo / "prd/spec.md", "## REQ-001 Sign in\n")
        # Not a translation: the screens' requirements, in a file of their own.
        self.write(self.repo / "prd/spec.ui.md", "## REQ-002 Show the sign-in screen\n")
        self.write(self.repo / "prd/spec.ui.ko.md", "## REQ-002 로그인 화면 보이기\n")
        # A translation ahead of its original is read, and its shared IDs show as duplicates.
        self.write(self.repo / "prd/plan.md", "## REQ-003 Plan the release\n")
        self.write(self.repo / "prd/plan.ko.md", "## REQ-003 출시 계획\n## REQ-004 새 요구사항\n")
        snapshot = self.snapshot()
        items = self.items(snapshot)
        self.assertEqual(set(items), {"REQ-001", "REQ-002", "REQ-003", "REQ-004"})
        self.assertEqual(items["REQ-002"]["where"], "prd/spec.ui.md:1")
        self.assertEqual(items["REQ-003"]["where"], "prd/plan.md:1", "the original's definition comes first")
        self.assertEqual(items["REQ-004"]["where"], "prd/plan.ko.md:2")
        self.assertEqual(self.refs(snapshot, "duplicate-id"), ["REQ-003"])
        self.assertEqual(snapshot["stages"]["02-prd"]["files"], 4)
        self.assertEqual(snapshot["stages"]["02-prd"]["skipped"], {"translation": 1}, "spec.ui.ko.md translates spec.ui.md")

    def test_translation_names(self):
        present = {Path("docs") / name for name in ("spec.md", "spec.MD", "notes.txt", "a.b.md")}
        for name, expected in (
            ("spec.ko.md", "spec.md"), ("spec.pt-BR.md", "spec.md"), ("spec.zh-Hans.md", "spec.md"), ("spec.es-419.md", "spec.md"),
            ("spec.ko.MD", "spec.MD"), ("a.b.ko.md", "a.b.md"), ("notes.ko.txt", "notes.txt"), ("notes.ko.md", None),
            ("spec.v2.md", None), ("spec.old.md", None), ("spec.KO.md", None), ("ko.md", None), ("other.ko.md", None),
        ):
            with self.subTest(name=name):
                self.assertEqual(hub.original_of(Path("docs") / name, present), expected and Path("docs") / expected)

    def test_secret_folders_are_skipped(self):
        self.project(stages={"02-prd": {"human": "notion", "source": "prd/", "truth": "source"}})
        self.write(self.repo / "prd/requirements.md", "## REQ-001 Sign in\n")
        self.write(self.repo / "prd/secrets/REQ-002.md", "# REQ-002 Hidden\n")
        self.write(self.repo / "prd/team/credentials/notes.md", "## REQ-003 Hidden\n")
        snapshot = self.snapshot()
        self.assertEqual(set(self.items(snapshot)), {"REQ-001"})
        self.assertEqual(snapshot["stages"]["02-prd"]["skipped"], {"secret": 2})

    def test_links_to_secret_files_are_skipped(self):
        self.project(stages={"02-prd": {"human": "notion", "source": "prd/", "truth": "source"}})
        self.write(self.repo / "prd/requirements.md", "## REQ-001 Sign in\n")
        self.write(self.repo / "secrets/REQ-002.md", "# REQ-002 Hidden\n")
        try:
            os.symlink(os.path.join("..", "secrets", "REQ-002.md"), str(self.repo / "prd/REQ-002.md"))
            os.symlink("loop.md", str(self.repo / "prd/loop.md"))
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available")
        snapshot = self.snapshot()
        self.assertEqual(set(self.items(snapshot)), {"REQ-001"})
        self.assertEqual(snapshot["stages"]["02-prd"]["skipped"], {"secret": 1, "unreadable": 1})

    def test_secrets_and_emails_are_redacted(self):
        key = "sk-" + "x" * 24
        address = "dev" + "@" + "corp.test"
        self.project(stages={"02-prd": {"human": "notion", "source": "prd.md", "truth": "source"}})
        self.write(self.repo / "prd.md", "## REQ-001 Ask %s with %s\n" % (address, key))
        text = json.dumps(self.snapshot())
        self.assertNotIn(key, text)
        self.assertNotIn(address, text)
        self.assertIn("Ask [redacted] with [redacted]", text)

    def test_links_that_hold_secrets_are_left_out(self):
        token = "ghp_" + "x" * 36
        address = "dev" + "%40" + "corp.test"
        # A word that ends in "sk" before a hyphen is not a key, in a title or in a page address.
        title = "Task" + "-management-and-reporting"
        page = "https://www.notion.so/acme/Task" + "-board-for-the-spring-release-" + "0123456789abcdef" * 2
        self.project(records={"kind": "notion", "location": "https://example.com/records?token=" + token},
                     stages={"02-prd": {"human": "notion", "source": "prd.md", "truth": "human", "link": "https://example.com/prd?owner=" + address}})
        self.write(self.repo / "prd.md", "| ID | Title | Link |\n| --- | --- | --- |\n"
                   "| REQ-001 | Sign in | https://example.com/req-1?token=%s |\n| REQ-002 | %s | %s |\n" % (token, title, page))
        snapshot = self.snapshot()
        items = self.items(snapshot)
        self.assertNotIn("link", items["REQ-001"])
        self.assertEqual((items["REQ-002"].get("title"), items["REQ-002"].get("link")), (title, page))
        self.assertEqual(snapshot["project"]["records"]["link"], "")
        self.assertNotIn("link", snapshot["stages"]["02-prd"])
        text = json.dumps(snapshot)
        self.assertNotIn(token, text)
        self.assertNotIn("corp.test", text)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_repository_state(self):
        self.project()
        def git(*args):
            subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "-c", "commit.gpgsign=false"] + list(args), check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        git("add", ".")
        git("commit", "-q", "-m", "start")
        git("remote", "add", "origin", "git" + "@github.com:example/acme-shop.git")
        info = self.snapshot()["repos"]["."]
        self.assertRegex(info["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual((info["branch"], info["dirty"], info["web"]), ("main", False, "https://github.com/example/acme-shop"))
        self.write(self.repo / "notes.md", "draft\n")
        self.assertTrue(self.snapshot()["repos"]["."]["dirty"])

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_reading_a_repository_runs_no_hook_and_writes_nothing(self):
        self.project()
        def git(*args):
            subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "-c", "commit.gpgsign=false"] + list(args), check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        git("add", ".")
        git("commit", "-q", "-m", "start")
        marker = self.base / "hook-ran"
        hook = self.base / "fsmonitor.sh"
        self.write(hook, "#!/bin/sh\necho ran > '%s'\nexit 1\n" % marker.as_posix())
        hook.chmod(0o755)
        git("config", "core.fsmonitor", hook.as_posix())
        settings = self.repo / ".corthex" / "project.json"
        os.utime(settings, (1000000000, 1000000000))  # makes `git status` want to refresh the index
        index = self.repo / ".git" / "index"
        before = (index.read_bytes(), index.stat().st_mtime_ns)
        self.assertIn("commit", hub.repo_info(self.repo))
        self.assertFalse(marker.exists(), "the repository's fsmonitor hook ran")
        self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), before, "the index was rewritten")

    def commit_all(self, root):
        for args in (["init", "-q", "-b", "main"], ["add", "."], ["commit", "-q", "-m", "start"]):
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "-c", "commit.gpgsign=false"] + args, check=True, capture_output=True)

    def set_filter(self, root, name, marker):
        subprocess.run(["git", "-C", str(root), "config", "filter.%s.clean" % name, "echo ran > '%s'; cat" % marker.as_posix()],
                       check=True, capture_output=True)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_reading_a_repository_runs_no_clean_filter(self):
        self.project()
        self.write(self.repo / ".gitattributes", "* filter=probe\n")
        self.commit_all(self.repo)
        marker = self.base / "filter-ran"
        self.set_filter(self.repo, "probe", marker)
        os.utime(self.repo / ".corthex" / "project.json", (1000000000, 1000000000))  # makes Git compare the content
        info = hub.repo_info(self.repo)
        self.assertIn("commit", info)
        self.assertFalse(marker.exists(), "the repository's clean filter ran")
        self.assertNotIn("dirty", info, "Git can only tell by running the filter")

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_changes_are_found_when_no_file_uses_a_filter(self):
        # Git for Windows and `git lfs install` set a filter for every repository.
        self.project()
        self.commit_all(self.repo)
        marker = self.base / "filter-ran"
        self.set_filter(self.repo, "unused", marker)
        settings = self.repo / ".corthex" / "project.json"
        os.utime(settings, (1000000000, 1000000000))
        self.assertIs(hub.repo_info(self.repo)["dirty"], False)
        self.write(settings, settings.read_text(encoding="utf-8").replace("Acme", "Acne"))
        self.assertIs(hub.repo_info(self.repo)["dirty"], True)
        self.assertFalse(marker.exists())

    @unittest.skipIf(os.name == "nt", "the stand-in git is a shell script")
    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_git_never_comes_from_the_current_folder(self):
        real = os.path.dirname(shutil.which("git"))
        self.project()
        self.commit_all(self.repo)
        marker = self.base / "stand-in-ran"
        stand_in = self.repo / "git"
        self.write(stand_in, "#!/bin/sh\necho ran > '%s'\n" % marker.as_posix())
        stand_in.chmod(0o755)
        here, path = os.getcwd(), os.environ.get("PATH", "")
        os.chdir(str(self.repo))
        # A relative entry is the current folder, which Windows searches first anyway.
        os.environ["PATH"] = os.pathsep.join([".", real])
        try:
            info = hub.repo_info(self.repo)
        finally:
            os.chdir(here)
            os.environ["PATH"] = path
        self.assertFalse(marker.exists(), "a git from the current folder ran")
        self.assertIn("commit", info)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_reading_a_repository_does_not_enter_its_submodules(self):
        self.project()
        part = self.base / "work" / "parts"
        self.write(part / "notes.md", "draft\n")
        self.write(part / ".gitattributes", "* filter=probe\n")
        self.commit_all(part)
        self.commit_all(self.repo)
        subprocess.run(["git", "-C", str(self.repo), "-c", "protocol.file.allow=always", "submodule", "add", "-q", part.as_posix(), "parts"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "-c", "commit.gpgsign=false", "commit", "-q", "-m", "parts"], check=True, capture_output=True)
        marker = self.base / "filter-ran"
        self.set_filter(self.repo / "parts", "probe", marker)
        os.utime(self.repo / "parts" / "notes.md", (1000000000, 1000000000))
        self.assertIs(hub.repo_info(self.repo)["dirty"], False)
        self.assertFalse(marker.exists(), "the submodule's clean filter ran")


class StatusTest(HubCase):
    def test_recorded_progress_reaches_the_snapshot(self):
        self.project(stages={"05-erd": {"skip": True}})
        hub.record_status(self.home, "acme-shop", "02-prd", "done", "PRD approved in the kickoff review", "2026-01-12",
                          "Write the user flows", [("warn", "SPEC-001 contradicts REQ-002 on refunds")], now=NOW)
        snapshot = self.snapshot()
        stage = snapshot["stages"]["02-prd"]
        self.assertEqual((stage["state"], stage["checkpoint"], stage["checkpoint_date"]), ("done", "PRD approved in the kickoff review", "2026-01-12"))
        self.assertEqual((stage["next"], stage["updated"]), ("Write the user flows", NOW))
        (review,) = self.found(snapshot, "review")
        self.assertEqual((review["by"], review["level"], review["stage"], review["refs"], review["at"]), ("review", "warn", "02-prd", ["REQ-002", "SPEC-001"], "2026-01-12"))
        self.assertEqual(snapshot["stages"]["03-user-flow"]["state"], "unknown")
        self.assertEqual(snapshot["stages"]["05-erd"]["state"], "skipped")
        self.assertEqual(snapshot["summary"]["states"], {"done": 1, "unknown": 11, "skipped": 1})

    def test_each_write_keeps_a_backup(self):
        path = hub.status_path(self.home, "acme-shop")
        hub.record_status(self.home, "acme-shop", "02-prd", "in_progress", now=NOW)
        first = read_text(path)
        hub.record_status(self.home, "acme-shop", "02-prd", checks=[("info", "check the glossary")], now=NOW)
        self.assertEqual(read_text(path.with_name(path.name + ".bak")), first)
        entry = hub.record_status(self.home, "acme-shop", "02-prd", clear_checks=True, now=NOW)
        self.assertEqual(entry, {"state": "in_progress", "updated": NOW})
        self.assertEqual(hub.record_status(self.home, "acme-shop", "02-prd", reset=True, now=NOW), {})
        self.assertEqual(hub.load_status(self.home, "acme-shop")["stages"], {})

    def test_bad_values_are_refused(self):
        for kwargs in ({"stage": "2-prd"}, {"state": "finished"}, {"date": "12/01/2026"}, {"checks": [("fatal", "x")]}, {"checks": [("warn", " ")]}, {"name": "Acme Shop"},
                       {"state": "done"}, {"state": "done", "checkpoint": "PRD approved"}, {"state": "done", "date": "2026-01-12"}):
            with self.subTest(**{key: str(value) for key, value in kwargs.items()}):
                args = {"name": "acme-shop", "stage": "02-prd"}
                args.update(kwargs)
                with self.assertRaises(ValueError):
                    hub.record_status(self.home, **args)
        self.assertFalse(hub.status_path(self.home, "acme-shop").exists())


class DoneTest(HubCase):
    def test_done_keeps_its_checkpoint(self):
        hub.record_status(self.home, "acme-shop", "02-prd", "done", "PRD approved in the kickoff review", "2026-01-12", now=NOW)
        entry = hub.record_status(self.home, "acme-shop", "02-prd", next_action="Write the user flows", now=NOW)
        self.assertEqual((entry["state"], entry["checkpoint_date"], entry["next"]), ("done", "2026-01-12", "Write the user flows"))
        with self.assertRaises(ValueError):
            hub.record_status(self.home, "acme-shop", "02-prd", checkpoint="", now=NOW)
        self.assertEqual(hub.load_status(self.home, "acme-shop")["stages"]["02-prd"]["checkpoint"], "PRD approved in the kickoff review")


class FitTest(unittest.TestCase):
    def snapshot(self, items=0, checks=0, title="Acme Shop"):
        return {
            "project": {"name": "acme-shop", "title": title},
            "items": [{"id": "REQ-%d" % i, "title": "t" * 100} for i in range(items)],
            "checks": [hub.check("unknown-ref", "warn", "REQ-%d is mentioned but not defined: %s" % (i, "x" * 500)) for i in range(checks)],
            "summary": {"items": items},
            "truncated": False,
        }

    def size(self, snapshot):
        return len(hub.dump(snapshot, compact=True).encode("utf-8"))

    def test_checks_are_cut_after_items(self):
        result = hub.fit(self.snapshot(items=500, checks=6000))
        self.assertLessEqual(self.size(result), hub.MAX_SNAPSHOT_BYTES)
        notice = result["checks"][0]
        self.assertEqual((notice["rule"], result["truncated"], result["items"]), ("truncated", True, []))
        self.assertEqual((notice["args"]["shown"], notice["args"]["total"], notice["args"]["checks_total"]), (0, 500, 6000))
        self.assertEqual(notice["args"]["checks_shown"], len(result["checks"]) - 1)
        self.assertLessEqual(notice["args"]["checks_shown"], hub.MAX_CHECKS)

    def test_small_snapshots_are_kept_whole(self):
        snapshot = self.snapshot(items=10, checks=10)
        result = hub.fit(snapshot)
        self.assertEqual((result["truncated"], len(result["items"]), len(result["checks"])), (False, 10, 10))

    def test_settings_over_the_limit_are_refused(self):
        with self.assertRaises(ValueError):
            hub.fit(self.snapshot(title="t" * hub.MAX_SNAPSHOT_BYTES))


class PageTest(HubCase):
    def page_data(self, page):
        start = page.index('<script id="hub-data" type="application/json">') + len('<script id="hub-data" type="application/json">')
        return json.loads(page[start:page.index("</script>", start)])

    def test_template_is_self_contained(self):
        page = read_text(TEMPLATE)
        self.assertEqual(page.count(hub.PLACEHOLDER), 1)
        self.assertIn("default-src 'none'", page)
        self.assertNotRegex(page, r"(?i)\b(?:src|href|action)\s*=\s*[\"']?(?:https?:)?//")
        for word in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(word, page)

    def test_page_data_cannot_close_its_script(self):
        title = "Shop </script><script>alert(1)</script> & <b>"
        self.project(title=title)
        self.register()
        path, snapshots, notes = hub.build_hub(self.home, now=NOW)
        page = read_text(path)
        self.assertEqual(page.count("</script>"), read_text(TEMPLATE).count("</script>"))
        data = self.page_data(page)
        self.assertEqual(data["projects"][0]["project"]["title"], title)
        self.assertEqual((data["schema"], data["origin"], data["lang"]), ("corthex-hub-page/0.1", "local", "en"))
        self.assertEqual((path, notes), (self.home / ".corthex" / "hub" / "index.html", []))

    def test_build_lists_projects_that_cannot_be_read(self):
        self.project()
        self.write(self.home / ".corthex" / "profile.json", {"language": "ko"})
        self.write(self.home / ".corthex" / "projects.json", {"projects": [{"name": "acme-shop", "path": str(self.repo)}, {"name": "blog", "path": str(self.base / "gone")}]})
        path, snapshots, notes = hub.build_hub(self.home, now=NOW)
        data = self.page_data(read_text(path))
        self.assertEqual([p["project"]["name"] for p in data["projects"]], ["acme-shop"])
        self.assertEqual(data["missing"], [{"name": "blog", "reason": "no snapshot"}])
        self.assertEqual(data["lang"], "ko")
        self.assertEqual(notes, ["blog: its folder is not on this machine"])
        self.assertTrue(hub.snapshot_path(self.home, "acme-shop").is_file())

    def test_a_project_is_read_only_under_its_registered_name(self):
        blog = self.base / "work" / "blog"
        self.write(blog / ".corthex" / "project.json", {"name": "blog", "title": "Blog"})
        self.project(name="blog")
        self.write(self.home / ".corthex" / "projects.json", {"projects": [{"name": "blog", "path": str(blog)}, {"name": "acme-shop", "path": str(self.repo)}]})
        path, snapshots, notes = hub.build_hub(self.home, now=NOW)
        self.assertEqual([s["project"]["title"] for s in snapshots], ["Blog"])
        self.assertEqual(self.page_data(read_text(path))["missing"], [{"name": "acme-shop", "reason": "no snapshot"}])
        self.assertEqual(notes, ["acme-shop: its .corthex/project.json names it blog, but ~/.corthex/projects.json registers it as acme-shop; use one name in both"])
        ((_, project, reason),) = hub.select_projects(self.home, [], self.repo)
        self.assertIsNone(project)
        self.assertIn("registers it as acme-shop", reason)

    def test_a_folder_cannot_take_a_registered_name(self):
        other = self.base / "work" / "acme-old"
        self.write(other / ".corthex" / "project.json", {"name": "acme-shop"})
        self.project()
        self.write(self.home / ".corthex" / "projects.json", {"projects": [{"name": "acme-shop", "path": str(other)}]})
        ((_, project, reason),) = hub.select_projects(self.home, [], self.repo)
        self.assertIsNone(project)
        self.assertIn("acme-shop is registered for another folder", reason)

    def test_a_registered_folder_may_be_spelled_another_way(self):
        variant = self.repo.parent / self.repo.name.upper()
        if not hub.is_dir(variant):
            self.skipTest("this file system tells letter cases apart")
        self.project()
        self.register(path=str(variant))
        ((_, project, reason),) = hub.select_projects(self.home, [], self.repo)
        self.assertIsNotNone(project, reason)

    def test_unregistered_snapshots_stay_off_the_page(self):
        self.project()
        self.register()
        old = self.snapshot()
        old["project"]["name"] = "old-shop"
        hub.save_snapshot(self.home, old)
        path, snapshots, notes = hub.build_hub(self.home, now=NOW)
        self.assertEqual([p["project"]["name"] for p in self.page_data(read_text(path))["projects"]], ["acme-shop"])
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].startswith("old-shop: left off the page"))
        self.assertTrue(hub.snapshot_path(self.home, "old-shop").is_file(), "the saved snapshot is kept")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_page_script_parses(self):
        page = read_text(TEMPLATE)
        script = page[page.rindex("<script>") + len("<script>"):page.rindex("</script>")]
        path = self.base / "hub.js"
        self.write(path, script)
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))


class Server(http.server.BaseHTTPRequestHandler):
    """A stand-in NEXUS server on this machine; the test sets `reply`."""

    received = []
    reply = (200, b'{"revision": 3}', {})

    def do_POST(self):
        self.answer()

    def do_DELETE(self):
        self.answer()

    def answer(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        headers = {name.lower(): value for name, value in self.headers.items()}
        type(self).received.append((self.command, self.path, headers, body))
        code, payload, headers = type(self).reply
        self.send_response(code)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class PushTest(HubCase):
    def setUp(self):
        super().setUp()
        Server.received = []
        Server.reply = (200, b'{"revision": 3}', {})
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Server)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.server.server_port
        self.project()
        self.register()
        hub.save_snapshot(self.home, self.snapshot())
        self.profile(push=["acme-shop"])
        self.env = {"CORTHEX_NEXUS_CLIENT_ID": "test-id", "CORTHEX_NEXUS_CLIENT_SECRET": "test-secret"}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def profile(self, **nexus):
        settings = {"url": self.url}
        settings.update(nexus)
        self.write(self.home / ".corthex" / "profile.json", {"language": "en", "nexus": settings})

    def test_push_sends_each_listed_project(self):
        lines = hub.push(self.home, env=self.env)
        self.assertEqual(lines, ["acme-shop: sent, HTTP 200, revision 3"])
        ((method, path, headers, body),) = Server.received
        self.assertEqual((method, path), ("POST", "/api/snapshots"))
        self.assertEqual((headers["cf-access-client-id"], headers["cf-access-client-secret"]), ("test-id", "test-secret"))
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(json.loads(body.decode("utf-8")), json.loads(read_text(hub.snapshot_path(self.home, "acme-shop"))))

    def test_dry_run_sends_nothing(self):
        (line,) = hub.push(self.home, dry_run=True, env={})
        self.assertRegex(line, r"^acme-shop: would send \d+ bytes to http://127\.0\.0\.1:\d+/api/snapshots$")
        self.assertEqual(Server.received, [])

    def test_refused_settings(self):
        cases = [
            ({"names": ["blog"]}, "add blog to nexus.push"),
            ({"url": "http://nexus.example.com"}, "must start with https://"),
            ({"url": "https://user:pw@example.com"}, "environment variables"),
            ({"url": "https://nexus.example.com"}, "CORTHEX_NEXUS_CLIENT_ID"),
        ]
        for kwargs, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(ValueError) as caught:
                    hub.push(self.home, env={}, **kwargs)
                self.assertIn(message, str(caught.exception))
        self.profile(push="acme-shop")
        with self.assertRaises(ValueError):
            hub.push(self.home, env=self.env)
        self.assertEqual(Server.received, [])

    def test_refused_token(self):
        for code, headers in ((302, {"Location": "https://example.com/login"}), (401, {}), (403, {})):
            with self.subTest(code=code):
                Server.reply = (code, b"", headers)
                with self.assertRaises(RuntimeError) as caught:
                    hub.push(self.home, env=self.env)
                self.assertIn("refused the service token (HTTP %d)" % code, str(caught.exception))
        Server.reply = (500, b"", {})
        with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
            hub.push(self.home, env=self.env)

    def test_the_server_reason_is_shown(self):
        cases = (
            (409, "the server holds a newer snapshot of acme-shop, made at 2026-01-12T10:00:00+09:00; build it again and send that"),
            (403, "Cloudflare Access did not check this request; protect this Worker with Access first"),
            (413, "the snapshot is larger than 1048576 bytes"),
        )
        for code, reason in cases:
            with self.subTest(code=code):
                Server.reply = (code, json.dumps({"error": reason}).encode("utf-8"), {"Content-Type": "application/json"})
                with self.assertRaises(RuntimeError) as caught:
                    hub.push(self.home, env=self.env)
                self.assertEqual(str(caught.exception), "the server refused it (HTTP %d): %s" % (code, reason))
        Server.reply = (400, json.dumps({"error": "bad \x1b[2Jsnapshot\x07"}).encode("utf-8"), {})
        with self.assertRaises(RuntimeError) as caught:
            hub.push(self.home, env=self.env)
        self.assertEqual(str(caught.exception), "the server refused it (HTTP 400): bad [2Jsnapshot")

    def test_remove(self):
        self.profile(push=[])
        Server.reply = (200, b'{"name": "acme-shop", "removed": true}', {})
        self.assertEqual(hub.remove(self.home, ["acme-shop"], env=self.env), ["acme-shop: removed from the server"])
        ((method, path, headers, body),) = Server.received
        self.assertEqual((method, path, body), ("DELETE", "/api/snapshots/acme-shop", b""))
        self.assertEqual((headers["cf-access-client-id"], headers["cf-access-client-secret"]), ("test-id", "test-secret"))
        Server.reply = (404, b'{"error": "no such project"}', {"Content-Type": "application/json"})
        self.assertEqual(hub.remove(self.home, ["blog"], env=self.env), ["blog: not on the server"])
        Server.reply = (404, b"", {})
        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            hub.remove(self.home, ["blog"], env=self.env)

    def test_remove_refusals_and_dry_run(self):
        (line,) = hub.remove(self.home, ["acme-shop"], dry_run=True, env={})
        self.assertEqual(line, "acme-shop: would remove it from %s" % self.url)
        cases = [
            ({"names": []}, "name the projects"),
            ({"names": ["../acme"]}, "../acme is not a project name"),
            ({"names": ["acme-shop"], "url": "https://nexus.example.com"}, "CORTHEX_NEXUS_CLIENT_ID"),
        ]
        for kwargs, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(ValueError) as caught:
                    hub.remove(self.home, env={}, **kwargs)
                self.assertIn(message, str(caught.exception))
        self.assertEqual(Server.received, [])


class CommandLineTest(HubCase):
    def run_hub(self, *args):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--home", str(self.home)] + list(args),
                                capture_output=True, cwd=str(self.base), env=env, timeout=60)
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")

    def test_commands(self):
        self.project()
        self.register()
        self.assertEqual(self.run_hub("--version")[1].strip(), "corthex-nexus " + hub.VERSION)
        code, out, err = self.run_hub("status", "acme-shop", "02-prd", "--state", "in_progress", "--next", "Review REQ-001", "--check", "info", "Check REQ-001")
        self.assertEqual((code, out.strip()), (0, "acme-shop 02-prd: in_progress"), err)
        code, out, err = self.run_hub("snapshot", "--path", str(self.repo), "--print")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["stages"]["02-prd"]["next"], "Review REQ-001")
        code, out, err = self.run_hub("build")
        self.assertEqual(code, 0, err)
        self.assertIn("acme-shop: 0 items, 0 errors, 0 warnings, 1 notes", out)
        self.assertTrue((self.home / ".corthex" / "hub" / "index.html").is_file())

    def test_errors_exit_with_one(self):
        code, out, err = self.run_hub("status", "acme-shop", "02-prd", "--date", "12/01/2026")
        self.assertEqual(code, 1)
        self.assertIn("the date must start with YYYY-MM-DD", err)
        for command in (["push"], ["remove", "acme-shop"]):
            code, out, err = self.run_hub(*command)
            self.assertEqual(code, 1)
            self.assertIn("no NEXUS address", err)
        code, out, err = self.run_hub("snapshot")
        self.assertEqual(code, 1)
        self.assertIn("no .corthex/project.json", err)


if __name__ == "__main__":
    unittest.main()
