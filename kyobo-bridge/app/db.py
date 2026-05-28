"""SQLite 연결·스키마·CRUD. Phase B-2 — Userscript sync upsert 지원."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

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
            ORDER BY synced_at DESC, title COLLATE NOCASE
            """
        ).fetchall()
        return [dict(r) for r in rows]


def count_books() -> int:
    with cursor() as cur:
        return cur.execute("SELECT COUNT(*) FROM books").fetchone()[0]


def upsert_books(items: Iterable[dict]) -> dict:
    """Userscript sync 가 보낸 도서 메타를 upsert.

    각 item 권장 키: kyobo_id, title, author, publisher, isbn, cover_url,
                     acquired_at, status, meta_json (또는 위 키 외 dict)
    `kyobo_id` 가 있으면 키로 upsert, 없으면 (title, author) 조합으로 upsert.
    """
    inserted = 0
    updated = 0
    now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

    with cursor() as cur:
        for raw in items:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            if not title:
                continue
            kyobo_id = (raw.get("kyobo_id") or "").strip() or None
            author = (raw.get("author") or "").strip() or None
            publisher = (raw.get("publisher") or "").strip() or None
            isbn = (raw.get("isbn") or "").strip() or None
            cover_url = (raw.get("cover_url") or "").strip() or None
            acquired_at = (raw.get("acquired_at") or "").strip() or None
            status = (raw.get("status") or "available").strip()

            # 알려진 키 외에는 meta_json 으로 보존
            known = {"kyobo_id", "title", "author", "publisher", "isbn",
                     "cover_url", "acquired_at", "status", "meta_json"}
            extra = {k: v for k, v in raw.items() if k not in known}
            meta = raw.get("meta_json")
            if extra:
                meta = json.dumps(extra, ensure_ascii=False)

            # 같은 책이 이미 있는지 (kyobo_id 우선, 없으면 title+author)
            if kyobo_id:
                row = cur.execute(
                    "SELECT id FROM books WHERE kyobo_id = ?", (kyobo_id,)
                ).fetchone()
            else:
                row = cur.execute(
                    "SELECT id FROM books WHERE title = ? AND COALESCE(author, '') = COALESCE(?, '')",
                    (title, author),
                ).fetchone()

            if row:
                cur.execute(
                    """
                    UPDATE books SET
                        title = ?, author = ?, publisher = ?, isbn = ?,
                        cover_url = ?, acquired_at = ?, status = ?,
                        synced_at = ?, meta_json = ?
                    WHERE id = ?
                    """,
                    (title, author, publisher, isbn, cover_url, acquired_at,
                     status, now, meta, row["id"]),
                )
                updated += 1
            else:
                cur.execute(
                    """
                    INSERT INTO books (
                        kyobo_id, title, author, publisher, isbn,
                        cover_url, acquired_at, status, synced_at, meta_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (kyobo_id, title, author, publisher, isbn, cover_url,
                     acquired_at, status, now, meta),
                )
                inserted += 1

    return {"inserted": inserted, "updated": updated, "synced_at": now}


def clear_books() -> int:
    with cursor() as cur:
        before = cur.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        cur.execute("DELETE FROM books")
        return before
