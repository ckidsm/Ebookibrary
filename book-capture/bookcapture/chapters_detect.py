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
from .anthropic_api import AnthropicAPI
import io, base64, json, time, re, unicodedata, urllib.request, urllib.error
from pathlib import Path

API_URL = AnthropicAPI.API_URL


# ─────────────────────────────────────────────────────────────────────────
# 목차(TOC) 기반 챕터 감지 (2026-07-18) — 색표지 없는 책 대응.
#   색표지·저밀도 후보(cover_candidates)로 장을 못 찾는 책(예: '혼자 공부하는 머신러닝')은,
#   ① 목차 페이지를 찾아 비전으로 '장 목록(순서·번호·제목)'을 뽑고,
#   ② 각 장을 **깨끗한 전사 텍스트**(ocr_text/, mojibake 아님)에서 위치 검색해 시작 페이지를 잡는다.
#   TOC가 인쇄 페이지번호를 주더라도 캡처 인덱스와 어긋나므로, 페이지번호가 아니라 '제목/장번호 매칭'으로 경계를 정한다.
# ─────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """비교용 정규화 — NFC + 공백·문장부호 제거 + 소문자."""
    s = unicodedata.normalize("NFC", s or "")
    return re.sub(r"[\s\W_]+", "", s).lower()


def _ocr_text(book_dir, n: int) -> str:
    p = Path(book_dir) / "summary" / "ocr_text" / f"page_{n:03d}.txt"
    try:
        return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
    except Exception:
        return ""


def _toc_score(text: str) -> int:
    """페이지가 '진짜 목차'인 정도 — '제목 …… 페이지번호' 로 끝나는 라인 수.
    산문·추천사·'이 책의 구성' 설명은 라인 끝 페이지번호가 없어 0에 가깝다(오탐 방지 핵심)."""
    # 라인이 (글자 포함) + (끝에 1~3자리 페이지번호) 로 끝남. 순수 숫자줄/짧은줄 제외.
    lines = 0
    for ln in text.splitlines():
        s = ln.strip()
        if len(s) < 4:
            continue
        m = re.search(r"[.·•\s]\s*(\d{1,3})\s*$", s)      # 끝이 페이지번호
        if not m:
            continue
        head = s[:m.start()].strip()
        if len(head) >= 3 and re.search(r"[가-힣A-Za-z]", head):   # 앞에 실제 제목
            lines += 1
    return lines


def _chap_markers(t: str) -> set:
    """텍스트의 서로 다른 장 마커 집합(부록 포함) — 'N장'·'CHAPTER N'·'부록 X'."""
    return set(re.findall(r"(?:제\s*)?(\d{1,2})\s*장", t)) \
        | set(re.findall(r"(?i)chapter\s*0*(\d{1,2})", t)) \
        | set(re.findall(r"부록\s*([A-Ea-e가-힣])", t))


