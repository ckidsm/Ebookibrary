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


def _lookup_salecmdtid(bridge: str, slug: str) -> str | None:
    """books 테이블에서 slug 매칭되는 책의 salecmdtid 조회.

    slug 형식이 다양해서 여러 방식 시도:
      1) salecmdtid 가 slug 와 동일 (E000... 형태)
      2) title 가공 = slug 매칭
    """
    if slug.startswith("E") and len(slug) > 10:
        return slug  # slug 자체가 salecmdtid 인 경우
    try:
        r = _http("GET", f"{bridge}/api/library/books", timeout=10.0)
        for b in r.get("books", []):
            if not b.get("salecmdtid"):
                continue
            if b.get("kyobo_id") == slug or _norm_slug(b.get("title", "")) == slug:
                return b["salecmdtid"]
    except Exception as e:
        print(f"[worker] salecmdtid 조회 실패: {e}")
    return None


def _norm_slug(title: str) -> str:
    """index.html 의 slugify() 와 같은 정규화."""
    import re
    s = re.sub(r"^\[[^\]]+\]\s*", "", title).strip()  # [epub3.0] 접두 제거
    s = re.sub(r"\s+", "_", s)
    return s


def is_cancelling(bridge: str, jid: int) -> bool:
    """job 의 현재 status 가 cancelling/cancelled 인지 확인."""
    try:
        r = _http("GET", f"{bridge}/api/jobs/{jid}", timeout=3.0)
        st = (r.get("job") or {}).get("status")
        return st in ("cancelling", "cancelled")
    except Exception:
        return False


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


# 현재 처리 중인 job — graceful 종료(SIGTERM/Ctrl+C) 시 failed 보고용.
_CURRENT_JID: int | None = None


