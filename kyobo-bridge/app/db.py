"""SQLite 연결·스키마. Phase B-1 은 books 테이블 1개로 시작."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_PATH = Path(os.environ.get("KYOBO_BRIDGE_DB", "/data/library.db"))


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def cursor() -> Iterator[sqlite3.Cursor]:
    conn = get_conn()
    try:
        yield conn.cursor()
    finally:
        conn.close()


def init_db() -> None:
    """앱 시작 시 호출. 스키마 멱등 생성."""
    with cursor() as cur:
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS books (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                kyobo_id      TEXT UNIQUE,
                title         TEXT NOT NULL,
                author        TEXT,
                publisher     TEXT,
                isbn          TEXT,
                cover_url     TEXT,
                acquired_at   TEXT,
                status        TEXT DEFAULT 'available',
                synced_at     TEXT DEFAULT (datetime('now')),
                meta_json     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_books_title  ON books(title);
            CREATE INDEX IF NOT EXISTS idx_books_synced ON books(synced_at);
            """
        )


def list_books() -> list[dict]:
    with cursor() as cur:
        rows = cur.execute(
            """
            SELECT id, kyobo_id, title, author, publisher, isbn,
                   cover_url, acquired_at, status, synced_at
            FROM books
            ORDER BY synced_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def count_books() -> int:
    with cursor() as cur:
        return cur.execute("SELECT COUNT(*) FROM books").fetchone()[0]
