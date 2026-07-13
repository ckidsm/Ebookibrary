# -*- coding: utf-8 -*-
"""챕터 자동 감지 (비전) → summary/chapters.json.

OCR 이 깨지는 책(임베디드 폰트 mojibake)에서도 동작하도록 **이미지 기반**으로 한다.
2단계:
  1) 표지(cover/divider) 후보 필터 — 페이지에 **흰색·검정 아닌 단일 색이 큰 면적**을 차지하면
     장/절 표지 후보(예: '이미지 처리 바이블'은 베이지 표지). 색을 하드코딩하지 않고 '지배색'으로
     일반화 → 다른 책의 파란/회색 표지도 감지. (API 없음, 빠름)
  2) 비전 확인 — 후보만 Claude 비전으로 읽어 {level: chapter|section|other, num, title} 판정.
     '장(chapter)'만 경계로 채택. 절/기타는 제외. tool_use 구조화 출력.

chapters.json = [{num,title,start,end,summary,topics}] (summary/topics 는 비움 → 개요/트리가 채움).
start=표지 페이지, end=다음 장 표지 직전. 후보가 ~10장이라 비전 호출 소수.
"""
from __future__ import annotations
import io, base64, json, time, urllib.request, urllib.error
from pathlib import Path

API_URL = "https://api.anthropic.com/v1/messages"


def _page_files(book_dir: Path):
    d = Path(book_dir)
    return sorted(d.glob("page_*.png"), key=lambda p: p.name)


def dominant_color_frac(path, grid=160):
    """(지배 비-흰/비-검 색의 면적비율, 그 색). 표지=한 색이 큰 면적."""
    from PIL import Image
    im = Image.open(path).convert("RGB").resize((grid, grid))
    buckets = {}
    for r, g, b in im.getdata():
        mx, mn = max(r, g, b), min(r, g, b)
        if mn > 225:              # 거의 흰색 배경 제외
            continue
        if mx < 55:               # 거의 검정 제외
            continue
        key = (r // 24, g // 24, b // 24)   # 색 양자화
        buckets[key] = buckets.get(key, 0) + 1
    if not buckets:
        return 0.0, None
    key, cnt = max(buckets.items(), key=lambda kv: kv[1])
    col = (key[0] * 24 + 12, key[1] * 24 + 12, key[2] * 24 + 12)
    return cnt / (grid * grid), col


def cover_candidates(book_dir, min_frac=0.30):
    """지배색 면적비율이 큰 페이지 = 장/절 표지 후보(번호 오름차순)."""
    cands = []
    for f in _page_files(book_dir):
        frac, col = dominant_color_frac(f)
        if frac >= min_frac:
            n = int(f.stem.split("_")[1])
            cands.append({"page": n, "frac": round(frac, 3), "color": col})
    return cands


def _img_b64(path, max_w=1100):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


_SYS = ("당신은 한국어 기술서의 페이지 이미지를 보고 그 페이지가 '장(章) 표지'인지 판정한다. "
        "장 표지 = 큰 색 배경에 'N장'/'CHAPTER N'/'부록' 등과 장 제목이 크게 있는 도입 페이지. "
        "본문·절(2.1 같은 소제목)·그림 페이지는 장 표지가 아니다.")


def _read_cover(key, model, path):
    tool = {
        "name": "report_cover",
        "description": "페이지 장표지 판정",
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "string", "enum": ["chapter", "section", "other"],
                          "description": "chapter=장 표지, section=절 표지, other=본문/그림 등"},
                "num": {"type": "integer", "description": "장 번호(부록/미상이면 0)"},
                "title": {"type": "string", "description": "장 제목(장 표지일 때만, 예 '기본 개념과 도구')"},
            },
            "required": ["level", "num", "title"],
        },
    }
    body = json.dumps({
        "model": model, "max_tokens": 300, "system": _SYS,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                          "data": _img_b64(path)}},
            {"type": "text", "text": "이 페이지가 장 표지인지 판정하고 report_cover 로 제출."},
        ]}],
        "tools": [tool], "tool_choice": {"type": "tool", "name": "report_cover"},
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(4):
        try:
            r = urllib.request.urlopen(req, timeout=90)
            d = json.load(r)
            for b in d.get("content", []):
                if b.get("type") == "tool_use":
                    u = d.get("usage", {})
                    return b["input"], u.get("input_tokens", 0), u.get("output_tokens", 0)
            return None, 0, 0
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                time.sleep(2 ** attempt * 2); continue
            raise
    return None, 0, 0


def generate_chapters(book_dir, cfg, min_frac=0.30, include_sections=False):
    """비전으로 chapters.json 생성. cfg=AiCfg(api_key/model). 반환 chapters 리스트."""
    book_dir = Path(book_dir)
    sd = book_dir / "summary"; sd.mkdir(exist_ok=True)
    files = _page_files(book_dir)
    last_page = int(files[-1].stem.split("_")[1]) if files else 0
    cands = cover_candidates(book_dir, min_frac=min_frac)
    key = cfg.api_key
    model = getattr(cfg, "model", "claude-sonnet-4-5") or "claude-sonnet-4-5"
    covers = []
    ci = co = 0
    for c in cands:
        path = book_dir / f"page_{c['page']:03d}.png"
        info, ti, to = _read_cover(key, model, path)
        ci += ti; co += to
        if not info:
            continue
        lvl = info.get("level")
        if lvl == "chapter" or (include_sections and lvl == "section"):
            covers.append({"page": c["page"], "level": lvl,
                           "num": info.get("num", 0), "title": info.get("title", "").strip()})
    # 페이지순 정렬 + 경계 계산(chapter 만 경계)
    covers.sort(key=lambda x: x["page"])
    chs = [c for c in covers if c["level"] == "chapter"]
    chapters = []
    for i, c in enumerate(chs):
        start = c["page"]
        end = (chs[i + 1]["page"] - 1) if i + 1 < len(chs) else last_page
        chapters.append({"num": c["num"] or (i + 1), "title": c["title"],
                         "start": start, "end": end, "summary": "", "topics": []})
    (sd / "chapters.json").write_text(
        json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[chapters] 후보 {len(cands)} → 장 {len(chapters)} (비전 in={ci} out={co})")
    for c in chapters:
        print(f"  {c['num']}장 {c['title']} (p.{c['start']}~{c['end']})")
    return chapters
