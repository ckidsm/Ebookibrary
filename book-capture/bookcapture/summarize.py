"""AI 요약 모듈 — OCR 텍스트 → batch JSON 페이지 객체.

기존 CLI_완전활용/summary/batch_NNN.json 스키마를 그대로 따른다:
{
  "num": 127,
  "topics": ["주제1", ...],          # 2~3개
  "terms":  ["용어1", ...],          # 3~5개
  "summary": "...<br>...<br>...",   # 3~5문장
  "points": ["포인트1", ...],        # 3~5개
  "chapter_intro": {...}            # 옵션 — 절 도입 페이지만
}

API: Anthropic Messages API (urllib 만 사용, 의존성 0).
"""

from __future__ import annotations
from .anthropic_api import AnthropicAPI

import base64
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .settings import AiCfg

API_URL = AnthropicAPI.API_URL
API_VERSION = AnthropicAPI.API_VERSION


SYSTEM_PROMPT = """\
당신은 한국어 기술 도서를 학습용으로 요약하는 전문가입니다.
주어진 페이지의 OCR 텍스트를 분석하여, 지정된 JSON 형식으로만 응답하세요.

원칙:
- 본문에 실제로 있는 내용만 작성. 추측·상상 금지.
- 절 번호·소제목 식별 (예: 4.1, 4.1.1).
- 본문이 짧거나 거의 비어 있으면 빈 배열·빈 문자열로 반환.
- JSON 외 다른 텍스트 절대 금지 (코드 펜스 ```도 금지).
"""


def build_user_prompt(num: int, ocr_text: str, is_chapter_intro_hint: bool = False) -> str:
    intro_note = ""
    if is_chapter_intro_hint:
        intro_note = (
            '\n- 이 페이지가 새 절/장의 첫 페이지로 보이면 "chapter_intro": '
            '{"title": "<절 제목>", "overview": "<2~3문장 요약>"} 도 추가.\n'
        )
    return f"""\
페이지 번호: {num}

OCR 원문:
---
{ocr_text.strip() or "(OCR 결과 비어있음)"}
---

다음 JSON 형식으로만 응답:
{{
  "num": {num},
  "topics": ["...", "..."],          // 2~3개, 페이지가 다루는 큰 주제
  "terms":  ["...", "...", "..."],   // 3~5개, 핵심 키워드/용어
  "summary": "...<br>...",           // 3~5문장. 마침표마다 <br> 줄바꿈. 절 번호 앞엔 ·
  "points": ["...", "..."]           // 3~5개, 구체적 포인트 (li 후보)
}}
규칙:
- "summary" 는 한 줄 문자열, 문장 사이 <br> 만 사용.
- "points" 는 굵게 표시할 소제목은 <strong>...</strong>, 코드/경로는 <code>...</code> 가능.
- JSON 객체만 출력. 코드 펜스, 설명, 인사말 모두 금지.{intro_note}
"""


# ─────────────────────────────────────────────────────────────
# 비전 요약 — OCR 이 mojibake(한글 폰트 깨짐)인 책용.
# OCR 텍스트 대신 **페이지 이미지**를 직접 Claude 에 보내 요약한다.
# (코드추출·챕터감지가 이미 비전으로 정확 → 요약도 비전이면 TOC·산문 페이지 환각 0)
# ─────────────────────────────────────────────────────────────
VISION_SYSTEM_PROMPT = """\
당신은 한국어 기술 도서를 학습용으로 요약하는 전문가입니다.
주어진 책 페이지 이미지를 직접 보고, 지정된 JSON 형식으로만 응답하세요.

원칙:
- 이미지에 실제로 보이는 내용만 작성. 추측·상상·환각 절대 금지.
- 이미지가 목차/색인/표지/판권/장 구분 페이지면 그 성격을 그대로 반영(억지 내용 생성 금지).
- 코드가 보이면 코드가 하는 일을, 그림/그래프가 보이면 그 의미를 설명.
- 절 번호·소제목이 보이면 식별 (예: 4.1, 4.1.1).
- 본문이 짧거나 거의 비어 있으면 빈 배열·빈 문자열로 반환.
- JSON 외 다른 텍스트 절대 금지 (코드 펜스 ```도 금지).
"""


