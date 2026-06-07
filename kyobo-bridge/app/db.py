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
                meta_json     TEXT,
                -- Phase #47: e-library 자동화·식별용
                salecmdtid    TEXT,
                can_web_view  INTEGER DEFAULT 0,
                progress_pct  INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_books_title       ON books(title);
            CREATE INDEX IF NOT EXISTS idx_books_synced      ON books(synced_at);
            -- idx_books_salecmdtid 는 ALTER 후에 별도 생성 (기존 DB 호환)

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

            -- 워커 클라이언트 추적 — 한 번이라도 ping 한 hostname/IP 기록
            CREATE TABLE IF NOT EXISTS worker_clients (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                client_ip   TEXT NOT NULL,
                hostname    TEXT,
                platform    TEXT,
                first_seen  TEXT DEFAULT (datetime('now')),
                last_seen   TEXT DEFAULT (datetime('now')),
                ping_count  INTEGER DEFAULT 1,
                UNIQUE(client_ip, hostname)
            );
            CREATE INDEX IF NOT EXISTS idx_worker_clients_last_seen
                ON worker_clients(last_seen);
            """
        )
        # 기존 books/jobs 테이블에 신규 컬럼 멱등 추가 (Phase #47, heartbeat)
        for col, ddl in [
            ("salecmdtid",   "ALTER TABLE books ADD COLUMN salecmdtid TEXT"),
            ("can_web_view", "ALTER TABLE books ADD COLUMN can_web_view INTEGER DEFAULT 0"),
            ("progress_pct", "ALTER TABLE books ADD COLUMN progress_pct INTEGER"),
            # 워커 생존 신호 — claim·progress 보고마다 갱신. 끊기면 reaper 가 회수.
            ("heartbeat",    "ALTER TABLE jobs ADD COLUMN heartbeat TEXT"),
            # 분석 시작한 웹 클라이언트 정보(JSON) — IP/OS/브라우저/MAC(best-effort)
            ("client_info",  "ALTER TABLE jobs ADD COLUMN client_info TEXT"),
        ]:
            try:
                cur.execute(ddl)
            except Exception:
                pass  # 이미 있으면 OK
        # 인덱스도 멱등
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_books_salecmdtid ON books(salecmdtid)")
        except Exception:
            pass


def upsert_worker_client(client_ip: str, hostname: str | None = None, platform: str | None = None) -> dict:
    """워커 ping 마다 호출. 같은 (ip, hostname) 이면 last_seen·ping_count 만 갱신."""
    with cursor() as cur:
        cur.execute(
            """INSERT INTO worker_clients(client_ip, hostname, platform)
               VALUES(?, ?, ?)
               ON CONFLICT(client_ip, hostname) DO UPDATE SET
                   last_seen  = datetime('now'),
                   ping_count = ping_count + 1,
                   platform   = COALESCE(excluded.platform, platform)""",
            (client_ip, hostname or '', platform),
        )
        row = cur.execute(
            "SELECT * FROM worker_clients WHERE client_ip = ? AND hostname = ?",
            (client_ip, hostname or ''),
        ).fetchone()
        return dict(row) if row else {}


def get_worker_client_by_ip(client_ip: str) -> dict | None:
    """같은 IP 에서 본 적 있는 워커 (가장 최근 ping). 사용자 모달이 자기 IP 와 매칭하려고."""
    with cursor() as cur:
        row = cur.execute(
            "SELECT * FROM worker_clients WHERE client_ip = ? ORDER BY last_seen DESC LIMIT 1",
            (client_ip,),
        ).fetchone()
        return dict(row) if row else None


def list_worker_clients(limit: int = 20) -> list[dict]:
    with cursor() as cur:
        rows = cur.execute(
            "SELECT * FROM worker_clients ORDER BY last_seen DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


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
               pages: str | None = None, client_info: str | None = None) -> dict:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO jobs(slug, title, mode, pages, client_info) VALUES(?, ?, ?, ?, ?)",
            (slug, title, mode, pages, client_info),
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
    """원격 워커용: 가장 오래된 pending 작업 claim. 단 upload-process 는 백엔드가
    직접 처리하므로 제외(원격 워커는 NAS 업로드 파일에 접근 못 함). 동시성: SQLite 트랜잭션."""
    with cursor() as cur:
        cur.execute("BEGIN IMMEDIATE")
        row = cur.execute(
            "SELECT * FROM jobs WHERE status = 'pending' AND mode != 'upload-process' "
            "ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            cur.execute("COMMIT")
            return None
        jid = row["id"]
        cur.execute(
            "UPDATE jobs SET status = 'running', started_at = datetime('now'), "
            "heartbeat = datetime('now') WHERE id = ?",
            (jid,),
        )
        cur.execute("COMMIT")
        return dict(row) | {"status": "running"}


def claim_next_upload_job() -> dict | None:
    """백엔드 처리기용: 가장 오래된 pending upload-process 작업을 running 으로 전이."""
    with cursor() as cur:
        cur.execute("BEGIN IMMEDIATE")
        row = cur.execute(
            "SELECT * FROM jobs WHERE status = 'pending' AND mode = 'upload-process' "
            "ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            cur.execute("COMMIT")
            return None
        jid = row["id"]
        cur.execute(
            "UPDATE jobs SET status = 'running', started_at = datetime('now'), "
            "heartbeat = datetime('now') WHERE id = ?",
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
    # 워커가 살아있다는 신호 — 모든 보고(progress/status)마다 heartbeat 갱신
    cols.append("heartbeat = datetime('now')")
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


# heartbeat 끊김 판정 임계 (초). 정상 작업은 progress 보고가 수 초 간격이라
# 넉넉히 잡아도 좀비는 확실히 걸린다. (요약 1p 가 재시도 누적 최대 ~180s 라 그 위)
STALE_JOB_SECONDS = 600

def reap_stale_jobs(stale_seconds: int = STALE_JOB_SECONDS) -> list[dict]:
    """heartbeat 가 끊긴 running/cancelling 작업을 failed 로 회수.

    워커가 죽거나(슬립·강제종료) 네트워크 단절로 progress 보고가 끊기면
    DB 에 'running' 으로 박제돼 큐가 막히고 새 워커도 다시 못 잡는다
    (claim 은 pending 만 가져감). 주기적으로 호출돼 좀비를 정리한다.

    Returns: 회수된 job dict 목록 (없으면 []).
    """
    with cursor() as cur:
        cur.execute(
            f"""SELECT id FROM jobs
                 WHERE status IN ('running', 'cancelling')
                   AND (heartbeat IS NULL
                        OR heartbeat < datetime('now', '-{int(stale_seconds)} seconds'))""",
        )
        ids = [r["id"] for r in cur.fetchall()]
        if not ids:
            return []
        msg = (f"워커 heartbeat 끊김 ({stale_seconds}s+ 무응답) — 자동 회수. "
               f"워커가 죽었거나 Mac 슬립/네트워크 단절일 수 있습니다. "
               f"필요하면 다시 [분석 시작] 하세요.")
        qmarks = ",".join("?" * len(ids))
        cur.execute(
            f"""UPDATE jobs SET status = 'failed',
                    finished_at = datetime('now'),
                    error = COALESCE(NULLIF(error, ''), ?)
                 WHERE id IN ({qmarks})""",
            (msg, *ids),
        )
    return [get_job(i) for i in ids]


def list_books() -> list[dict]:
    with cursor() as cur:
        rows = cur.execute(
            """
            SELECT id, kyobo_id, title, author, publisher, isbn,
                   cover_url, acquired_at, status, synced_at,
                   salecmdtid, can_web_view, progress_pct
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

            # Phase #47: e-library 자동화 필드
            salecmdtid = (raw.get("salecmdtid") or "").strip() or None
            # kyobo_id 가 없으면 salecmdtid 를 키로 사용 (가장 안정적 ID)
            if not kyobo_id and salecmdtid:
                kyobo_id = salecmdtid
            can_web_view = 1 if raw.get("can_web_view") else 0
            progress_pct = raw.get("progress_pct")
            try:
                progress_pct = int(progress_pct) if progress_pct is not None else None
            except (TypeError, ValueError):
                progress_pct = None

            # 알려진 키 외에는 meta_json 으로 보존
            known = {"kyobo_id", "title", "author", "publisher", "isbn",
                     "cover_url", "acquired_at", "status", "meta_json",
                     "salecmdtid", "can_web_view", "progress_pct"}
            extra = {k: v for k, v in raw.items() if k not in known}
            meta = raw.get("meta_json")
            if extra:
                meta = json.dumps(extra, ensure_ascii=False)

            # 같은 책이 이미 있는지 (kyobo_id 우선, 없으면 salecmdtid, 없으면 title+author)
            row = None
            if kyobo_id:
                row = cur.execute(
                    "SELECT id FROM books WHERE kyobo_id = ?", (kyobo_id,)
                ).fetchone()
            if not row and salecmdtid:
                row = cur.execute(
                    "SELECT id FROM books WHERE salecmdtid = ?", (salecmdtid,)
                ).fetchone()
            if not row:
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
                        synced_at = ?, meta_json = ?,
                        salecmdtid = COALESCE(?, salecmdtid),
                        can_web_view = ?,
                        progress_pct = COALESCE(?, progress_pct)
                    WHERE id = ?
                    """,
                    (title, author, publisher, isbn, cover_url, acquired_at,
                     status, now, meta, salecmdtid, can_web_view, progress_pct, row["id"]),
                )
                updated += 1
            else:
                cur.execute(
                    """
                    INSERT INTO books (
                        kyobo_id, title, author, publisher, isbn,
                        cover_url, acquired_at, status, synced_at, meta_json,
                        salecmdtid, can_web_view, progress_pct
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (kyobo_id, title, author, publisher, isbn, cover_url,
                     acquired_at, status, now, meta,
                     salecmdtid, can_web_view, progress_pct),
                )
                inserted += 1

    return {"inserted": inserted, "updated": updated, "synced_at": now}


def clear_books() -> int:
    with cursor() as cur:
        before = cur.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        cur.execute("DELETE FROM books")
        return before
