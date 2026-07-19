# -*- coding: utf-8 -*-
"""교보 로컬 캡처 데스크탑 앱 (pywebview).

기존 교보 웹 라이브러리를 네이티브 창으로 embed + hook.js 주입으로 "로컬 매크로" 버튼 후킹.
사용자가 책을 골라 로컬 매크로(auto)로 분석 시작 → JsApi.start_local → orchestrator.analyze
(캡처 프리플라이트 → 캡처→전사→요약→…→발행). 진행은 evaluate_js 로 웹 오버레이에 push.

실행: book-capture/ 에서  `.venv/bin/python -m desktop.main`  (또는 desktop/run.command 더블클릭)
"""
from __future__ import annotations
import json
import sys
import threading
from pathlib import Path

import webview  # pywebview

from desktop import orchestrator

WEB_URL = "https://redcodeme.synology.me/kyobo/"
_HOOK_JS = (Path(__file__).parent / "hook.js").read_text(encoding="utf-8")


class JsApi:
    """웹 JS ↔ Python 브리지. 웹에서 window.pywebview.api.<메서드>() 로 호출."""

    def __init__(self):
        self._window = None
        self._cancel = threading.Event()
        self._confirm = threading.Event()
        self._confirm_ok = False
        self._busy = threading.Lock()

    def set_window(self, w):
        self._window = w

    # ── JS 로 push (오버레이 갱신) ──
    def _push(self, kind: str, payload: dict):
        if not self._window:
            return
        try:
            js = "window.__kyoboApp && window.__kyoboApp.%s(%s)" % (
                kind, json.dumps(payload, ensure_ascii=False))
            self._window.evaluate_js(js)
        except Exception as e:
            print("[app] push 실패:", e)

    # ── 웹에서 호출하는 API ──
    def start_local(self, payload):
        """mode=auto 로컬 매크로 시작. payload={slug,title,mode,salecmdtid,pages}."""
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "error": "이미 분석 진행 중"}
        self._cancel.clear()
        threading.Thread(target=self._run, args=(payload,), daemon=True).start()
        return {"ok": True}

    def cancel(self):
        self._cancel.set()
        # 프리플라이트 대기 중이면 깨워서 취소 처리
        self._confirm_ok = False
        self._confirm.set()
        return {"ok": True}

    def book_confirm(self, ok=True):
        self._confirm_ok = bool(ok)
        self._confirm.set()
        return {"ok": True}

    # ── 캡처 프리플라이트 폴백: 다이얼로그 표시 + 확인 대기 ──
    def _on_prompt(self, title) -> bool:
        self._confirm.clear()
        self._push("prompt", {"title": title})
        self._confirm.wait()  # book_confirm/cancel 까지 블록
        return self._confirm_ok and not self._cancel.is_set()

    def _run(self, payload):
        try:
            slug = payload.get("slug")
            title = payload.get("title") or slug
            self._push("start", {"slug": slug, "title": title})

            def on_progress(i, n, name, cur, tot, line):
                self._push("progress", {"stage": i, "stage_total": n, "step": name,
                                        "cur": cur, "tot": tot, "line": line})

            book = {"slug": slug, "title": title,
                    "salecmdtid": payload.get("salecmdtid"), "pages": payload.get("pages")}
            try:
                res = orchestrator.analyze(
                    book,
                    on_progress=on_progress,
                    on_prompt=self._on_prompt,
                    should_cancel=self._cancel.is_set,
                    on_line=lambda s: sys.stdout.write(s),
                )
            except Exception as e:
                import traceback
                res = {"status": "failed", "error": f"{type(e).__name__}: {e}",
                       "stdout_tail": traceback.format_exc()[-400:]}
            self._push("done", res)
        finally:
            try:
                self._busy.release()
            except Exception:
                pass


def _inject_hook(window):
    try:
        window.evaluate_js(_HOOK_JS)
    except Exception as e:
        print("[app] hook 주입 실패:", e)


def main():
    api = JsApi()
    window = webview.create_window(
        "교보 캡처", WEB_URL, js_api=api, width=1360, height=920,
        min_size=(1000, 700),
    )
    api.set_window(window)
    # 페이지 로드마다 hook 재주입(웹 내 네비게이션 대비)
    window.events.loaded += lambda: _inject_hook(window)
    webview.start()


if __name__ == "__main__":
    main()
