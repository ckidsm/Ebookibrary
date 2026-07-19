# -*- coding: utf-8 -*-
"""책 개요 생성 → summary/book_overview.json (첫 페이지 '📋 책 개요' 카드).

구성(2026-07-12 확정): **전체 요약 1개 + 챕터별 상세 요약(각 ~1페이지, 8챕터=~8장)**.
  overview·target_reader·key_topics·key_terms·must_read_pages·study_guide + chapter_digests.

입력: summary/chapters.json(장 경계·제목) + summary/pages_data.json(검증된 페이지 요약).
Claude **tool_use**(구조화 출력) → 인용부호/줄바꿈 이스케이프 문제 0(텍스트 JSON 파싱 대비 견고).
CLI(`bookcapture overview`)·scripts/gen_book_overview.py·백엔드 upload_processor 가 공유.
"""
from __future__ import annotations
from .anthropic_api import AnthropicAPI
import json, re, time, urllib.request, urllib.error
from pathlib import Path

API_URL = AnthropicAPI.API_URL


def _call_tool(cfg, system, user, tool, max_tokens=2600, images=None):
    key = cfg.api_key
    model = getattr(cfg, "model", None) or AnthropicAPI.DEFAULT_MODEL
    content = list(images or []) + [{"type": "text", "text": user}]
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": content}],
        "tools": [tool], "tool_choice": {"type": "tool", "name": tool["name"]},
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": AnthropicAPI.API_VERSION, "content-type": "application/json"})
    for attempt in range(AnthropicAPI.MAX_RETRIES):
        try:
            r = urllib.request.urlopen(req, timeout=AnthropicAPI.TIMEOUT_TEXT)
            d = json.load(r)
            u = d.get("usage", {})
            for b in d.get("content", []):
                if b.get("type") == "tool_use":
                    return b["input"], u.get("input_tokens", 0), u.get("output_tokens", 0)
            raise RuntimeError("tool_use 응답 없음")
        except urllib.error.HTTPError as e:
            if AnthropicAPI.is_retryable(e.code) and attempt < AnthropicAPI.MAX_RETRIES - 1:
                time.sleep(AnthropicAPI.BACKOFF_BASE ** attempt * 2); continue
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:200]}")
    raise RuntimeError("재시도 초과")


def _pages_text(pages, start, end, limit=6000):
    out = []
    for p in pages:
        n = p.get("num") or p.get("page")
        if n is None or not (start <= int(n) <= end):
            continue
        summ = re.sub(r"<[^>]+>", " ", str(p.get("summary", ""))).strip()
        pts = [re.sub(r"<[^>]+>", " ", str(x)).strip() for x in (p.get("points") or [])]
        line = f"[p.{n}] {summ}" + (" / 핵심: " + "; ".join(pts) if pts else "")
        out.append(line)
    return "\n".join(out)[:limit]


_CH_SYS = ("당신은 한국어 기술서 편집자다. 주어진 '페이지별 요약'을 종합해 그 장(章)의 핵심을 "
           "독자가 장 전체 흐름을 파악하도록 정리한다. 페이지 나열이 아니라 개념의 연결로 서술한다.")
_CH_TOOL = {
    "name": "save_chapter_digest", "description": "장 상세 요약 저장",
    "input_schema": {"type": "object", "properties": {
        "body": {"type": "string", "description": "장 상세 요약 HTML(<p>·<strong>·<ul><li>). 약 700~1000자."}},
        "required": ["body"]},
}
_BOOK_SYS = ("당신은 한국어 기술서 편집자다. 장별 요약을 바탕으로 책 전체 개요 메타데이터를 만든다. "
             "정확하고 담백하게, 근거 없는 내용은 넣지 않는다.")
