# -*- coding: utf-8 -*-
"""빌드된 summary/index.html 에 챕터 트리 + 표 정리본을 한 번에 주입 (다른 책 재사용).

build_html 이 만든 **깨끗한** index.html(챕터/정리본 미주입)을 입력으로,
  1) add_chapter_tree.build()  — 사이드바 접기/펴기 트리 + 챕터 요약 카드
  2) add_page_extras.build()   — 표 있는 페이지에 재구성 HTML 표(정리본) + CSS
를 순서대로 적용해 최종 index.html 을 만든다.

⚠️ 멱등 아님: 이미 주입된 index 에 다시 돌리면 카드/표가 중복 삽입된다.
   → 기본은 이미 주입돼 있으면 중단. 새 조각만 추가하려면 개별 add_*.py 를 직접.

사용:
  python scripts/finalize_book.py <summary_dir> [--out index.html] [--force]
    <summary_dir>/index.html         (입력=깨끗한 빌드 결과)
    <summary_dir>/chapters.json      (있으면 챕터 트리 주입)
    <summary_dir>/page_extras.json   (있으면 표 정리본 주입)
"""
import json, sys, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import add_chapter_tree as act
import add_page_extras as ape


def finalize(summary_dir: Path, out_name="index.html", force=False):
    idx = summary_dir / "index.html"
    html = idx.read_text(encoding="utf-8")

    already_ch = "chapter-summary" in html
    already_pe = 'class="page-extra"' in html or "page-extra" in html
    if (already_ch or already_pe) and not force:
        raise SystemExit(
            f"⚠ 이미 주입됨(chapter={already_ch}, extras={already_pe}). "
            f"깨끗한 빌드 결과에 돌리세요. 강제하려면 --force (중복 주의).")

    steps = []
    chj = summary_dir / "chapters.json"
    if chj.exists():
        chapters = json.load(open(chj, encoding="utf-8"))
        html = act.build(html, chapters, 0)
        steps.append(f"챕터 {len(chapters)}개")

    exj = summary_dir / "page_extras.json"
    if exj.exists():
        extras = json.load(open(exj, encoding="utf-8"))
        html = ape.build(html, extras)
        # kbd/다중표 CSS 보강(멱등)
        if ".page-extra kbd" not in html:
            KBD = ("\n.page-extra kbd { display:inline-block; background:#2b3440; color:#e6edf3; "
                   "border:1px solid #48505b; border-bottom-width:2px; border-radius:4px; padding:0 6px; "
                   "font-size:0.82em; font-family:ui-monospace,Menlo,Consolas,monospace; line-height:1.5; "
                   "white-space:nowrap; }\n.page-extra .ptable + .ptable { margin-top:10px; }\n")
            html = html.replace("</style>", KBD + "</style>", 1)
        tables = html.count('class="ptable"')
        steps.append(f"표 페이지 {len(extras)}개(표 {tables}개)")

    out = summary_dir / out_name
    out.write_text(html, encoding="utf-8")
    print(f"✅ 최종화 완료 → {out}")
    print("   적용:", ", ".join(steps) if steps else "(주입할 json 없음)")
    print(f"   크기: {len(html.encode()):,} bytes")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("summary_dir")
    ap.add_argument("--out", default="index.html")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    finalize(Path(a.summary_dir), a.out, a.force)


if __name__ == "__main__":
    main()