def build_vision_user_prompt(num: int, is_chapter_intro_hint: bool = False) -> str:
    intro_note = ""
    if is_chapter_intro_hint:
        intro_note = (
            '\n- 이 페이지가 새 절/장의 첫 페이지로 보이면 "chapter_intro": '
            '{"title": "<절 제목>", "overview": "<2~3문장 요약>"} 도 추가.\n'
        )
    return f"""\
이것은 책의 {num}번째 페이지 이미지입니다. 페이지를 보고 다음 JSON 형식으로만 응답:
{{
  "num": {num},
  "topics": ["...", "..."],          // 2~3개, 페이지가 다루는 큰 주제
  "terms":  ["...", "...", "..."],   // 3~5개, 핵심 키워드/용어
  "summary": "...<br>...",           // 3~5문장. 마침표마다 <br> 줄바꿈. 절 번호 앞엔 ·
  "points": ["...", "..."]           // 3~5개, 구체적 포인트 (li 후보)
}}
규칙:
- "summary" 는 한 줄 문자열, 문장 사이 <br> 만 사용.
- "points" 는 굵게 표시할 소제목은 <strong>...</strong>, 코드/경로는 <code>...</code> 가능.
- 페이지에 내용이 거의 없으면(표지·간지 등) topics/terms/points 는 빈 배열, summary 는 그 성격만 짧게.
- JSON 객체만 출력. 코드 펜스, 설명, 인사말 모두 금지.{intro_note}
"""


