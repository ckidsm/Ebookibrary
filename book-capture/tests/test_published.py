"""발행본(라이브 URL) 검증 — 4권 모두 HTTP 200 + 뷰어 기능 마커 + 발행 자원 스키마.

네트워크 필요. KYOBO_SKIP_NET=1 로 스킵. 발행 자원만 GET(읽기전용).
pages_data.json·chapters.json 은 index.html 에 인라인 → 미발행(404 정상), 검증 안 함.

이 스위트가 잡은 실제 발행 불일치(2026-07-19):
  · 밑바닥 LLM  = 코드모달 UI 는 있으나 code_blocks.json 미발행(404) → 코드패널 로드 실패.
                 → **2026-07-19 코드추출(118p·307블록)+재발행으로 해소.** strict 검증으로 승격됨.
  · 클로드코드  = 레거시 발행본. 📋책개요는 있으나 **챕터별 상세요약(chapter_digests)·코드모달 없음**.
                 로컬 산출물이 없어 재캡처/복원 필요 → 미해소. xfail 로 문서화.
"""
import json

import pytest

from conftest import BOOKS, SKIP_NET, published_url, param_books

pytestmark = pytest.mark.skipif(SKIP_NET, reason="KYOBO_SKIP_NET=1 (네트워크 스킵)")

# 아직 미해소인 발행 완전성 이슈 — 재발행되면 집합에서 빼 strict 검증으로 승격.
_LEGACY_NO_DIGESTS = {"클로드_코드로_시작하는_실전_에이전틱_코딩"}
_MISSING_CODE_JSON: set[str] = set()   # 밑바닥LLM 해소(2026-07-19) → 비어있음


def _xfail_if(slug: str, known: set, reason: str):
    if slug in known:
        pytest.xfail(reason)


# ── 불변 조건: 4권 모두 200 + 뷰어 기능 마커 ──────────────────
@param_books()
def test_published_viewer_ok(book, fetch):
    code, body = fetch(published_url(book["slug"]))
    assert code == 200, f"{book['slug']}: HTTP {code}"
    html = body.decode("utf-8", "ignore")
    n_cards = html.count('class="page-card"')
    assert n_cards >= book["min_pages"], f"{book['slug']}: 페이지카드 {n_cards} < {book['min_pages']}"
    assert 'id="imageModal"' in html, f"{book['slug']}: 이미지 모달 없음"
    assert "window.KYOBO_SLUG" in html, f"{book['slug']}: KYOBO_SLUG 없음"
    assert "📋 책 개요" in html, f"{book['slug']}: 책 개요 없음"


# ── 불변 조건: book_overview.json 200 + 개요 본문 존재 ─────────
@param_books()
def test_published_overview_present(book, fetch):
    code, body = fetch(published_url(book["slug"], "summary/book_overview.json"))
    assert code == 200, f"{book['slug']}: overview HTTP {code}"
    ov = json.loads(body)
    assert isinstance(ov, dict) and ov.get("overview"), f"{book['slug']}: overview 본문 없음"


# ── 불변 조건: 첫 페이지 자원(썸네일·원본·OCR) 200 ────────────
@param_books()
def test_published_first_page_assets(book, fetch):
    code_img, _ = fetch(published_url(book["slug"], "thumbs/page_001.png"))
    assert code_img == 200, f"{book['slug']}: 썸네일 page_001 HTTP {code_img}"
    code_raw, _ = fetch(published_url(book["slug"], "page_001.png"))
    assert code_raw == 200, f"{book['slug']}: 원본 page_001 HTTP {code_raw}"
    code_ocr, ocr = fetch(published_url(book["slug"], "summary/ocr_text/page_001.txt"))
    assert code_ocr == 200, f"{book['slug']}: ocr page_001 HTTP {code_ocr}"
    assert len(ocr.strip()) > 0, f"{book['slug']}: ocr page_001 비어있음"


# ── 완전성: 챕터별 상세요약(chapter_digests) 존재·유효 ─────────
@param_books()
def test_published_chapter_digests(book, fetch):
    _xfail_if(book["slug"], _LEGACY_NO_DIGESTS,
              "레거시 발행본 — chapter_digests 없음(finalize+overview 재실행 대상)")
    code, body = fetch(published_url(book["slug"], "summary/book_overview.json"))
    assert code == 200
    ov = json.loads(body)
    digests = ov.get("chapter_digests") or []
    assert len(digests) >= 1, f"{book['slug']}: chapter_digests 없음"
    for c in digests:
        assert c.get("title") and c.get("body"), f"{book['slug']}: 챕터요약 필드 누락"


# ── 완전성: 코드모달 UI 가 있으면 code_blocks.json 도 발행돼야 ──
@param_books()
def test_published_code_blocks_consistency(book, fetch):
    """뷰어에 코드모달(mCodeWrap)이 있으면 code_blocks.json 이 200 이어야(패널 로드 성공).
    코드모달이 없는 책(레거시/코드없음)은 code_blocks 미발행이 정상."""
    _xfail_if(book["slug"], _MISSING_CODE_JSON,
              "코드모달은 있으나 code_blocks.json 404 — 발행 누락(재발행 대상)")
    _, body = fetch(published_url(book["slug"]))
    has_code_modal = "mCodeWrap" in body.decode("utf-8", "ignore")
    code, cbody = fetch(published_url(book["slug"], "summary/code_blocks.json"))
    if has_code_modal:
        assert code == 200, f"{book['slug']}: 코드모달 있으나 code_blocks.json HTTP {code}"
        assert isinstance(json.loads(cbody), (dict, list))
    # 코드모달 없으면 code_blocks 404 여도 정상(별도 단언 없음)
