-- CORTHEX-MEMORY search index, format 2 (C2 target): projects/<project>/index.db in the memory store.
-- Stage 05 of CORTHEX's own project. The records around it, in files, are in memory.md beside
-- this file. The search index can always be made again from the memory items, so it is never
-- migrated: a file with another user_version, another embedding model or another vector
-- length is deleted and built again.
-- These rebuildable index tables do not represent a named aggregate or read model on
-- the domain board; terms: none makes that explicit for the NEXUS cross-check.
-- Plain tables only, without FTS5, which some Python builds leave out: the plugin splits the
-- words itself (stage 06) and scores them in Python. Each connection turns on
-- PRAGMA foreign_keys = ON and PRAGMA secure_delete = ON, and after a forget the code runs
-- PRAGMA wal_checkpoint(TRUNCATE), so that the words of a forgotten item stay neither in the
-- file's free pages nor in its write-ahead log.

PRAGMA user_version = 2;
PRAGMA journal_mode = WAL;

-- TBL-019 index_meta (CTX-003, terms: none) ← SPEC-016, SPEC-019, SPEC-023, SPEC-025, SPEC-027, SPEC-145
-- What the index was built with, one row per name: embedding_model, embedding_dims, words
-- (the version of the word splitting) and built (when the index was last built whole, UTC).
CREATE TABLE index_meta (
  name  TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- TBL-020 index_items (CTX-003, terms: none) ← SPEC-015, SPEC-016, SPEC-019, SPEC-023, SPEC-025, SPEC-027, SPEC-029, SPEC-035, SPEC-145
-- One row per memory item of the project, of any item status; a forgotten item has none.
-- speaker and said are those of the item's deciding quote; terms is the number of words that
-- the item's kind, title, text and quotes were split into.
CREATE TABLE index_items (
  item    TEXT    PRIMARY KEY,
  kind    TEXT    NOT NULL CHECK (kind IN ('decision', 'preference', 'lesson', 'reference', 'fact')),
  status  TEXT    NOT NULL CHECK (status IN ('current', 'superseded', 'withdrawn', 'undone')),
  speaker TEXT    NOT NULL CHECK (speaker IN ('user', 'agent')),
  said    TEXT    NOT NULL,
  terms   INTEGER NOT NULL CHECK (terms >= 0)
);
CREATE INDEX index_items_status ON index_items (status, said);

-- TBL-021 index_vectors (CTX-003, terms: none) ← SPEC-016, SPEC-019, SPEC-023, SPEC-025, SPEC-027, SPEC-145
-- The embedding of an item: float32 numbers, little-endian, scaled to length 1, as many as
-- embedding_dims says. An item whose embedding failed has no row, and is found by words only
-- until a later curation, consolidation or sync embeds it.
CREATE TABLE index_vectors (
  item   TEXT PRIMARY KEY REFERENCES index_items (item) ON DELETE CASCADE,
  vector BLOB NOT NULL CHECK (length(vector) > 0 AND length(vector) % 4 = 0)
);

-- TBL-022 index_terms (CTX-003, terms: none) ← SPEC-015, SPEC-016, SPEC-019, SPEC-023, SPEC-025, SPEC-027, SPEC-145
-- How often each word occurs in an item, for searches by words (SPEC-025), the items that a
-- long request carries first (SPEC-015) and the identifiers that recall scores (SPEC-023).
CREATE TABLE index_terms (
  term  TEXT    NOT NULL,
  item  TEXT    NOT NULL REFERENCES index_items (item) ON DELETE CASCADE,
  count INTEGER NOT NULL CHECK (count > 0),
  PRIMARY KEY (term, item)
);
CREATE INDEX index_terms_item ON index_terms (item);
