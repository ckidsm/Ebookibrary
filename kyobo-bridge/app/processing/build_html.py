"""HTML 빌드 — pages_data.json → summary/index.html.

기존 books/CLI_완전활용/summary/generate_html.py 의 핵심 로직 이식:
- 좌측 사이드바 트리 (챕터-섹션-페이지) + scroll spy
- 페이지 카드 (좌: 원본 이미지, 우: 요약)
- 이미지 모달

스킵: chs-card (챕터 종합 카드, chapters_data.json 필요) — 사용자 수동 작성용.
      Phase C-4 또는 후속에서 자동 생성 옵션 추가 가능.
"""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path


# ── 사이드바 ───────────────────────────────────────────────
def _build_sidebar(chapters: list[dict]) -> str:
    out = []
    for ch in chapters:
        ch_id = ch.get("id", "")
        ch_title = ch["title"]
        ip = ch.get("intro_page") or {}
        href = f"#{ch_id}" if ch_id else f"#page-{ip.get('num', '')}"
        out.append('        <div class="tree-chapter">')
        out.append(
            f'            <a href="{href}" class="tree-chapter-title" '
            f'data-target="{ch_id}">{html.escape(ch_title)}</a>'
        )
        intro = ch.get("intro_page")
        if intro:
            out.append('            <div class="tree-pages tree-pages-intro">')
            out.append(
                f'                <a href="#page-{intro["num"]}" class="tree-page">'
                f'<span class="page-num">p.{intro["num"]}</span> '
                f'{html.escape(intro.get("label", ""))}</a>'
            )
            out.append("            </div>")
        for sec in ch["sections"]:
            if sec["title"].strip() == ch_title.strip():
                continue
            out.append('            <div class="tree-section">')
            out.append(
                f'                <div class="tree-section-title">{html.escape(sec["title"])}</div>'
            )
            out.append('                <div class="tree-pages">')
            for p in sec["pages"]:
                out.append(
                    f'                    <a href="#page-{p["num"]}" class="tree-page">'
                    f'<span class="page-num">p.{p["num"]}</span> '
                    f'{html.escape(p.get("label", ""))}</a>'
                )
            out.append("                </div>")
            out.append("            </div>")
        out.append("        </div>")
    return "\n".join(out)


# ── 페이지 카드 ─────────────────────────────────────────────
def _build_page_card(page: dict, prev_num: int | None, next_num: int | None, image_pattern: str) -> str:
    num = page["num"]
    nav = []
    if prev_num: nav.append(f'<a href="#page-{prev_num}">&larr; 이전</a>')
    if next_num: nav.append(f'<a href="#page-{next_num}">다음 &rarr;</a>')
    nav_html = "".join(nav)

    intro = ""
    if page.get("chapter_intro"):
        ci = page["chapter_intro"]
        intro = (
            f'<div class="chapter-intro"><h3>{html.escape(ci.get("title",""))}</h3>'
            f'<p>{ci.get("overview") or ci.get("desc","")}</p></div>'
        )

    topics = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in page.get("topics", []))
    terms = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in page.get("terms", []))
    summary = page.get("summary", "")
    points_html = ""
    if page.get("points"):
        items = "".join(f"<li>{p}</li>" for p in page["points"])
        points_html = (
            '<div class="section"><div class="section-title">핵심 내용</div>'
            f"<ul>{items}</ul></div>"
        )

    img_src = image_pattern.format(num=num)
    return f"""<div class="page-card" id="page-{num}">
    <div class="page-header">
        <h2>Page {num}</h2>
        <div class="page-nav">{nav_html}</div>
    </div>
    <div class="page-body">
        <div class="page-image"><img src="{img_src}" alt="Page {num}" loading="lazy"></div>
        <div class="page-summary">
            {intro}
            <div class="section"><div class="section-title">주요 주제</div><div class="tag-list">{topics}</div></div>
            <div class="section"><div class="section-title">주요 용어</div><div class="tag-list">{terms}</div></div>
            <div class="section"><div class="section-title">강의 요약</div><p class="summary-text">{summary}</p></div>
            {points_html}
        </div>
    </div>
</div>"""


