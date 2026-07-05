# -*- coding: utf-8 -*-
"""페이지 이미지 → 언어별 소스코드 비전 추출 (thin wrapper).
로직은 bookcapture/extract_code.py (파이프라인 표준 모듈). CLI로도 `python -m bookcapture code` 사용 가능.

사용: python scripts/extract_code.py --book-dir books/<slug> [--pages 24,26] [--bridge URL]
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bookcapture import settings as cfg_mod
from bookcapture.extract_code import extract_code_blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-dir", required=True)
    ap.add_argument("--pages")
    ap.add_argument("--bridge")
    a = ap.parse_args()
    s = cfg_mod.load(bridge_url=a.bridge)
    pages = [int(x) for x in a.pages.replace("-", ",").split(",") if x.strip().isdigit()] if a.pages else None
    extract_code_blocks(Path(a.book_dir), s.ai, pages=pages)


if __name__ == "__main__":
    main()
