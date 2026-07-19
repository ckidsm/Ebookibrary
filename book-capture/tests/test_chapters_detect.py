"""chapters_detect.py 순수 함수 단위 테스트 — 정규화·목차판정·가짜장 제거·목차페이지 탐지.

비전 API 호출 함수(_read_cover/_read_toc/generate_chapters)는 제외.
안정화 로직(_drop_false_chapters)과 결정적 텍스트 판정만 검증. tmp 파일만 사용.
"""
from pathlib import Path

import pytest

from bookcapture.chapters_detect import (
    _norm, _toc_score, _chap_markers, _drop_false_chapters, find_toc_pages,
)


# ── _norm (NFC + 공백/문장부호 제거 + 소문자) ─────────────────
def test_norm_strips_and_lowercases():
    assert _norm("  1장  나의 첫! 머신러닝 ") == "1장나의첫머신러닝"
    assert _norm("Deep Learning") == "deeplearning"
    assert _norm("") == ""


def test_norm_nfc_equivalence():
    # 같은 글자의 NFD(분해형)/NFC(결합형) 는 정규화 후 동일해야(교보 창명 NFD 사고 방지)
    import unicodedata
    nfc = "교보"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd            # 바이트는 다름
    assert _norm(nfc) == _norm(nfd)   # 정규화 후 같음


# ── _toc_score (진짜 목차 라인 수) ───────────────────────────
def test_toc_score_counts_title_pagenum_lines():
    toc = "1장 나의 첫 머신러닝 ........ 14\n2장 데이터 다루기 ...... 44\n3장 회귀 알고리즘 · 82"
    assert _toc_score(toc) == 3


def test_toc_score_ignores_prose():
    prose = ("이 책은 머신러닝을 처음 배우는 사람을 위한 입문서입니다.\n"
             "코드를 직접 따라 하며 개념을 익힐 수 있습니다.\n"
             "즐겁게 공부하세요!")
    assert _toc_score(prose) == 0


# ── _chap_markers (장 마커 집합) ─────────────────────────────
def test_chap_markers_extracts_all_forms():
    t = "1장 소개\nCHAPTER 2 basics\n제3장 심화\n부록 A 설치"
    m = _chap_markers(t)
    assert "1" in m and "2" in m and "3" in m and "A" in m


# ── _drop_false_chapters (역행/중복 번호 제거) ────────────────
def test_drop_false_chapters_removes_backward_numbers():
    chs = [
        {"num": 1, "title": "1장 시작"},
        {"num": 1, "title": "텐서플로"},      # 섹션 오검출(번호 역행) → 제거
        {"num": 2, "title": "2장 심화"},
        {"num": 2, "title": "케라스"},        # 중복 → 제거
        {"num": 0, "title": "부록 A"},        # num=0(부록) 은 위치순 통과
        {"num": 3, "title": "3장 응용"},
    ]
    out = _drop_false_chapters(chs)
    titles = [c["title"] for c in out]
    assert titles == ["1장 시작", "2장 심화", "부록 A", "3장 응용"]


def test_drop_false_chapters_keeps_monotonic():
    chs = [{"num": 1}, {"num": 2}, {"num": 3}]
    assert _drop_false_chapters(chs) == chs


# ── find_toc_pages (목차 페이지 블록 탐지) ────────────────────
def _write_ocr(book_dir: Path, page: int, text: str):
    d = book_dir / "summary" / "ocr_text"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"page_{page:03d}.txt").write_text(text, encoding="utf-8")


def _blank_pages(book_dir: Path, nums):
    # find_toc_pages 는 page_*.png 로 스캔 대상 페이지를 정함 → 더미 파일 필요
    for n in nums:
        (book_dir / f"page_{n:03d}.png").write_bytes(b"\x89PNG\r\n")


def test_find_toc_pages_detects_toc_block(tmp_path: Path):
    book = tmp_path / "book"
    book.mkdir()
    _blank_pages(book, range(1, 6))
    # p1 산문(제외), p2·p3 목차(장≥3, 페이지번호 라인 밀집)
    _write_ocr(book, 1, "머리말\n이 책을 읽는 방법에 대한 안내입니다.")
    _write_ocr(book, 2, "목차\n1장 소개 ...... 10\n2장 기초 ...... 30\n"
                        "3장 심화 ...... 55\n4장 응용 ...... 80\n"
                        "5장 정리 ...... 110\n6장 부록 ...... 140")
    _write_ocr(book, 3, "7장 실전 ...... 160\n8장 배포 ...... 190\n"
                        "9장 마무리 ...... 210\n부록 A 설치 ...... 230\n"
                        "부록 B 참고 ...... 240\n찾아보기 ...... 250")
    pages = find_toc_pages(book, scan_first=10, min_lines=6)
    assert 2 in pages and 3 in pages
    assert 1 not in pages          # 산문은 제외


def test_find_toc_pages_empty_for_prose_only(tmp_path: Path):
    book = tmp_path / "book"
    book.mkdir()
    _blank_pages(book, range(1, 4))
    for n in range(1, 4):
        _write_ocr(book, n, "이것은 일반 본문입니다. 페이지 번호로 끝나는 목차 라인이 없습니다.")
    assert find_toc_pages(book, scan_first=10, min_lines=6) == []
