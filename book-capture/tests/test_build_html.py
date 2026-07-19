"""build_html.py 단위 테스트 — 페이지카드·사이드바·책개요 렌더 + 실제 4권 산출물 라운드트립.

순수 렌더 함수 + tmp 빌드만 사용. **발행본 index.html 은 절대 안 건드림**(tmp 로만 빌드).
"""
import json
from pathlib import Path

import pytest

from bookcapture.build_html import (
    _build_page_card, _build_sidebar, _build_overview, build_html,
)
from conftest import LOCAL_BOOKS, summary_dir, param_books


# ── _build_page_card ────────────────────────────────────────
def test_page_card_renders_fields_and_escapes():
    page = {
        "num": 42,
        "topics": ["신경망", "<b>주입</b>"],
        "terms": ["텐서"],
        "summary": "요약 본문",
        "points": ["핵심1", "핵심2"],
    }
    html = _build_page_card(page, prev_num=41, next_num=43, image_pattern="../thumbs/page_{num:03d}.png")
    assert 'id="page-42"' in html
    assert 'src="../thumbs/page_042.png"' in html
    assert "신경망" in html and "텐서" in html and "요약 본문" in html
    assert "<li>핵심1</li>" in html
    assert "#page-41" in html and "#page-43" in html      # 이전/다음 네비
    # topics 는 escape 되어야(주입 방지)
    assert "&lt;b&gt;주입&lt;/b&gt;" in html


def test_page_card_first_page_has_no_prev():
    html = _build_page_card({"num": 1, "summary": ""}, prev_num=None, next_num=2, image_pattern="p{num:03d}")
    assert "이전" not in html
    assert "다음" in html


# ── _build_sidebar ──────────────────────────────────────────
def test_sidebar_lists_chapters():
    chapters = [
        {"title": "1장 시작", "id": "chs-chapter-1", "intro_page": {"num": 1, "label": "1장"},
         "sections": [{"title": "1.1 개요", "pages": [{"num": 2, "label": "1.1"}]}]},
        {"title": "2장 심화", "id": "chs-chapter-2", "intro_page": {"num": 10, "label": "2장"},
         "sections": []},
    ]
    html = _build_sidebar(chapters)
    assert html.count("tree-chapter-title") == 2
    assert "1장 시작" in html and "2장 심화" in html
    assert "#page-2" in html                # 섹션 페이지 링크


# ── _build_overview ─────────────────────────────────────────
def test_overview_none_returns_empty():
    assert _build_overview(None) == ""
    assert _build_overview({}) == ""


def test_overview_renders_digests_and_topics():
    ov = {
        "target_reader": "입문자",
        "overview": "이 책은 ...",
        "key_topics": ["머신러닝", "딥러닝"],
        "key_terms": [{"term": "KNN", "desc": "최근접이웃"}],
        "must_read_pages": [{"page": 31, "why": " KNN 예제"}],
        "chapter_digests": [
            {"title": "1장 첫 머신러닝", "start": 14, "end": 33, "body": "KNN 으로 ..."},
        ],
    }
    html = _build_overview(ov)
    assert "📋 책 개요" in html
    assert "머신러닝" in html and "KNN" in html
    assert 'class="cd-item"' in html
    assert "#page-31" in html and "#page-14" in html


# ── build_html 라운드트립(합성) ──────────────────────────────
def test_build_html_writes_index_with_all_pages(tmp_path: Path):
    book_dir = tmp_path / "책"
    (book_dir / "summary").mkdir(parents=True)
    pages = [{"num": n, "summary": f"p{n}", "topics": [], "terms": [], "points": []} for n in range(1, 6)]
    pages_data = {"chapters": [{"title": "전체", "id": "", "intro_page": None,
                                "sections": [{"title": "기타", "pages": [{"num": n, "label": ""} for n in range(1, 6)]}]}],
                  "pages": pages}
    ov = {"overview": "개요", "chapter_digests": [{"title": "1장", "start": 1, "end": 5, "body": "본문"}]}
    out = build_html(book_dir, pages_data, title="테스트책", overview=ov)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert html.count('class="page-card"') == 5     # 페이지 5개 전부
    assert "📋 책 개요" in html                       # 개요 주입
    assert 'id="imageModal"' in html                 # 모달 존재
    assert "window.KYOBO_SLUG" in html
    assert "5페이지" in html


# ── 실제 4권(로컬 보유분) 라운드트립 — 발행본 재현성 ──────────
@param_books(local_only=True)
def test_real_book_rebuilds_cleanly(book, tmp_path: Path):
    """실제 pages_data + overview 로 index.html 을 tmp 에 재빌드 → 페이지 수·개요·모달 검증.
    발행본을 덮어쓰지 않도록 tmp book_dir 로만 빌드(읽기전용 원칙)."""
    sd = summary_dir(book["slug"])
    pages_data = json.loads((sd / "pages_data.json").read_text(encoding="utf-8"))
    ov_path = sd / "book_overview.json"
    ov = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else None

    n_pages = len(pages_data["pages"])
    assert n_pages >= book["min_pages"], f"{book['slug']}: {n_pages}p < {book['min_pages']}"

    tmp_book = tmp_path / book["slug"]
    (tmp_book / "summary").mkdir(parents=True)
    out = build_html(tmp_book, pages_data, title=book["slug"], overview=ov)
    html = out.read_text(encoding="utf-8")
    assert html.count('class="page-card"') == n_pages   # 모든 페이지 카드 렌더
    assert 'id="imageModal"' in html
    if ov and ov.get("chapter_digests"):
        assert 'class="cd-item"' in html                # 챕터 상세요약 주입
        assert "📋 책 개요" in html