def run_one(bridge: str, job: dict) -> None:
    global _CURRENT_JID
    jid = job["id"]
    _CURRENT_JID = jid
    slug = job["slug"]
    mode = job.get("mode") or "auto"
    pages = job.get("pages")
    print(f"\n[worker] ╔════════════════════════════════════════════════")
    print(f"[worker] ║ 🚀 job #{jid} 시작")
    print(f"[worker] ║   slug={slug!r}")
    print(f"[worker] ║   mode={mode!r}")
    print(f"[worker] ║   pages={pages!r}")
    print(f"[worker] ║   raw job={job!r}")
    print(f"[worker] ╚════════════════════════════════════════════════")

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
            ["code", "--book-dir", str(book_dir)],
            ["merge", "--book-dir", str(book_dir)],
            ["build", "--book-dir", str(book_dir)],
        ]
    elif mode == "upload-process":
        # Phase #67: 사용자가 업로드한 PNG 들을 처리 — capture 스킵
        # 업로드된 파일은 백엔드가 LIBRARY_BOOKS_DIR/<slug>/ 에 저장.
        # Mac 워커는 OneDrive 안 book-capture/books/<slug>/ 로 처리 — 백엔드 books_dir 와 워커 book_dir 가 다름.
        # 해결: 백엔드 books_dir 의 파일을 워커가 SCP/sync 또는 직접 접근.
        # 가장 단순: 워커가 백엔드 books_dir 에서 직접 처리.
        # 다만 worker 가 NAS books_dir 에 직접 접근 못 함 (다른 머신).
        # 대안: 백엔드 → worker 로 파일 전송 endpoint, 또는 OneDrive 동기화 활용.
        # 가장 빠른 길: 사용자 업로드를 NAS 정적 폴더에 저장하고,
        # worker 가 직접 OCR/요약/HTML 처리 (이미 만들어진 도구 그대로 사용).
        # → 다만 책 폴더가 NAS 안에 있어야 — Mac 워커가 NAS SMB 또는 비슷한 방법으로 접근.
        # 일단 단순화: 백엔드에서 처리 (워커가 백엔드 안에서 실행되거나, 백엔드가 ocr/summarize/merge/build 직접).
        # 현재 워커는 Mac local 이라 직접 처리는 OneDrive 동기화 폴더에서만 가능.
        # → upload-process 는 일단 book-capture/books/<slug>/ 에 미리 파일 있다고 가정.
        steps = [
            ["ocr", "--book-dir", str(book_dir)],
            ["summarize", "--book-dir", str(book_dir)] + (["--pages", pages] if pages else []),
            ["code", "--book-dir", str(book_dir)],
            ["merge", "--book-dir", str(book_dir)],
            ["build", "--book-dir", str(book_dir)],
        ]
    elif mode == "capture-only":
        # 하이브리드(#67): 캡처만 워커가 하고, PNG 를 백엔드로 업로드 →
        # 백엔드가 upload-process 로 OCR/요약/빌드. 원격(Windows) 에 최적.
        # count = 최대 페이지 안전 상한(책 끝에서 같은 화면 감지 시 자동 중단되므로 넉넉히).
        # 300 은 두꺼운 책(500p+)을 다 못 찍어서 1500 으로 상향.
        cap = ["capture-auto", "--slug", slug, "--count", "1500", "--interval", "2"]
        sale_id = job.get("salecmdtid") or _lookup_salecmdtid(bridge, slug)
        if sale_id:
            cap += ["--book-id", sale_id]
        # 시작 페이지(job.pages 가 숫자면) — N>1 이면 그 번호부터 이어서 캡처
        _sp = str(job.get("pages") or "").strip()
        if _sp.isdigit() and int(_sp) > 1:
            cap += ["--start-page", _sp]
        steps = [
            cap,
            ["upload", "--slug", slug, "--title", (job.get("title") or slug)],
        ]
    elif mode == "capture-browser":
        # 🌐 브라우저 웹뷰어 캡처 — 사용자가 wviewer(바로보기)를 브라우저 전체화면으로 띄워두면
        # 데스크탑 앱 없이 포그라운드(브라우저)를 화면캡처 + → 키로 페이지 넘김.
        # 교보 데스크탑 앱 DRM(화면캡처 파란화면)을 우회. (wviewer 웹페이지는 OS 캡처 못 막음)
        print(f"[worker] 🌐 mode=capture-browser — 브라우저 웹뷰어 화면캡처(--no-app)")
        cap = ["capture-auto", "--slug", slug, "--count", "1500", "--interval", "2", "--no-app"]
        _sp = str(job.get("pages") or "").strip()
        if _sp.isdigit() and int(_sp) > 1:
            cap += ["--start-page", _sp]
        steps = [
            cap,
            ["upload", "--slug", slug, "--title", (job.get("title") or slug)],
        ]
    elif mode == "auto-web":
        # Phase #47: e-library 통과 → wviewer 캡처 (화면 점유 X)
        print(f"[worker] 🌐 mode=auto-web 분기 진입")
        salecmdtid = job.get("salecmdtid")
        if salecmdtid:
            print(f"[worker] ✓ job 안에 salecmdtid 있음: {salecmdtid}")
        else:
            print(f"[worker] 📖 job 에 salecmdtid 없음 → books 테이블 조회 (slug={slug})")
            salecmdtid = _lookup_salecmdtid(bridge, slug)
            print(f"[worker] 조회 결과: salecmdtid={salecmdtid!r}")
        if not salecmdtid:
            msg = f"auto-web 모드인데 salecmdtid 없음 (slug={slug}). books 테이블에 등록됐는지 확인."
            print(f"[worker] {msg}")
            report(bridge, jid, status="failed", error=msg)
            return
        steps = [
            ["wviewer", "capture-lib",
             "--salecmdtid", salecmdtid,
             "--slug", slug,
             "--out-dir", str(book_dir),
             "--max-pages", "300", "--delay", "1.5"],
            ["ocr", "--book-dir", str(book_dir)],
            ["summarize", "--book-dir", str(book_dir)] + (["--pages", pages] if pages else []),
            ["code", "--book-dir", str(book_dir)],
            ["merge", "--book-dir", str(book_dir)],
            ["build", "--book-dir", str(book_dir)],
        ]
    else:  # auto = 로컬 매크로 최종 파이프라인 (capture→…→build→챕터→개요→최종화)
        print(f"[worker] 🖥 mode={mode!r} (로컬 매크로 분기) — capture-auto 실행 예정")
        cap = ["capture-auto", "--slug", slug, "--count", "1500", "--interval", "1.5"]
        # salecmdtid 가 있으면 deep link 책 자동 열기 (kyoboebook://book/<id>)
        sale_id = job.get("salecmdtid") or _lookup_salecmdtid(bridge, slug)
        if sale_id:
            print(f"[worker] ✓ salecmdtid={sale_id} → deep link 책 자동 열기 시도")
            cap += ["--book-id", sale_id]
        else:
            print(f"[worker] ⚠ salecmdtid 없음 — 사용자가 책 직접 펼친 상태 가정")
        steps = [
            cap,
            ["ocr", "--book-dir", str(book_dir)],
            ["summarize", "--book-dir", str(book_dir)] + (["--pages", pages] if pages else []),
            ["code", "--book-dir", str(book_dir)],
            ["merge", "--book-dir", str(book_dir)],
            ["build", "--book-dir", str(book_dir)],
            ["chapters-auto", "--book-dir", str(book_dir)],          # 비전 장 표지 감지
            ["overview", "--book-dir", str(book_dir), "--title", (job.get("title") or slug)],
            ["finalize", "--book-dir", str(book_dir)],               # 챕터트리+표 주입
            ["publish", "--book-dir", str(book_dir)],                # NAS 발행(NAS_PASS 있으면)
        ]

    print(f"[worker] 📋 실행할 steps ({len(steps)}개):")
    for idx, s in enumerate(steps, 1):
        print(f"[worker]   {idx}. {' '.join(map(str, s))}")
    stdout_buf: list[str] = []
    n = len(steps)
    last_report_ts = 0.0
    last_cancel_check_ts = 0.0
    REPORT_MIN_INTERVAL = 0.6
    CANCEL_CHECK_INTERVAL = 1.5   # 1.5s 마다 status 체크 (취소 감지)

    for i, args in enumerate(steps, 1):
        step_name = args[0]
        # 단계 사이에 cancel 체크
        if is_cancelling(bridge, jid):
            print(f"[worker] ⏹ cancel 감지 — 종료")
            report(bridge, jid, status="cancelled",
                   progress=progress_payload(i, n, step_name, 0, 0, "사용자가 중단"))
            return

        report(bridge, jid,
               progress=progress_payload(i, n, step_name, 0, 0, "시작..."))
        print(f"\n[worker] [{i}/{n}] {step_name} ...")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "bookcapture", *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",       # 자식이 UTF-8 로 출력(cp949 콘솔 무관)
                errors="replace",
                bufsize=1,
            )
            assert proc.stdout
            sub_current = sub_total = 0
            for line in proc.stdout:
                print(line, end="")
                stdout_buf.append(line)
                if len(stdout_buf) > 200:
                    stdout_buf = stdout_buf[-200:]

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
                # 주기적으로 cancel 체크 → subprocess SIGTERM
                if (now - last_cancel_check_ts) >= CANCEL_CHECK_INTERVAL:
                    last_cancel_check_ts = now
                    if is_cancelling(bridge, jid):
                        print(f"[worker] ⏹ cancel 감지 — subprocess SIGTERM")
                        try: proc.terminate()
                        except Exception: pass
                        try: proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            try: proc.kill()
                            except Exception: pass
                        report(bridge, jid, status="cancelled",
                               progress=progress_payload(i, n, step_name,
                                                         sub_current, sub_total,
                                                         "중단됨"),
                               stdout_tail="".join(stdout_buf[-30:]))
                        return
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