# ── 메인 빌드 ──────────────────────────────────────────────
_CSS = """\
html { font-size: 18px; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif; background: #f5f5f5; color: #333; display: flex; min-height: 100vh; font-size: 0.85rem; }

/* Sidebar */
.sidebar { width: 320px; background: #1a2332; color: white; position: fixed; top: 0; left: 0; height: 100vh; overflow-y: auto; z-index: 100; display: flex; flex-direction: column; }
.sidebar-header { padding: 18px 20px; border-bottom: 1px solid #2c3e50; }
.sidebar-header h1 { font-size: 1.05rem; margin-bottom: 4px; }
.sidebar-header .subtitle { font-size: 0.72rem; color: #8899aa; line-height: 1.5; }
.tree { padding: 10px 0; flex: 1; overflow-y: auto; }
.tree-chapter { padding: 0; margin-bottom: 2px; }
.tree-chapter-title { display: block; padding: 11px 18px; font-size: 0.84rem; font-weight: 700; color: #7ee787; text-decoration: none; border-left: 3px solid transparent; transition: all 0.15s; cursor: pointer; }
.tree-chapter-title:hover { background: #2c3e50; }
.tree-chapter-title.active { background: #f1c40f; color: #1a2332 !important; border-left-color: #f39c12; }
.tree-section { padding: 0; }
.tree-section-title { display: block; padding: 6px 18px 6px 30px; font-size: 0.72rem; font-weight: 600; color: #95a5a6; cursor: default; }
.tree-pages { padding: 0; }
.tree-pages-intro { margin-bottom: 4px; }
.tree-page { display: block; padding: 5px 18px 5px 42px; font-size: 0.7rem; color: #bdc3c7; text-decoration: none; transition: all 0.15s; border-left: 3px solid transparent; }
.tree-page:hover { background: #2c3e50; color: white; }
.tree-page.active { background: #f1c40f; color: #2c3e50 !important; font-weight: 700; border-left-color: #f39c12; }
.tree-page .page-num { color: #7f8c8d; margin-right: 6px; font-size: 0.92em; }
.tree-page.active .page-num { color: #1a2332; }

/* Main */
.main { margin-left: 320px; flex: 1; padding: 24px 28px; max-width: calc(100vw - 360px); }

/* Main Title */
.main-title { background: linear-gradient(135deg, #1a2332 0%, #2c3e50 100%); border-radius: 12px; padding: 28px 32px; margin-bottom: 28px; color: white; box-shadow: 0 4px 24px rgba(0,0,0,0.15); }
.main-title h1 { font-size: 1.6rem; margin: 0 0 6px; font-weight: 800; }
.main-title .mt-sub { font-size: 0.9rem; color: #8899aa; margin-bottom: 12px; }
.main-title .mt-desc { font-size: 0.82rem; color: #bcc8d4; line-height: 1.7; margin-bottom: 14px; }
.main-title .mt-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.mt-tag { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 0.72rem; font-weight: 600; color: white; background: rgba(41,128,185,0.4); }

/* Page Cards */
.page-card { background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); margin-bottom: 30px; overflow: hidden; scroll-margin-top: 20vh; }
.page-header { background: #1abc9c; color: white; padding: 14px 22px; display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { font-size: 1.05rem; }
.page-nav { display: flex; gap: 8px; }
.page-nav a { color: white; text-decoration: none; padding: 4px 12px; border: 1px solid rgba(255,255,255,0.5); border-radius: 4px; font-size: 0.74rem; }
.page-nav a:hover { background: rgba(255,255,255,0.2); }
.page-body { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
.page-image { padding: 18px; background: #fafafa; border-right: 1px solid #eee; display: flex; align-items: flex-start; justify-content: center; }
.page-image img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px; cursor: pointer; transition: transform 0.3s; }
.page-image img:hover { transform: scale(1.02); }
.page-summary { padding: 22px; }
.section { margin-bottom: 18px; }
.section-title { font-size: 0.82rem; font-weight: 700; color: #1abc9c; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 2px solid #1abc9c; display: inline-block; }
.section ul { list-style: none; padding: 0; }
.section li { padding: 4px 0 4px 16px; position: relative; font-size: 0.82rem; line-height: 1.6; }
.section li::before { content: "\\25B8"; position: absolute; left: 0; color: #1abc9c; }
.section li strong { color: #2c3e50; }
.section li code { background: #f4f4f4; padding: 1px 5px; border-radius: 3px; font-family: 'SF Mono', Consolas, Menlo, monospace; font-size: 0.92em; color: #c0392b; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { background: #e8f8f5; color: #1abc9c; padding: 4px 10px; border-radius: 12px; font-size: 0.74rem; font-weight: 600; }
.summary-text { font-size: 0.82rem; line-height: 1.8; color: #555; }
.chapter-intro { background: #f0faf7; border-left: 4px solid #1abc9c; padding: 14px 18px; margin-bottom: 18px; border-radius: 0 8px 8px 0; }
.chapter-intro h3 { font-size: 0.95rem; color: #2c3e50; margin-bottom: 6px; }
.chapter-intro p { font-size: 0.8rem; line-height: 1.7; color: #555; margin: 0; }

.signature { margin-top: 40px; padding: 18px 22px; background: white; border-radius: 8px; border-left: 4px solid #1abc9c; font-size: 0.78rem; color: #555; }
.signature strong { color: #2c3e50; }

/* Modal */
.modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; justify-content: center; align-items: center; cursor: zoom-out; }
.modal-overlay.active { display: flex; }
.modal-overlay img { max-width: 95vw; max-height: 95vh; object-fit: contain; border-radius: 4px; box-shadow: 0 0 40px rgba(0,0,0,0.5); }
.modal-close { position: fixed; top: 20px; right: 30px; color: white; font-size: 2em; cursor: pointer; z-index: 1001; line-height: 1; }
.modal-close:hover { color: #1abc9c; }

@media (max-width: 900px) {
    .sidebar { width: 240px; }
    .main { margin-left: 240px; max-width: calc(100vw - 260px); padding: 16px; }
    .page-body { grid-template-columns: 1fr; }
    .page-image { border-right: none; border-bottom: 1px solid #eee; }
}
"""

