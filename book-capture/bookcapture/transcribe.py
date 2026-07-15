# -*- coding: utf-8 -*-
"""페이지 이미지 → 깨끗한 본문 텍스트(비전) → summary/ocr_text/page_NNN.txt.

교보 이북은 폰트 때문에 tesseract OCR 이 전 페이지 mojibake(한글 0%)라, 팝업의
'📄 OCR 텍스트' 패널이 개판이 된다. tesseract 대신 **비전 전사**로 정확한 한글 본문·코드를 복원.

엔진(2026-07-15 실측 비교로 결정):
  - 기본 **Gemini 2.5-flash** — Claude 비전과 품질 동등~우세인데 ~18배 저렴($7.3→~$0.4/권).
  - 폴백 Claude — Gemini 키 없을 때. `ai.ocr_provider`/키 유무로 자동 선택.

resume: `.vision_done.json` manifest 로 완료 페이지 추적(코드 페이지는 한글비율 낮아
        한글 판별 불가). refresh=True 면 전부 재전사.
"""
from __future__ import annotations
from .anthropic_api import AnthropicAPI
from .gemini_api import GeminiAPI, generate as gemini_generate, img_b64 as gemini_img_b64
import sys, json, base64, io, time, re, urllib.request, urllib.error
from pathlib import Path

API_URL = AnthropicAPI.API_URL
API_VERSION = AnthropicAPI.API_VERSION

_SYS = ("당신은 한국어 기술 도서 페이지를 정확히 전사(transcribe)하는 전문가입니다. "
        "페이지 이미지에 인쇄된 텍스트를 읽는 순서 그대로, 있는 그대로 옮겨 적습니다.")
_USER = (
    "이 책 페이지 이미지의 모든 텍스트를 읽는 순서대로 전사하세요. 규칙:\n"
    "- 본문·제목·소제목·코드·캡션·표의 텍스트를 실제 인쇄된 내용 그대로(한글은 한글로) 옮긴다.\n"
    "- 코드 블록은 들여쓰기를 보존한다. 그림 자체는 옮기지 말고 그림 안/아래의 글자만.\n"
    "- 페이지 번호·머리말/꼬리말 같은 장식 요소는 생략해도 된다.\n"
    "- 없는 내용을 지어내지 말 것. 표지·간지 등 글자가 거의 없으면 보이는 그 몇 글자만.\n"
    "- 설명·요약·해설을 덧붙이지 말고 **전사 텍스트만** 출력한다. 마크다운 코드펜스도 쓰지 말 것.")


def _hangul_ratio(t: str) -> float:
    L = [c for c in t if c.isalpha()]
    if not L:
        return 0.0
    return len([c for c in L if "가" <= c <= "힣"]) / len(L)


def _img_b64(path: Path, max_w: int = AnthropicAPI.CODE_MAX_W) -> str:
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def _call(api_key, model, b64):
    body = {"model": model, "max_tokens": 4000, "temperature": 0, "system": _SYS,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": _USER}]}]}
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode(),
        headers={"x-api-key": api_key, "anthropic-version": API_VERSION, "content-type": "application/json"})
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(req, timeout=AnthropicAPI.TIMEOUT_VISION) as r:
                d = json.loads(r.read())
            txt = "".join(b.get("text", "") for b in d.get("content", []))
            u = d.get("usage", {})
            return txt.strip(), u.get("input_tokens", 0), u.get("output_tokens", 0)
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:200]
            if "credit balance is too low" in msg:
                raise RuntimeError("credit balance is too low")
            if AnthropicAPI.is_retryable(e.code) and attempt < 4:
                time.sleep(AnthropicAPI.BACKOFF_BASE ** attempt); continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        except Exception:
            if attempt < 4:
                time.sleep(AnthropicAPI.BACKOFF_BASE ** attempt); continue
            raise
    raise RuntimeError("재시도 초과")