_PING_META: dict | None = None

def _ping_meta() -> dict:
    """첫 호출 시만 계산. hostname/platform 은 변하지 않음."""
    global _PING_META
    if _PING_META is None:
        import socket, platform as _pf
        try:
            hn = socket.gethostname()
        except Exception:
            hn = ''
        s = _pf.system().lower()
        plat = 'mac' if s == 'darwin' else 'windows' if s.startswith('win') else 'linux' if s == 'linux' else s
        _PING_META = {"hostname": hn, "platform": plat, "version": _local_version()}
    return _PING_META


def _app_window_title() -> str:
    """Windows 면 교보 앱 창 제목(열린 책 확인용). 그 외엔 빈 문자열."""
    try:
        import platform as _pf
        if _pf.system() == "Windows":
            from . import win_app
            return win_app.get_app_window_title()
    except Exception:
        pass
    return ""


def _capture_display_meta():
    """macOS: 로컬 매크로 캡처 대상 모니터의 양면 표준 준비상태(compact).
    웹 게이트가 '브라우저 모니터'가 아니라 '실제 캡처 모니터'로 판정하게 실어 보낸다.
    비-mac/실패 시 None. (규칙 엔진: capture_standard.CaptureStandardV1)"""
    try:
        import platform as _pf
        if _pf.system() != "Darwin":
            return None
        from . import mac_displays
        rd = mac_displays.capture_readiness(2)
        plan = rd.get("plan")
        if not plan:
            return None
        app_eval = rd.get("app_eval")
        return {
            "ok": rd["ok"],
            "reason": rd["reason"],
            "app_detected": rd["app_display_id"] is not None,
            "app_meets": (app_eval["meets"] if app_eval else None),
            "app_page_px": (app_eval["page_px"] if app_eval else None),
            "any_meets": plan["any_meets"],
            "chosen": (plan["chosen"]["name"] if plan["chosen"] else None),
            "displays": [
                {"kind": e["kind"], "name": e["name"], "backing": e["backing_width"],
                 "page_px": e["page_px"], "single_page_px": e["single_page_px"],
                 "meets": e["meets"], "is_app": (e["display_id"] == rd["app_display_id"])}
                for e in plan["evaluations"]
            ],
            "advice": (app_eval["advice"] if app_eval and app_eval["advice"] else plan["advice"]),
        }
    except Exception:
        return None