_JS = """\
const modal = document.getElementById('imageModal');
const modalImg = document.getElementById('modalImg');
document.querySelectorAll('.page-image img').forEach(function(img) {
    img.addEventListener('click', function() {
        modalImg.src = img.src;
        modal.classList.add('active');
    });
});
modal.addEventListener('click', function() { modal.classList.remove('active'); });
document.getElementById('modalClose').addEventListener('click', function() { modal.classList.remove('active'); });
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') modal.classList.remove('active');
});

var spyDisabled = false;
document.querySelectorAll('.tree-chapter-title, .tree-page').forEach(function(link) {
    link.addEventListener('click', function() {
        spyDisabled = true;
        setTimeout(function() { spyDisabled = false; }, 1000);
    });
});

var allSidebarLinks = document.querySelectorAll('.tree-chapter-title, .tree-page');
var linkMap = {};
allSidebarLinks.forEach(function(a) {
    var h = a.getAttribute('href') || '';
    if (h.startsWith('#')) linkMap[h.slice(1)] = a;
});
function setActive(id) {
    allSidebarLinks.forEach(function(a) { a.classList.remove('active'); });
    var link = linkMap[id];
    if (link) {
        link.classList.add('active');
        link.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
}
var spyTargets = document.querySelectorAll('.page-card');
var observer = new IntersectionObserver(function(entries) {
    if (spyDisabled) return;
    entries.forEach(function(entry) {
        if (entry.isIntersecting) setActive(entry.target.id);
    });
}, { rootMargin: '-15% 0px -75% 0px', threshold: 0 });
spyTargets.forEach(function(t) { observer.observe(t); });
"""


def build_html(
    book_dir: Path,
    pages_data: dict,
    title: str | None = None,
    subtitle: str = "도서 페이지별 요약 노트",
    signature: str = "YUNDEOKSOO",
    image_pattern: str | None = None,
) -> Path:
    """pages_data → summary/index.html 생성.

    image_pattern: 페이지 이미지 src 패턴.
    기본은 `../thumbs/page_NNN.png` (capture-auto 가 1800px 썸네일 생성).
    """
    title = title or book_dir.name
    pages = pages_data["pages"]
    chapters = pages_data["chapters"]
    if image_pattern is None:
        # books/<slug>/thumbs/page_NNN.png — capture-auto 표준 출력
        image_pattern = "../thumbs/page_{num:03d}.png"

    sidebar = _build_sidebar(chapters)
    page_cards = []
    for i, p in enumerate(pages):
        prev_num = pages[i-1]["num"] if i > 0 else None
        next_num = pages[i+1]["num"] if i < len(pages) - 1 else None
        page_cards.append(_build_page_card(p, prev_num, next_num, image_pattern))

    doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} - 도서 요약</title>