def find_toc_pages(book_dir, scan_first=30, min_lines=6):
    """목차 페이지들 — **연속 블록** 방식(2026-07-18 재설계).
    목차는 보통 여러 페이지에 걸치고 각 페이지는 1~2개 장만 담는다(예 '혼자 공부하는 머신러닝'은
    한 스프레드에 Chapter 하나). 그래서 '페이지당 장 ≥3'을 요구하면 첫/끝 장 페이지를 놓친다.
    → '제목 …… 페이지번호' 라인이 밀집한 페이지(sc≥min_lines)를 모아, **블록 전체**가 진짜 목차인지
       (‘목차’ 키워드 존재 또는 블록 통틀어 서로 다른 장 ≥3개)만 확인하고, 그 **연속 범위 전체**를 반환.
    산문/추천사는 페이지번호 라인이 없어 sc≈0 → 애초에 후보에 안 듦(오탐 방지 유지). 목차 없는 책은 []."""
    files = _page_files(book_dir)
    dense = []          # 페이지번호 라인 밀집 페이지(목차 본체 후보)
    kw_pages = set()
    all_ch = set()
    for f in files[:scan_first]:
        n = int(f.stem.split("_")[1])
        t = _ocr_text(book_dir, n)
        if not t:
            continue
        if _toc_score(t) >= min_lines:
            dense.append(n)
            all_ch |= _chap_markers(t)
            if ("목차" in t) or ("contents" in t.lower()) or ("차례" in t):
                kw_pages.add(n)
    if not dense:
        return []
    # 블록 전체가 진짜 목차인지: '목차' 키워드 또는 블록 통틀어 서로 다른 장 ≥3개
    if not (kw_pages or len(all_ch) >= 3):
        return []
    # 연속 범위(min..max) 전체를 목차로 — 사이 페이지도 밀집(sc≥min_lines/2)이면 포함(목차는 연속)
    lo, hi = min(dense), max(dense)
    block = []
    for n in range(lo, hi + 1):
        t = _ocr_text(book_dir, n)
        if n in dense or (t and _toc_score(t) >= min_lines // 2):
            block.append(n)
    return block


_TOC_SYS = ("당신은 한국어 기술서의 '목차(Contents)' 페이지 이미지를 보고 **장(章) 목록**을 추출한다. "
            "'장' = 1장·2장·CHAPTER N·제N장·부록 A/B 같은 최상위 단위. "
            "절·소제목(1.1, 2.3 등 하위 항목)은 제외한다. 목차에 나온 **순서 그대로**.")


def _read_toc(key, model, path):
    """목차 페이지 이미지 1장 → 장 목록. 반환 (list[{num,title}], in_tok, out_tok)."""
    tool = {
        "name": "report_toc",
        "description": "목차에서 장 목록 추출",
        "input_schema": {
            "type": "object",
            "properties": {
                "chapters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "num": {"type": "integer", "description": "장 번호(부록/미상=0)"},
                            "title": {"type": "string", "description": "장 제목(번호·페이지번호 제외한 제목만)"},
                        },
                        "required": ["num", "title"],
                    },
                },
            },
            "required": ["chapters"],
        },
    }
    body = json.dumps({
        "model": model, "max_tokens": 1500, "temperature": AnthropicAPI.DETECT_TEMPERATURE,
        "system": _TOC_SYS,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                          "data": _img_b64(path)}},
            {"type": "text", "text": "이 목차 페이지의 장 목록을 report_toc 로 제출."},
        ]}],
        "tools": [tool], "tool_choice": {"type": "tool", "name": "report_toc"},
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": AnthropicAPI.API_VERSION, "content-type": "application/json"})
    for attempt in range(AnthropicAPI.MAX_RETRIES):
        try:
            r = urllib.request.urlopen(req, timeout=AnthropicAPI.TIMEOUT_VISION)
            d = json.load(r)
            for b in d.get("content", []):
                if b.get("type") == "tool_use":
                    u = d.get("usage", {})
                    return b["input"].get("chapters", []), u.get("input_tokens", 0), u.get("output_tokens", 0)
            return [], 0, 0
        except urllib.error.HTTPError as e:
            if AnthropicAPI.is_retryable(e.code) and attempt < AnthropicAPI.MAX_RETRIES - 1:
                time.sleep(AnthropicAPI.BACKOFF_BASE ** attempt * 2); continue
            raise
    return [], 0, 0


def _locate_start(book_dir, nums, ch, search_from):
    """장 ch={num,title}의 시작 캡처 페이지를 전사 텍스트에서 찾음.
    앵커 우선순위: (1) 'N장'/'제N장'/'chapter N' 헤딩 + 제목, (2) 헤딩만, (3) 긴 제목 단독 매칭."""
    num, title = ch.get("num", 0), (ch.get("title") or "").strip()
    tn = _norm(title)
    # 장번호 헤딩 패턴(정규화 전 원문에서 검사)
    head_pats = []
    if num:
        head_pats = [re.compile(rf"(?m)^\s*(?:제\s*)?{num}\s*장\b"),
                     re.compile(rf"(?i)\bchapter\s*0*{num}\b"),
                     re.compile(rf"(?m)^\s*부록\s*{num}\b")]
    best = None  # (점수, page)
    for n in nums:
        if n < search_from:
            continue
        raw = _ocr_text(book_dir, n)
        if not raw:
            continue
        head_hit = any(p.search(raw[:400]) for p in head_pats)   # 헤딩은 페이지 상단
        title_hit = bool(tn) and len(tn) >= 4 and tn in _norm(raw)
        if head_hit and title_hit:
            return n, 3          # 최상: 장번호+제목 동시 → 즉시 확정
        score = 2 if head_hit else (1 if title_hit else 0)
        if score and (best is None or score > best[0]):
            best = (score, n)
    return (best[1], best[0]) if best else (None, 0)


