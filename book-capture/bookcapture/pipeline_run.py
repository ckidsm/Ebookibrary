# -*- coding: utf-8 -*-
"""파이프라인 step 배열 생성 + subprocess 순차 실행 (worker/데스크탑앱 공용, 2026-07-19).

worker.py 와 desktop 앱이 **같은 검증된 로직**으로 캡처→분석→발행을 돌리도록,
worker.run_one 에 인라인돼 있던 (1) mode→CLI 서브커맨드 배열, (2) subprocess 루프·
진행률 파싱·취소 를 여기로 추출했다. 콜백 기반이라 워커는 백엔드 report/cancel 를,
앱은 UI 갱신 콜백을 주입한다.
"""
from __future__ import annotations
import re
import sys
import subprocess
import time
import traceback

# stdout 한 줄에서 "현재/전체" 추출 (각 단계 출력 형식)
_PROGRESS_PATTERNS = [
    re.compile(r"\[ocr\]\s+(\d+)/(\d+)\s+\S+"),          # "[ocr]   12/185 완료 (page_127)"
    re.compile(r"\[summarize\]\s+(\d+)/(\d+)"),          # "[summarize] 47/185 (25%) p.173"
    re.compile(r"\[(\d+)/(\d+)\]\s+캡처"),                # "[12/300] 캡처 중..." (capture-auto)
]

# 실패해도 잡 전체는 살리는 선택 단계(2026-07-14: chapters-auto 0개가 잡 전체 실패시키던 버그 대응)
OPTIONAL_STEPS = ("chapters-auto", "overview", "finalize", "publish")


def parse_subprogress(line: str):
    for pat in _PROGRESS_PATTERNS:
        m = pat.search(line)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def build_steps(mode, slug, book_dir, title=None, salecmdtid=None, pages=None):
    """mode → CLI 서브커맨드 배열. (salecmdtid 해석·PNG 존재검사 등 사전조건은 caller 책임.)

    pages: worker 관례상 (a) summarize `--pages`, (b) capture `--start-page` 로 이중 사용.
           (start-page>1 이면 그 번호부터 이어 캡처. 대부분 1페이지부터라 None.)
    """
    bd = str(book_dir)
    title = title or slug
    _pages = ["--pages", str(pages)] if pages else []
    _sp = str(pages or "").strip()

    if mode in ("summarize-only", "upload-process"):
        return [
            ["ocr", "--vision", "--book-dir", bd],
            ["summarize", "--book-dir", bd] + _pages,
            ["code", "--book-dir", bd],
            ["merge", "--book-dir", bd],
            ["build", "--book-dir", bd],
        ]
    if mode == "capture-only":
        cap = ["capture-auto", "--slug", slug, "--count", "1500", "--interval", "2"]
        if salecmdtid:
            cap += ["--book-id", salecmdtid]
        if _sp.isdigit() and int(_sp) > 1:
            cap += ["--start-page", _sp]
        return [cap, ["upload", "--slug", slug, "--title", title]]
    if mode == "capture-browser":
        cap = ["capture-auto", "--slug", slug, "--count", "1500", "--interval", "2", "--no-app"]
        if _sp.isdigit() and int(_sp) > 1:
            cap += ["--start-page", _sp]
        return [cap, ["upload", "--slug", slug, "--title", title]]
    if mode == "auto-web":
        if not salecmdtid:
            raise ValueError("auto-web 모드엔 salecmdtid 필요")
        return [
            ["wviewer", "capture-lib", "--salecmdtid", salecmdtid, "--slug", slug,
             "--out-dir", bd, "--max-pages", "300", "--delay", "1.5"],
            ["ocr", "--vision", "--book-dir", bd],
            ["summarize", "--book-dir", bd] + _pages,
            ["code", "--book-dir", bd],
            ["merge", "--book-dir", bd],
            ["build", "--book-dir", bd],
        ]
    # auto (기본) — 로컬 매크로 풀 파이프라인 (capture→…→build→챕터→개요→최종화→발행)
    cap = ["capture-auto", "--slug", slug, "--count", "1500", "--interval", "0.8", "--no-ocr"]
    if salecmdtid:
        cap += ["--book-id", salecmdtid]
    if _sp.isdigit() and int(_sp) > 1:
        cap += ["--start-page", _sp]
    return [
        cap,
        ["ocr", "--vision", "--book-dir", bd],
        ["summarize", "--book-dir", bd] + _pages,
        ["code", "--book-dir", bd],
        ["merge", "--book-dir", bd],
        ["build", "--book-dir", bd],
        ["chapters-auto", "--book-dir", bd],
        ["overview", "--book-dir", bd, "--title", title],
        ["finalize", "--book-dir", bd],
        ["publish", "--book-dir", bd],
    ]


def run_pipeline(steps, on_progress=None, should_cancel=None, on_line=None, env=None):
    """steps 를 `python -m bookcapture …` subprocess 로 **순차** 실행.

    on_progress(i, n, step_name, sub_cur, sub_total, line): 진행 보고(라인마다).
    should_cancel() -> bool: True 면 현재 subprocess SIGTERM 후 중단.
    on_line(line): 자식 stdout 원문 라인(기본 sys.stdout).
    env: subprocess 환경변수(기본 상속).
    반환: {status: done|failed|cancelled, error?, stdout_tail, failed_step?}
    """
    n = len(steps)
    buf: list[str] = []
    _line = on_line or (lambda s: sys.stdout.write(s))

    def emit(i, name, cur, tot, line):
        if on_progress:
            try:
                on_progress(i, n, name, cur, tot, line)
            except Exception:
                pass

    for i, args in enumerate(steps, 1):
        step_name = args[0]
        if should_cancel and should_cancel():
            return {"status": "cancelled", "stdout_tail": "".join(buf[-30:]), "failed_step": step_name}
        emit(i, step_name, 0, 0, "시작...")
        _line(f"\n[pipeline] [{i}/{n}] {step_name} ...\n")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "bookcapture", *args],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
            )
            assert proc.stdout
            sub_cur = sub_tot = 0
            last_cancel = 0.0
            for line in proc.stdout:
                _line(line)
                buf.append(line)
                if len(buf) > 200:
                    del buf[:-200]
                p = parse_subprogress(line)
                if p:
                    sub_cur, sub_tot = p
                emit(i, step_name, sub_cur, sub_tot, line.strip()[:140] or step_name)
                now = time.monotonic()
                if should_cancel and (now - last_cancel) >= 1.5:
                    last_cancel = now
                    if should_cancel():
                        try: proc.terminate()
                        except Exception: pass
                        try: proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            try: proc.kill()
                            except Exception: pass
                        return {"status": "cancelled", "stdout_tail": "".join(buf[-30:]), "failed_step": step_name}
            rc = proc.wait()
            emit(i, step_name, sub_tot or 1, sub_tot or 1, f"{step_name} 완료")
            if rc != 0:
                if step_name in OPTIONAL_STEPS:
                    _line(f"[pipeline] ⚠ 선택 단계 '{step_name}' exit {rc} — 건너뛰고 계속\n")
                    continue
                return {"status": "failed", "error": f"step '{step_name}' exit {rc}",
                        "stdout_tail": "".join(buf[-30:]), "failed_step": step_name}
        except Exception as e:
            return {"status": "failed", "error": f"{type(e).__name__}: {e}",
                    "stdout_tail": "".join(buf[-20:]) + "\n" + traceback.format_exc()[-500:],
                    "failed_step": step_name}
    return {"status": "done", "stdout_tail": "".join(buf[-30:])}
