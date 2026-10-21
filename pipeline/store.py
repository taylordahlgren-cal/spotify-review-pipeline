"""SQLite state store. Only the orchestrator (main thread) writes; every batch commits in one transaction,
so an interruption can never leave a half-saved batch or double-count a record."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS source (
  review_id TEXT PRIMARY KEY, row_idx INTEGER, source_sha256 TEXT, text_sha TEXT, empty INTEGER,
  in_scope INTEGER, review_rating TEXT, review_likes TEXT, app_version TEXT, review_timestamp TEXT);
CREATE INDEX IF NOT EXISTS source_text ON source(text_sha);
CREATE TABLE IF NOT EXISTS texts (
  text_sha TEXT PRIMARY KEY, text TEXT, rep_review_id TEXT, priority INTEGER, n_rows INTEGER, n_rows_scope INTEGER,
  in_scope INTEGER);
CREATE INDEX IF NOT EXISTS texts_priority ON texts(in_scope, priority);
CREATE TABLE IF NOT EXISTS results (
  text_sha TEXT, cache_key TEXT, status TEXT, rep_review_id TEXT, label_config TEXT, topic TEXT, subtopic TEXT,
  intent TEXT, sentiment REAL, severity INTEGER, entities TEXT, evidence_quote TEXT, needs_review INTEGER,
  review_reason TEXT, request_id TEXT, model TEXT, attempts INTEGER, quarantine_reason TEXT, notes TEXT,
  session_id TEXT, completed_at TEXT, PRIMARY KEY (text_sha, cache_key));
CREATE TABLE IF NOT EXISTS failures (
  text_sha TEXT, cache_key TEXT, attempts INTEGER, last_error TEXT, session_id TEXT, PRIMARY KEY (text_sha, cache_key));
CREATE TABLE IF NOT EXISTS calls (
  request_id TEXT PRIMARY KEY, seq INTEGER, run_id TEXT, session_id TEXT, role TEXT, phase TEXT, outcome TEXT,
  cost_usd REAL, body TEXT);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, n INTEGER, run_id TEXT, command TEXT, phase TEXT, started_at TEXT, ended_at TEXT,
  stop_reason TEXT, completed_texts_start INTEGER, completed_texts_end INTEGER, ledger TEXT, wall_s REAL);
CREATE TABLE IF NOT EXISTS verify (
  text_sha TEXT PRIMARY KEY, rep_review_id TEXT, topic TEXT, intent TEXT, severity INTEGER, sentiment REAL,
  confidence TEXT, request_id TEXT, label_config TEXT);
CREATE TABLE IF NOT EXISTS stage_cache (key TEXT PRIMARY KEY, role TEXT, output TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS stage_times (run_id TEXT, stage TEXT, started_at TEXT, wall_s REAL, detail TEXT);
"""


class Store:
    def __init__(self, state_dir):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "state.sqlite", isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    # meta
    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def tx(self):
        return _Tx(self.db)

    def next_call_seq(self):
        return (self.db.execute("SELECT COALESCE(MAX(seq),0) FROM calls").fetchone()[0]) + 1

    def add_calls(self, calls):
        seq = self.next_call_seq()
        for c in calls:
            self.db.execute("INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?)",
                            (c["request_id"], seq, c["run_id"], c["session_id"], c["role"], c["phase"], c["outcome"],
                             c.get("cost_usd", 0.0), json.dumps(c, ensure_ascii=False)))
            seq += 1

    def calls(self, run_id=None):
        q = "SELECT body FROM calls" + (" WHERE run_id=?" if run_id else "") + " ORDER BY seq"
        return [json.loads(r[0]) for r in self.db.execute(q, (run_id,) if run_id else ())]

    def completed_text_count(self, cache_key):
        return self.db.execute("SELECT COUNT(*) FROM results WHERE cache_key=? AND status='completed'", (cache_key,)).fetchone()[0]

    def completed_review_ids(self, cache_key):
        """All source rows whose exact text has a completed result (originals + exact-text reuse)."""
        q = ("SELECT s.review_id FROM source s JOIN results r ON r.text_sha=s.text_sha AND r.cache_key=? "
             "WHERE r.status='completed' AND s.empty=0 ORDER BY s.row_idx")
        return [r[0] for r in self.db.execute(q, (cache_key,))]

    def stage_cache_get(self, key):
        row = self.db.execute("SELECT output FROM stage_cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def stage_cache_put(self, key, role, output, ts):
        self.db.execute("INSERT OR REPLACE INTO stage_cache VALUES (?,?,?,?)", (key, role, json.dumps(output), ts))

    def stage_time(self, run_id, stage, started_at, wall_s, detail=None):
        self.db.execute("INSERT INTO stage_times VALUES (?,?,?,?,?)", (run_id, stage, started_at, wall_s, json.dumps(detail or {})))


class _Tx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        self.db.execute("COMMIT" if exc_type is None else "ROLLBACK")
        return False
