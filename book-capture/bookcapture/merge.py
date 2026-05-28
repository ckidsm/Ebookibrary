"""batch_*.json 들을 합쳐 pages_data.json 생성.

기존 books/CLI_완전활용/summary/merge_batches.py 의 로직을 함수로 이식.
chapter_id 자동 부여, 중복 페이지 제거, 챕터/섹션 트리 자동 생성.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def _make_chapter_id(sid: str, ci_title: str) -> str:
    s = (sid or "").strip()
    if s.startswith("Part"):
        m = re.search(r"Part\s*(\d+)", s)
        if m: return f"chs-part-{m.group(1)}"
    if s.endswith("장"):
        m = re.match(r"(\d+)", s)
        if m: return f"chs-chapter-{m.group(1)}"
    if ci_title:
        m = re.match(r"(\d+)장", ci_title)
        if m: return f"chs-chapter-{m.group(1)}"
        m = re.match(r"Part\s*(\d+)", ci_title)
        if m: return f"chs-part-{m.group(1)}"
    return ""


def _build_chapters(all_pages: list[dict], fallback_title: str) -> list[dict]:
    """페이지 리스트 → 챕터/섹션 트리. 기존 로직 그대로."""
    chapters: list[dict] = []
    current_chapter: dict | None = None
    current_section: dict | None = None

    for page in all_pages:
        sid = page.get("section_id", "")
        ci = page.get("chapter_intro")

        is_new_chapter = False
        if "장" in sid and "." not in sid:
            is_new_chapter = True
        elif "Part" in sid or "part" in sid:
            is_new_chapter = True

        if is_new_chapter:
            if current_section and current_chapter:
                current_chapter["sections"].append(current_section)
            if current_chapter:
                chapters.append(current_chapter)
            ch_title = (ci or {}).get("title") or sid
            ch_id = _make_chapter_id(sid, ch_title)
            current_chapter = {
                "title": ch_title,
                "id": ch_id,
                "sections": [],
                "intro_page": {"num": page["num"], "label": sid},
            }
            current_section = None
        elif ci and "." in sid:
            if current_section and current_chapter:
                current_chapter["sections"].append(current_section)
            current_section = {
                "title": ci.get("title") or sid,
                "pages": [{"num": page["num"], "label": sid}],
            }
        else:
            if current_section is None:
                if current_chapter is None:
                    current_chapter = {"title": sid, "id": "", "sections": [], "intro_page": None}
                current_section = {"title": sid or "기타", "pages": []}
            label = sid if sid else f"p.{page['num']}"
            current_section["pages"].append({"num": page["num"], "label": label})

    if current_section and current_chapter:
        current_chapter["sections"].append(current_section)
    if current_chapter:
        chapters.append(current_chapter)

    if not chapters:
        chapters = [{
            "title": fallback_title,
            "id": "",
            "sections": [{
                "title": "전체 페이지",
                "pages": [{"num": p["num"], "label": f"p.{p['num']}"} for p in all_pages],
            }],
            "intro_page": None,
        }]
    return chapters


def merge_batches(
    summary_dir: Path,
    out_path: Path | None = None,
    fallback_title: str = "도서",
) -> dict:
    """summary_dir 안의 batch_*.json (또는 batch_NNN.json) 일괄 머지.

    Returns: { pages, chapters, total, range }
    """
    batch_files = sorted(summary_dir.glob("batch_*.json"))
    if not batch_files:
        raise FileNotFoundError(f"{summary_dir} 에 batch_*.json 없음")

    all_pages: list[dict] = []
    for bf in batch_files:
        try:
            with bf.open(encoding="utf-8") as f:
                pages = json.load(f)
            if not isinstance(pages, list):
                print(f"[merge] WARN: {bf.name} 은 list 가 아님 (skip)")
                continue
            all_pages.extend(pages)
            print(f"[merge] {bf.name}: {len(pages)} 페이지")
        except Exception as e:
            print(f"[merge] WARN: {bf.name} 로드 실패: {e}")

    if not all_pages:
        raise ValueError("유효한 페이지가 0개")

    # 정렬 + 중복 제거 (num 키)
    all_pages.sort(key=lambda p: p["num"])
    seen, uniq = set(), []
    for p in all_pages:
        if p["num"] in seen: continue
        seen.add(p["num"]); uniq.append(p)
    all_pages = uniq

    chapters = _build_chapters(all_pages, fallback_title)
    data = {"chapters": chapters, "pages": all_pages}

    out_path = out_path or (summary_dir / "pages_data.json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[merge] {out_path} 생성")
    print(f"  · 총 {len(all_pages)} 페이지 (p.{all_pages[0]['num']} ~ p.{all_pages[-1]['num']})")
    print(f"  · 챕터 {len(chapters)}개")
    for ch in chapters:
        intro = f" intro p.{ch['intro_page']['num']}" if ch.get("intro_page") else ""
        print(f"    [{ch.get('id') or '-'}] {ch['title']}{intro} ({len(ch['sections'])} sections)")

    return {
        "pages": len(all_pages),
        "chapters": len(chapters),
        "range": (all_pages[0]["num"], all_pages[-1]["num"]),
        "out_path": str(out_path),
    }
