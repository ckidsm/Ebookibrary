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

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


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


@dataclass
class SummarizeResult:
    page: dict           # 파싱된 batch JSON 페이지 객체
    input_tokens: int
    output_tokens: int
    raw_text: str        # 디버그용
    cost_usd: float


# Claude 가격표 (per 1M tokens, 2026-05 시점 — 변경 시 갱신)
_PRICES = {
    "claude-sonnet-4-5":   (3.0, 15.0),
    "claude-sonnet-4-7":   (3.0, 15.0),
    "claude-haiku-4-5":    (1.0,  5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-opus-4":      (15.0, 75.0),
    "claude-opus-4-7":    (15.0, 75.0),
}

def _price(model: str, in_tok: int, out_tok: int) -> float:
    in_p, out_p = _PRICES.get(model, (3.0, 15.0))
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
            with urllib.request.urlopen(req, timeout=60) as resp:
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
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
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
) -> dict:
    """여러 페이지 OCR → batch JSON 파일 저장.

    Returns: { pages_done, in_tok, out_tok, cost_usd, errors }
    """
    pages_done = 0
    errors: list[tuple[int, str]] = []
    skipped: list[tuple[int, str]] = []   # 오염(콘솔 화면)으로 건너뛴 페이지
    in_total = out_total = 0
    cost_total = 0.0
    results: list[dict] = []

    nums = sorted(ocr_files.keys())
    if page_range:
        lo, hi = page_range
        nums = [n for n in nums if lo <= n <= hi]

    for i, num in enumerate(nums, 1):
        text = ocr_files[num].read_text(encoding="utf-8")
        # 캡처 오염 검사 — 터미널/콘솔이 책 대신 찍힌 페이지는 요약 안 하고 제외
        bad, why = is_contaminated_ocr(text)
        if bad:
            skipped.append((num, why))
            print(f"[summarize] ⏭ p.{num:03d} 오염 감지(콘솔 화면, 지문='{why}') — 건너뜀",
                  file=sys.stderr)
            continue
        try:
            r = summarize_page(num, text, cfg)
            results.append(r.page)
            pages_done += 1
            in_total += r.input_tokens
            out_total += r.output_tokens
            cost_total += r.cost_usd
            if progress:
                pct = i / len(nums) * 100
                print(f"[summarize] {i}/{len(nums)} ({pct:.0f}%) p.{num:03d} · "
                      f"in={r.input_tokens} out={r.output_tokens} cum=${cost_total:.3f}")
        except Exception as e:
            errors.append((num, str(e)))
            print(f"[summarize] ✗ p.{num:03d}: {e}", file=sys.stderr)
            # 크레딧 소진은 영구 에러 — 남은 페이지도 전부 실패하니 즉시 중단.
            if "credit balance is too low" in str(e):
                print("[summarize] ⛔ Anthropic 크레딧 소진 — 남은 페이지 중단. "
                      "충전 후 재처리(resume)하세요.", file=sys.stderr)
                break

    # batch JSON 저장 (기존 스키마: list of page dicts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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
