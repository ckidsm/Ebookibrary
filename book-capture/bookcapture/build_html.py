"""HTML 빌드 — Phase C-3 에서 AI 요약 JSON 형식 확정 후 본격 구현.

지금(C-2)은 placeholder:
- 책 폴더 안 *.png 와 ocr_text/page_*.txt 만 모아 단순 인덱스 페이지 생성
- CLI_완전활용 처럼 사이드바·챕터 카드는 C-3 에서 generate_html.py 패턴으로 이식
"""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path


INDEX_TEMPLATE = """<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<title>{title} — 페이지 인덱스 (Phase C-2)</title>
<style>
body{{font-family:-apple-system,sans-serif;background:#0a0c10;color:#e6ecf2;margin:0;padding:30px;}}
.hd{{margin-bottom:18px;}}
.hd h1{{margin:0 0 6px;color:#22d3ee;}}
.hd .sub{{color:#8b96a8;font-size:13px;font-family:monospace;}}
.warn{{background:rgba(245,158,11,0.15);border:1px solid #f59e0b;color:#fbbf24;
       padding:12px 16px;border-radius:8px;margin:18px 0;font-size:13px;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;}}
.card{{background:#11151c;border:1px solid #2f3a4d;border-radius:8px;padding:10px;}}
.card img{{width:100%;border-radius:4px;display:block;}}
.card .meta{{font-family:monospace;font-size:11px;color:#8b96a8;margin-top:6px;
             display:flex;justify-content:space-between;}}
.card .ocrhint{{color:#10b981;}} .card .ocrno{{color:#f59e0b;}}
</style></head><body>
<div class="hd">
  <h1>📖 {title}</h1>
  <div class="sub">Phase C-2 placeholder · {n_pages} 페이지 · 빌드일 {today}</div>
</div>
<div class="warn">
  ⚠ 이 페이지는 캡처 결과 확인용 임시 인덱스입니다.
  Phase C-3 에서 AI 요약이 추가되면 CLI_완전활용 처럼 사이드바·챕터 카드 본문이 생성됩니다.
</div>
<div class="grid">
{cards}
</div>
</body></html>
"""

CARD = """  <div class="card">
    <img src="{img_rel}" alt="page {num}" loading="lazy">
    <div class="meta"><span>p.{num:03d}</span>
      <span class="{ocr_cls}">{ocr_label}</span>
    </div>
  </div>"""


def build_index(book_dir: Path, title: str | None = None) -> Path:
    """캡처된 페이지로 임시 인덱스 HTML 생성. summary/index.html 반환."""
    pngs = sorted(book_dir.glob("*.png"))
    ocr_dir = book_dir / "summary" / "ocr_text"
    summary_dir = book_dir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    out = summary_dir / "index.html"

    title = title or book_dir.name
    cards = []
    for p in pngs:
        # 파일명 끝 _NNN.png 가 페이지 번호
        num_part = p.stem.split("_")[-1]
        try:
            num = int(num_part)
        except ValueError:
            num = 0
        ocr_file = ocr_dir / f"page_{num:03d}.txt"
        has_ocr = ocr_file.exists()
        cards.append(CARD.format(
            img_rel=f"../{p.name}",
            num=num,
            ocr_cls="ocrhint" if has_ocr else "ocrno",
            ocr_label="OCR ✓" if has_ocr else "OCR ✗",
        ))

    html_text = INDEX_TEMPLATE.format(
        title=html.escape(title),
        n_pages=len(pngs),
        today=date.today().isoformat(),
        cards="\n".join(cards),
    )
    out.write_text(html_text, encoding="utf-8")
    print(f"[build_html] {out} ({len(pngs)} 페이지)")
    return out
