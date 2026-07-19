# -*- coding: utf-8 -*-
"""페이지 이미지 → 언어별(C#/Python 등) 소스코드 비전 추출 → summary/code_blocks.json.

팝업 뷰어의 '💻 소스코드' 패널용. OCR은 코드 품질이 낮아(문자오류·들여쓰기 손실·산문혼입)
Claude 비전으로 정밀 추출한다. 파이프라인 표준 단계(ocr·summarize와 같은 계층).

code_blocks.json 형식: { "24": [{"lang":"C#","title":"예제 2.7 ...","code":"..."}], ... }
- 코드 자동감지(pages=None) 또는 지정. 증분 저장 + resume. 429/5xx 재시도.
"""
from __future__ import annotations
from .anthropic_api import AnthropicAPI
import sys, json, base64, io, time, re, urllib.request, urllib.error
from pathlib import Path

API_URL = AnthropicAPI.API_URL
API_VERSION = AnthropicAPI.API_VERSION
_PRICES = AnthropicAPI.PRICES

_SYS = ("You extract SOURCE CODE from a Korean programming-book page image. "
        "The book teaches OpenCV with C# (OpenCvSharp) and Python (cv2/numpy) examples, "
        "often showing both languages. Return ONLY real source code, exactly as printed.")
_USER = ("이 책 페이지 이미지에서 소스코드 블록을 모두 추출하세요. 규칙:\n"
         "- 언어별로 분리: 'C#' 또는 'Python'.\n"
         "- 들여쓰기와 코드를 원문 그대로 보존(문자 정확히). 산문·표·[출력 결과] 박스·캡션·페이지번호는 제외.\n"
         "- 코드에 붙은 예제 제목(예: '예제 2.7 C# ...')이 있으면 title에 담되 없으면 생략.\n"
         "- 코드가 없으면 {\"blocks\":[]}.\n"
         '반드시 이 JSON만 출력: {"blocks":[{"lang":"C#","title":"...","code":"...."},{"lang":"Python","code":"...."}]}')

# 코드 자동감지용 시그니처
_CS = re.compile(r'Cv2\.|using\s+OpenCvSharp|Console\.|new\s+Mat|videoWriter\.|namespace\s|ColorConversion')
_PY = re.compile(r'cv2\.|import\s+cv2|import\s+numpy|np\.|def\s+\w+\(|print\(|plt\.')


def _img_b64(path, max_w=AnthropicAPI.CODE_MAX_W):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def _extract_json(txt):
    m = re.search(r'\{.*\}', txt, re.S)
    return json.loads(m.group(0)) if m else {"blocks": []}


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
            return _extract_json(txt), u.get("input_tokens", 0), u.get("output_tokens", 0)
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:200]
            if AnthropicAPI.is_retryable(e.code) and attempt < 4:
                time.sleep(AnthropicAPI.BACKOFF_BASE ** attempt); continue
            if "credit balance is too low" in msg:
                raise RuntimeError("credit balance is too low")
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        except Exception:
            if attempt < 4: time.sleep(AnthropicAPI.BACKOFF_BASE ** attempt); continue
            raise
    raise RuntimeError("재시도 초과")


def detect_code_pages(summary_dir: Path) -> list[int]:
    ot = summary_dir / "ocr_text"
    pages = []
    for f in sorted(ot.glob("page_*.txt")):
        t = f.read_text(encoding="utf-8")
        if len(_CS.findall(t)) + len(_PY.findall(t)) >= 2:
            pages.append(int(re.search(r'(\d+)', f.name).group(1)))
    return pages


def extract_code_blocks(book_dir: Path, ai, pages=None, progress=True) -> dict:
    """book_dir 아래 코드 페이지 이미지 → summary/code_blocks.json. ai=settings AiCfg(api_key,model).
    반환: {pages, blocks, cost_usd, done}."""
    book_dir = Path(book_dir)
    sd = book_dir / "summary"
    if not ai or not getattr(ai, "api_key", ""):
        print("[code] API 키 없음 — 코드 추출 건너뜀", file=sys.stderr)
        return {"pages": 0, "blocks": 0, "cost_usd": 0.0, "done": False}
    model = getattr(ai, "model", None) or AnthropicAPI.DEFAULT_MODEL
    ip, op = AnthropicAPI.price(model)
    if pages is None:
        pages = detect_code_pages(sd)
    out = sd / "code_blocks.json"
    result = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    todo = [n for n in pages if str(n) not in result]
    print(f"[code] 코드 페이지 {len(pages)}장, 남은 {len(todo)}장 (model={model})")
    cost = 0.0
    it_total = ot_total = 0
    for i, n in enumerate(todo, 1):
        img = book_dir / "thumbs" / f"page_{n:03d}.png"
        if not img.exists(): img = book_dir / f"page_{n:03d}.png"
        if not img.exists():
            continue
        try:
            data, it, ot_ = _call(ai.api_key, model, _img_b64(img))
        except Exception as e:  # ⚠️ RuntimeError 뿐 아니라 **모든 예외**(타임아웃·연결오류 등)를 잡아야
            # 한 페이지 실패로 전체 추출이 크래시(조기 종료)하지 않음(2026-07-14 근본원인).
            if "credit balance is too low" in str(e) or "usage limits" in str(e):
                out.write_text(json.dumps({k: result[k] for k in sorted(result, key=int)}, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"[code] ⛔ API 한도/크레딧 — 충전·상향 후 재실행(resume): {e}", file=sys.stderr); break
            print(f"[code] ✗ p{n:03d} 건너뜀: {e}", file=sys.stderr); continue
        blocks = [b for b in data.get("blocks", []) if b.get("code", "").strip()]
        if blocks: result[str(n)] = blocks
        cost += it / 1e6 * ip + ot_ / 1e6 * op
        it_total += it; ot_total += ot_
        if progress:
            print(f"[code] {i}/{len(todo)} p{n:03d}: {len(blocks)} block · cum=${cost:.3f}")
        if i % 10 == 0:
            out.write_text(json.dumps({k: result[k] for k in sorted(result, key=int)}, ensure_ascii=False, indent=1), encoding="utf-8")
    result = {k: result[k] for k in sorted(result, key=int)}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(v) for v in result.values())
    print(f"[code] 저장: {out} ({len(result)} 페이지·{total} 블록, 비용 ${cost:.3f})")
    if it_total or ot_total:
        from . import cost as _cost
        _cost.record(book_dir, "code", model, it_total, ot_total, cost)
    return {"pages": len(result), "blocks": total, "cost_usd": cost, "done": True}