def _img_b64(path: Path, max_w: int = AnthropicAPI.CODE_MAX_W) -> str:
    """페이지 PNG → base64 (긴 변 기준 다운스케일). 한글 가독성 위해 CODE_MAX_W(1500) 사용."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def summarize_page_vision(
    num: int,
    img_path: Path,
    cfg: AiCfg,
    is_chapter_intro_hint: bool = False,
    max_retries: int = 3,
) -> "SummarizeResult":
    """페이지 이미지 1장 → batch JSON 페이지 객체 (비전, OCR 무관)."""
    if not cfg.api_key:
        raise RuntimeError(
            "AI API 키 없음. 환경변수 ANTHROPIC_API_KEY 설정하거나 "
            "메인 ⚙ 설정에서 키 저장 후 다시 시도하세요."
        )
    b64 = _img_b64(img_path)
    body = {
        "model": cfg.model,
        "max_tokens": 4000,
        "temperature": cfg.temperature,
        "system": VISION_SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/png", "data": b64}},
                {"type": "text", "text": build_vision_user_prompt(num, is_chapter_intro_hint)},
            ]},
        ],
    }
    req = urllib.request.Request(
        API_URL, method="POST",
        headers={"x-api-key": cfg.api_key, "anthropic-version": API_VERSION,
                 "content-type": "application/json"},
        data=json.dumps(body).encode("utf-8"),
    )
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=AnthropicAPI.TIMEOUT_VISION) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                text = "".join(b.get("text", "") for b in payload.get("content", []))
                usage = payload.get("usage", {})
                in_t = usage.get("input_tokens", 0)
                out_t = usage.get("output_tokens", 0)
                try:
                    page = _extract_json(text)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"JSON 파싱 실패: {e}\n---\n{text[:500]}")
                page["num"] = num
                return SummarizeResult(page=page, input_tokens=in_t, output_tokens=out_t,
                                       raw_text=text, cost_usd=_price(cfg.model, in_t, out_t))
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode("utf-8", errors="replace")[:300]
            last_err = f"HTTP {e.code} {e.reason}: {body_txt}"
            if "credit balance is too low" in body_txt:
                raise RuntimeError("credit balance is too low")
            if AnthropicAPI.is_retryable(e.code) and attempt < max_retries:
                time.sleep(2 ** attempt); continue
            raise RuntimeError(last_err)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < max_retries:
                time.sleep(2 ** attempt); continue
            raise
    raise RuntimeError(last_err or "알 수 없는 오류")


@dataclass
class SummarizeResult:
    page: dict           # 파싱된 batch JSON 페이지 객체
    input_tokens: int
    output_tokens: int
    raw_text: str        # 디버그용
    cost_usd: float


# Claude 가격표 (per 1M tokens, 2026-05 시점 — 변경 시 갱신)
_PRICES = AnthropicAPI.PRICES

def _price(model: str, in_tok: int, out_tok: int) -> float:
    in_p, out_p = AnthropicAPI.price(model)
    return in_tok / 1_000_000 * in_p + out_tok / 1_000_000 * out_p


# 캡처 도중 화면 위로 올라온 터미널/콘솔이 책 대신 찍히는 오염(#page17 사고) 방지.
# 책에는 절대 안 나오고 "이 작업 환경"에서만 나오는 지문만 사용 → 오탐 최소화.
# (일반 셸 단어 curl/grep 등은 HTTP 책 예제에 나올 수 있어 제외)
_CONSOLE_FINGERPRINTS = (
    "/Users/deoksooyun",          # macOS 홈 경로
    "OneDrive",
    "KyoboLibrary",
    "book-capture",
    "bookcapture",
    "deploy.sh",
    "summary/thumbs",
    "ocr_text",
    "192.168.10.205",             # NAS 고정 IP (예제 IP 오탐 피하려 풀 IP)
    "kyobo-bridge",
    "redcodeme",
    ".synology.me",
)
_CONSOLE_FILE_PATTERNS = (
    re.compile(r"page_\d{3}\.(png|txt)"),   # 썸네일/OCR 파일명
    re.compile(r"batch_\d{3}\.json"),       # batch 산출물명
)


def is_contaminated_ocr(text: str) -> tuple[bool, str]:
    """OCR 텍스트가 책 페이지가 아니라 우리 콘솔/터미널 화면인지 판정.

    Returns: (오염여부, 근거 문자열). 지문 하나라도 걸리면 오염으로 본다
    (모두 이 환경 고유 문자열이라 책 본문엔 등장하지 않음).
    """
    for fp in _CONSOLE_FINGERPRINTS:
        if fp in text:
            return True, fp
    for pat in _CONSOLE_FILE_PATTERNS:
        m = pat.search(text)
        if m:
            return True, m.group(0)
    return False, ""


def _extract_json(text: str) -> dict:
    """모델 응답에서 JSON 객체만 추출. 코드 펜스/잡담 제거."""
    s = text.strip()
    # 코드펜스 제거 — 닫는 ``` 가 없어도(응답 truncate) 안전하게.
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    # 첫 { 부터 마지막 } 까지
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        s = s[i:j + 1]
    return json.loads(s)


def summarize_page(
    num: int,
    ocr_text: str,
    cfg: AiCfg,
    is_chapter_intro_hint: bool = False,
    max_retries: int = 3,
) -> SummarizeResult:
    """OCR 1페이지 → batch JSON 1페이지 객체."""
    if not cfg.api_key:
        raise RuntimeError(
            "AI API 키 없음. 환경변수 ANTHROPIC_API_KEY 설정하거나 "
            "메인 ⚙ 설정에서 키 저장 후 다시 시도하세요."
        )

    body = {
        "model": cfg.model,
        # 4000: 코드·용어 많은 페이지는 1500 으로 잘려 JSON truncate → 파싱 실패.
        "max_tokens": 4000,
        "temperature": cfg.temperature,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": build_user_prompt(num, ocr_text, is_chapter_intro_hint)},
        ],
    }
    req = urllib.request.Request(
        API_URL,
        method="POST",
        headers={
            "x-api-key": cfg.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        },
        data=json.dumps(body).encode("utf-8"),
    )

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=AnthropicAPI.TIMEOUT_QUICK) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                text = payload["content"][0]["text"]
                usage = payload.get("usage", {})
                in_t = usage.get("input_tokens", 0)
                out_t = usage.get("output_tokens", 0)
                try:
                    page = _extract_json(text)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"JSON 파싱 실패: {e}\n---\n{text[:500]}")
                # 안전망 — num 강제
                page["num"] = num
                return SummarizeResult(
                    page=page,
                    input_tokens=in_t,
                    output_tokens=out_t,
                    raw_text=text,
                    cost_usd=_price(cfg.model, in_t, out_t),
                )
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode("utf-8", errors="replace")[:300]
            last_err = f"HTTP {e.code} {e.reason}: {body_txt}"
            if AnthropicAPI.is_retryable(e.code) and attempt < max_retries:
                wait = 2 ** attempt
                print(f"[summarize] {last_err} — {wait}초 후 재시도 ({attempt}/{max_retries})")
                time.sleep(wait)
                continue
            raise RuntimeError(last_err)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"[summarize] {last_err} — {wait}초 후 재시도 ({attempt}/{max_retries})")
                time.sleep(wait)
                continue
            raise

    raise RuntimeError(last_err or "알 수 없는 오류")


def summarize_pages(
    ocr_files: dict[int, Path],
    cfg: AiCfg,
    out_path: Path,
    page_range: tuple[int, int] | None = None,
    progress: bool = True,
    images: dict[int, Path] | None = None,
) -> dict:
    """여러 페이지 OCR(또는 이미지) → batch JSON 파일 저장.

    images 를 주면 **비전 요약**(OCR mojibake 책용) — ocr_files 대신 이미지 사용.
    Returns: { pages_done, in_tok, out_tok, cost_usd, errors }
    """
    vision = images is not None
    source = images if vision else ocr_files
    pages_done = 0
    errors: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []   # 오염(콘솔 화면)으로 건너뛴 페이지
    in_total = out_total = 0
    cost_total = 0.0
    results: list[dict] = []

    nums = sorted(source.keys())
    if page_range:
        lo, hi = page_range
        nums = [n for n in nums if lo <= n <= hi]

    # resume — 기존 out_path 에 이미 요약된 페이지는 건너뛰고 재사용(크래시 대비 증분).
    by_num: dict[int, dict] = {}
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            for p in (prev if isinstance(prev, list) else prev.get("pages", [])):
                n = p.get("num")
                if n is not None:
                    by_num[int(n)] = p
        except Exception:
            by_num = {}
    if by_num:
        print(f"[summarize] resume — 기존 {len(by_num)}장 재사용")

    def _save():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        merged = [by_num[k] for k in sorted(by_num)]
        out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    for i, num in enumerate(nums, 1):
        if num in by_num:
            pages_done += 1
            continue
        if not vision:
            text = ocr_files[num].read_text(encoding="utf-8")
            # 캡처 오염 검사 — 터미널/콘솔이 책 대신 찍힌 페이지는 요약 안 하고 제외
            bad, why = is_contaminated_ocr(text)
            if bad:
                skipped.append((num, why))
                print(f"[summarize] ⏭ p.{num:03d} 오염 감지(콘솔 화면, 지문='{why}') — 건너뜀",
                      file=sys.stderr)
                continue
        try:
            r = (summarize_page_vision(num, images[num], cfg) if vision
                 else summarize_page(num, text, cfg))
            by_num[num] = r.page
            pages_done += 1
            in_total += r.input_tokens
            out_total += r.output_tokens
            cost_total += r.cost_usd
            if progress:
                pct = i / len(nums) * 100
                print(f"[summarize] {i}/{len(nums)} ({pct:.0f}%) p.{num:03d} · "
                      f"in={r.input_tokens} out={r.output_tokens} cum=${cost_total:.3f}")
            if i % 5 == 0:      # 5장마다 증분 저장(크래시/슬립 대비)
                _save()
        except Exception as e:
            errors.append((num, str(e)))
            print(f"[summarize] ✗ p.{num:03d}: {e}", file=sys.stderr)
            # 크레딧 소진은 영구 에러 — 남은 페이지도 전부 실패하니 즉시 중단.
            if "credit balance is too low" in str(e):
                print("[summarize] ⛔ Anthropic 크레딧 소진 — 남은 페이지 중단. "
                      "충전 후 재처리(resume)하세요.", file=sys.stderr)
                break

    # batch JSON 저장 (기존 스키마: list of page dicts)
    results = [by_num[k] for k in sorted(by_num)]
    _save()
    note = f", 오염 제외 {len(skipped)}장" if skipped else ""
    print(f"[summarize] 저장: {out_path} ({pages_done} 페이지{note}, 비용 ${cost_total:.3f})")
    if skipped:
        print(f"[summarize] ⏭ 오염 제외 페이지: "
              + ", ".join(f"p.{n}({w})" for n, w in skipped), file=sys.stderr)

    return {
        "pages_done": pages_done,
        "errors": errors,
        "skipped": skipped,
        "in_tok": in_total,
        "out_tok": out_total,
        "cost_usd": cost_total,
        "out_path": str(out_path),
    }
