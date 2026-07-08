"""Unit tests for the served_by column migration + log_ingest/get_last_ingest."""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as dbmod  # noqa: E402

# The pre-migration ingest_runs table (no served_by), matching the old schema.
_OLD_INGEST = (
    "CREATE TABLE ingest_runs (run_id INTEGER PRIMARY KEY, series_id INTEGER, "
    "ts TEXT NOT NULL, rows_added INTEGER, from_date DATE, to_date DATE, "
    "status TEXT, error TEXT)"
)


def test_migrate_adds_served_by_and_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.execute(_OLD_INGEST)
    dbmod._migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ingest_runs)")}
    assert "served_by" in cols
    dbmod._migrate(conn)  # second call must not raise


def test_migrate_noop_when_table_missing():
    conn = sqlite3.connect(":memory:")
    dbmod._migrate(conn)  # no ingest_runs table yet — must not raise


def test_log_and_read_served_by():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(_OLD_INGEST)
    dbmod._migrate(conn)
    dbmod.log_ingest(conn, 1, 3, "2026-07-01", "2026-07-08", "success", served_by="fred")
    last = dbmod.get_last_ingest(conn, 1)
    assert last["served_by"] == "fred" and last["status"] == "success"
