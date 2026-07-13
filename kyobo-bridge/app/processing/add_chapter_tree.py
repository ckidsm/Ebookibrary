# -*- coding: utf-8 -*-
"""summary/index.html 에 챕터 트리(접기/펴기) + 챕터 요약 카드 주입 — 다른 책에도 재사용.

chapters.json 형식 (배열):
  [{"num":1,"title":"...","start":18,"end":31,"summary":"...","topics":["..",".."]}, ...]
  (앞부분 front matter 는 num:0 또는 생략 — start<첫 챕터 start 면 '표지·서문·목차' 그룹으로 묶음)

사용: python scripts/add_chapter_tree.py index.html chapters.json [out.html]
챕터 경계·요약은 detect_chapters.py 로 초안 뽑고 사람이 검토·보완.
"""
import re, json, sys


def esc(s): return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


CSS = """
.tree-cgroup { border-bottom: 1px solid rgba(255,255,255,0.06); }
.tree-cg-head { display:flex; align-items:center; gap:6px; padding:9px 14px; cursor:pointer; color:#cdd9e5; font-size:0.82rem; font-weight:600; user-select:none; }
.tree-cg-head:hover { background:rgba(255,255,255,0.05); }
.cg-arrow { font-size:0.6rem; transition:transform 0.15s; color:#7a8ba0; }
.tree-cgroup.open .cg-arrow { transform:rotate(90deg); }
.cg-name { flex:1; }
.cg-range { font-size:0.68rem; color:#7a8ba0; font-weight:400; }
.tree-cg-pages { display:none; padding:2px 0 6px; background:rgba(0,0,0,0.15); }
.tree-cgroup.open .tree-cg-pages { display:block; }
.tree-chsum { color:#7ee787 !important; font-weight:600; }
.chapter-summary { background:linear-gradient(135deg,#12303a 0%,#1a2332 100%); border-radius:14px; padding:26px 30px; margin:8px 0 30px; color:#e6edf3; box-shadow:0 4px 24px rgba(0,0,0,0.18); scroll-margin-top:20vh; border-left:5px solid #1abc9c; }
.chsum-badge { display:inline-block; background:#1abc9c; color:#04120e; font-weight:800; font-size:0.72rem; letter-spacing:1px; padding:3px 10px; border-radius:20px; }
.chsum-title { font-size:1.35rem; margin:10px 0 4px; color:#fff; }
.chsum-range { font-size:0.74rem; color:#8fb7c9; margin-bottom:12px; }
.chsum-body { font-size:0.92rem; line-height:1.75; color:#cfe0ea; margin:0 0 14px; }
.chsum-chips { display:flex; flex-wrap:wrap; gap:7px; }
.chsum-chip { background:rgba(26,188,156,0.16); color:#7ee7cd; font-size:0.76rem; padding:4px 11px; border-radius:16px; }
"""

JS = """
function toggleCg(h){ h.parentElement.classList.toggle('open'); }
(function(){
  document.addEventListener('DOMContentLoaded', function(){
    var first=document.querySelector('.tree-cgroup'); if(first) first.classList.add('open');
  });
  var mo=new MutationObserver(function(muts){ muts.forEach(function(m){
    if(m.target.classList && m.target.classList.contains('active')){
      var g=m.target.closest('.tree-cgroup'); if(g) g.classList.add('open'); }
  });});
  document.querySelectorAll('.tree-page').forEach(function(a){ mo.observe(a,{attributes:true,attributeFilter:['class']}); });
})();
"""


def build(html, chapters, total_pages):
    chapters = sorted(chapters, key=lambda c: c["start"])
    first_start = chapters[0]["start"]
    # ── 트리 ──
    tree = []
    if first_start > 1:  # 앞부분(front matter)
        tree.append('<div class="tree-cgroup"><div class="tree-cg-head" onclick="toggleCg(this)"><span class="cg-arrow">▶</span><span class="cg-name">표지·서문·목차</span><span class="cg-range">p.1-%d</span></div><div class="tree-cg-pages">' % (first_start - 1))
        for n in range(1, first_start):
            tree.append(f'<a href="#page-{n}" class="tree-page"><span class="page-num">p.{n}</span> p.{n}</a>')
        tree.append('</div></div>')
    for c in chapters:
        a, b = c["start"], c["end"]
        tree.append(f'<div class="tree-cgroup"><div class="tree-cg-head" onclick="toggleCg(this)"><span class="cg-arrow">▶</span><span class="cg-name">CH{c["num"]}. {esc(c["title"])}</span><span class="cg-range">p.{a}-{b}</span></div><div class="tree-cg-pages">')
        tree.append(f'<a href="#chapter-{c["num"]}" class="tree-page tree-chsum">📖 챕터 요약</a>')
        for n in range(a, b + 1):
            tree.append(f'<a href="#page-{n}" class="tree-page"><span class="page-num">p.{n}</span> p.{n}</a>')
        tree.append('</div></div>')
    tree_html = "\n".join(tree)
    html = re.sub(r'<div class="tree">.*?</nav>',
                  '<div class="tree">\n' + tree_html + '\n        </div>\n    </div>\n</nav>',
                  html, count=1, flags=re.S)
    # ── 챕터 카드 ──
    for c in chapters:
        chips = "".join(f'<span class="chsum-chip">{esc(t)}</span>' for t in c.get("topics", []))
        card = (f'<div class="chapter-summary" id="chapter-{c["num"]}">'
                f'<div class="chsum-badge">CHAPTER {c["num"]}</div>'
                f'<h2 class="chsum-title">{esc(c["title"])}</h2>'
                f'<div class="chsum-range">p.{c["start"]} – p.{c["end"]} · 이 챕터에서 다루는 내용</div>'
                f'<p class="chsum-body">{esc(c.get("summary",""))}</p>'
                f'<div class="chsum-chips">{chips}</div></div>\n')
        marker = f'<div class="page-card" id="page-{c["start"]}">'
        if marker in html:
            html = html.replace(marker, card + marker, 1)
    # ── CSS / JS ──
    html = html.replace("</style>", CSS + "\n</style>", 1)
    if "</script>\n\n</body>" in html:
        html = html.replace("</script>\n\n</body>", JS + "\n</script>\n\n</body>", 1)
    else:
        html = html.replace("</script>", JS + "\n</script>", 1)
    return html


def main():
    if len(sys.argv) < 3:
        print("사용: add_chapter_tree.py index.html chapters.json [out.html]"); return 1
    idx, chj = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else idx
    html = open(idx, encoding="utf-8").read()
    chapters = json.load(open(chj, encoding="utf-8"))
    html = build(html, chapters, 0)
    open(out, "w", encoding="utf-8").write(html)
    print(f"주입 완료 → {out} (챕터 {len(chapters)}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
