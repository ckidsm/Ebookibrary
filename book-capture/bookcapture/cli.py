"""통합 CLI — `python -m bookcapture <subcommand>`.

서브커맨드:
  settings          현재 백엔드 설정 출력
  capture           기존 kyobo_app.py 호출(인터랙티브, 옵션 1/2/3)
  ocr               <book_dir> 내 *.png OCR → summary/ocr_text/
  build             <book_dir> 캡처+OCR 결과로 summary/index.html (Phase C-2 placeholder)
  run               전 단계 일괄: capture → ocr → build

옵션 공통:
  --slug NAME       도서 폴더명 (output/<slug>/)
  --bridge URL      백엔드 URL 오버라이드 (기본: $KYOBO_BRIDGE_URL)
  --refresh         OCR 캐시 무시
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import settings as cfg
from . import ocr as ocr_mod
from . import build_html


def cmd_settings(args) -> int:
    s = cfg.load(bridge_url=args.bridge)
    print(f"bookcapture v{__version__}")
    print(cfg.explain(s))
    if not s.ai.api_key:
        print("\n⚠ AI 키 없음 — 환경변수 ANTHROPIC_API_KEY 또는 OPENAI_API_KEY 설정 권장")
    return 0


def cmd_capture(args) -> int:
    # 기존 kyobo_app.py 의 main() 을 그대로 호출 (인터랙티브 메뉴)
    from . import kyobo_app
    s = cfg.load(bridge_url=args.bridge)
    out_dir = Path(s.output.books_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[capture] 출력 베이스: {out_dir}")
    print(f"[capture] 설정: {cfg.explain(s)}")
    # kyobo_app.main() 은 sys.argv 를 보므로 옵션 주입
    mode = args.mode or "3"  # 기본 = 연속 캡처
    sys.argv = ["kyobo_app", mode]
    kyobo_app.main()
    return 0


def _resolve_book_dir(args) -> Path:
    s = cfg.load(bridge_url=args.bridge)
    base = Path(s.output.books_dir).expanduser().resolve()
    if args.slug:
        return base / args.slug
    if args.book_dir:
        return Path(args.book_dir).expanduser().resolve()
    print("✗ --slug 또는 --book-dir 중 하나 필요", file=sys.stderr)
    sys.exit(2)


def cmd_ocr(args) -> int:
    s = cfg.load(bridge_url=args.bridge)
    book_dir = _resolve_book_dir(args)
    if not book_dir.exists():
        print(f"✗ 폴더 없음: {book_dir}", file=sys.stderr); return 2
    ocr_mod.ocr_book(book_dir, cfg=s.ocr, refresh=args.refresh)
    return 0


def cmd_build(args) -> int:
    book_dir = _resolve_book_dir(args)
    if not book_dir.exists():
        print(f"✗ 폴더 없음: {book_dir}", file=sys.stderr); return 2
    build_html.build_index(book_dir, title=args.slug or book_dir.name)
    return 0


def cmd_run(args) -> int:
    """capture → ocr → build 일괄 실행 (대화형)."""
    rc = cmd_capture(args)
    if rc != 0: return rc
    rc = cmd_ocr(args)
    if rc != 0: return rc
    rc = cmd_build(args)
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bookcapture", description="교보 e-book 캡처·OCR·요약·빌드 파이프라인")
    p.add_argument("--bridge", help="백엔드 URL (기본: $KYOBO_BRIDGE_URL)")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("settings", help="현재 설정 출력").set_defaults(func=cmd_settings)

    pc = sub.add_parser("capture", help="기존 kyobo_app 캡처 인터랙티브")
    pc.add_argument("--mode", choices=["1", "2", "3"], help="1=전체 / 2=윈도우 / 3=연속")
    pc.set_defaults(func=cmd_capture)

    po = sub.add_parser("ocr", help="책 폴더 OCR")
    po.add_argument("--slug")
    po.add_argument("--book-dir")
    po.add_argument("--refresh", action="store_true")
    po.set_defaults(func=cmd_ocr)

    pb = sub.add_parser("build", help="HTML 인덱스 빌드 (Phase C-2 placeholder)")
    pb.add_argument("--slug")
    pb.add_argument("--book-dir")
    pb.set_defaults(func=cmd_build)

    pr = sub.add_parser("run", help="capture → ocr → build 일괄")
    pr.add_argument("--slug")
    pr.add_argument("--book-dir")
    pr.add_argument("--mode", choices=["1", "2", "3"], default="3")
    pr.add_argument("--refresh", action="store_true")
    pr.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