def transcribe_book(book_dir: Path, ai, refresh: bool = False,
                    page_range: tuple[int, int] | None = None, progress: bool = True) -> dict:
    """책 폴더 페이지 이미지 → 비전 전사 → summary/ocr_text/page_NNN.txt(덮어씀).
    반환: {done, skipped, cost_usd}."""
    book_dir = Path(book_dir)
    # 엔진 선택: Gemini 키 있고 ocr_provider!=claude 면 Gemini(싸고 우세), 아니면 Claude 폴백
    gkey = getattr(ai, "gemini_api_key", "") if ai else ""
    use_gemini = bool(gkey) and getattr(ai, "ocr_provider", "gemini") != "claude"
    if use_gemini:
        engine = "gemini"
        model = getattr(ai, "gemini_model", None) or GeminiAPI.DEFAULT_MODEL
        ip, op = GeminiAPI.price(model)
        api_key = gkey
    else:
        if not ai or not getattr(ai, "api_key", ""):
            print("[transcribe] 전사 키 없음(Gemini/Claude 둘 다) — 건너뜀", file=sys.stderr)
            return {"done": 0, "skipped": 0, "cost_usd": 0.0}
        engine = "claude"
        model = getattr(ai, "model", None) or AnthropicAPI.DEFAULT_MODEL
        ip, op = AnthropicAPI.price(model)
        api_key = ai.api_key

    ocr_dir = book_dir / "summary" / "ocr_text"
    ocr_dir.mkdir(parents=True, exist_ok=True)

    imgs: dict[int, Path] = {}
    for p in sorted(book_dir.glob("page_*.png")):
        m = re.search(r"page_(\d+)\.png$", p.name)
        if m:
            imgs[int(m.group(1))] = p
    if not imgs:  # 원본 없으면 thumbs
        for p in sorted((book_dir / "thumbs").glob("page_*.png")):
            m = re.search(r"page_(\d+)\.png$", p.name)
            if m:
                imgs[int(m.group(1))] = p
    if not imgs:
        print(f"[transcribe] {book_dir} 에 page_*.png 없음", file=sys.stderr)
        return {"done": 0, "skipped": 0, "cost_usd": 0.0}

    nums = sorted(imgs)
    if page_range:
        lo, hi = page_range
        nums = [n for n in nums if lo <= n <= hi]

    # resume — 완료 페이지 manifest(코드 페이지는 한글비율 낮아 한글 판별 불가라 별도 추적)
    manifest = ocr_dir / ".vision_done.json"
    vdone: set[int] = set()
    if manifest.exists() and not refresh:
        try:
            vdone = set(json.loads(manifest.read_text(encoding="utf-8")))
        except Exception:
            vdone = set()

    def _save_manifest():
        manifest.write_text(json.dumps(sorted(vdone)), encoding="utf-8")

    def _transcribe_one(img_path: Path):
        """엔진별 1페이지 전사 → (text, in_tok, out_tok)."""
        if engine == "gemini":
            return gemini_generate(api_key, model,
                                   f"{_SYS}\n\n{_USER}", image_b64=gemini_img_b64(img_path),
                                   max_tokens=8000, temperature=0.0, thinking=False)
        return _call(api_key, model, _img_b64(img_path))

    done = skipped = 0
    cost = 0.0
    print(f"[transcribe] {len(nums)} 페이지 비전 전사 (engine={engine}, model={model}, "
          f"refresh={refresh}, 기존 완료 {len(vdone & set(nums))}장)")
    for i, n in enumerate(nums, 1):
        cache = ocr_dir / f"page_{n:03d}.txt"
        if n in vdone and cache.exists() and not refresh:
            skipped += 1
            continue
        try:
            txt, it, ot = _transcribe_one(imgs[n])
        except Exception as e:
            es = str(e)
            if "credit balance is too low" in es or "quota exceeded" in es:
                print(f"[transcribe] ⛔ {engine} 한도/크레딧 소진 — 중단(resume 가능): {e}", file=sys.stderr); break
            print(f"[transcribe] ✗ p{n:03d} 건너뜀: {e}", file=sys.stderr); continue
        cache.write_text(txt, encoding="utf-8")
        vdone.add(n)
        done += 1
        cost += it / 1e6 * ip + ot / 1e6 * op
        if done % 5 == 0:
            _save_manifest()
        if progress:
            print(f"[transcribe] {i}/{len(nums)} p.{n:03d} · {len(txt)}자 "
                  f"(in={it} out={ot} cum=${cost:.3f})")
    _save_manifest()
    print(f"[transcribe] 완료 — 전사 {done}장, 재사용 {skipped}장, ${cost:.3f}")
    return {"done": done, "skipped": skipped, "cost_usd": cost}