def generate_chapters_via_toc(book_dir, cfg):
    """목차 기반 chapters.json 생성(색표지 없는 책 대응). 반환 chapters 리스트(빈 리스트 가능)."""
    book_dir = Path(book_dir)
    sd = book_dir / "summary"; sd.mkdir(exist_ok=True)
    files = _page_files(book_dir)
    if not files:
        return []
    nums = [int(f.stem.split("_")[1]) for f in files]
    last_page = nums[-1]
    toc_pages = find_toc_pages(book_dir)
    if not toc_pages:
        print("[chapters/toc] 목차 페이지 후보 없음 — TOC 경로 스킵")
        return []
    key = cfg.api_key
    model = getattr(cfg, "model", None) or AnthropicAPI.DEFAULT_MODEL
    # 목차 페이지들에서 장 목록 수집(순서 유지, num으로 중복 제거)
    raw_ch, ci, co = [], 0, 0
    for p in toc_pages:
        lst, ti, to = _read_toc(key, model, book_dir / f"page_{p:03d}.png")
        ci += ti; co += to
        raw_ch.extend(lst)
    if ci or co:
        from . import cost as _cost
        _cost.record(book_dir, "chapters-toc", model, ci, co, AnthropicAPI.cost_usd(model, ci, co))
    # 중복 제거: 번호 있는 장은 **번호 기준**(같은 장이 스프레드 경계로 두 목차페이지에 걸쳐 두 번 잡힘 —
    #   제목이 미세하게 달라도 같은 장). 번호 없는 부록(num=0)은 제목 기준.
    seen_num, seen_title, toc_ch = set(), set(), []
    for c in raw_ch:
        t = (c.get("title") or "").strip()
        if not t:
            continue
        # 문장형 '제목' 거부(산문 오탐 방어): 너무 긴 것만. (짧은 제목이 '~합니다'로 끝나는 건
        #  정상 — 예 '딥러닝을 시작합니다'. 종결어미로만 거르면 진짜 장 제목을 놓침 — 2026-07-18 수정)
        if len(t) > 40:
            print(f"[chapters/toc] ⚠ 제목 같지 않아 제외(너무 김): {t[:30]}…")
            continue
        num = c.get("num", 0) or 0
        if num:
            if num in seen_num:
                continue
            seen_num.add(num)
        else:
            nt = _norm(t)
            if nt in seen_title:
                continue
            seen_title.add(nt)
        toc_ch.append({"num": num, "title": t})
    if not toc_ch:
        print(f"[chapters/toc] 목차에서 장 못 뽑음(비전 in={ci} out={co})")
        return []
    # 각 장 시작 페이지를 전사 텍스트에서 위치 검색(목차 페이지 이후부터)
    after = max(toc_pages)
    located = []
    search_from = after + 1
    for ch in toc_ch:
        pg, score = _locate_start(book_dir, nums, ch, search_from)
        if pg:
            located.append({"num": ch["num"], "title": ch["title"], "start": pg, "score": score})
            search_from = pg + 1
        else:
            print(f"[chapters/toc] ⚠ '{ch['title']}' 본문 위치 못 찾음 — 스킵")
    # sanity: 진짜 챕터라면 시작들이 책 전반에 퍼져 있어야 함. 좁은 후반부에 몰리면(섹션목록 오검출)
    #   신뢰 불가 → 빈 리스트(가비지로 chapters.json 오염 방지).
    located.sort(key=lambda x: x["start"])
    located = _drop_false_chapters(located)   # 중복/역행 장번호 제거(스프레드 경계로 같은 장이 두 목차페이지에 걸침)
    if len(located) >= 2 and last_page > 0:
        span = (located[-1]["start"] - located[0]["start"]) / last_page
        first_pos = located[0]["start"] / last_page
        if span < 0.30 or first_pos > 0.6:
            print(f"[chapters/toc] ⚠ 시작 분포 비정상(span={span:.2f}, first={first_pos:.2f}) — 신뢰 불가, 스킵")
            return []
    # contiguity 게이트(2026-07-18): 불완전한 결과로 수동본을 덮지 않도록 — 장 번호가 1..K 연속이고
    #   추출한 TOC 장을 전부 위치확인했을 때만 채택. 구멍/누락이 있으면 스킵(→ 0장, 수동 유지).
    if len(located) < len(toc_ch):
        print(f"[chapters/toc] ⚠ 추출 {len(toc_ch)}장 중 {len(located)}장만 위치확인 — 불완전, 스킵")
        return []
    numbered = sorted(c["num"] for c in located if c.get("num"))
    if numbered and (numbered[0] > 1 or numbered != list(range(numbered[0], numbered[0] + len(numbered)))):
        print(f"[chapters/toc] ⚠ 장 번호 불연속/누락 {numbered} — 불완전, 스킵(수동본 보호)")
        return []
    # 경계 계산
    chapters = []
    for i, c in enumerate(located):
        end = (located[i + 1]["start"] - 1) if i + 1 < len(located) else last_page
        chapters.append({"num": c["num"] or (i + 1), "title": c["title"],
                         "start": c["start"], "end": end, "summary": "", "topics": []})
    (sd / "chapters.json").write_text(
        json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[chapters/toc] 목차 p{toc_pages} → 장 {len(chapters)} (비전 in={ci} out={co})")
    for c in chapters:
        print(f"  {c['num']}장 {c['title']} (p.{c['start']}~{c['end']})")
    return chapters


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


def text_density(path, grid=(150, 100)):
    """어두운(텍스트) 픽셀 비율. 챕터 표지·구분 페이지는 대체로 저밀도(큰 제목만)."""
    from PIL import Image
    d = list(Image.open(path).convert("L").resize(grid).getdata())
    return sum(1 for p in d if p < 110) / len(d)


def cover_candidates(book_dir, min_frac=0.30, low_density_max=0.010,
                     blank_min=0.0002, max_low=25):
    """장/절 표지 후보 — 두 신호를 합침(색표지 없는 책도 감지 넓힘, 2026-07-14):
      (1) **지배색 큰 페이지**(베이지 등 색표지),
      (2) **저-텍스트밀도 페이지**(색 없이 큰 제목만 있는 챕터 표지/구분). 단 blank(내용 0)는 제외.
    최종 '장 표지' 판정은 비전(_read_cover)이 하므로 후보를 넓게 잡아도 됨(퀴즈·본문은 비전이 걸러냄).
    """
    files = _page_files(book_dir)
    cands = {}
    lows = []
    for f in files:
        n = int(f.stem.split("_")[1])
        frac, col = dominant_color_frac(f)
        if frac >= min_frac:
            cands[n] = {"page": n, "frac": round(frac, 3), "color": col, "why": "color"}
        td = text_density(f)
        if blank_min <= td <= low_density_max:   # 저밀도(제목 위주). blank(td<blank_min) 제외
            lows.append((td, n))
    lows.sort()  # 밀도 낮은 순
    for td, n in lows[:max_low]:
        cands.setdefault(n, {"page": n, "td": round(td, 4), "why": "low-density"})
    return sorted(cands.values(), key=lambda c: c["page"])


def _img_b64(path, max_w=AnthropicAPI.VISION_MAX_W):
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
        "model": model, "max_tokens": 300, "temperature": AnthropicAPI.DETECT_TEMPERATURE,
        "system": _SYS,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                          "data": _img_b64(path)}},
            {"type": "text", "text": "이 페이지가 장 표지인지 판정하고 report_cover 로 제출."},
        ]}],
        "tools": [tool], "tool_choice": {"type": "tool", "name": "report_cover"},
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": AnthropicAPI.API_VERSION, "content-type": "application/json"})
    for attempt in range(AnthropicAPI.MAX_RETRIES):
        try:
            r = urllib.request.urlopen(req, timeout=AnthropicAPI.TIMEOUT_VISION)
            d = json.load(r)
            for b in d.get("content", []):
                if b.get("type") == "tool_use":
                    u = d.get("usage", {})
                    return b["input"], u.get("input_tokens", 0), u.get("output_tokens", 0)
            return None, 0, 0
        except urllib.error.HTTPError as e:
            if AnthropicAPI.is_retryable(e.code) and attempt < AnthropicAPI.MAX_RETRIES - 1:
                time.sleep(AnthropicAPI.BACKOFF_BASE ** attempt * 2); continue
            raise
    return None, 0, 0