def ping(bridge: str) -> None:
    try:
        body = dict(_ping_meta())
        body["app_title"] = _app_window_title()   # 동적(열린 책에 따라 변함)
        cd = _capture_display_meta()               # macOS 캡처 모니터 준비상태(웹 게이트용)
        if cd is not None:
            body["capture_display"] = cd
        _http("POST", f"{bridge}/api/worker/ping", body=body, timeout=3.0)
    except Exception:
        pass  # silent — heartbeat 실패해도 worker 자체는 계속


def _fail_current_job(bridge: str, reason: str) -> None:
    """종료 신호를 받았을 때, 처리 중이던 job 이 아직 running 이면 failed 로 정리.

    이렇게 안 하면 워커가 죽은 자리에 job 이 'running' 으로 박제돼
    (어제 #51 처럼) 큐가 막힌다. 백엔드 reaper 가 결국 회수하지만,
    graceful 종료 땐 즉시 표시되도록 워커가 먼저 알린다.
    """
    if _CURRENT_JID is None:
        return
    try:
        r = _http("GET", f"{bridge}/api/jobs/{_CURRENT_JID}", timeout=3.0)
        st = (r.get("job") or {}).get("status")
        if st in ("running", "cancelling"):
            report(bridge, _CURRENT_JID, status="failed", error=reason)
            print(f"[worker] ⚠ job #{_CURRENT_JID} → failed ({reason})")
    except Exception as e:
        print(f"[worker] 종료 중 job 정리 실패: {e}")


