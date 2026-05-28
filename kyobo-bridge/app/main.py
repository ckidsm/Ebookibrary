"""Kyobo Bridge · FastAPI entrypoint.

Phase B-2: Userscript sync receiver 활성화.
            교보 사이트는 SPA라 백엔드 로그인 프록시 미구현(501) — 향후 cURL 캡처 시 추가.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .db import (
    clear_books, count_books, init_db, list_books, upsert_books,
    get_all_settings, set_all_settings,
)

log = logging.getLogger("kyobo-bridge")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Kyobo Bridge starting · version=%s", __version__)
    init_db()
    log.info("DB ready · books=%d", count_books())
    yield
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
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
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
