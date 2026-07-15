# -*- coding: utf-8 -*-
"""Google Gemini API 상수·헬퍼 (OCR/본문전사용 — Claude 대비 ~18배 저렴).

교보 이북 OCR/전사는 Gemini 2.5-flash 가 Claude 비전과 품질 동등~우세인데 훨씬 싸서
(2026-07-15 실측 비교) 전사 기본 엔진으로 채택. anthropic_api.AnthropicAPI 와 같은 계층.

키: 환경변수 GEMINI_API_KEY(또는 GOOGLE_API_KEY). billing 활성 키 권장
    (무료 티어는 503 과부하·429 쿼터로 전권 실행 불안정).
"""
from __future__ import annotations
import base64
import io
import json
import time
import urllib.request
import urllib.error


class GeminiAPI:
    """Gemini generateContent 파라미터. 클래스 상수로 참조."""
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    DEFAULT_MODEL = "gemini-2.5-flash"     # OCR/전사 품질·가성비 최적(실측)

    # 가격 ($/1M 토큰) = (input, output). thinking 끄면 output=전사 토큰만.
    PRICES = {
        "gemini-2.5-flash":      (0.30, 2.50),
        "gemini-2.5-pro":        (1.25, 10.0),
        "gemini-2.0-flash":      (0.10, 0.40),
        "gemini-2.0-flash-lite": (0.075, 0.30),
    }
    DEFAULT_PRICE = (0.30, 2.50)

    MAX_RETRIES = 6
    RETRY_STATUS = (429, 500, 503)         # 429 쿼터·503 과부하(무료 티어 잦음)
    BACKOFF_BASE = 2

    VISION_MAX_W = 1500                     # 전사 이미지 다운스케일 폭(px)
    TIMEOUT = 120

    @classmethod
    def price(cls, model):
        return cls.PRICES.get(model, cls.DEFAULT_PRICE)

    @classmethod
    def is_retryable(cls, status_code):
        return status_code in cls.RETRY_STATUS


def img_b64(path, max_w: int = GeminiAPI.VISION_MAX_W) -> str:
    """페이지 이미지 → base64 JPEG(전사엔 JPEG 품질 88이면 충분·전송 작음)."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def generate(api_key: str, model: str, prompt: str, image_b64: str | None = None,
             max_tokens: int = 8000, temperature: float = 0.0,
             thinking: bool = False) -> tuple[str, int, int]:
    """Gemini generateContent 호출 → (text, in_tokens, out_tokens). 429/503 재시도.
    thinking=False 면 thinkingBudget=0 로 사고토큰 비용 제거(전사엔 불필요)."""
    parts = []
    if image_b64:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})
    parts.append({"text": prompt})
    gen_cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if not thinking:
        gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
    body = {"contents": [{"parts": parts}], "generationConfig": gen_cfg}
    url = f"{GeminiAPI.BASE}/{model}:generateContent?key={api_key}"
    last = None
    for attempt in range(1, GeminiAPI.MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=GeminiAPI.TIMEOUT) as r:
                d = json.load(r)
            cand = (d.get("candidates") or [{}])[0]
            txt = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
            u = d.get("usageMetadata", {})
            return txt.strip(), u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:200]
            last = f"HTTP {e.code}: {msg}"
            if "quota" in msg.lower() and e.code == 429:
                # 일일/RPM 쿼터 소진 — 재시도해도 소용, 상위에서 중단 처리
                raise RuntimeError("gemini quota exceeded")
            if GeminiAPI.is_retryable(e.code) and attempt < GeminiAPI.MAX_RETRIES:
                time.sleep(min(GeminiAPI.BACKOFF_BASE ** attempt * 2, 40)); continue
            raise RuntimeError(last)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < GeminiAPI.MAX_RETRIES:
                time.sleep(GeminiAPI.BACKOFF_BASE ** attempt); continue
            raise
    raise RuntimeError(last or "gemini 재시도 초과")