def _start_caffeinate():
    """job 실행 동안만 macOS 절전(유휴 시스템 슬립)을 막는다.

    어제 #51 좀비의 원인 후보가 Mac 슬립이었다. job 단위로만 켜고
    끝나면 바로 끄므로 평소 전력엔 영향 없다.
      -i 유휴 시스템 슬립 방지 · -m 디스크 슬립 방지 · -s AC 전원 시 슬립 방지
      -w <pid> 워커가 죽으면 caffeinate 도 따라 종료(orphan 방지 안전망)
    macOS 가 아니거나 caffeinate 가 없으면 조용히 무시.
    """
    import os
    import shutil
    caf = shutil.which("caffeinate")
    if not caf:
        return None
    try:
        return subprocess.Popen(
            [caf, "-i", "-m", "-s", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[worker] caffeinate 시작 실패(무시): {e}")
        return None


def _stop_caffeinate(proc) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try: proc.kill()
        except Exception: pass


# ── 자동 업데이트 ────────────────────────────────────────────
_LAST_UPDATE_CHECK = 0.0
_UPDATE_INTERVAL = 300.0   # 5분마다 서버 버전 확인


def _static_base(bridge: str) -> str:
    """정적 사이트(zip·버전 파일) base 를 bridge(api) 로부터 추론."""
    if "192.168.10.205" in bridge:
        return "http://192.168.10.205:8080"
    if "redcodeme" in bridge:
        return "https://redcodeme.synology.me/kyobo"
    return "https://redcodeme.synology.me/kyobo"   # 기본 = 도메인(LAN IP 하드코딩 금지)


def _local_version() -> str:
    try:
        from pathlib import Path as _P
        p = _P(__file__).parent / "_version.txt"
        return p.read_text(encoding="utf-8").strip() if p.exists() else ""
    except Exception:
        return ""


def _maybe_self_update(bridge: str) -> None:
    """서버 버전이 다르면 워커 코드 자동 다운로드·교체 후 재시작.
    재시작은 os._exit → Task Scheduler(Win)/launchd(Mac) KeepAlive 가 되살림.
    job 사이(idle)에서만 호출되므로 진행 중 작업을 끊지 않는다."""
    global _LAST_UPDATE_CHECK
    import os as _os, io as _io, zipfile as _zip
    now = time.monotonic()
    if (now - _LAST_UPDATE_CHECK) < _UPDATE_INTERVAL:
        return
    _LAST_UPDATE_CHECK = now
    lv = _local_version()
    if not lv:
        return  # 버전 파일 없는 구버전 — 다음 수동 설치 때 생성됨
    static = _static_base(bridge)
    try:
        with urllib.request.urlopen(f"{static}/install/worker-version.txt", timeout=8) as r:
            sv = r.read().decode("utf-8").strip()
    except Exception:
        return
    if not sv or sv == lv:
        return
    print(f"[worker] 🔄 새 버전 감지: {lv} → {sv} — 코드 갱신(워커는 계속 실행)")
    try:
        from pathlib import Path as _P
        bc_dir = _P(__file__).parent.parent  # book-capture/
        with urllib.request.urlopen(f"{static}/install/bookcapture.zip?t={sv}", timeout=60) as r:
            data = r.read()
        with _zip.ZipFile(_io.BytesIO(data)) as z:
            z.extractall(str(bc_dir))
        # ⚠️ 워커를 종료하지 않는다. capture-auto/ocr/upload 는 매번 새 subprocess 라
        #    디스크의 새 코드를 즉시 사용. worker.py 자체 변경만 다음 재시작 때 반영.
        #    (os._exit 로 재시작하면 Windows 작업스케줄러가 정상종료=재시작안함 → 워커 죽음)
        print("[worker] ✓ 코드 갱신 완료 — 다음 작업부터 새 코드 적용 (재시작 없음)")
    except Exception as e:
        print(f"[worker] 자동 업데이트 실패(다음 주기 재시도): {e}")


def run_worker(bridge: str | None = None, interval: float = 2.0) -> int:
    global _CURRENT_JID
    bridge = (bridge or DEFAULT_BRIDGE_URL).rstrip("/")
    print(f"[worker] 시작 · bridge={bridge} · {interval}s polling · v={_local_version() or '?'}")
    print(f"[worker] Ctrl+C 로 종료")

    # launchctl 이 보내는 SIGTERM 에도 in-flight job 을 정리하고 나간다.
    import signal

    def _on_term(signum, frame):
        print(f"\n[worker] 종료 신호({signum}) 수신 — 정리 후 종료")
        _fail_current_job(bridge, f"워커 종료(signal {signum})로 중단됨")
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, _on_term)
    except Exception:
        pass  # 일부 환경(비메인 스레드 등)에서는 등록 불가 — 백엔드 reaper 가 커버

    while True:
        try:
            ping(bridge)
            job = claim_one(bridge)
            if job:
                caf = _start_caffeinate()   # job 도는 동안만 절전 차단
                if caf:
                    print(f"[worker] ☕ caffeinate ON (job #{job.get('id')} 동안 슬립 차단)")
                try:
                    run_one(bridge, job)
                finally:
                    _stop_caffeinate(caf)    # 모든 종료 경로에서 해제
                _CURRENT_JID = None   # 정상 종료된 job — 더는 우리 책임 아님
            else:
                _maybe_self_update(bridge)   # idle 일 때만 자동 업데이트 확인
                time.sleep(interval)
        except (KeyboardInterrupt, SystemExit):
            print("\n[worker] 사용자/시스템 종료")
            _fail_current_job(bridge, "워커 종료(Ctrl+C)로 중단됨")
            return 0
        except Exception as e:
            print(f"[worker] loop 오류: {e}")
            time.sleep(interval)
