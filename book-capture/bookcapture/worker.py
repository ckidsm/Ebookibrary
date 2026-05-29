"""백엔드 jobs 큐를 polling 하는 worker.

흐름:
  ┌────────────────┐                   ┌────────────────┐
  │  Web (8080)    │ POST /api/jobs    │   Bridge       │
  │  [분석 시작]   │ ────────────────▶ │   (SQLite)     │
  └────────────────┘                   │   jobs.status  │
                                       │   = 'pending'  │
                                       └───────┬────────┘
                                               │ POST /api/jobs/next/claim
                                               ▼
                                       ┌────────────────┐
                                       │ Mac worker     │
                                       │  ./bookcapture │
                                       │   ocr+sum+...  │
                                       └───┬────────────┘
                                           │ PATCH progress, status
                                           ▼ done/failed

캡처 단계는 인터랙티브 + 책 열기가 필요해 워커가 자동 못 함.
=> mode='auto' 일 때는 OCR + 요약 + merge + build 만 자동.
   capture 는 사용자가 별도 `bookcapture capture --mode 3` 으로 미리 진행.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from .settings import DEFAULT_BRIDGE_URL, load as load_settings


# stdout 한 줄에서 "현재/전체" 추출하기 위한 패턴 (각 단계 출력 형식)
#   ocr:        "[ocr]   12/185 완료 (page_127)"
#   summarize:  "[summarize] 47/185 (25%) p.173 ..."
#   merge/build: 단일 줄
_PROGRESS_PATTERNS = [
    re.compile(r"\[ocr\]\s+(\d+)/(\d+)\s+\S+"),
    re.compile(r"\[summarize\]\s+(\d+)/(\d+)"),
    re.compile(r"\[(\d+)/(\d+)\]\s+캡처"),   # capture-auto 의 "[12/300] 캡처 중..."
]


def parse_subprogress(line: str) -> tuple[int, int] | None:
    for pat in _PROGRESS_PATTERNS:
        m = pat.search(line)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def _http(method: str, url: str, body: dict | None = None, timeout: float = 10.0) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body_txt = resp.read().decode("utf-8") or "{}"
        return json.loads(body_txt) if body_txt.strip().startswith("{") else {}


def claim_one(bridge: str) -> dict | None:
    try:
        r = _http("POST", f"{bridge}/api/jobs/next/claim")
        return r.get("job")
    except urllib.error.HTTPError as e:
        print(f"[worker] claim 실패: HTTP {e.code} {e.read().decode()[:200]}")
    except Exception as e:
        print(f"[worker] claim 실패: {e}")
    return None


def report(bridge: str, jid: int, **fields) -> None:
    try:
        _http("PATCH", f"{bridge}/api/jobs/{jid}", body=fields)
    except Exception as e:
        print(f"[worker] report 실패 ({jid}): {e}")


def progress_payload(
    stage: int, stage_total: int, stage_name: str,
    current: int = 0, total: int = 0, msg: str = "",
) -> str:
    """프론트 프로그레스바용 JSON 문자열. db.jobs.progress 에 그대로 저장."""
    # 전체 pct = (완료된 stage + 현재 stage 내 비율) / stage_total
    sub_pct = (current / total) if total > 0 else 0.0
    pct = ((stage - 1) + sub_pct) / stage_total * 100
    return json.dumps({
        "stage": stage,
        "stage_total": stage_total,
        "stage_name": stage_name,
        "current": current,
        "total": total,
        "pct": round(pct, 1),
        "msg": msg[:200],
    }, ensure_ascii=False)


def run_one(bridge: str, job: dict) -> None:
    jid = job["id"]
    slug = job["slug"]
    mode = job.get("mode") or "auto"
    pages = job.get("pages")
    print(f"\n[worker] === job #{jid} 시작 (slug={slug}, mode={mode}) ===")

    s = load_settings(bridge_url=bridge)
    books_dir = Path(s.output.books_dir).expanduser().resolve()
    book_dir = books_dir / slug

    # CLI 서브커맨드 결정
    steps: list[list[str]] = []
    if mode == "summarize-only":
        # 캡처 PNG 가 미리 있어야 함
        if not list(book_dir.glob("*.png")):
            msg = (f"책 폴더에 캡처 PNG 없음: {book_dir}\n"
                   f"먼저 capture-only 작업 실행 또는 수동 capture")
            print(f"[worker] {msg}")
            report(bridge, jid, status="failed", error=msg)
            return
        steps = [
            ["ocr", "--book-dir", str(book_dir)],
            ["summarize", "--book-dir", str(book_dir)] + (["--pages", pages] if pages else []),
            ["merge", "--book-dir", str(book_dir)],
            ["build", "--book-dir", str(book_dir)],
        ]
    elif mode == "capture-only":
        steps = [["capture-auto", "--slug", slug, "--count", "300", "--interval", "2"]]
    else:  # auto = capture + ocr + summarize + merge + build (5단계)
        steps = [
            ["capture-auto", "--slug", slug, "--count", "300", "--interval", "2"],
            ["ocr", "--book-dir", str(book_dir)],
            ["summarize", "--book-dir", str(book_dir)] + (["--pages", pages] if pages else []),
            ["merge", "--book-dir", str(book_dir)],
            ["build", "--book-dir", str(book_dir)],
        ]

    stdout_buf: list[str] = []
    n = len(steps)
    last_report_ts = 0.0
    REPORT_MIN_INTERVAL = 0.6  # 너무 잦은 PATCH 방지

    for i, args in enumerate(steps, 1):
        step_name = args[0]
        # 단계 시작 신호
        report(bridge, jid,
               progress=progress_payload(i, n, step_name, 0, 0, "시작..."))
        print(f"\n[worker] [{i}/{n}] {step_name} ...")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "bookcapture", *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout
            sub_current = sub_total = 0
            for line in proc.stdout:
                print(line, end="")
                stdout_buf.append(line)
                if len(stdout_buf) > 200:
                    stdout_buf = stdout_buf[-200:]

                # 현재/전체 추출 시도 (페이지 진행)
                parsed = parse_subprogress(line)
                if parsed:
                    sub_current, sub_total = parsed

                now = time.monotonic()
                if (now - last_report_ts) >= REPORT_MIN_INTERVAL:
                    last_report_ts = now
                    report(bridge, jid,
                           progress=progress_payload(
                               i, n, step_name, sub_current, sub_total,
                               line.strip()[:140] or step_name,
                           ))
            rc = proc.wait()
            # 단계 종료 신호 (100%)
            report(bridge, jid,
                   progress=progress_payload(i, n, step_name,
                                             sub_total or 1, sub_total or 1,
                                             f"{step_name} 완료"))
            if rc != 0:
                msg = f"step '{step_name}' exit {rc}"
                report(bridge, jid, status="failed", error=msg,
                       stdout_tail="".join(stdout_buf[-30:]))
                print(f"[worker] ✗ {msg}")
                return
        except Exception as e:
            tb = traceback.format_exc()
            report(bridge, jid, status="failed", error=f"{type(e).__name__}: {e}",
                   stdout_tail="".join(stdout_buf[-20:]) + "\n" + tb[-500:])
            print(f"[worker] ✗ exception in {step_name}: {e}")
            return

    # 최종 완료
    report(bridge, jid, status="done",
           progress=progress_payload(n, n, "done", 1, 1, "전체 완료"),
           stdout_tail="".join(stdout_buf[-30:]))
    print(f"[worker] ✓ job #{jid} 완료")


def ping(bridge: str) -> None:
    try:
        _http("POST", f"{bridge}/api/worker/ping", body={}, timeout=3.0)
    except Exception:
        pass  # silent — heartbeat 실패해도 worker 자체는 계속


def run_worker(bridge: str | None = None, interval: float = 5.0) -> int:
    bridge = (bridge or DEFAULT_BRIDGE_URL).rstrip("/")
    print(f"[worker] 시작 · bridge={bridge} · {interval}s polling")
    print(f"[worker] Ctrl+C 로 종료")
    while True:
        try:
            ping(bridge)
            job = claim_one(bridge)
            if job:
                run_one(bridge, job)
            else:
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[worker] 사용자 종료")
            return 0
        except Exception as e:
            print(f"[worker] loop 오류: {e}")
            time.sleep(interval)
