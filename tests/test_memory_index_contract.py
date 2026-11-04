"""Execute the C2 index DDL without enabling a runtime or migrating a store."""

import sqlite3
import unittest

from _common import ROOT


class IndexContractTest(unittest.TestCase):
    def test_c2_item_statuses_keep_the_sqlite_constraint(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript((ROOT / "docs/05-erd/memory-index.sql").read_text(encoding="utf-8"))
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone(), (2,))
        insert = "INSERT INTO index_items VALUES (?, 'fact', ?, 'user', '2026-11-03T00:00:00.000Z', 1)"
        for status in ("current", "superseded", "withdrawn", "undone"):
            connection.execute(insert, (status, status))
        for status in ("unknown", "", "UNDONE"):
            with self.subTest(status=status), self.assertRaises(sqlite3.IntegrityError):
                connection.execute(insert, (status, status))
        self.assertEqual(connection.execute("SELECT count(*) FROM index_items").fetchone(), (4,))
