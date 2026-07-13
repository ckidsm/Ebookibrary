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


def _finalize_html(book_dir) -> None:
    """빌드된 index.html 에 챕터트리(chapters.json) + 표정리본(page_extras.json) 주입.
    이미 주입돼 있으면 스킵(멱등). CLI/finalize_book.py 와 동일 규칙."""
    from pathlib import Path as _P
    sd = _P(book_dir) / "summary"
    idx = sd / "index.html"
    if not idx.exists():
        return
    html = idx.read_text(encoding="utf-8")
    changed = False
    ch = sd / "chapters.json"
    if ch.exists() and "chapter-summary" not in html:
        from .processing.add_chapter_tree import build as _tree
        pages_total = len(list(_P(book_dir).glob("page_*.png")))
        html = _tree(html, json.loads(ch.read_text(encoding="utf-8")), pages_total)
        changed = True
    pe = sd / "page_extras.json"
    if pe.exists() and "page-extra" not in html:
        from .processing.add_page_extras import build as _extras
        html = _extras(html, json.loads(pe.read_text(encoding="utf-8")))
        changed = True
    if changed:
        idx.write_text(html, encoding="utf-8")


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

        # ── 0.5) 오염 검사(커서·알림·비책) — OCR 전에 오염 페이지 제거 ──
        if cfg.api_key:
            try:
                from .processing.contamination import check_contamination
                db.update_job(jid, progress=_progress(1, N, "ocr", 0, len(pngs), "오염 검사..."))
                check_contamination(book_dir, cfg, remove=True)
            except Exception as e:
                log.warning("오염 검사 실패(무시): %s", e)

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
        _tot_pg = len(ocr_files)
        db.update_job(jid, progress=_progress(2, N, "summarize", 0, _tot_pg, "AI 요약 시작..."))
        out_path = book_dir / "summary" / "batch_001.json"
        # 페이지별 진행을 잡에 반영 — 웹 진행바가 실시간으로 올라가고, 하트비트 역할도 함

        def _sum_cb(done: int, tot: int, num: int) -> None:
            if _cancelling(jid):
                return
            db.update_job(jid, progress=_progress(
                2, N, "summarize", done, tot,
                f"AI 요약 중 — {done}/{tot}장 (현재 p.{num}, 남은 {tot - done}장)"))

        res = summarize_pages(ocr_files, cfg, out_path, progress=True, progress_cb=_sum_cb)
        db.update_job(jid, progress=_progress(
            2, N, "summarize", res.get("pages_done", 0), len(ocr_files),
            f"요약 {res.get('pages_done',0)}p · ${res.get('cost_usd',0):.3f}"
            + (f" · 오염제외 {len(res['skipped'])}" if res.get("skipped") else "")))

        # ── 2.5) 소스코드 비전 추출 → code_blocks.json (팝업 '💻 소스코드' 패널용) ──
        if cfg.api_key and not _cancelling(jid):
            try:
                from .processing.extract_code import extract_code_blocks
                db.update_job(jid, progress=_progress(
                    2, N, "summarize", res.get("pages_done", 0), len(ocr_files), "소스코드 추출..."))
                extract_code_blocks(book_dir, cfg)
            except Exception as e:
                log.warning("소스코드 추출 실패(무시): %s", e)

        # ── 3) merge ─────────────────────────────────────────
        if _cancelling(jid):
            return
        db.update_job(jid, progress=_progress(3, N, "merge", 0, 0, "병합..."))
        merge_batches(book_dir / "summary", fallback_title=title)

        # ── 3.4) 챕터 자동 감지(비전, 장 표지) → chapters.json (OCR 깨진 책도 동작) ──
        if cfg.api_key and not (book_dir / "summary" / "chapters.json").exists():
            try:
                from .processing.chapters_detect import generate_chapters
                db.update_job(jid, progress=_progress(3, N, "merge", 1, 1, "챕터 감지..."))
                generate_chapters(book_dir, cfg)
            except Exception as e:
                log.warning("챕터 감지 실패(무시): %s", e)

        # ── 3.5) 책 개요(전체요약+장별 상세요약) — 머리말 카드 ──
        if cfg.api_key:
            try:
                from .processing.book_overview import generate_overview
                db.update_job(jid, progress=_progress(3, N, "merge", 1, 1, "책 개요 생성..."))
                generate_overview(book_dir, cfg, title)
            except Exception as e:
                log.warning("책 개요 생성 실패(무시): %s", e)

        # ── 4) build HTML ────────────────────────────────────
        if _cancelling(jid):
            return
        db.update_job(jid, progress=_progress(4, N, "build", 0, 0, "HTML 생성..."))
        idx = build_index(book_dir, title=title)

        # ── 4.5) 최종화 — 챕터트리 + 표정리본 주입(chapters.json / page_extras.json) ──
        try:
            _finalize_html(book_dir)
        except Exception as e:
            log.warning("최종화(챕터트리) 실패(무시): %s", e)

        # ── analysis_meta.json — 분석 히스토리(날짜·비용·토큰·페이지·모델). 모달이 읽어 표시 ──
        try:
            import datetime as _dt
            _mp = book_dir / "summary" / "analysis_meta.json"
            _prev = 0.0
            if _mp.exists():
                try:
                    _prev = float(json.loads(_mp.read_text(encoding="utf-8")).get("cost_usd_total", 0))
                except Exception:
                    _prev = 0.0
            _rc = float(res.get("cost_usd", 0))
            _mp.write_text(json.dumps({
                "analyzed_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "pages": res.get("pages_done", 0),
                "cost_usd": round(_rc, 4),
                "cost_usd_total": round(_prev + _rc, 4),
                "input_tokens": res.get("in_tok", 0),
                "output_tokens": res.get("out_tok", 0),
                "model": cfg.model,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("analysis_meta 기록 실패(무시): %s", e)

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
            # 도서 헤더 디테일 — 출판일·개정일(무료 정규식) + 종류·분야·소개(AI 1회)
            try:
                from .processing.book_meta import extract_dates, extract_meta_ai
                if cfg.api_key:
                    meta.update(extract_meta_ai(pages_txt, cfg, title=title))  # 종류·분야·소개+날짜(정확)
                else:
                    meta.update(extract_dates(pages_txt))  # 무료 폴백(날짜만, 부정확)
            except Exception as e:
                log.warning("도서 메타 추출 실패(무시): %s", e)
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
