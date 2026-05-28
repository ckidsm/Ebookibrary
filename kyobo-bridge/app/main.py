"""Kyobo Bridge · FastAPI entrypoint.

Phase B-1: 헬스체크 + skeleton 도서 API + SQLite.
Phase B-2 (다음): /api/auth/kyobo/login (백엔드 프록시) + sync 동작.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .db import count_books, init_db, list_books

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

# LAN 안의 library-web(8080)·외부 도메인에서 호출 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://192.168.10.205:8080",
        "http://192.168.10.205:9000",
        "https://redcodeme.synology.me",
        "http://localhost:8080",
        "http://localhost:8765",  # 로컬 미리보기
    ],
    allow_credentials=True,
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


# ── 도서 카탈로그 (skeleton) ─────────────────────────────────
@app.get("/api/library/books")
def get_books() -> dict:
    return {"books": list_books(), "version": __version__}


# Phase B-2 에서 추가될 라우트 placeholders (지금은 501)
@app.post("/api/auth/kyobo/login", status_code=501)
def kyobo_login() -> dict:
    return {"detail": "not implemented yet (Phase B-2)"}


@app.post("/api/library/sync", status_code=501)
def sync_kyobo_library() -> dict:
    return {"detail": "not implemented yet (Phase B-2)"}
