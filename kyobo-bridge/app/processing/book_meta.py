"""도서 헤더 메타 추출 — 판권/소개/목차/끝페이지 OCR 에서 출판정보 추출.

extract_dates() : 출판일·개정일을 정규식으로 추출(무료, 토큰 0).
extract_meta_ai(): 종류·분야·소개를 AI 1회 호출로 추출(소량 토큰, 선택).
"""
from __future__ import annotations
import re

_DATE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def extract_dates(pages: dict[int, str]) -> dict:
    """판권 페이지(보통 앞 6p, '발행' 포함)에서 날짜를 모아
    가장 이른 날짜=출판일(초판), 가장 늦은 날짜=개정일(최신 쇄/개정). 무료."""
    found: list[str] = []
    for pn in sorted(pages)[:6]:
        t = pages.get(pn) or ""
        if "발행" not in t and "쇄" not in t and "판" not in t:
            continue
        for m in _DATE.finditer(t):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1980 <= y <= 2035 and 1 <= mo <= 12 and 1 <= d <= 31:
                found.append(f"{y}-{mo:02d}-{d:02d}")
    if not found:
        return {}
    uniq = sorted(set(found))
    out = {"pub_date": uniq[0]}
    if len(uniq) > 1:
        out["revision_date"] = uniq[-1]
    return out


def _front_back_blob(pages: dict[int, str], limit: int = 9000) -> str:
    nums = sorted(pages)
    pick = nums[:6] + nums[-2:]
    seen = set()
    parts = []
    for n in pick:
        if n in seen:
            continue
        seen.add(n)
        parts.append(f"[p.{n}]\n{(pages.get(n) or '')[:1200]}")
    return "\n\n".join(parts)[:limit]


def extract_meta_ai(pages: dict[int, str], cfg, title: str = "") -> dict:
    """앞(판권·소개)+목차+끝 텍스트로 AI 1회 호출 → {category, field, description}.
    summarize 의 API 호출 인프라를 재사용. 실패 시 {} 반환."""
    import json
    from . import summarize as S

    blob = _front_back_blob(pages)
    prompt = (
        f'다음은 책 "{title}" 의 판권·소개·목차·끝부분 OCR 텍스트입니다.\n'
        "이를 바탕으로 아래 JSON 으로만 답하세요(모르면 null):\n"
        "{\n"
        '  "category": "도서 종류 (입문서/전문서/실용서/교재/자격증 등 한 단어급)",\n'
        '  "field": "분야 (예: 인공지능·머신러닝 / 영상·미디어 / 정보처리)",\n'
        '  "pub_date": "초판(처음) 발행일 YYYY-MM-DD, 없으면 null",\n'
        '  "revision_date": "최신 쇄/개정판 발행일 YYYY-MM-DD, 초판만 있으면 null",\n'
        '  "description": "2~3문장 소개"\n'
        "}\n"
        '규칙: 날짜는 판권면의 "초판 발행"·"N쇄 발행"·"개정판 발행" 표기에서만 추출. '
        "전화번호·주소·ISBN·우편번호 숫자를 날짜로 쓰지 말 것. JSON 객체만 출력, 코드펜스·설명 금지.\n\n"
        f"텍스트:\n{blob}"
    )
    try:
        text, _it, _ot = S._post_message(cfg, prompt)  # (text, in_tok, out_tok)
        obj = S._extract_json(text)
        keys = ("category", "field", "pub_date", "revision_date", "description")
        return {k: obj.get(k) for k in keys if obj.get(k)}
    except Exception:
        return {}
