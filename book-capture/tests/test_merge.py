"""merge.py 단위 테스트 — chapter_id 부여 · 챕터 트리 · batch 머지(정렬/중복제거).

순수 함수 + tmp 파일만 사용. API·하드웨어·발행본 무관.
"""
import json
from pathlib import Path

import pytest

from bookcapture.merge import _make_chapter_id, _build_chapters, merge_batches


# ── _make_chapter_id ────────────────────────────────────────
@pytest.mark.parametrize("sid, ci_title, expected", [
    ("3장", "", "chs-chapter-3"),
    ("제5장", "", ""),                      # section_id 는 'N장' 으로 끝나야(끝이 '장') 매치
    ("Part 2", "", "chs-part-2"),
    ("", "5장 신경망", "chs-chapter-5"),      # ci_title 폴백
    ("", "Part 3 심화", "chs-part-3"),
    ("1.1", "소제목", ""),                   # 절은 챕터 id 없음
    ("", "", ""),
])
def test_make_chapter_id(sid, ci_title, expected):
    assert _make_chapter_id(sid, ci_title) == expected


# ── _build_chapters ─────────────────────────────────────────
def test_build_chapters_groups_by_chapter_and_section():
    pages = [
        {"num": 1, "section_id": "1장", "chapter_intro": {"title": "1장 첫걸음"}},
        {"num": 2, "section_id": "1.1", "chapter_intro": {"title": "1.1 개요"}},
        {"num": 3, "section_id": "1.1"},
        {"num": 4, "section_id": "2장", "chapter_intro": {"title": "2장 심화"}},
        {"num": 5, "section_id": "2.1", "chapter_intro": {"title": "2.1 응용"}},
    ]
    chs = _build_chapters(pages, "폴백")
    assert len(chs) == 2
    assert chs[0]["title"] == "1장 첫걸음"
    assert chs[0]["id"] == "chs-chapter-1"
    assert chs[0]["intro_page"]["num"] == 1
    assert chs[1]["title"] == "2장 심화"
    assert chs[1]["id"] == "chs-chapter-2"
    # 1장에 1.1 섹션이 페이지 2,3 을 담아야
    sec_titles = [s["title"] for s in chs[0]["sections"]]
    assert "1.1 개요" in sec_titles


def test_build_chapters_plain_pages_single_group():
    """구조(section_id/chapter_intro) 없는 페이지 → 한 챕터 안 '기타' 섹션에 전부.
    (fallback_title 은 chapters 가 아예 비었을 때만 쓰이며, 구조 없어도 챕터 1개는 생성됨.)"""
    pages = [{"num": 1}, {"num": 2}, {"num": 3}]
    chs = _build_chapters(pages, "제목없음")
    assert len(chs) == 1
    assert chs[0]["sections"][0]["title"] == "기타"
    all_nums = [p["num"] for s in chs[0]["sections"] for p in s["pages"]]
    assert all_nums == [1, 2, 3]


# ── merge_batches ───────────────────────────────────────────
def test_merge_batches_sorts_dedups_and_writes(tmp_path: Path):
    sd = tmp_path / "summary"
    sd.mkdir()
    # 일부러 순서 뒤섞음 + 중복(num=2) 포함
    (sd / "batch_001.json").write_text(json.dumps([
        {"num": 3, "summary": "c"},
        {"num": 1, "summary": "a"},
    ]), encoding="utf-8")
    (sd / "batch_002.json").write_text(json.dumps([
        {"num": 2, "summary": "b"},
        {"num": 2, "summary": "b-중복"},   # 중복 → 첫 것만
    ]), encoding="utf-8")

    res = merge_batches(sd, fallback_title="테스트책")

    assert res["pages"] == 3
    assert res["range"] == (1, 3)
    data = json.loads((sd / "pages_data.json").read_text(encoding="utf-8"))
    nums = [p["num"] for p in data["pages"]]
    assert nums == [1, 2, 3]                       # 정렬됨
    # 중복 제거: num=2 는 첫 등장(b)만
    p2 = next(p for p in data["pages"] if p["num"] == 2)
    assert p2["summary"] == "b"
    assert "chapters" in data and len(data["chapters"]) >= 1


def test_merge_batches_raises_without_batches(tmp_path: Path):
    sd = tmp_path / "summary"
    sd.mkdir()
    with pytest.raises(FileNotFoundError):
        merge_batches(sd)