_BOOK_TOOL = {
    "name": "save_book_overview", "description": "책 개요 메타데이터 저장",
    "input_schema": {"type": "object", "properties": {
        "target_reader": {"type": "string", "description": "대상 독자 한두 문장"},
        "overview": {"type": "string", "description": "전체 종합 요약 HTML(<p>·<strong>), 약 1페이지"},
        "key_topics": {"type": "array", "items": {"type": "string"}},
        "key_terms": {"type": "array", "items": {"type": "object", "properties": {
            "term": {"type": "string"}, "desc": {"type": "string"}}, "required": ["term", "desc"]}},
        "study_guide": {"type": "string", "description": "학습 가이드 HTML(<p>)"},
        "must_read_pages": {"type": "array", "items": {"type": "object", "properties": {
            "page": {"type": "integer"}, "why": {"type": "string"}}, "required": ["page", "why"]}},
    }, "required": ["target_reader", "overview", "key_topics", "key_terms",
                    "study_guide", "must_read_pages"]},
}


def _gen_chapter(cfg, book_title, ch, pages):
    user = (f"책: 《{book_title}》\n장: {ch['num']}장 — {ch['title']} (p.{ch['start']}~{ch['end']})\n"
            f"장 소개: {ch.get('summary','')}\n\n이 장의 페이지별 요약:\n{_pages_text(pages, ch['start'], ch['end'])}\n\n"
            "위를 종합해 이 장의 상세 요약을 작성하라. 규칙: 약 1페이지(700~1000자). "
            "HTML 2~4문단 <p>…</p>, 필요시 <p><strong>소주제</strong> …</p>, 항목은 <ul><li>. "
            "개념 흐름 중심, 코드·수식 나열 금지. save_chapter_digest 로 제출.")
    out, ti, to = _call_tool(cfg, _CH_SYS, user, _CH_TOOL, max_tokens=2000)
    return out["body"], ti, to


def _gen_meta(cfg, book_title, chapters):
    chlist = "\n".join(f"{c['num']}장 {c['title']} (p.{c['start']}~{c['end']}): {c.get('summary','')}"
                       for c in chapters)
    user = (f"책: 《{book_title}》\n장별 요약:\n{chlist}\n\n"
            "책 개요 메타데이터를 save_book_overview 로 제출. overview 는 장들을 관통하는 흐름으로 "
            "약 1페이지(<p> 2~3문단). key_topics 10개 내외, key_terms 15~20개, must_read_pages 5~8개"
            "(page 정수, why 는 ' — '로 시작), study_guide <p>.")
    return _call_tool(cfg, _BOOK_SYS, user, _BOOK_TOOL, max_tokens=4096)


def generate_overview(book_dir, cfg, title=None):
    """chapters.json + pages_data.json → book_overview.json. chapters 재사용(resume). 반환 dict|None."""
    book_dir = Path(book_dir)
    sd = book_dir / "summary" if (book_dir / "summary").is_dir() else book_dir
    ch_path, pd_path = sd / "chapters.json", sd / "pages_data.json"
    if not pd_path.exists():
        print("[overview] pages_data.json 없음 — 스킵"); return None
    pdata = json.loads(pd_path.read_text(encoding="utf-8"))
    pages = pdata if isinstance(pdata, list) else (pdata.get("pages") or [])
    chapters = json.loads(ch_path.read_text(encoding="utf-8")) if ch_path.exists() else []
    title = title or book_dir.name.replace("_", " ")

    meta, ci, co = _gen_meta(cfg, title, chapters) if chapters else ({}, 0, 0)
    # 챕터 요약 재사용(있으면 재호출 안 함)
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
            digests.append(prev[c["num"]]); continue
        try:
            body, ti, to = _gen_chapter(cfg, title, c, pages)
            ci += ti; co += to
            digests.append({"num": c["num"], "title": f"{c['num']}장 · {c['title']}",
                            "start": c["start"], "end": c["end"], "body": body})
        except Exception as e:
            print(f"[overview] {c['num']}장 실패(계속): {e}")
    if digests:
        meta["chapter_digests"] = digests
    if not meta:
        print("[overview] 생성 실패"); return None
    out_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[overview] {out_path.name} (장 {len(digests)} · in={ci} out={co})")
    if ci or co:
        _ovmodel = getattr(cfg, "model", None) or AnthropicAPI.DEFAULT_MODEL
        from . import cost as _cost
        _cost.record(book_dir, "overview", _ovmodel, ci, co, AnthropicAPI.cost_usd(_ovmodel, ci, co))
    return meta
