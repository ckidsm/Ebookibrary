# -*- coding: utf-8 -*-
"""챕터·페이지 요약 → summary/book_overview.json (첫 페이지 '📋 책 개요' 카드용).

구성(사용자 기준 2026-07-12): **전체 요약 1개 + 챕터별 약 1장(8챕터면 ~8장 분량)**.
  - overview        : 책 전체 종합 요약(전체 요약)
  - chapter_digests : 챕터별 상세 요약(각 ~1페이지) — 그 장 페이지 요약을 집대성
  - target_reader / key_topics / key_terms / must_read_pages / study_guide

입력: summary/chapters.json(장 경계·제목) + summary/pages_data.json(페이지별 요약).
      OCR 이 아니라 **이미 검증된 페이지 요약**을 종합하므로 정확. Claude Sonnet.
사용: python scripts/gen_book_overview.py <book_dir> [--title 제목] [--model claude-sonnet-4-5]
"""
from __future__ import annotations
import sys, json, time, re, urllib.request, urllib.error, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bookcapture import settings as S  # noqa: E402

API_URL = "https://api.anthropic.com/v1/messages"
_PRICES = {"claude-sonnet-4-5": (3.0, 15.0), "claude-haiku-4-5": (1.0, 5.0)}


def _call_tool(key, model, system, user, tool, max_tokens=2600):
    """tool_use 로 구조화 출력 강제 → API 가 검증한 JSON(dict) 반환.
    (HTML/인용부호가 섞인 값도 이스케이프 문제 없이 안전. 텍스트 JSON 파싱 대비 견고.)"""
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user}],
        "tools": [tool], "tool_choice": {"type": "tool", "name": tool["name"]},
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(4):
        try:
            r = urllib.request.urlopen(req, timeout=180)
            d = json.load(r)
            u = d.get("usage", {})
            for b in d.get("content", []):
                if b.get("type") == "tool_use":
                    return b["input"], u.get("input_tokens", 0), u.get("output_tokens", 0)
            raise RuntimeError("tool_use 응답 없음")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                time.sleep(2 ** attempt * 2); continue
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:200]}")
    raise RuntimeError("재시도 초과")


def _pages_text(pages, start, end, limit=6000):
    """장 범위 페이지들의 요약+핵심을 한 덩어리 텍스트로(모델 입력용)."""
    out = []
    for p in pages:
        n = p.get("num") or p.get("page")
        if n is None or not (start <= int(n) <= end):
            continue
        summ = re.sub(r"<[^>]+>", " ", str(p.get("summary", ""))).strip()
        pts = [re.sub(r"<[^>]+>", " ", str(x)).strip() for x in (p.get("points") or [])]
        line = f"[p.{n}] {summ}"
        if pts:
            line += " / 핵심: " + "; ".join(pts)
        out.append(line)
    t = "\n".join(out)
    return t[:limit]


CH_SYS = ("당신은 한국어 기술서 편집자다. 주어진 '페이지별 요약'을 종합해 그 장(章)의 핵심을 "
          "독자가 장 전체 흐름을 파악하도록 정리한다. 페이지 나열이 아니라 개념의 연결로 서술한다.")


def gen_chapter(key, model, book_title, ch, pages):
    body_src = _pages_text(pages, ch["start"], ch["end"])
    user = (
        f"책: 《{book_title}》\n장: {ch['num']}장 — {ch['title']} (p.{ch['start']}~{ch['end']})\n"
        f"장 소개: {ch.get('summary','')}\n\n"
        f"이 장의 페이지별 요약:\n{body_src}\n\n"
        "위를 종합해 이 장의 상세 요약을 작성하라. 규칙:\n"
        "- 분량: 약 1페이지(한국어 700~1000자). 장이 크면 조금 더.\n"
        "- 형식: HTML. 2~4개 문단을 <p>…</p> 로. 필요시 <p><strong>소주제</strong> …</p>.\n"
        "  핵심 항목 나열이 유용하면 <ul><li>…</li></ul>(3~5개). 중요한 용어·기법은 <strong>.\n"
        "- 내용: 무엇을/왜/어떻게 배우는지 개념 흐름 중심. 코드·수식 나열 금지. 과장 금지.\n"
        "결과는 save_chapter_digest 도구로 제출.")
    tool = {
        "name": "save_chapter_digest",
        "description": "장 상세 요약 저장",
        "input_schema": {
            "type": "object",
            "properties": {"body": {"type": "string",
                           "description": "장 상세 요약 HTML(<p>·<strong>·<ul><li>). 약 700~1000자."}},
            "required": ["body"],
        },
    }
    out, ti, to = _call_tool(key, model, CH_SYS, user, tool, max_tokens=2000)
    return out["body"], ti, to


