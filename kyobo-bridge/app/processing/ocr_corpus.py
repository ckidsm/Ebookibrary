"""OCR 코퍼스 DB — 페이지별 OCR 텍스트를 구조화 저장(학습/추론용 기초 데이터).

도커 밖 마운트 폴더(`/data/ocr_corpus/`)에 SQLite 로 보관. 중요한 데이터라
새 데이터 생성(save_book)마다 타임스탬프 백업본을 backups/ 에 남긴다.

스키마:
  book_master : 도서 목록 마스터 (도서명 + 메타 디테일)
  book_pages  : 도서별 페이지(번호 + OCR 텍스트 내용)
"""
from __future__ import annotations
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

CORPUS_DIR = Path(os.environ.get("OCR_CORPUS_DIR", "/data/ocr_corpus"))
DB_PATH = CORPUS_DIR / "ocr_corpus.db"
BACKUP_DIR = CORPUS_DIR / "backups"
KEEP_BACKUPS = 30


def _conn() -> sqlite3.Connection:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS book_master (
            slug        TEXT PRIMARY KEY,      -- 도서 식별(폴더명)
            title       TEXT,                  -- 도서명 헤더
            author      TEXT,
            publisher   TEXT,
            kyobo_id    TEXT,
            salecmdtid  TEXT,
            isbn        TEXT,
            category    TEXT,                  -- 도서 종류(입문서/전문서/실용서 ...)
            field       TEXT,                  -- 분야(인공지능·머신러닝 / 영상·미디어 ...)
            pub_date    TEXT,                  -- 출판일(초판 발행일)
            revision_date TEXT,                -- 개정일(최신 쇄/개정판 발행일)
            description TEXT,                  -- 소개글(요약)
            page_count  INTEGER,
            source      TEXT,                  -- capture-browser / upload / backfill ...
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS book_pages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            book_slug   TEXT NOT NULL,
            page_num    INTEGER NOT NULL,
            ocr_text    TEXT,                  -- 페이지 OCR/교정 텍스트 내용
            char_count  INTEGER,
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(book_slug, page_num)
        );
        CREATE INDEX IF NOT EXISTS idx_pages_book ON book_pages(book_slug);
        """
    )
    # 기존 DB 호환 — 누락 컬럼 보강
    have = {r[1] for r in c.execute("PRAGMA table_info(book_master)")}
    for col in ("category", "field", "pub_date", "revision_date", "description"):
        if col not in have:
            c.execute(f"ALTER TABLE book_master ADD COLUMN {col} TEXT")
    c.commit()
    return c


def backup(tag: str = "") -> Path | None:
    """현재 DB 를 backups/ocr_corpus_<ts>[_tag].db 로 복사. 최근 KEEP_BACKUPS 개만 유지."""
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(ch for ch in (tag or "")[:30] if ch.isalnum() or ch in "_-")
    dst = BACKUP_DIR / (f"ocr_corpus_{ts}_{safe}.db" if safe else f"ocr_corpus_{ts}.db")
    shutil.copy2(DB_PATH, dst)
    olds = sorted(BACKUP_DIR.glob("ocr_corpus_*.db"))
    for old in olds[:-KEEP_BACKUPS]:
        try:
            old.unlink()
        except Exception:
            pass
    return dst


def save_book(slug: str, meta: dict, pages: dict[int, str]) -> int:
    """도서 1권의 마스터 메타 + 페이지별 OCR 텍스트를 upsert 하고 백업.
    meta: title/author/publisher/kyobo_id/salecmdtid/isbn/source
    pages: {page_num: ocr_text}
    반환: 저장된 페이지 수."""
    c = _conn()
    try:
        c.execute(
            """INSERT INTO book_master
                 (slug,title,author,publisher,kyobo_id,salecmdtid,isbn,
                  category,field,pub_date,revision_date,description,page_count,source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(slug) DO UPDATE SET
                 title=excluded.title, author=excluded.author, publisher=excluded.publisher,
                 kyobo_id=excluded.kyobo_id, salecmdtid=excluded.salecmdtid, isbn=excluded.isbn,
                 category=COALESCE(excluded.category, book_master.category),
                 field=COALESCE(excluded.field, book_master.field),
                 pub_date=COALESCE(excluded.pub_date, book_master.pub_date),
                 revision_date=COALESCE(excluded.revision_date, book_master.revision_date),
                 description=COALESCE(excluded.description, book_master.description),
                 page_count=excluded.page_count, source=excluded.source,
                 updated_at=datetime('now')""",
            (slug, meta.get("title"), meta.get("author"), meta.get("publisher"),
             meta.get("kyobo_id"), meta.get("salecmdtid"), meta.get("isbn"),
             meta.get("category"), meta.get("field"), meta.get("pub_date"),
             meta.get("revision_date"), meta.get("description"),
             len(pages), meta.get("source", "capture")),
        )
        for pn, txt in pages.items():
            txt = txt or ""
            c.execute(
                """INSERT INTO book_pages (book_slug,page_num,ocr_text,char_count)
                   VALUES (?,?,?,?)
                   ON CONFLICT(book_slug,page_num) DO UPDATE SET
                     ocr_text=excluded.ocr_text, char_count=excluded.char_count,
                     updated_at=datetime('now')""",
                (slug, int(pn), txt, len(txt)),
            )
        c.commit()
        n = c.execute("SELECT COUNT(*) FROM book_pages WHERE book_slug=?", (slug,)).fetchone()[0]
    finally:
        c.close()
    backup(tag=slug)
    return n


def stats() -> dict:
    c = _conn()
    try:
        books = c.execute("SELECT COUNT(*) FROM book_master").fetchone()[0]
        pages = c.execute("SELECT COUNT(*) FROM book_pages").fetchone()[0]
        chars = c.execute("SELECT COALESCE(SUM(char_count),0) FROM book_pages").fetchone()[0]
    finally:
        c.close()
    return {"books": books, "pages": pages, "chars": chars, "db": str(DB_PATH)}
