"""TASK-063: ship the authoritative result contract as a standalone resource."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from _common import ROOT, load_json
from test_memory_api import errors

PLUGIN = ROOT / "plugins/corthex-memory"
RESOURCE = Path("skills/corthex-memory/scripts/memory_lib/result.schema.json")
AUTHORITATIVE = ROOT / "docs/06-api/memory-result.schema.json"


class PackagedResultSchemaTest(unittest.TestCase):
    def test_tc333_packaged_bytes_match_the_authoritative_contract(self):
        self.assertEqual((PLUGIN / RESOURCE).read_bytes(), AUTHORITATIVE.read_bytes())

    def test_tc333_all_result_fixtures_retain_independent_schema_verdicts(self):
        schema = load_json(PLUGIN / RESOURCE)
        examples = load_json(ROOT / "docs/06-api/memory-examples.json")["result"]
        self.assertEqual((len(examples["valid"]), len(examples["invalid"])), (27, 8))
        for group, fits in (("valid", True), ("invalid", False)):
            for name, value in examples[group].items():
                with self.subTest(group=group, example=name):
                    self.assertEqual(not errors(schema, value, schema), fits)

    def test_tc333_copied_plugin_resource_needs_no_repository_docs(self):
        with tempfile.TemporaryDirectory(prefix="memory-result-resource-") as temporary:
            folder = Path(temporary)
            copied = folder / "plugin"
            shutil.copytree(PLUGIN, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            self.assertFalse((folder / "docs").exists())
            self.assertFalse((copied / "docs").exists())
            program = (
                "from pathlib import Path;import hashlib,json,sys;"
                "p=Path(sys.argv[1]);s=json.loads(p.read_text(encoding='utf-8'));"
                "assert s['type']=='object' and 'data' in s['required'];"
                "print(hashlib.sha256(p.read_bytes()).hexdigest())"
            )
            result = subprocess.run([sys.executable, "-I", "-c", program, str(copied / RESOURCE)],
                                    cwd=str(folder), capture_output=True, timeout=10)
            self.assertEqual((result.returncode, result.stderr), (0, b""))
            self.assertEqual(result.stdout.decode("ascii").strip(),
                             hashlib.sha256(AUTHORITATIVE.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
