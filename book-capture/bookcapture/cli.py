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
from . import merge as merge_mod
from . import summarize as summarize_mod


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


def cmd_merge(args) -> int:
    """batch_*.json 들 → pages_data.json + 챕터/섹션 트리."""
    book_dir = _resolve_book_dir(args)
    summary_dir = book_dir / "summary"
    if not summary_dir.exists():
        print(f"✗ summary 폴더 없음: {summary_dir}", file=sys.stderr); return 2
    try:
        merge_mod.merge_batches(summary_dir, fallback_title=args.slug or book_dir.name)
        return 0
    except Exception as e:
        print(f"✗ merge 실패: {e}", file=sys.stderr); return 1


def cmd_build(args) -> int:
    book_dir = _resolve_book_dir(args)
    if not book_dir.exists():
        print(f"✗ 폴더 없음: {book_dir}", file=sys.stderr); return 2
    build_html.build_index(book_dir, title=args.slug or book_dir.name)
    return 0


def cmd_summarize(args) -> int:
    """OCR 결과 → batch JSON (Claude/OpenAI API)."""
    s = cfg.load(bridge_url=args.bridge)
    book_dir = _resolve_book_dir(args)
    if not book_dir.exists():
        print(f"✗ 폴더 없음: {book_dir}", file=sys.stderr); return 2

    ocr_dir = book_dir / "summary" / "ocr_text"
    if not ocr_dir.exists():
        print(f"✗ OCR 결과 없음: {ocr_dir} — 먼저 `ocr` 서브커맨드 실행", file=sys.stderr); return 2

    # ocr_text/page_NNN.txt → {num: path}
    import re
    files: dict[int, "Path"] = {}
    for p in sorted(ocr_dir.glob("page_*.txt")):
        m = re.search(r"page_(\d+)\.txt$", p.name)
        if m:
            files[int(m.group(1))] = p
    if not files:
        print(f"✗ {ocr_dir} 에 page_*.txt 없음", file=sys.stderr); return 2

    page_range = None
    if args.pages:
        try:
            lo, hi = args.pages.split("-")
            page_range = (int(lo), int(hi))
        except Exception:
            print(f"✗ --pages 형식: 127-155 (받은 값: {args.pages})", file=sys.stderr); return 2

    out_path = book_dir / "summary" / (args.out or f"batch_{min(files):03d}.json")
    print(f"[summarize] 시작 · {len(files)} 페이지 · model={s.ai.model}")
    res = summarize_mod.summarize_pages(files, cfg=s.ai, out_path=out_path, page_range=page_range)
    print(f"\n결과: {res['pages_done']}건 성공, {len(res['errors'])}건 실패, "
          f"입력 {res['in_tok']} / 출력 {res['out_tok']} 토큰, ${res['cost_usd']:.3f}")
    return 0 if not res["errors"] else 1


def cmd_run(args) -> int:
    """capture → ocr → (summarize) → merge → build 일괄 (대화형)."""
    rc = cmd_capture(args)
    if rc != 0: return rc
    rc = cmd_ocr(args)
    if rc != 0: return rc
    if not getattr(args, "no_summarize", False):
        rc = cmd_summarize(args)
        if rc != 0: print(f"[run] summarize 일부 실패 (계속 진행)")
    rc = cmd_merge(args)
    if rc != 0: print(f"[run] merge 실패 (batch JSON 없음 가능) — placeholder HTML 만 생성")
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

    pm = sub.add_parser("merge", help="batch_*.json → pages_data.json (챕터/섹션 트리)")
    pm.add_argument("--slug")
    pm.add_argument("--book-dir")
    pm.set_defaults(func=cmd_merge)

    pb = sub.add_parser("build", help="HTML 빌드 (pages_data.json 있으면 본격, 없으면 placeholder)")
    pb.add_argument("--slug")
    pb.add_argument("--book-dir")
    pb.set_defaults(func=cmd_build)

    ps = sub.add_parser("summarize", help="OCR 결과 → batch JSON (Claude API)")
    ps.add_argument("--slug")
    ps.add_argument("--book-dir")
    ps.add_argument("--pages", help="페이지 범위 (예: 127-155)")
    ps.add_argument("--out", help="출력 파일명 (기본: batch_<첫페이지>.json)")
    ps.set_defaults(func=cmd_summarize)

    pr = sub.add_parser("run", help="capture → ocr → summarize → build 일괄")
    pr.add_argument("--slug")
    pr.add_argument("--book-dir")
    pr.add_argument("--mode", choices=["1", "2", "3"], default="3")
    pr.add_argument("--refresh", action="store_true")
    pr.add_argument("--no-summarize", action="store_true", help="AI 요약 단계 스킵 (비용 0)")
    pr.add_argument("--pages")
    pr.add_argument("--out")
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
