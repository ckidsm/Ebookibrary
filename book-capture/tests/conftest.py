"""4권 검증 스위트 공용 픽스처·상수 (단일 관리처).

실행:
  book-capture/.venv/bin/pytest tests/ -v              # 전체
  book-capture/.venv/bin/pytest tests/test_merge.py    # 개별
  KYOBO_SKIP_NET=1 ... pytest tests/                   # 네트워크(test_published) 스킵

검증 대상: 이미 캡처·분석·발행된 4권. 로컬 산출물(pages_data/overview/…)을 픽스처로
쓰고, 발행 URL 은 HTTP 로 검증. **재캡처·API 호출·발행본 수정 없음(읽기전용).**
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

# book-capture/ 를 import 경로에 (bookcapture.* 로드)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BOOKS_DIR = ROOT / "books"
PUBLISHED_BASE = "https://redcodeme.synology.me/kyobo/books"

# 검증 대상 4권 — 사용자가 지정한 URL 의 슬러그.
#   min_pages: '교재 하나당 실제 40개 정도' 요구 → 발행 뷰어에 최소 이만큼의 페이지 카드가 있어야 함.
BOOKS = [
    {"slug": "혼자_공부하는_머신러닝plus딥러닝",        "min_pages": 40},
    {"slug": "클로드_코드로_시작하는_실전_에이전틱_코딩", "min_pages": 40},
    {"slug": "이미지_처리_바이블",                    "min_pages": 40},
    {"slug": "밑바닥부터_만들면서_배우는_LLM",          "min_pages": 40},
]

SKIP_NET = os.environ.get("KYOBO_SKIP_NET") == "1"


def summary_dir(slug: str) -> Path:
    return BOOKS_DIR / slug / "summary"


def has_local(slug: str) -> bool:
    return (summary_dir(slug) / "pages_data.json").exists()


# 로컬 산출물이 있는 책만(픽스처 기반 유닛테스트 대상). 클로드코드는 발행본만 있어 네트워크 테스트만 커버.
LOCAL_BOOKS = [b for b in BOOKS if has_local(b["slug"])]


def published_url(slug: str, rel: str = "summary/index.html") -> str:
    return f"{PUBLISHED_BASE}/{urllib.parse.quote(slug)}/{rel}"


@pytest.fixture(scope="session")
def fetch():
    """발행 자원을 HTTP GET → (status, bytes). 세션 캐시로 중복 요청 방지."""
    cache: dict[str, tuple[int, bytes]] = {}

    def _get(url: str) -> tuple[int, bytes]:
        if url in cache:
            return cache[url]
        req = urllib.request.Request(url, headers={"User-Agent": "kyobo-test/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = (r.getcode(), r.read())
        except urllib.error.HTTPError as e:
            res = (e.code, b"")
        cache[url] = res
        return res

    return _get


def param_books(local_only: bool = False):
    """pytest.mark.parametrize 용 — 책 목록을 id 와 함께."""
    src = LOCAL_BOOKS if local_only else BOOKS
    return pytest.mark.parametrize("book", src, ids=[b["slug"] for b in src])
