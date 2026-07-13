# -*- coding: utf-8 -*-
"""캡처 오염 검사 (비전) — 마우스 커서·알림 배너·토스트/팝업·비책(터미널 등) 혼입 감지.

배경(2026-07-13): WID(-l) 캡처는 창 내용만 찍어 깨끗하지만, WID 실패 시 -R 영역 폴백이
교보가 최전면 아닐 때 **터미널을 찍는 오염** 사고(page_369). 1차 방어는 capture 의 최전면 게이트,
이건 **게시 전 안전망** — 각 페이지를 Claude 비전으로 훑어 오염 페이지를 표시/제거한다.

싸게: 기본 Haiku(간단한 시각 판정). remove=True 면 오염 페이지 + 대응 thumbs/raw 삭제.
CLI: bookcapture contamination-check --book-dir <책> [--remove]
"""
from __future__ import annotations
from .anthropic_api import AnthropicAPI
import io, base64, json, time, urllib.request, urllib.error
from pathlib import Path

API_URL = AnthropicAPI.API_URL
_TOOL = {
    "name": "report_contamination", "description": "캡처 오염 판정",
    "input_schema": {"type": "object", "properties": {
        "cursor": {"type": "boolean", "description": "마우스 커서(화살표 포인터)가 보이면 true"},
        "notification": {"type": "boolean", "description": "macOS 알림배너·토스트·팝업·다이얼로그가 보이면 true"},
        "non_book": {"type": "boolean", "description": "책 본문이 아닌 것(터미널·바탕화면·다른 앱 창)이 섞였으면 true"},
        "note": {"type": "string", "description": "한 줄 근거"},
    }, "required": ["cursor", "notification", "non_book", "note"]},
}


def _b64(path, max_w=AnthropicAPI.VISION_MAX_W):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "PNG", optimize=True)
    return base64.b64encode(b.getvalue()).decode()


def _check_one(key, model, path):
    body = json.dumps({
        "model": model, "max_tokens": 250,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(path)}},
            {"type": "text", "text": "이 캡처 이미지에 마우스 커서·알림배너·토스트/팝업·비책(터미널 등) 콘텐츠가 "
                                     "섞였는지 report_contamination 으로 판정."},
        ]}],
        "tools": [_TOOL], "tool_choice": {"type": "tool", "name": "report_contamination"},
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": AnthropicAPI.API_VERSION, "content-type": "application/json"})
    for attempt in range(AnthropicAPI.MAX_RETRIES):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=AnthropicAPI.TIMEOUT_QUICK))
            for b in d.get("content", []):
                if b.get("type") == "tool_use":
                    return b["input"]
            return None
        except urllib.error.HTTPError as e:
            if AnthropicAPI.is_retryable(e.code) and attempt < AnthropicAPI.MAX_RETRIES - 1:
                time.sleep(AnthropicAPI.BACKOFF_BASE ** attempt * 2); continue
            raise
    return None


def is_contaminated_page(path, cfg, model=AnthropicAPI.VISION_MODEL, brightness_gate=125):
    """캡처 1장이 오염(커서·알림·비책)인지 판정 → (bool, reasons).
    싼 사전필터: 책 페이지는 밝음(흰 배경, mean≥gate) → 비전 생략(오염 아님).
    어두운 캡처(터미널 등)만 비전 확인 → 비용·시간 절약. 인라인 재캡처용."""
    try:
        from PIL import Image, ImageStat
        mean = ImageStat.Stat(Image.open(path).convert("L")).mean[0]
    except Exception:
        return False, []
    if mean >= brightness_gate:
        return False, []
    key = cfg.api_key
    if not key:
        return False, []
    info = _check_one(key, getattr(cfg, "model", None) or model, path)
    if not info:
        return False, []
    reasons = [k for k in ("cursor", "notification", "non_book") if info.get(k)]
    return bool(reasons), reasons


def check_contamination(book_dir, cfg, model=AnthropicAPI.VISION_MODEL, remove=False):
    """책 폴더 page_*.png 전수 오염 검사. 반환 {checked, flagged:[{page,reasons,note}], removed:[]}.
    remove=True 면 오염 페이지 + thumbs/ + source_raws/ 대응분 삭제."""
    book_dir = Path(book_dir)
    key = cfg.api_key
    if not key:
        return {"checked": 0, "flagged": [], "removed": [], "error": "API 키 없음"}
    pages = sorted(book_dir.glob("page_*.png"), key=lambda p: p.name)
    flagged, removed = [], []
    for f in pages:
        info = _check_one(key, model, f)
        if not info:
            continue
        reasons = [k for k in ("cursor", "notification", "non_book") if info.get(k)]
        if reasons:
            n = int(f.stem.split("_")[1])
            flagged.append({"page": n, "reasons": reasons, "note": info.get("note", "")})
            print(f"  ⚠️ page_{n:03d}: {reasons} — {info.get('note','')[:70]}")
            if remove:
                f.unlink(missing_ok=True)
                (book_dir / "thumbs" / f.name).unlink(missing_ok=True)
                (book_dir / "source_raws" / f"raw_{n:03d}.png").unlink(missing_ok=True)
                removed.append(n)
    print(f"[contamination] {len(pages)}장 검사 · 오염 {len(flagged)}장" +
          (f" · 제거 {len(removed)}장" if remove else ""))
    return {"checked": len(pages), "flagged": flagged, "removed": removed}