<style>
{_CSS}
</style>
</head>
<body>

<nav class="sidebar">
    <div class="sidebar-header">
        <h1>{html.escape(title)}</h1>
        <div class="subtitle">{html.escape(subtitle)}</div>
    </div>
    <div class="tree">
{sidebar}
    </div>
</nav>

<div class="main">

<div class="main-title">
    <h1>{html.escape(title)}</h1>
    <div class="mt-sub">{html.escape(subtitle)}</div>
    <div class="mt-desc">
        교보eBook 앱에서 캡처한 도서 이미지를 바탕으로 정리한 페이지별 요약 노트.
        좌측 사이드바의 페이지 번호를 클릭하면 해당 페이지의 상세 요약과 원본 이미지로 이동합니다.
    </div>
    <div class="mt-tags">
        <span class="mt-tag">{len(pages)}페이지</span>
        <span class="mt-tag">{len(chapters)}챕터</span>
    </div>
</div>

{"".join(page_cards)}

<div class="signature">
    작성: <strong>{html.escape(signature)}</strong> · {date.today().isoformat()} · 자동 생성 (bookcapture)
</div>

</div>

<div class="modal-overlay" id="imageModal">
    <span class="modal-close" id="modalClose">&times;</span>
    <img id="modalImg" src="" alt="">
</div>

<script>
{_JS}
</script>

</body>
</html>
"""

    out = book_dir / "summary" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"[build_html] {out} ({len(pages)} 페이지, {len(chapters)} 챕터)")
    return out


# ── 하위 호환: C-2 placeholder API 유지 ─────────────────────
def build_index(book_dir: Path, title: str | None = None) -> Path:
    """C-2 placeholder. summary/pages_data.json 있으면 build_html() 호출,
    없으면 단순 썸네일 그리드 인덱스."""
    summary_dir = book_dir / "summary"
    pages_data_path = summary_dir / "pages_data.json"
    if pages_data_path.exists():
        with pages_data_path.open(encoding="utf-8") as f:
            pages_data = json.load(f)
        return build_html(book_dir, pages_data, title=title)
    # 폴백 — 단순 그리드 (C-2 placeholder 유지)
    pngs = sorted(book_dir.glob("*.png"))
    ocr_dir = summary_dir / "ocr_text"
    summary_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for p in pngs:
        try: num = int(p.stem.split("_")[-1])
        except ValueError: num = 0
        has_ocr = (ocr_dir / f"page_{num:03d}.txt").exists()
        cards.append(
            f'<div class="card"><img src="../{p.name}" loading="lazy">'
            f'<div class="meta"><span>p.{num:03d}</span>'
            f'<span class="{"ocrhint" if has_ocr else "ocrno"}">'
            f'{"OCR ✓" if has_ocr else "OCR ✗"}</span></div></div>'
        )
    out = summary_dir / "index.html"
    out.write_text(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>{html.escape(title or book_dir.name)} — placeholder</title>
<style>body{{font-family:-apple-system,sans-serif;background:#0a0c10;color:#e6ecf2;margin:0;padding:30px;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;}}
.card{{background:#11151c;border:1px solid #2f3a4d;border-radius:8px;padding:10px;}}
.card img{{width:100%;border-radius:4px;display:block;}}
.card .meta{{font-family:monospace;font-size:11px;color:#8b96a8;margin-top:6px;display:flex;justify-content:space-between;}}
.ocrhint{{color:#10b981;}} .ocrno{{color:#f59e0b;}}</style></head>
<body><h1 style="color:#22d3ee">📖 {html.escape(title or book_dir.name)}</h1>
<p style="color:#8b96a8;font-family:monospace;">
  placeholder · {len(pngs)} 페이지 · pages_data.json 생성하면 본격 빌드 (merge 필요)
</p>
<div class="grid">{''.join(cards)}</div></body></html>""", encoding="utf-8")
    print(f"[build_html] placeholder {out} ({len(pngs)} 페이지)")
    return out
