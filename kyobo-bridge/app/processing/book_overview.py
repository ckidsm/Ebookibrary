"""책 전체 개요(overview) 생성.

pages_data.json(페이지별 topics·terms·summary)을 종합해 책 머리말 카드용 JSON
(전체 요약·대상 독자·핵심 주제·꼭 알아야 할 용어·핵심 페이지·학습 가이드)을
AI 1회 호출로 만든다. summary/book_overview.json 으로 저장.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .summarize import AiCfg, _post_message, _extract_json

OVERVIEW_SYSTEM = (
    "당신은 한국어 도서를 분석해 독자에게 책 전체 지도를 그려 주는 전문 편집자입니다. "
    "페이지별 요약을 종합해, 이 책이 무엇을 다루고 무엇을 꼭 알아야 하는지 명확히 정리합니다. "
    "과장 없이 사실에 근거하고, 한국어로 답합니다."
)


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _digest(pages: list[dict]) -> str:
    """페이지별 한 줄 다이제스트 — 개요 생성 입력."""
    out = []
    for p in pages:
        num = p.get("num")
        topics = ", ".join(p.get("topics") or [])
        terms = ", ".join(p.get("terms") or [])
        summ = _strip_html(p.get("summary") or "")[:160]
        out.append(f"p.{num}: [{topics}] 용어: {terms} | {summ}")
    return "\n".join(out)


def _build_prompt(title: str, pages: list[dict]) -> str:
    return f"""다음은 '{title}' 책의 전체 {len(pages)}페이지를 페이지별로 정리(주제·용어·요약)한 것입니다.
이를 종합해 '책 전체 개요'를 만들어 주세요.

[페이지별 정리]
{_digest(pages)}

아래 JSON 형식 **만** 출력하세요(설명·코드펜스 금지):
{{
  "overview": "이 책이 무엇을 다루는지 2~3문단. 문단 구분은 <br><br> 사용",
  "target_reader": "누구를 위한 책인지 한 문장",
  "key_topics": ["핵심 주제 6~10개 (짧은 구)"],
  "key_terms": [{{"term": "용어명", "desc": "한 줄 설명"}}],
  "must_read_pages": [{{"page": 정수페이지번호, "why": "왜 꼭 봐야 하는지"}}],
  "study_guide": "이 책을 어떤 순서로/어떻게 읽으면 좋은지. <br> 줄바꿈 허용"
}}
규칙: key_terms 12~20개, must_read_pages 6~10개(실제 존재하는 페이지번호만), 모두 위 페이지 정리에 근거."""


def generate_overview(book_dir: Path, cfg: AiCfg, title: str) -> dict | None:
    """summary/pages_data.json → book_overview.json 생성·저장. 실패 시 None."""
    summary_dir = book_dir / "summary"
    pd_path = summary_dir / "pages_data.json"
    if not pd_path.exists():
        return None
    pages = json.loads(pd_path.read_text(encoding="utf-8")).get("pages", [])
    if not pages:
        return None
    text, in_t, out_t = _post_message(
        cfg, _build_prompt(title, pages), system=OVERVIEW_SYSTEM, max_tokens=4000)
    ov = _extract_json(text)
    # 핵심 페이지는 실제 존재하는 번호만 유지
    valid = {p.get("num") for p in pages}
    if isinstance(ov.get("must_read_pages"), list):
        ov["must_read_pages"] = [
            m for m in ov["must_read_pages"]
            if isinstance(m, dict) and m.get("page") in valid
        ]
    ov["_meta"] = {"in_tok": in_t, "out_tok": out_t, "pages": len(pages)}
    out_path = summary_dir / "book_overview.json"
    out_path.write_text(json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[overview] {out_path} (용어 {len(ov.get('key_terms', []))} · "
          f"핵심페이지 {len(ov.get('must_read_pages', []))} · in={in_t} out={out_t})")
    return ov
