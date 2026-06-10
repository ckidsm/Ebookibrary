"""백엔드 업로드 처리기 (#67 멀티 OS).

mode='upload-process' job 을 백엔드(컨테이너)가 직접 소비한다.
업로드된 PNG 는 NAS 의 LIBRARY_BOOKS_WRITE_DIR/<slug>/ 에 있고,
컨테이너 안에서 OCR(tesseract) → AI 요약 → merge → HTML 빌드까지 끝낸다.
산출물은 곧 정적 서빙 폴더라 별도 배포 불필요.

원격 워커(Mac 등)는 capture 계열만 claim 하고 upload-process 는 안 잡는다
(db.claim_next_job 에서 제외). 따라서 OS 무관하게 업로드만으로 분석 완료.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from pathlib import Path

from . import db
from .processing.settings import AiCfg, OcrCfg
from .processing.ocr import ocr_book
from .processing.summarize import summarize_pages
from .processing.merge import merge_batches
from .processing.build_html import build_index

log = logging.getLogger("kyobo-bridge")

_WRITE_ROOT = Path(os.environ.get("LIBRARY_BOOKS_WRITE_DIR", "/mnt/library-rw/books"))


def _ai_cfg() -> AiCfg:
    ai = db.get_setting("ai", {}) or {}
    return AiCfg(
        provider=ai.get("provider", "claude"),
        model=ai.get("model", "claude-sonnet-4-5"),
        api_key=ai.get("api_key", "") or os.environ.get("ANTHROPIC_API_KEY", ""),
        language=ai.get("language", "ko"),
        temperature=float(ai.get("temperature", 0.3)),
    )


def _ocr_cfg() -> OcrCfg:
    o = db.get_setting("ocr", {}) or {}
    return OcrCfg(lang=o.get("lang", "kor+eng"), use_thumbs=bool(o.get("use_thumbs", True)))


def _progress(stage: int, total: int, name: str, cur: int = 0, tot: int = 0, msg: str = "") -> str:
    sub = (cur / tot) if tot > 0 else 0.0
    pct = ((stage - 1) + sub) / total * 100
    return json.dumps({
        "stage": stage, "stage_total": total, "stage_name": name,
        "current": cur, "total": tot, "pct": round(pct, 1), "msg": msg[:200],
    }, ensure_ascii=False)


def _cancelling(jid: int) -> bool:
    j = db.get_job(jid)
    return bool(j and j.get("status") in ("cancelling", "cancelled"))


def process_upload_job(job: dict) -> None:
    """업로드된 책 1권: OCR → 요약 → merge → build. 진행률·상태 보고."""
    jid = job["id"]
    slug = job["slug"]
    title = job.get("title") or slug
    book_dir = _WRITE_ROOT / slug
    N = 4  # ocr, summarize, merge, build (capture 는 업로드라 스킵)
    log.info("📥 upload-process job #%s 시작 slug=%s dir=%s", jid, slug, book_dir)

    # 장시간 OCR/요약(단일 호출, 수~수십 분) 동안 60초마다 heartbeat 갱신 →
    # 600s watchdog(reap_stale_jobs)이 진행 중인 잡을 죽이지 않도록.
    _hb_stop = threading.Event()
    def _hb_keeper():
        while not _hb_stop.wait(60):
            db.touch_heartbeat(jid)
    _hbt = threading.Thread(target=_hb_keeper, name=f"hb-{jid}", daemon=True)
    _hbt.start()

    try:
        pngs = sorted(book_dir.glob("*.png")) + sorted(book_dir.glob("*.jpg")) \
               + sorted(book_dir.glob("*.jpeg")) + sorted(book_dir.glob("*.webp"))
        if not pngs:
            db.update_job(jid, status="failed",
                          error=f"업로드 이미지 없음: {book_dir}")
            return

        # ── 1) OCR ───────────────────────────────────────────
        db.update_job(jid, progress=_progress(1, N, "ocr", 0, len(pngs), "OCR 시작..."))
        if _cancelling(jid):
            return
        ocr_files = ocr_book(book_dir, _ocr_cfg())
        if not ocr_files:
            db.update_job(jid, status="failed",
                          error="OCR 결과 없음 (tesseract 미설치 또는 이미지 인식 실패)")
            return
        db.update_job(jid, progress=_progress(1, N, "ocr", len(ocr_files), len(ocr_files), "OCR 완료"))

        # ── 2) AI 요약 ───────────────────────────────────────
        if _cancelling(jid):
            return
        cfg = _ai_cfg()
        if not cfg.api_key:
            db.update_job(jid, status="failed",
                          error="AI API 키 없음 — ⚙ 설정에서 키 저장 후 다시 시도")
            return
        db.update_job(jid, progress=_progress(2, N, "summarize", 0, len(ocr_files), "AI 요약 시작..."))
        out_path = book_dir / "summary" / "batch_001.json"
        res = summarize_pages(ocr_files, cfg, out_path, progress=True)
        db.update_job(jid, progress=_progress(
            2, N, "summarize", res.get("pages_done", 0), len(ocr_files),
            f"요약 {res.get('pages_done',0)}p · ${res.get('cost_usd',0):.3f}"
            + (f" · 오염제외 {len(res['skipped'])}" if res.get("skipped") else "")))

        # ── 3) merge ─────────────────────────────────────────
        if _cancelling(jid):
            return
        db.update_job(jid, progress=_progress(3, N, "merge", 0, 0, "병합..."))
        merge_batches(book_dir / "summary", fallback_title=title)

        # ── 4) build HTML ────────────────────────────────────
        if _cancelling(jid):
            return
        db.update_job(jid, progress=_progress(4, N, "build", 0, 0, "HTML 생성..."))
        idx = build_index(book_dir, title=title)

        # ── 5) OCR 코퍼스 DB 저장 (학습/추론용 기초 데이터 + 백업) ──
        try:
            from .processing.ocr_corpus import save_book as _corpus_save
            ocr_txt_dir = book_dir / "summary" / "ocr_text"
            pages_txt: dict[int, str] = {}
            if ocr_txt_dir.exists():
                for f in sorted(ocr_txt_dir.glob("page_*.txt")):
                    try:
                        pn = int(f.stem.split("_")[-1])
                    except ValueError:
                        continue
                    pages_txt[pn] = f.read_text(encoding="utf-8")
            meta = {"title": title, "source": "upload-process"}
            try:
                for b in db.list_books():
                    if (b.get("title") or "") == title:
                        meta.update({"author": b.get("author"), "publisher": b.get("publisher"),
                                     "kyobo_id": b.get("kyobo_id"), "salecmdtid": b.get("salecmdtid"),
                                     "isbn": b.get("isbn")})
                        break
            except Exception:
                pass
            saved = _corpus_save(slug, meta, pages_txt)
            log.info("📚 OCR 코퍼스 DB: %s · %d 페이지 저장+백업", slug, saved)
        except Exception as e:
            log.warning("OCR 코퍼스 DB 저장 실패(무시): %s", e)

        db.update_job(jid, status="done",
                      progress=_progress(N, N, "done", 1, 1, "전체 완료"))
        log.info("✓ upload-process job #%s 완료 → %s", jid, idx)
    except Exception as e:
        tb = traceback.format_exc()
        log.error("✗ upload-process job #%s 실패: %s\n%s", jid, e, tb[-800:])
        db.update_job(jid, status="failed", error=f"{type(e).__name__}: {e}")
    finally:
        _hb_stop.set()


_stop = threading.Event()


def run_processor_loop(interval: float = 3.0) -> None:
    log.info("📥 업로드 처리기 시작 (interval=%ss)", interval)
    while not _stop.is_set():
        try:
            job = db.claim_next_upload_job()
            if job:
                process_upload_job(job)
            else:
                _stop.wait(interval)
        except Exception as e:
            log.error("업로드 처리기 loop 오류: %s", e)
            _stop.wait(interval)


def start_processor() -> threading.Thread:
    t = threading.Thread(target=run_processor_loop, name="upload-processor", daemon=True)
    t.start()
    return t


def stop_processor() -> None:
    _stop.set()