BOOK_SYS = ("당신은 한국어 기술서 편집자다. 장별 요약을 바탕으로 책 전체 개요 메타데이터를 만든다. "
            "정확하고 담백하게, 근거 없는 내용은 넣지 않는다.")


def gen_book_meta(key, model, book_title, chapters):
    chlist = "\n".join(f"{c['num']}장 {c['title']} (p.{c['start']}~{c['end']}): {c.get('summary','')}"
                       for c in chapters)
    user = (
        f"책: 《{book_title}》\n장별 요약:\n{chlist}\n\n"
        "이 책의 개요 메타데이터를 save_book_overview 도구로 제출하라.\n"
        "- overview: 책 전체를 아우르는 종합 요약(전체 요약). 약 1페이지, HTML <p> 2~3문단, 중요 용어 <strong>. "
        "장들을 관통하는 흐름으로 서술(장 단순 나열 금지).\n"
        "- key_topics: 주요 주제 10개 내외.\n"
        "- key_terms: 이미지처리·딥러닝 핵심 용어 15~20개(term/desc).\n"
        "- must_read_pages: 각 장 시작 등 5~8개(page 정수, why 는 ' — ' 로 시작).\n"
        "- study_guide: 학습 가이드 HTML <p>.")
    tool = {
        "name": "save_book_overview",
        "description": "책 개요 메타데이터 저장",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_reader": {"type": "string", "description": "대상 독자 한두 문장"},
                "overview": {"type": "string", "description": "전체 종합 요약 HTML(<p>·<strong>)"},
                "key_topics": {"type": "array", "items": {"type": "string"}},
                "key_terms": {"type": "array", "items": {"type": "object",
                              "properties": {"term": {"type": "string"}, "desc": {"type": "string"}},
                              "required": ["term", "desc"]}},
                "study_guide": {"type": "string", "description": "학습 가이드 HTML(<p>)"},
                "must_read_pages": {"type": "array", "items": {"type": "object",
                                    "properties": {"page": {"type": "integer"}, "why": {"type": "string"}},
                                    "required": ["page", "why"]}},
            },
            "required": ["target_reader", "overview", "key_topics", "key_terms",
                         "study_guide", "must_read_pages"],
        },
    }
    out, ti, to = _call_tool(key, model, BOOK_SYS, user, tool, max_tokens=4096)
    return out, ti, to


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book_dir")
    ap.add_argument("--title", default=None)
    ap.add_argument("--model", default="claude-sonnet-4-5")
    a = ap.parse_args()
    bd = Path(a.book_dir)
    sd = bd / "summary" if (bd / "summary").is_dir() else bd
    chapters = json.loads((sd / "chapters.json").read_text(encoding="utf-8"))
    pdata = json.loads((sd / "pages_data.json").read_text(encoding="utf-8"))
    pages = pdata if isinstance(pdata, list) else (pdata.get("pages") or [])
    title = a.title or bd.name.replace("_", " ")
    key = S.load().ai.api_key
    if not key:
        print("❌ API 키 없음 (settings/env)"); return 1

    ci, co = 0, 0
    print(f"📖 《{title}》 책 개요 생성 — {len(chapters)}장, 전체요약+장별 1장")
    meta, ti, to = gen_book_meta(key, a.model, title, chapters)
    ci += ti; co += to
    print(f"  [메타] 키: {sorted(meta.keys())} (in {ti} out {to})")

    # 챕터 요약은 재사용(resume): 기존 book_overview.json 에 있으면 재호출 안 함
    out_path = sd / "book_overview.json"
    prev = {}
    if out_path.exists():
        try:
            prev = {d["num"]: d for d in json.loads(out_path.read_text(encoding="utf-8")).get("chapter_digests", [])}
        except Exception:
            prev = {}
    digests = []
    for c in chapters:
        if c["num"] in prev and prev[c["num"]].get("body"):
            digests.append(prev[c["num"]]); print(f"  [{c['num']}장] 재사용")
            continue
        body, ti, to = gen_chapter(key, a.model, title, c, pages)
        ci += ti; co += to
        digests.append({"num": c["num"], "title": f"{c['num']}장 · {c['title']}",
                        "start": c["start"], "end": c["end"], "body": body})
        print(f"  [{c['num']}장] {c['title']} — {len(body)}자 (in {ti} out {to})")

    meta["chapter_digests"] = digests
    (sd / "book_overview.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    pin, pout = _PRICES.get(a.model, (3.0, 15.0))
    cost = ci / 1e6 * pin + co / 1e6 * pout
    print(f"✅ book_overview.json 저장 (in {ci} out {co}, ${cost:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
