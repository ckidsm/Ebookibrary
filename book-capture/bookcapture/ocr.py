"""OCR 모듈 — 기존 verify_ocr.py 패턴을 단순화.

각 페이지 PNG → tesseract(kor+eng) → ocr_text/page_NNN.txt 캐싱.
검증(batch JSON 대조)은 Phase C-3 의 AI 요약 후에 다시 검토.
"""

from __future__ import annotations

import re
from pathlib import Path

from .settings import OcrCfg

try:
    from PIL import Image
    import pytesseract
    HAS_OCR = True
except ImportError:  # pragma: no cover
    HAS_OCR = False


PAGE_NUM_RE = re.compile(r"_(\d{3,5})\.(png|jpg|jpeg)$", re.IGNORECASE)


def page_num_from_filename(p: Path) -> int | None:
    m = PAGE_NUM_RE.search(p.name)
    return int(m.group(1)) if m else None


def ocr_one(img_path: Path, lang: str = "kor+eng") -> str:
    """단일 이미지 OCR. tesseract 없으면 빈 문자열."""
    if not HAS_OCR:
        return ""
    try:
        with Image.open(img_path) as im:
            return pytesseract.image_to_string(im, lang=lang)
    except Exception as e:
        return f"[OCR_ERROR] {e}"


def make_thumbnails(book_dir: Path, max_px: int = 1800) -> Path:
    """원본 PNG가 max_px 초과면 thumbs/ 에 리사이즈본 생성. thumbs 경로 반환."""
    thumbs = book_dir / "thumbs"
    if not HAS_OCR:
        return thumbs
    thumbs.mkdir(exist_ok=True)
    for src in sorted(book_dir.glob("*.png")):
        dst = thumbs / src.name
        if dst.exists():
            continue
        try:
            with Image.open(src) as im:
                w, h = im.size
                if max(w, h) <= max_px:
                    im.save(dst, optimize=True)
                else:
                    r = max_px / max(w, h)
                    im.resize((int(w * r), int(h * r)), Image.LANCZOS).save(dst, optimize=True)
        except Exception as e:
            print(f"[ocr] thumbnail 실패 {src.name}: {e}")
    return thumbs


def ocr_book(
    book_dir: Path,
    cfg: OcrCfg | None = None,
    refresh: bool = False,
) -> dict[int, Path]:
    """책 폴더 전체를 OCR. ocr_text/page_NNN.txt 캐시 생성.
    반환: {page_num: ocr_text_path}
    """
    cfg = cfg or OcrCfg()
    if not HAS_OCR:
        print("[ocr] Pillow·pytesseract 미설치 — 스킵")
        return {}

    src_dir = make_thumbnails(book_dir, max_px=1800) if cfg.use_thumbs else book_dir
    ocr_dir = book_dir / "summary" / "ocr_text"
    ocr_dir.mkdir(parents=True, exist_ok=True)

    results: dict[int, Path] = {}
    pngs = sorted(src_dir.glob("*.png"))
    print(f"[ocr] {len(pngs)} 페이지 OCR 시작 (lang={cfg.lang}, src={src_dir.name})")

    for i, img in enumerate(pngs, 1):
        pnum = page_num_from_filename(img) or i
        cache = ocr_dir / f"page_{pnum:03d}.txt"
        if cache.exists() and not refresh:
            results[pnum] = cache
            continue
        text = ocr_one(img, lang=cfg.lang)
        cache.write_text(text, encoding="utf-8")
        results[pnum] = cache
        if i % 10 == 0 or i == len(pngs):
            print(f"[ocr]   {i}/{len(pngs)} 완료 (page_{pnum:03d})")

    print(f"[ocr] 완료 — {len(results)} 페이지")
    return results
