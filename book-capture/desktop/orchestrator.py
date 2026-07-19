# -*- coding: utf-8 -*-
"""로컬 파이프라인 오케스트레이터 — pywebview 앱(main.py)이 호출.

analyze(book, callbacks): (1) 캡처 프리플라이트 — 교보앱에 대상 책을 열고, 못 열면
사용자에게 다이얼로그로 열기 요청 후 확인 대기. (2) build_steps('auto') + run_pipeline
(캡처→전사→요약→코드→merge→build→챕터→개요→최종화→발행). 백그라운드 스레드 실행 가정.
"""
from __future__ import annotations
import re
import unicodedata
from pathlib import Path


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", str(s or ""))
    return re.sub(r"[\s\W_]+", "", s).lower()


def book_dir_for(slug: str) -> Path:
    from bookcapture.settings import load as load_settings
    s = load_settings()
    return Path(s.output.books_dir).expanduser().resolve() / slug


def preflight_open_book(title, salecmdtid, book_dir, on_prompt, should_cancel=None) -> bool:
    """교보앱에 대상 책을 연다. 이미 맞는 책이 열려있으면 바로 진행.
    deep link 로 못 열면 on_prompt(title) 로 사용자에게 열기 요청 → 확인(True)/취소(False) 대기.
    반환: 진행 가능(True) / 취소(False)."""
    from bookcapture.kyobo_app import KyoboAppScreenshot
    try:
        bot = KyoboAppScreenshot(output_dir=str(book_dir))
    except Exception:
        # 인스턴스 못 만들어도 캡처(capture-auto subprocess)가 자체 처리 → 그냥 진행
        return True
    if bot.system != "Darwin":
        return True  # macOS 전용 프리플라이트. 그 외는 캡처 단계에 위임.

    def _matches() -> bool:
        try:
            if not (bot.is_app_running() and bot.has_app_window()):
                return False
            cur = bot.get_current_book_title() or ""
            tn = _norm(title)
            cn = _norm(cur)
            return bool(cn) and (not tn or tn in cn or cn in tn)
        except Exception:
            return False

    # 1) deep link 로 책 열기 시도(salecmdtid 있을 때)
    if salecmdtid:
        try:
            bot.open_book_by_id(salecmdtid)
        except Exception:
            pass
    if _matches():
        return True

    # 2) 앱 실행이라도 시도(창 없으면)
    try:
        if not (bot.is_app_running() and bot.has_app_window()):
            bot.launch_app()
    except Exception:
        pass
    if _matches():
        return True

    # 3) 폴백: 사용자에게 "교보앱에서 이 책을 열어주세요" 다이얼로그 → 확인 대기
    if should_cancel and should_cancel():
        return False
    if on_prompt is None:
        return True   # 다이얼로그 없이 진행(캡처가 현재 화면 캡처)
    return bool(on_prompt(title))


def analyze(book: dict, on_progress=None, on_prompt=None, should_cancel=None,
            on_line=None, env=None) -> dict:
    """책 하나를 로컬에서 캡처~발행. 반환: run_pipeline 결과 dict(+preflight 취소 시 cancelled)."""
    from bookcapture.pipeline_run import build_steps, run_pipeline

    slug = book.get("slug") or _norm(book.get("title", "")) or "untitled"
    # slug 은 웹의 slugify 결과를 그대로 받는 게 정확(폴더명 일치). 없으면 title 기반 근사.
    title = book.get("title") or slug
    salecmdtid = book.get("salecmdtid")
    pages = book.get("pages")
    bd = book_dir_for(slug)

    # (1) 캡처 프리플라이트 — 책 열기 + 폴백 다이얼로그
    if not preflight_open_book(title, salecmdtid, bd, on_prompt, should_cancel):
        return {"status": "cancelled", "error": "책 열기 취소", "failed_step": "capture-auto"}

    # (2) 파이프라인 실행 (auto: 캡처→…→발행)
    steps = build_steps("auto", slug, bd, title=title, salecmdtid=salecmdtid, pages=pages)
    return run_pipeline(steps, on_progress=on_progress, should_cancel=should_cancel,
                        on_line=on_line, env=env)