def _drop_false_chapters(chs):
    """가짜 장 제거(안정화) — 페이지순으로 보며 장 번호가 **이전 채택 장 이하로 역행/중복**하면
    섹션 표지의 오검출로 보고 드롭한다. (예: 1장 뒤 다시 num=1 '텐서플로' → 제거.)
    num=0(부록·미상)은 번호가 없으므로 위치 순서로 통과시킨다."""
    out, maxnum = [], 0
    for c in chs:
        n = c.get("num", 0) or 0
        if n and n <= maxnum:
            print(f"[chapters] ⚠ 가짜 장 제거(번호 {n}<= 이전 {maxnum}): {c.get('title', '')[:24]}")
            continue
        out.append(c)
        maxnum = max(maxnum, n)
    return out


def generate_chapters(book_dir, cfg, min_frac=0.30, include_sections=False):
    """비전으로 chapters.json 생성. cfg=AiCfg(api_key/model). 반환 chapters 리스트."""
    book_dir = Path(book_dir)
    sd = book_dir / "summary"; sd.mkdir(exist_ok=True)
    files = _page_files(book_dir)
    last_page = int(files[-1].stem.split("_")[1]) if files else 0
    cands = cover_candidates(book_dir, min_frac=min_frac)
    key = cfg.api_key
    model = getattr(cfg, "model", None) or AnthropicAPI.DEFAULT_MODEL
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
    if ci or co:   # 결과(성공/스킵) 무관하게 소비된 비전 비용 기록
        from . import cost as _cost
        _cost.record(book_dir, "chapters", model, ci, co, AnthropicAPI.cost_usd(model, ci, co))
    # 페이지순 정렬 + 경계 계산(chapter 만 경계)
    covers.sort(key=lambda x: x["page"])
    chs = [c for c in covers if c["level"] == "chapter"]
    chs = _drop_false_chapters(chs)   # 번호 역행/중복 = 섹션 오검출 제거(안정화 2026-07-18)
    # 완전성 검사(2026-07-19, '인공지능 개념 사전' 검증에서 발견): 비전이 읽은 장 번호에 큰 구멍이
    #   있으면(컬러 장표지 없는 장을 놓침) 순차 재번호(i+1)가 그 불완전성을 숨겨 **위조 연속번호**를
    #   만든다(실제 1·3·8·9·10·11·13 → 가짜 1~7). → 번호가 촘촘(구멍 ≤2, 1~2에서 시작)할 때만
    #   재번호로 소소한 오류 교정(부록 '9장'→'8장'), 구멍 크면 스킵(수동 chapters.json 또는 목차 필요).
    vnums = [c["num"] for c in chs if c.get("num")]
    dense = bool(vnums) and min(vnums) <= 2 and ((max(vnums) - min(vnums) + 1) - len(vnums) <= 2)
    if chs and not dense:
        print(f"[chapters] ⚠ cover 감지 불완전 — 실제 장번호 {sorted(vnums)} 구멍 큼(컬러 장표지 없는 장 누락). "
              f"위조 연속번호 대신 스킵 → 수동 chapters.json 또는 목차 경로 필요.")
        return []
    chapters = []
    for i, c in enumerate(chs):
        start = c["page"]
        end = (chs[i + 1]["page"] - 1) if i + 1 < len(chs) else last_page
        # dense 일 때만 여기 도달 → 위치 순 1..N 재번호 안전(부록 '9장'→'8장' 등 교정)
        chapters.append({"num": i + 1, "title": c["title"],
                         "start": start, "end": end, "summary": "", "topics": []})
    (sd / "chapters.json").write_text(
        json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[chapters] 후보 {len(cands)} → 장 {len(chapters)} (비전 in={ci} out={co})")
    for c in chapters:
        print(f"  {c['num']}장 {c['title']} (p.{c['start']}~{c['end']})")
    return chapters
