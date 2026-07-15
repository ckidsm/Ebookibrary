"""백엔드 /api/settings 에서 설정을 가져오고, 환경변수가 있으면 우선 적용.

API 키 같은 민감 정보는 응답에서 마스킹되므로 환경변수로 따로 받는다:
- ANTHROPIC_API_KEY
- OPENAI_API_KEY
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# 기본 백엔드 = 도메인 기반(어디서든 도달). LAN IP 하드코딩 금지 — VPN/네트워크 무관하게 동작해야 함.
#   외부/일반: https://redcodeme.synology.me:9443 (Synology Reverse Proxy → 컨테이너 9000)
#   LAN 전용 설치 등 특수 상황은 KYOBO_BRIDGE_URL 환경변수로 오버라이드(예: http://192.168.10.205:9000).
DEFAULT_BRIDGE_URL = os.environ.get(
    "KYOBO_BRIDGE_URL",
    "https://redcodeme.synology.me:9443",
)


@dataclass
class CaptureCfg:
    region: dict = field(default_factory=lambda: {"x": 0, "y": 0, "w": 0, "h": 0})
    delay_sec: float = 1.5
    max_pages: int = 400
    next_key: str = "right"
    first_page_wait: float = 3.0
    skip_duplicate_hash: bool = True


@dataclass
class OcrCfg:
    lang: str = "kor+eng"
    use_thumbs: bool = True


@dataclass
class AiCfg:
    provider: str = "claude"
    model: str = "claude-sonnet-4-5"
    api_key: str = ""           # 환경변수에서 채워짐
    language: str = "ko"
    temperature: float = 0.3
    # 요약·개요 전용(저비용) 모델 — Gemini 전사가 이미 깨끗한 텍스트를 주므로 텍스트요약을
    # 싼 Haiku 로 해도 정확. 이미지(비전)요약보다 대폭 저렴(2026-07-15).
    summarize_model: str = "claude-haiku-4-5"
    # OCR/본문전사 전용 엔진 — Gemini 가 Claude 대비 ~18배 싸고 품질 동등~우세(2026-07-15)
    ocr_provider: str = "gemini"          # gemini | claude (전사 엔진)
    gemini_api_key: str = ""              # 환경변수 GEMINI_API_KEY/GOOGLE_API_KEY
    gemini_model: str = "gemini-2.5-flash"


@dataclass
class OutputCfg:
    books_dir: str = "./books"
    thumb_max_px: int = 1800


@dataclass
class Settings:
    capture: CaptureCfg = field(default_factory=CaptureCfg)
    ocr: OcrCfg = field(default_factory=OcrCfg)
    ai: AiCfg = field(default_factory=AiCfg)
    output: OutputCfg = field(default_factory=OutputCfg)


def _merge_dc(dc: Any, src: dict) -> None:
    if not isinstance(src, dict):
        return
    for k, v in src.items():
        if hasattr(dc, k):
            cur = getattr(dc, k)
            if isinstance(cur, dict) and isinstance(v, dict):
                cur.update(v)
            else:
                setattr(dc, k, v)


def load(bridge_url: str | None = None) -> Settings:
    s = Settings()

    # 1) 백엔드에서 가져오기 (실패해도 기본값으로 진행) — urllib(표준 라이브러리)만 사용
    url = (bridge_url or DEFAULT_BRIDGE_URL).rstrip("/") + "/api/settings"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = (json.loads(resp.read().decode("utf-8")) or {}).get("settings", {})
            _merge_dc(s.capture, data.get("capture") or {})
            _merge_dc(s.ocr, data.get("ocr") or {})
            _merge_dc(s.ai, data.get("ai") or {})
            _merge_dc(s.output, data.get("output") or {})
    except Exception as e:
        print(f"[settings] 백엔드 로드 실패 ({url}): {e} — 기본값 사용")

    # 2) 키 조회 우선순위: 환경변수 → 백엔드 LAN secret endpoint → (마스킹된 응답값)
    env_key = None
    if s.ai.provider == "claude":
        env_key = os.environ.get("ANTHROPIC_API_KEY")
    elif s.ai.provider == "openai":
        env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        s.ai.api_key = env_key

    # Gemini(전사 엔진) 키 — 환경변수 우선
    gkey = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if gkey:
        s.ai.gemini_api_key = gkey

    if not s.ai.api_key:
        # 환경변수도 없고 1)단계 응답은 마스킹뿐 → LAN secret 으로 평문 시도
        secret_url = (bridge_url or DEFAULT_BRIDGE_URL).rstrip("/") + "/api/secrets/ai"
        try:
            req = urllib.request.Request(secret_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("api_key"):
                    s.ai.api_key = data["api_key"]
        except Exception as e:
            print(f"[settings] secret 로드 실패 ({secret_url}): {e}")

    return s


def explain(s: Settings) -> str:
    """가독성 좋은 한 줄 요약 (로그용)."""
    r = s.capture.region
    key_mask = f"{s.ai.api_key[:7]}..." if s.ai.api_key else "(없음)"
    return (
        f"capture[{r['x']},{r['y']} {r['w']}×{r['h']}] "
        f"delay={s.capture.delay_sec}s max={s.capture.max_pages} key={s.capture.next_key} | "
        f"ocr[{s.ocr.lang}, thumbs={s.ocr.use_thumbs}] | "
        f"ai[{s.ai.provider}/{s.ai.model}, key={key_mask}] | "
        f"ocr전사[{s.ai.ocr_provider}/{s.ai.gemini_model}, "
        f"gkey={'있음' if s.ai.gemini_api_key else '없음'}] | "
        f"out={s.output.books_dir}"
    )
