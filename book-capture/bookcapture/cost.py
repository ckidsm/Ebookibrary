# -*- coding: utf-8 -*-
"""단계별 API 비용 기록·집계 (2026-07-19).

각 AI 단계(전사/요약/코드/챕터/개요)가 `record()` 로 비용을 `<book>/summary/cost_log.tsv` 에 append.
`report()` 가 이를 읽어 단계별·합계·페이지당 비용을 출력. process_book.sh / cli `cost` 가 사용.
"""
from __future__ import annotations
from pathlib import Path
import datetime as _dt


def _path(book_dir) -> Path:
    return Path(book_dir) / "summary" / "cost_log.tsv"


def reset(book_dir) -> None:
    """파이프라인 시작 시 호출(처음부터 실행할 때). 기존 로그 비움."""
    p = _path(book_dir)
    if p.exists():
        p.unlink()


def record(book_dir, stage: str, model: str, in_tok: int, out_tok: int, usd: float) -> None:
    """한 단계의 비용 1줄 기록 + [COST] 표준 출력(로그 grep 용)."""
    p = _path(book_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    ts = "-"  # Date.now 불가 환경 대비 — 필요 시 호출측에서 넘김
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{stage}\t{model}\t{int(in_tok)}\t{int(out_tok)}\t{usd:.4f}\t{ts}\n")
    print(f"[COST] {stage}: ${usd:.4f}  ({model} in={in_tok} out={out_tok})", flush=True)


def report(book_dir, pages: int | None = None) -> dict:
    """cost_log.tsv 집계 → 단계별·합계·페이지당 출력. 반환 dict."""
    p = _path(book_dir)
    rows = []
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 5:
                rows.append((parts[0], parts[1], int(parts[2]), int(parts[3]), float(parts[4])))
    if pages is None:  # page_*.png 수로 추정
        pages = len(list(Path(book_dir).glob("page_*.png"))) or None
    total = sum(r[4] for r in rows)
    print("─" * 52)
    print(f"💰 API 비용 요약 — {Path(book_dir).name}")
    print("─" * 52)
    # 단계별 집계(같은 단계 여러 번이면 합산)
    agg: dict[str, list] = {}
    for st, md, i, o, u in rows:
        a = agg.setdefault(st, [md, 0, 0, 0.0])
        a[1] += i; a[2] += o; a[3] += u
    for st, (md, i, o, u) in agg.items():
        print(f"  {st:<12} {md:<22} in={i:>8} out={o:>7}  ${u:.4f}")
    print("─" * 52)
    print(f"  합계  ${total:.4f}" + (f"  ·  캡처 {pages}장  ·  장당 ${total/pages:.4f}" if pages else ""))
    print("─" * 52)
    return {"total_usd": round(total, 4), "pages": pages,
            "per_page_usd": round(total / pages, 5) if pages else None,
            "stages": {st: {"model": v[0], "in": v[1], "out": v[2], "usd": round(v[3], 4)}
                       for st, v in agg.items()}}
