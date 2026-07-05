# -*- coding: utf-8 -*-
"""페이지 카드에 '정리본'(표 등 구조화 HTML)을 추가 — 표가 있는 페이지에 깔끔한 표 삽입.

page_extras.json 형식: { "38": "<div class=\\"section page-extra\\">...</div>", ... }
각 값은 .page-summary 맨 끝(핵심 내용 아래)에 삽입된다. 표 정리는 사람이 이미지 보고 작성/검토.
사용: python scripts/add_page_extras.py index.html page_extras.json [out.html]
"""
import re, json, sys

CSS = """
.page-extra .ptable { width:100%; border-collapse:collapse; margin:6px 0 4px; font-size:0.8rem; }
.page-extra .ptable th { background:#eef4f3; color:#1a6b5a; text-align:left; padding:7px 10px; border:1px solid #d8e3e0; font-weight:700; }
.page-extra .ptable td { padding:7px 10px; border:1px solid #e5ebe9; vertical-align:top; line-height:1.55; color:#444; }
.page-extra .ptable td code, .page-extra .ptable th code { background:#f3f5f7; padding:1px 5px; border-radius:4px; font-size:0.92em; color:#c0392b; }
.page-extra .ptable tbody tr:nth-child(even) td { background:#fafcfb; }
.page-extra .ptable-note { font-size:0.76rem; color:#777; margin-top:4px; }
.page-extra .section-title { color:#16a085; }
.page-extra kbd { display:inline-block; background:#2b3440; color:#e6edf3; border:1px solid #48505b; border-bottom-width:2px; border-radius:4px; padding:0 6px; font-size:0.82em; font-family:ui-monospace,Menlo,Consolas,monospace; line-height:1.5; white-space:nowrap; }
.page-extra .ptable + .ptable { margin-top:10px; }
"""


def build(html, extras):
    # 카드 경계로 각 페이지 span 잡아 삽입
    for num, extra in extras.items():
        num = int(num)
        start = html.find(f'<div class="page-card" id="page-{num}">')
        if start < 0:
            print(f"⚠ page-{num} 카드 없음", file=sys.stderr); continue
        nxt = html.find('<div class="page-card" id="page-', start + 10)
        end = nxt if nxt > 0 else len(html)
        card = html[start:end]
        # page-summary 닫힘 직전에 삽입
        m = re.search(r'\n        </div>\n    </div>\n</div>', card)
        if not m:
            print(f"⚠ page-{num} 삽입 지점 못찾음", file=sys.stderr); continue
        newcard = card[:m.start()] + "\n            " + extra + card[m.start():]
        html = html[:start] + newcard + html[end:]
    # CSS 1회 주입
    if ".page-extra .ptable" not in html:
        html = html.replace("</style>", CSS + "\n</style>", 1)
    return html


def main():
    if len(sys.argv) < 3:
        print("사용: add_page_extras.py index.html page_extras.json [out.html]"); return 1
    idx, exj = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else idx
    html = open(idx, encoding="utf-8").read()
    extras = json.load(open(exj, encoding="utf-8"))
    html = build(html, extras)
    open(out, "w", encoding="utf-8").write(html)
    print(f"정리본 주입 완료 → {out} (페이지 {len(extras)}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
