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

            -- Phase C-1: 키-값 설정 저장
            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value_json  TEXT,
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            -- Phase C-3 Part3: 분석 작업 큐
            CREATE TABLE IF NOT EXISTS jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                slug         TEXT NOT NULL,
                title        TEXT,
                mode         TEXT DEFAULT 'auto',          -- auto | capture-only | summarize-only
                pages        TEXT,                          -- "127-155" 또는 null=전체
                status       TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done|failed|cancelled
                created_at   TEXT DEFAULT (datetime('now')),
                started_at   TEXT,
                finished_at  TEXT,
                progress     TEXT,                          -- worker 가 주기적으로 갱신 ("OCR 12/185" 등)
                stdout_tail  TEXT,                          -- 마지막 출력 일부 (디버그)
                error        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_status_created
                ON jobs(status, created_at);
            """
        )


# ── Phase C-1: settings 키-값 CRUD ──────────────────────
import json as _json

def get_setting(key: str, default=None):
    with cursor() as cur:
        row = cur.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        if not row: return default
        try: return _json.loads(row["value_json"])
        except Exception: return default

def set_setting(key: str, value) -> None:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO settings(key, value_json) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=datetime('now')",
            (key, _json.dumps(value, ensure_ascii=False)),
        )

def get_all_settings() -> dict:
    with cursor() as cur:
        rows = cur.execute("SELECT key, value_json FROM settings").fetchall()
        out = {}
        for r in rows:
            try: out[r["key"]] = _json.loads(r["value_json"])
            except Exception: out[r["key"]] = None
        return out

def set_all_settings(items: dict) -> int:
    n = 0
    for k, v in items.items():
        set_setting(k, v)
        n += 1
    return n


# ── Phase C-3 Part3: jobs CRUD ──────────────────────────────
def create_job(slug: str, title: str | None = None, mode: str = "auto",
               pages: str | None = None) -> dict:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO jobs(slug, title, mode, pages) VALUES(?, ?, ?, ?)",
            (slug, title, mode, pages),
        )
        jid = cur.lastrowid
        row = cur.execute(
            "SELECT * FROM jobs WHERE id = ?", (jid,)
        ).fetchone()
        return dict(row)


def list_jobs(status: str | None = None, limit: int = 50) -> list[dict]:
    with cursor() as cur:
        if status:
            rows = cur.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_job(jid: int) -> dict | None:
    with cursor() as cur:
        row = cur.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
        return dict(row) if row else None


def claim_next_job() -> dict | None:
    """가장 오래된 pending 작업을 running 으로 전이 + 반환. 동시성: SQLite 트랜잭션."""
    with cursor() as cur:
        cur.execute("BEGIN IMMEDIATE")
        row = cur.execute(
            "SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            cur.execute("COMMIT")
            return None
        jid = row["id"]
        cur.execute(
            "UPDATE jobs SET status = 'running', started_at = datetime('now') WHERE id = ?",
            (jid,),
        )
        cur.execute("COMMIT")
        return dict(row) | {"status": "running"}


def update_job(jid: int, **fields) -> dict | None:
    if not fields:
        return get_job(jid)
    cols, vals = [], []
    for k, v in fields.items():
        if k not in ("status", "progress", "stdout_tail", "error",
                     "finished_at", "started_at"):
            continue
        cols.append(f"{k} = ?")
        vals.append(v)
    # status 가 done/failed/cancelled 면 finished_at 자동 설정
    if fields.get("status") in ("done", "failed", "cancelled") and "finished_at" not in fields:
        cols.append("finished_at = datetime('now')")
    if not cols:
        return get_job(jid)
    vals.append(jid)
    with cursor() as cur:
        cur.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id = ?", vals)
    return get_job(jid)


def cancel_job(jid: int) -> dict | None:
    """pending → 즉시 cancelled. running → cancelling (worker 가 감지 후 종료)."""
    with cursor() as cur:
        # pending 이면 즉시 cancelled
        cur.execute(
            "UPDATE jobs SET status = 'cancelled', finished_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'",
            (jid,),
        )
        if cur.rowcount == 0:
            # running 이면 cancelling 으로 전이 (worker polling 이 감지)
            cur.execute(
                "UPDATE jobs SET status = 'cancelling' "
                "WHERE id = ? AND status = 'running'",
                (jid,),
            )
    return get_job(jid)


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
