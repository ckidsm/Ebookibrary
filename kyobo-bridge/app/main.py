"""Kyobo Bridge · FastAPI entrypoint.

Phase B-2: Userscript sync receiver 활성화.
            교보 사이트는 SPA라 백엔드 로그인 프록시 미구현(501) — 향후 cURL 캡처 시 추가.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .db import (
    clear_books, count_books, init_db, list_books, upsert_books,
    get_all_settings, get_setting, set_setting, set_all_settings,
    create_job, list_jobs, get_job, claim_next_job, update_job, cancel_job,
    reap_stale_jobs,
    upsert_worker_client, get_worker_client_by_ip, list_worker_clients,
    car_log_add, car_log_list, car_log_delete,
    admin_log_add, admin_log_list,
    access_log_add, access_log_list,
)

import os
import time as _time
import json as _json
import secrets as _secrets
import ipaddress
from urllib import request as _urlreq, parse as _urlparse
from fastapi import Request
from fastapi.responses import RedirectResponse

# 차량 기록 API 키 (portal '내 차 정보' 보호). 미설정 시 개방.
CAR_API_KEY = os.environ.get("CAR_API_KEY", "")

# ── Synology SSO Server (OIDC) — 관리자 로그인 ──
OIDC_AUTH     = "https://redcodeme.synology.me:5560/webman/sso/SSOOauth.cgi"
OIDC_TOKEN    = "https://redcodeme.synology.me:5560/webman/sso/SSOAccessToken.cgi"
OIDC_USERINFO = "https://redcodeme.synology.me:5560/webman/sso/SSOUserInfo.cgi"
OIDC_REDIRECT = "https://redcodeme.synology.me:9443/api/admin/sso/callback"
ADMIN_PAGE    = "https://redcodeme.synology.me/docs/admin.html"
_admin_sessions: dict = {}   # sid -> {user, exp}
_oidc_states: dict = {}      # state -> exp
# 무차별 대입 방지: IP 별 최근 실패 타임스탬프
_car_fails: dict[str, list[float]] = {}
_CAR_FAIL_WINDOW = 300   # 5분
_CAR_FAIL_MAX = 8        # 5분 내 8회 실패 시 차단


def _is_lan(client_ip: str) -> bool:
    """LAN 내부(또는 docker bridge) IP 만 허용. 외부 노출 차단."""
    try:
        ip = ipaddress.ip_address(client_ip)
        return (
            ip.is_loopback
            or ip.is_private          # 10/8, 172.16/12, 192.168/16
            or ip.is_link_local
        )
    except Exception:
        return False

log = logging.getLogger("kyobo-bridge")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Kyobo Bridge starting · version=%s", __version__)
    init_db()
    log.info("DB ready · books=%d", count_books())
    # 업로드(upload-process) 백엔드 처리기 — 멀티 OS (#67)
    from .upload_processor import start_processor, stop_processor
    start_processor()
    yield
    stop_processor()
    log.info("Kyobo Bridge shutdown")


app = FastAPI(
    title="Kyobo Bridge",
    description="교보문고 e-Library 연동 백엔드 (NAS 9000 포트)",
    version=__version__,
    lifespan=lifespan,
)

# LAN 안의 library-web(8080)·외부 도메인·Userscript(교보 도메인)에서 호출 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://192.168.10.205:8080",
        "http://192.168.10.205:9000",
        "https://redcodeme.synology.me",
        "http://localhost:8080",
        "http://localhost:8765",
        # Userscript 가 교보 도메인에서 fetch 시
        "https://elibrary.kyobobook.co.kr",
        "https://ebook.kyobobook.co.kr",
        "https://mmbr.kyobobook.co.kr",
    ],
    allow_credentials=True,   # 관리자 세션 쿠키 전송 허용
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Car-Key", "Authorization"],
)


# ── 헬스 ─────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "kyobo-bridge",
        "version": __version__,
        "books": count_books(),
    }


# ── 도서 카탈로그 ────────────────────────────────────────────
@app.get("/api/library/books")
def get_books() -> dict:
    return {"books": list_books(), "version": __version__}


# Phase C-4: 분석 완료된 도서(슬러그) 목록 — 정적 라이브러리 폴더 스캔
import os as _os
from pathlib import Path as _Path

@app.get("/api/books/analyzed")
def list_analyzed_books() -> dict:
    """books/<slug>/summary/index.html 이 존재하는 슬러그 반환.
    프론트가 카드 클릭 시 분석 상태 판정에 사용."""
    root = _Path(_os.environ.get("LIBRARY_BOOKS_DIR", "/mnt/library/books"))
    out: list[dict] = []
    if not root.exists():
        return {"analyzed": [], "books_dir": str(root), "exists": False}
    for d in sorted(root.iterdir()):
        if not d.is_dir(): continue
        index = d / "summary" / "index.html"
        if index.exists():
            try:
                pages = 0
                pages_data = d / "summary" / "pages_data.json"
                if pages_data.exists():
                    import json as _j
                    pd = _j.loads(pages_data.read_text(encoding="utf-8"))
                    pages = len(pd.get("pages", []))
            except Exception:
                pages = 0
            out.append({
                "slug": d.name,
                "pages": pages,
                "url": f"books/{d.name}/summary/index.html",
            })
    return {"analyzed": out, "books_dir": str(root), "exists": True}


@app.delete("/api/library/books", status_code=200)
def reset_books() -> dict:
    removed = clear_books()
    log.info("books cleared: %d", removed)
    return {"removed": removed}


# ── sync receiver (Userscript) ───────────────────────────────
class BookItem(BaseModel):
    title: str = Field(..., min_length=1)
    kyobo_id: str | None = None
    author: str | None = None
    publisher: str | None = None
    isbn: str | None = None
    cover_url: str | None = None
    acquired_at: str | None = None
    status: str | None = "available"
    # 그 외 임의 필드는 모델 외에서 받으므로 extra='allow'
    model_config = {"extra": "allow"}


class SyncRequest(BaseModel):
    source: str = Field("kyobo-elibrary", description="동기화 소스 식별")
    books: list[BookItem] = Field(..., description="동기화할 도서 메타 리스트")
    model_config = {"extra": "allow"}


@app.post("/api/library/sync")
def sync_kyobo_library(payload: SyncRequest) -> dict:
    if not payload.books:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="books가 비어 있음",
        )
    # pydantic model → dict (extra 필드 포함)
    items: list[dict[str, Any]] = [b.model_dump() for b in payload.books]
    result = upsert_books(items)
    log.info("sync from %s: %s", payload.source, result)
    return {"ok": True, "source": payload.source, **result, "total": count_books()}


# ── 백엔드 프록시 로그인 (미구현 — SPA 분석 필요) ────────────
class LoginRequest(BaseModel):
    kyobo_id: str
    kyobo_pw: str


# ── Phase C-1: 설정 (캡처·OCR·AI 등) ────────────────────────
DEFAULT_SETTINGS = {
    "capture": {
        # macOS screencapture 좌표 (책 본문 영역) — 0,0,0,0 이면 사용자 미설정
        "region": {"x": 0, "y": 0, "w": 0, "h": 0},
        "delay_sec": 1.5,             # 페이지 넘김 후 대기
        "max_pages": 400,             # 안전 한도
        "next_key": "right",          # AppleScript 키 이름 (right, space, page_down 등)
        "first_page_wait": 3.0,       # 최초 도서 로딩 대기
        "skip_duplicate_hash": True,  # 같은 PNG 해시 N회 연속 시 중단
    },
    "ocr": {
        "lang": "kor+eng",
        "use_thumbs": True,           # 1800px 리사이즈본 사용 (Claude 호환)
    },
    "ai": {
        "provider": "claude",         # claude | openai | none
        "model": "claude-sonnet-4-5", # 사용자 설정 가능
        "api_key": "",                # 사용자가 직접 입력 (UI 마스킹)
        "language": "ko",
        "temperature": 0.3,
    },
    "output": {
        # NAS 측 절대경로 (compose 마운트는 /mnt/data 식으로 추가 가능)
        # 기본은 컨테이너 외부에서 rsync 받을 디렉토리 (Mac 로컬 도구가 사용)
        "books_dir": "./books",
        "thumb_max_px": 1800,
    },
}


@app.get("/api/settings")
def get_settings_endpoint() -> dict:
    saved = get_all_settings()
    # 기본값 + 저장값 머지 (얕은 머지, top-level 키 단위)
    merged = {**DEFAULT_SETTINGS}
    for k, v in saved.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    # api_key 는 응답에서 마스킹 (저장은 그대로)
    if isinstance(merged.get("ai"), dict) and merged["ai"].get("api_key"):
        key = merged["ai"]["api_key"]
        merged["ai"]["api_key_masked"] = (
            key[:7] + "..." + key[-4:] if len(key) > 12 else "***"
        )
        merged["ai"]["api_key"] = ""  # 평문은 응답에 안 내보냄
    return {"settings": merged}


class SettingsUpdate(BaseModel):
    capture: dict | None = None
    ocr: dict | None = None
    ai: dict | None = None
    output: dict | None = None
    model_config = {"extra": "allow"}


@app.put("/api/settings")
def put_settings(payload: SettingsUpdate) -> dict:
    items = {k: v for k, v in payload.model_dump().items() if v is not None}
    # ai.api_key 가 빈 문자열로 오면 기존 값 유지 (마스킹 응답 후 사용자가 안 건드린 경우)
    if "ai" in items and items["ai"].get("api_key") == "":
        prev = get_all_settings().get("ai") or {}
        if prev.get("api_key"):
            items["ai"]["api_key"] = prev["api_key"]
    n = set_all_settings(items)
    return {"ok": True, "updated_keys": n}


# ── Worker heartbeat (Phase C-3 Part3 보강) ─────────────────
_worker_last_seen: dict[str, float] = {}  # ip → timestamp

class WorkerPing(BaseModel):
    hostname: str | None = None
    platform: str | None = None  # "mac" | "windows" | "linux"
    version: str | None = None   # 워커 코드 버전(_version.txt)
    app_title: str | None = None # 교보 앱 창 제목(열린 책 확인용)


_last_worker_version: str | None = None  # 최근 ping 한 워커의 버전
_last_app_title: str | None = None       # 최근 ping 한 워커가 본 교보 창 제목


def _read_server_version() -> str:
    """배포된 워커 최신 버전(install/worker-version.txt). 컨테이너의 ro 마운트에서 읽음."""
    for p in ("/mnt/library/install/worker-version.txt",):
        try:
            with open(p, encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


@app.post("/api/worker/ping")
def worker_ping(request: Request, body: WorkerPing | None = None) -> dict:
    """worker 가 polling 마다 호출. hostname/platform 도 받아 worker_clients 에 영구 기록."""
    client = request.client.host if request.client else "unknown"
    if not _is_lan(client):
        raise HTTPException(403, "LAN 전용")
    import time as _t
    global _last_worker_version, _last_app_title
    _worker_last_seen[client] = _t.time()
    hostname = (body.hostname if body else None) or ''
    platform = body.platform if body else None
    if body and body.version:
        _last_worker_version = body.version
    if body is not None:
        _last_app_title = body.app_title or ""   # 매 ping 갱신(책 바뀌면 반영)
    upsert_worker_client(client, hostname=hostname, platform=platform)
    return {"ok": True, "client": client}


@app.get("/api/worker/status")
def worker_status(request: Request) -> dict:
    """alive 여부 + (요청자 IP 와 매칭되는) 전에 본 워커 정보."""
    import time as _t
    now = _t.time()
    alive = False
    last_ip = None
    last_ago = None
    for ip, ts in _worker_last_seen.items():
        ago = now - ts
        if ago < 30:
            alive = True
            if last_ago is None or ago < last_ago:
                last_ago = ago; last_ip = ip

    # 요청자 IP 로 워커 등록 이력 매칭 — 같은 LAN/NAT 출구 IP 의 사용자에게
    # "전에 본 워커가 있다" 안내 가능. 외부 사용자도 OK (자기 hostname 의 워커만 매칭).
    requester_ip = request.client.host if request.client else None
    known = None
    if requester_ip:
        row = get_worker_client_by_ip(requester_ip)
        if row:
            # last_seen → 몇 분 전인지 계산
            from datetime import datetime as _dt
            try:
                ls = _dt.strptime(row['last_seen'], '%Y-%m-%d %H:%M:%S')
                ago_sec = (_dt.utcnow() - ls).total_seconds()
            except Exception:
                ago_sec = None
            known = {
                "hostname": row['hostname'] or None,
                "platform": row['platform'],
                "ping_count": row['ping_count'],
                "last_seen_ago_sec": round(ago_sec, 1) if ago_sec is not None else None,
            }
    server_ver = _read_server_version()
    wv = _last_worker_version
    return {
        "alive": alive,
        "worker_ip": last_ip,
        "last_ping_ago_sec": round(last_ago, 1) if last_ago is not None else None,
        "previously_seen": bool(known),
        "known": known,
        "worker_version": wv,
        "server_version": server_ver or None,
        "up_to_date": bool(wv and server_ver and wv == server_ver),
        "app_title": _last_app_title or None,
    }


# ── Phase C-3 Part3: 분석 작업 큐 ───────────────────────────
class JobCreate(BaseModel):
    slug: str
    title: str | None = None
    mode: str = "auto"          # auto | auto-web | capture-only | summarize-only
    pages: str | None = None    # "127-155"
    salecmdtid: str | None = None  # auto-web 모드에서 worker 가 사용

class JobPatch(BaseModel):
    status: str | None = None
    progress: str | None = None
    stdout_tail: str | None = None
    error: str | None = None


# ── 파일 업로드 (#67 Phase) ─────────────────────────
@app.post("/api/books/{slug}/upload")
async def upload_book_pages(
    slug: str,
    files: list[UploadFile] = File(...),
    title: str | None = Form(default=None),
) -> dict:
    """사용자가 본인 OS 도구로 캡처한 PNG/JPG 다수 업로드.
    저장 위치: <LIBRARY_BOOKS_DIR>/<slug>/page_NNN.png
    저장 후 mode='upload-process' job 자동 등록 → worker 가 OCR + AI 요약 + HTML.
    """
    import os as _os
    import shutil as _sh
    from pathlib import Path as _Path

    if not slug.strip():
        raise HTTPException(400, "slug 필수")
    if not files:
        raise HTTPException(400, "files 필수")

    root = _Path(_os.environ.get("LIBRARY_BOOKS_DIR", "/mnt/library/books"))
    # 컨테이너 안에서 ro 마운트일 수 있어 별도 쓰기 경로 시도
    write_root = _Path(_os.environ.get("LIBRARY_BOOKS_WRITE_DIR", str(root)))
    book_dir = write_root / slug.strip()
    book_dir.mkdir(parents=True, exist_ok=True)

    # 새 분석 = 깨끗이 새로: 기존 page 이미지·썸네일·요약 산출물 제거(잔여 페이지 섞임 방지).
    # (업로드는 책 1권 전체 캡처를 통째로 올리는 것이므로 항상 새로 시작)
    cleared = 0
    for _ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for _p in book_dir.glob(_ext):
            try: _p.unlink(); cleared += 1
            except Exception: pass
    for _sub in ("thumbs", "summary"):
        _d = book_dir / _sub
        if _d.exists():
            try: _sh.rmtree(_d)
            except Exception: pass
    log.info("📤 업로드 전 정리: slug=%s 기존 %d장 + thumbs/summary 삭제", slug, cleared)

    # 정렬 — 사용자가 보낸 순서 보존, 단 파일명에서 숫자 추출해 정렬 시도
    import re as _re
    def _natural_key(f: UploadFile):
        name = f.filename or ""
        m = _re.search(r'(\d+)', name)
        return (int(m.group(1)) if m else 999999, name)
    sorted_files = sorted(files, key=_natural_key)

    saved = []
    for i, up in enumerate(sorted_files, 1):
        # 이미지 형식 검사
        ctype = (up.content_type or "").lower()
        if not (ctype.startswith("image/") or (up.filename or "").lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))):
            continue
        # 저장 확장자 — 원본 유지
        ext = ".png"
        if (up.filename or "").lower().endswith((".jpg", ".jpeg")): ext = ".jpg"
        elif (up.filename or "").lower().endswith(".webp"): ext = ".webp"
        dst = book_dir / f"page_{i:03d}{ext}"
        with dst.open("wb") as fp:
            _sh.copyfileobj(up.file, fp)
        saved.append({"index": i, "name": dst.name, "size": dst.stat().st_size, "orig": up.filename})

    log.info("📤 업로드 완료: slug=%s files=%d dir=%s", slug, len(saved), book_dir)

    # 자동으로 job 등록 (mode=upload-process: capture 스킵, ocr부터)
    job = create_job(slug=slug.strip(), title=title, mode="upload-process", pages=None)
    log.info("✓ upload-process job 생성: #%s", job["id"])

    return {
        "ok": True,
        "slug": slug,
        "uploaded": len(saved),
        "files": saved,
        "book_dir": str(book_dir),
        "job": job,
    }


@app.post("/api/books/{slug}/upload-video")
async def upload_book_video(
    slug: str,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    fps: float = Form(default=1.5),
    diff: int = Form(default=8),
) -> dict:
    """화면녹화 영상 1개 업로드 → ffmpeg 로 페이지 프레임 추출 → upload-process job.
    iPad/모바일: 교보 책 넘기며 화면녹화 → 이 영상만 올리면 서버가 페이지별로 잘라 OCR."""
    import os as _os, shutil as _sh, tempfile as _tf
    from pathlib import Path as _Path
    from .video_frames import extract_pages, has_ffmpeg

    if not slug.strip():
        raise HTTPException(400, "slug 필수")
    if not has_ffmpeg():
        raise HTTPException(503, "서버에 ffmpeg 미설치 — 이미지 업로드를 사용하세요")

    root = _Path(_os.environ.get("LIBRARY_BOOKS_DIR", "/mnt/library/books"))
    write_root = _Path(_os.environ.get("LIBRARY_BOOKS_WRITE_DIR", str(root)))
    book_dir = write_root / slug.strip()
    book_dir.mkdir(parents=True, exist_ok=True)

    # 새 분석 = 기존 산출물 정리(이미지 업로드와 동일)
    cleared = 0
    for _ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for _p in book_dir.glob(_ext):
            try: _p.unlink(); cleared += 1
            except Exception: pass
    for _sub in ("thumbs", "summary"):
        _d = book_dir / _sub
        if _d.exists():
            try: _sh.rmtree(_d)
            except Exception: pass

    # 영상 임시 저장 (스트리밍)
    suffix = _os.path.splitext(file.filename or "")[1].lower() or ".mov"
    tmp = _tf.NamedTemporaryFile(prefix="kyovid_", suffix=suffix, delete=False)
    tmp_path = tmp.name
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk: break
            tmp.write(chunk)
        tmp.close()
        sz = _os.path.getsize(tmp_path)
        log.info("📹 영상 업로드: slug=%s size=%.1fMB", slug, sz / 1e6)
        # 프레임 추출 (블로킹 — threadpool 에서)
        import asyncio as _asyncio
        res = await _asyncio.get_event_loop().run_in_executor(
            None, lambda: extract_pages(tmp_path, book_dir, fps=fps, diff_thresh=diff))
    finally:
        try: _os.unlink(tmp_path)
        except Exception: pass

    if not res.get("ok"):
        raise HTTPException(500, "프레임 추출 실패: " + str(res.get("error")))
    pages = res.get("pages", 0)
    if pages < 1:
        raise HTTPException(422, "추출된 페이지가 없습니다 (영상이 너무 짧거나 페이지 변화 미감지)")

    log.info("📹 영상→페이지 %d장 추출 완료: slug=%s", pages, slug)
    job = create_job(slug=slug.strip(), title=title, mode="upload-process", pages=None)
    return {
        "ok": True, "slug": slug, "pages": pages,
        "frames_raw": res.get("frames_raw"), "book_dir": str(book_dir), "job": job,
    }


def _parse_ua(ua: str) -> tuple[str, str]:
    """User-Agent → (os, browser) 대략 판별 (외부 의존성 없음)."""
    import re as _re
    u = ua or ""
    if "Windows NT 10" in u or "Windows NT 11" in u:
        os_ = "Windows 10/11"
    elif "Windows NT" in u:
        os_ = "Windows"
    elif "Mac OS X" in u or "Macintosh" in u:
        m = _re.search(r"Mac OS X (\d+[_.]\d+)", u)
        os_ = "macOS " + (m.group(1).replace("_", ".") if m else "")
    elif "iPhone" in u or "iPad" in u:
        os_ = "iOS/iPadOS"
    elif "Android" in u:
        os_ = "Android"
    elif "Linux" in u:
        os_ = "Linux"
    else:
        os_ = "unknown"
    if "Edg/" in u:
        br = "Edge"
    elif "OPR/" in u or "Opera" in u:
        br = "Opera"
    elif "Chrome/" in u and "Chromium" not in u:
        br = "Chrome"
    elif "Firefox/" in u:
        br = "Firefox"
    elif "Safari/" in u and "Chrome" not in u:
        br = "Safari"
    else:
        br = "unknown"
    return os_, br


def _best_effort_mac(ip: str) -> str | None:
    """LAN IP 면 컨테이너 ARP 테이블에서 MAC 조회 시도.

    Docker bridge 라 클라이언트가 게이트웨이 IP 로 보이면 못 잡는다 → None.
    그래도 host-net/일부 경로에서 잡힐 수 있어 best-effort 로 시도.
    """
    import re as _re
    if not ip or not _re.match(r"^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)", ip):
        return None
    try:
        with open("/proc/net/arp") as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if len(p) >= 4 and p[0] == ip and p[3] != "00:00:00:00:00:00":
                    return p[3]
    except Exception:
        pass
    return None


def _client_info(request: Request) -> dict:
    """분석을 시작한 웹 클라이언트의 접속 정보 수집."""
    h = request.headers
    xff = h.get("x-forwarded-for", "")
    peer = request.client.host if request.client else ""
    real_ip = (xff.split(",")[0].strip() if xff else "") or h.get("x-real-ip", "") or peer
    ua = h.get("user-agent", "")
    os_, br = _parse_ua(ua)
    return {
        "ip": real_ip,                 # 추정 실제 클라이언트 IP (XFF 우선)
        "peer_ip": peer,               # 직접 소켓 상대 (Docker 면 게이트웨이일 수 있음)
        "x_forwarded_for": xff,
        "os": os_,
        "browser": br,
        "lang": h.get("accept-language", "").split(",")[0],
        "mac": _best_effort_mac(real_ip),   # 대개 None (HTTP 로는 MAC 수집 불가)
        "user_agent": ua[:300],
    }


@app.post("/api/jobs", status_code=status.HTTP_201_CREATED)
def post_job(payload: JobCreate, request: Request) -> dict:
    import json as _j
    ci = _client_info(request)
    log.info("🆕 POST /api/jobs slug=%r mode=%r ▸ 접속: os=%s browser=%s ip=%s peer=%s mac=%s lang=%s",
             payload.slug, payload.mode, ci["os"], ci["browser"],
             ci["ip"], ci["peer_ip"], ci["mac"], ci["lang"])
    log.info("   └ UA=%r", ci["user_agent"])
    if not payload.slug.strip():
        log.warning("✗ POST /api/jobs 400 — slug 빈 값")
        raise HTTPException(400, "slug 필수")
    job = create_job(
        slug=payload.slug.strip(),
        title=payload.title,
        mode=payload.mode,
        pages=payload.pages,
        client_info=_j.dumps(ci, ensure_ascii=False),
    )
    log.info("✓ job 생성: #%s slug=%s mode=%s status=%s ▸ 시작 OS=%s/%s",
             job["id"], job["slug"], job["mode"], job["status"], ci["os"], ci["browser"])
    return {"job": job}


@app.get("/api/jobs")
def get_jobs(status_: str | None = None, limit: int = 50) -> dict:
    # FastAPI 가 ?status= 으로 받기 위해 query 파라미터 이름 매핑
    # 좀비(heartbeat 끊긴 running) 회수 — UI 가 살아있는 잡으로 오인하지 않도록
    for j in reap_stale_jobs():
        log.warning("☠ stale job #%s 자동 failed (heartbeat 끊김) slug=%s", j["id"], j.get("slug"))
    return {"jobs": list_jobs(status=status_, limit=limit)}


@app.get("/api/jobs/{jid}")
def get_one_job(jid: int) -> dict:
    job = get_job(jid)
    if not job:
        raise HTTPException(404, f"job #{jid} 없음")
    return {"job": job}


@app.post("/api/jobs/next/claim")
def claim_next(request: Request) -> dict:
    """worker 가 다음 pending 작업을 잡는다. LAN 전용."""
    client = request.client.host if request.client else ""
    if not _is_lan(client):
        raise HTTPException(403, f"LAN 전용 (요청 IP: {client})")
    # 워커가 2s 마다 호출 → 좀비 회수의 주 트리거. claim 전에 정리해서
    # 죽은 잡이 큐를 막거나 같은 책 중복 running 으로 남지 않게 한다.
    for j in reap_stale_jobs():
        log.warning("☠ stale job #%s 자동 failed (heartbeat 끊김) slug=%s", j["id"], j.get("slug"))
    job = claim_next_job()
    if not job:
        return {"job": None}
    log.info("👷 job claimed: #%s slug=%s mode=%s by %s",
             job["id"], job["slug"], job.get("mode"), client)
    return {"job": job}


@app.patch("/api/jobs/{jid}")
def patch_job(jid: int, payload: JobPatch, request: Request) -> dict:
    client = request.client.host if request.client else ""
    if not _is_lan(client):
        raise HTTPException(403, "LAN 전용")
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    job = update_job(jid, **fields)
    if not job:
        raise HTTPException(404, f"job #{jid} 없음")
    # progress·status 변경 시 로그 (verbose)
    log_msg = f"📊 job #{jid} update"
    if "status" in fields: log_msg += f" status={fields['status']}"
    if "error" in fields: log_msg += f" error={fields['error'][:100]!r}"
    if "progress" in fields:
        prog = fields["progress"]
        try:
            import json as _j
            pg = _j.loads(prog) if isinstance(prog, str) else prog
            log_msg += f" progress[{pg.get('stage_name')}]={pg.get('pct')}% {pg.get('msg','')[:60]}"
        except Exception:
            log_msg += f" progress={str(prog)[:80]}"
    log.info(log_msg)
    return {"job": job}


@app.delete("/api/jobs/{jid}")
def delete_job(jid: int) -> dict:
    """pending 작업만 취소. running 은 worker 가 자체 처리."""
    job = cancel_job(jid)
    if not job:
        raise HTTPException(404, f"job #{jid} 없음")
    return {"job": job}


# ── Phase C-3: LAN 전용 시크릿 (book-capture worker 용) ──────
@app.get("/api/secrets/ai")
def get_ai_secret(request: Request) -> dict:
    """평문 API 키 반환 — LAN 내부 IP 만 허용. 외부에서 호출 시 403."""
    client = request.client.host if request.client else ""
    if not _is_lan(client):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"LAN 전용 endpoint (요청 IP: {client})",
        )
    ai = get_setting("ai", {}) or {}
    return {
        "provider": ai.get("provider", "claude"),
        "model": ai.get("model", "claude-sonnet-4-5"),
        "api_key": ai.get("api_key", ""),
        "language": ai.get("language", "ko"),
        "temperature": ai.get("temperature", 0.3),
    }


@app.post(
    "/api/auth/kyobo/login",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
def kyobo_login(_: LoginRequest) -> dict:
    return {
        "detail": (
            "교보 사이트가 SPA 라 HTML 정적 분석으로는 로그인 endpoint를 알 수 없습니다. "
            "Userscript(추천) 또는 사용자가 본인 브라우저 devtools에서 실제 로그인 XHR을 "
            "Copy as cURL 하여 보내주시면 그때 백엔드 프록시를 활성화합니다."
        ),
        "alternative": "POST /api/library/sync (Userscript 사용 권장)",
    }


# ── 차량 정비/주행 기록 (portal '내 차 정보') ────────────────
class CarLogIn(BaseModel):
    category: str                       # odometer | oil_change | consumable
    event_date: str | None = None       # YYYY-MM-DD
    odo_km: int | None = None
    item: str | None = None
    value: str | None = None


def _real_ip(request: Request) -> str:
    """실제 클라이언트 IP — 리버스프록시 X-Forwarded-For 우선(도커 게이트웨이 172.x 대신)."""
    h = request.headers
    xff = h.get("x-forwarded-for", "")
    peer = request.client.host if request.client else ""
    return (xff.split(",")[0].strip() if xff else "") or h.get("x-real-ip", "") or peer


def _check_car_key(request: Request) -> None:
    """env CAR_API_KEY 또는 DB settings('car_api_key') 와 X-Car-Key 헤더 비교.
    무차별 대입 방지(IP별 rate-limit) 포함. 둘 다 없으면 개방."""
    ip = request.client.host if request.client else "?"   # rate-limit 키(peer, 스푸핑 불가)
    rip = _real_ip(request)                                # 로그용 실제 IP
    now = _time.time()
    fails = [t for t in _car_fails.get(ip, []) if now - t < _CAR_FAIL_WINDOW]
    _car_fails[ip] = fails
    if len(fails) >= _CAR_FAIL_MAX:
        admin_log_add("", "car_blocked", f"rate-limit {len(fails)}회", rip)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="too many attempts — 잠시 후 다시 시도")
    expected = CAR_API_KEY or (get_setting("car_api_key", "") or "")
    if expected and request.headers.get("X-Car-Key") != expected:
        fails.append(now)
        _car_fails[ip] = fails
        log.warning("car API 인증 실패 ip=%s (%d/%d)", rip, len(fails), _CAR_FAIL_MAX)
        admin_log_add("", "car_auth_fail", f"{len(fails)}/{_CAR_FAIL_MAX}", rip)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid car key")


@app.get("/api/car/profile")
def car_profile_get(request: Request) -> dict:
    _check_car_key(request)
    admin_log_add("", "car_view", "내 차 정보 조회", _real_ip(request))
    return {"profile": get_setting("car_profile", {})}


@app.post("/api/car/profile")
def car_profile_set(payload: dict, request: Request) -> dict:
    _check_car_key(request)
    set_setting("car_profile", payload)
    return {"ok": True}


@app.get("/api/car/log")
def car_log_get(request: Request, category: str | None = None) -> dict:
    _check_car_key(request)
    return {"records": car_log_list(category)}


@app.post("/api/car/log", status_code=status.HTTP_201_CREATED)
def car_log_post(payload: CarLogIn, request: Request) -> dict:
    _check_car_key(request)
    if not payload.category:
        raise HTTPException(status_code=400, detail="category 필수")
    rec = car_log_add(payload.category, payload.event_date, payload.odo_km,
                      payload.item, payload.value)
    return {"record": rec}


@app.delete("/api/car/log/{rec_id}")
def car_log_del(rec_id: int, request: Request) -> dict:
    _check_car_key(request)
    return {"deleted": car_log_delete(rec_id)}


# ── 관리자: Synology SSO(OIDC) 로그인 + 관리 기능 ────────────
def _read_secret(fname: str, env_key: str) -> str:
    """민감 비밀은 DB가 아닌 env 또는 /data 의 별도 파일에서 읽음 (DB 분리 저장)."""
    v = os.environ.get(env_key, "")
    if v:
        return v.strip()
    try:
        p = os.path.join(os.path.dirname(os.environ.get("KYOBO_BRIDGE_DB", "/data/library.db")), fname)
        if os.path.exists(p):
            return open(p, encoding="utf-8").read().strip()
    except Exception:
        pass
    return ""


def _oidc_cfg():
    cid = (os.environ.get("OIDC_CLIENT_ID", "") or get_setting("oidc_client_id", "") or "").strip()
    # client_secret: env > /data/oidc_client_secret 파일 > (폴백) DB
    csec = _read_secret("oidc_client_secret", "OIDC_CLIENT_SECRET") or (get_setting("oidc_client_secret", "") or "")
    admins = get_setting("admin_users", []) or []
    return cid, csec, admins

def _gc(d: dict) -> None:
    now = _time.time()
    for k in [k for k, v in list(d.items())
              if (v.get("exp", 0) if isinstance(v, dict) else v) < now]:
        d.pop(k, None)

def _admin_user(request: Request):
    _gc(_admin_sessions)
    s = _admin_sessions.get(request.cookies.get("admin_session", ""))
    return s["user"] if s else None

def _require_admin(request: Request) -> str:
    u = _admin_user(request)
    if not u:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="관리자 로그인 필요")
    return u


@app.get("/api/admin/sso/login")
def admin_sso_login() -> RedirectResponse:
    cid, _, _ = _oidc_cfg()
    if not cid:
        raise HTTPException(500, "OIDC client_id 미설정")
    state = _secrets.token_urlsafe(16)
    _oidc_states[state] = _time.time() + 600
    qs = _urlparse.urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": OIDC_REDIRECT,
        "scope": "openid email groups", "state": state,
    })
    return RedirectResponse(OIDC_AUTH + "?" + qs, status_code=302)


@app.get("/api/admin/sso/callback")
def admin_sso_callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    _gc(_oidc_states)
    if not state or state not in _oidc_states:
        raise HTTPException(400, "invalid state")
    _oidc_states.pop(state, None)
    cid, csec, admins = _oidc_cfg()
    # 1) code → access_token
    body = _urlparse.urlencode({
        "grant_type": "authorization_code", "code": code, "redirect_uri": OIDC_REDIRECT,
        "client_id": cid, "client_secret": csec,
    }).encode()
    try:
        tok = _json.loads(_urlreq.urlopen(
            _urlreq.Request(OIDC_TOKEN, data=body,
                            headers={"Content-Type": "application/x-www-form-urlencoded"}),
            timeout=15).read())
    except Exception as e:
        raise HTTPException(403, f"token 교환 실패: {e}")
    at = tok.get("access_token")
    if not at:
        raise HTTPException(403, "access_token 없음")
    # 2) userinfo
    try:
        info = _json.loads(_urlreq.urlopen(
            _urlreq.Request(OIDC_USERINFO, headers={"Authorization": "Bearer " + at}),
            timeout=15).read())
    except Exception as e:
        raise HTTPException(403, f"userinfo 실패: {e}")
    user = info.get("username") or info.get("preferred_username") or info.get("email") or info.get("sub") or ""
    if admins and user not in admins and info.get("email") not in admins:
        raise HTTPException(403, f"허용되지 않은 계정입니다: {user}")
    # 3) 세션 발급
    sid = _secrets.token_urlsafe(24)
    _admin_sessions[sid] = {"user": user, "exp": _time.time() + 3600 * 8}
    log.info("admin 로그인: %s", user)
    admin_log_add(user, "login", "관리자 로그인", _real_ip(request))
    resp = RedirectResponse(ADMIN_PAGE, status_code=302)
    resp.set_cookie("admin_session", sid, httponly=True, secure=True,
                    samesite="lax", max_age=3600 * 8, path="/")
    return resp


@app.get("/api/admin/me")
def admin_me(request: Request) -> dict:
    return {"user": _require_admin(request)}


@app.post("/api/admin/logout")
def admin_logout(request: Request) -> dict:
    u = _admin_user(request)
    _admin_sessions.pop(request.cookies.get("admin_session", ""), None)
    if u:
        admin_log_add(u, "logout", "", _real_ip(request))
    return {"ok": True}


@app.get("/api/admin/log")
def admin_log_get(request: Request, limit: int = 100) -> dict:
    _require_admin(request)
    return {"events": admin_log_list(min(max(limit, 1), 500))}


@app.get("/api/admin/access-log")
def admin_access_log(request: Request, limit: int = 200) -> dict:
    _require_admin(request)
    return {"events": access_log_list(min(max(limit, 1), 1000))}


@app.post("/api/admin/exec")
def admin_exec(payload: dict, request: Request) -> dict:
    """읽기 전용 진단 콘솔 — 허용목록(고정 ID)만 실행. 자유 명령/호스트 제어 불가."""
    _require_admin(request)
    import subprocess
    cmd = (payload.get("cmd") or "").strip()

    def sh(args):
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=8).stdout.strip()
        except Exception as e:
            return f"(실행 오류: {e})"

    if cmd == "health":
        out = f"service = kyobo-bridge\nversion = {__version__}\nbooks   = {count_books()}"
    elif cmd == "date":
        try:
            up = open("/proc/uptime").read().split()[0]
            up = f"{float(up)/3600:.1f} 시간"
        except Exception:
            up = "?"
        out = sh(["date", "+%Y-%m-%d %H:%M:%S %Z"]) + f"\n컨테이너 가동: {up}"
    elif cmd == "disk":
        out = sh(["df", "-h", "/data", "/"])
    elif cmd == "mem":
        try:
            out = "\n".join(open("/proc/meminfo").read().splitlines()[:4])
        except Exception as e:
            out = str(e)
    elif cmd == "dbstat":
        out = (f"books       {count_books()}\n"
               f"access_log  {len(access_log_list(100000))}\n"
               f"admin_log   {len(admin_log_list(100000))}\n"
               f"car_log     {len(car_log_list(None, 100000))}")
    elif cmd == "recent":
        rows = access_log_list(12)
        out = "\n".join(f"{r['ts']}  {(r['ip'] or ''):<15} {(r['device'] or ''):<4} "
                        f"{(r['os'] or ''):<12} {r['page']}" for r in rows) or "(없음)"
    elif cmd == "events":
        rows = admin_log_list(12)
        out = "\n".join(f"{r['ts']}  {(r['action'] or ''):<14} {(r.get('user') or '-'):<10} "
                        f"{(r.get('ip') or '')} {(r.get('detail') or '')}" for r in rows) or "(없음)"
    elif cmd == "code":
        out = "현재 인증번호: " + (get_setting("car_api_key", "") or "(미설정)")
    elif cmd == "env":
        sec = os.environ.get("OIDC_CLIENT_SECRET") or _read_secret("oidc_client_secret", "OIDC_CLIENT_SECRET")
        out = (f"TZ = {os.environ.get('TZ')}\nDB = {os.environ.get('KYOBO_BRIDGE_DB')}\n"
               f"OIDC client_id = {(get_setting('oidc_client_id','') or '')[:8]}…\n"
               f"OIDC secret 설정됨 = {'예' if sec else '아니오'}\n"
               f"admin_users = {get_setting('admin_users', [])}")
    else:
        raise HTTPException(400, "허용되지 않은 명령입니다 (읽기 전용 진단만 가능)")

    admin_log_add(_admin_user(request), "exec", cmd, _real_ip(request))
    return {"cmd": cmd, "out": out}


class TrackIn(BaseModel):
    page: str = ""


@app.post("/api/track")
def track(payload: TrackIn, request: Request) -> dict:
    """모든 포털 페이지가 로드 시 호출하는 접속 비콘 (공개)."""
    ci = _client_info(request)
    ua = ci.get("user_agent", "")
    device = "모바일" if any(x in ua for x in ("iPhone", "iPad", "Android", "Mobile")) else "PC"
    access_log_add(ci["ip"], payload.page, ci["os"], ci["browser"], device,
                   ci.get("mac"), _is_lan(ci["ip"]), ua)
    return {"ok": True}


@app.get("/api/admin/car-code")
def admin_get_code(request: Request) -> dict:
    _require_admin(request)
    return {"code": get_setting("car_api_key", "")}


@app.post("/api/admin/car-code")
def admin_set_code(payload: dict, request: Request) -> dict:
    _require_admin(request)
    code = (payload.get("code") or "").strip()
    if len(code) < 4:
        raise HTTPException(400, "코드는 4자 이상이어야 합니다")
    set_setting("car_api_key", code)
    u = _admin_user(request)
    log.info("car 접근코드 변경 by %s", u)
    admin_log_add(u, "code_change", "인증번호 변경", _real_ip(request))
    return {"ok": True, "code": code}
