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
from .db import clear_books, count_books, init_db, list_books, upsert_books

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
