#!/usr/bin/env python3
"""
도서 페이지 요약 HTML 자동 생성 스크립트.
HTML_문서_작성규칙.md를 따른다:
  - html { font-size: 18px; } 기본
  - 좌측 고정 사이드바 + 우측 본문
  - 본문 최상단 .main-title 블록
  - 사이드바 클릭 하이라이트 + scroll spy
  - 이모지 미사용 (본문)
  - 하단 서명

입력: pages_data.json + chapters_data.json
출력: index.html
"""
import json
from pathlib import Path
from datetime import date

SCRIPT_DIR = Path(__file__).parent

BOOK_TITLE = "CLI 완전활용"
BOOK_SUB = "AI 터미널 도구 3종 (Claude Code · Codex · Gemini CLI) 완전 정복"
SIGNATURE_NAME = "YUNDEOKSOO"
SIGNATURE_DATE = date.today().isoformat()
SIGNATURE_DESC = "도서 페이지별 요약 및 챕터 종합"


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ---------------- Sidebar ----------------

def build_sidebar(chapters):
    """챕터 제목은 챕터 종합 카드(#chs-*) 링크. 중복 섹션은 자동 회피."""
    out = []
    for ch in chapters:
        ch_id = ch.get('id', '')
        ch_title = ch['title']
        href = f"#{ch_id}" if ch_id else f"#page-{ch.get('intro_page', {}).get('num', '')}"
        out.append(f'        <div class="tree-chapter">')
        out.append(f'            <a href="{href}" class="tree-chapter-title" data-target="{ch_id}">{ch_title}</a>')

        # 챕터 도입 페이지가 있으면 직접 링크 (별도 섹션 없이)
        intro = ch.get('intro_page')
        if intro:
            out.append(f'            <div class="tree-pages tree-pages-intro">')
            out.append(f'                <a href="#page-{intro["num"]}" class="tree-page"><span class="page-num">p.{intro["num"]}</span> {intro["label"]}</a>')
            out.append(f'            </div>')

        for sec in ch['sections']:
            # 섹션 제목이 챕터 제목과 같으면 표시 생략 (중복 방지)
            if sec['title'].strip() == ch_title.strip():
                continue
            out.append(f'            <div class="tree-section">')
            out.append(f'                <div class="tree-section-title">{sec["title"]}</div>')
            out.append(f'                <div class="tree-pages">')
            for p in sec['pages']:
                out.append(f'                    <a href="#page-{p["num"]}" class="tree-page"><span class="page-num">p.{p["num"]}</span> {p["label"]}</a>')
            out.append(f'                </div>')
            out.append(f'            </div>')
        out.append(f'        </div>')
    return '\n'.join(out)


# ---------------- Chapter Summary Cards ----------------

def render_tags(tags):
    parts = []
    for t in tags:
        cls = "chs-tag core" if t.get('core') else "chs-tag"
        parts.append(f'<span class="{cls}">{t["text"]}</span>')
    return ''.join(parts)


def render_points(points):
    items = ''.join(f'<li>{p}</li>' for p in points)
    return f'<ul class="chs-points">{items}</ul>'


def render_table(tbl):
    headers = ''.join(f'<th>{h}</th>' for h in tbl['headers'])
    rows = []
    for row in tbl['rows']:
        cells = ''.join(f'<td>{c}</td>' for c in row)
        rows.append(f'<tr>{cells}</tr>')
    body = ''.join(rows)
    footer = ''
    if tbl.get('footer'):
        footer = f'<tfoot><tr><td colspan="{len(tbl["headers"])}">{tbl["footer"]}</td></tr></tfoot>'
    return f'''<div class="chs-block">
    <div class="chs-block-title">{tbl["title"]}</div>
    <table class="chs-table"><thead><tr>{headers}</tr></thead><tbody>{body}</tbody>{footer}</table>
</div>'''


def render_section(sec):
    blocks = []
    blocks.append(f'<div class="chs-block-title">{sec["title"]}</div>')

    if sec.get('points'):
        blocks.append(render_points(sec['points']))
    if sec.get('subsections'):
        for sub in sec['subsections']:
            blocks.append(f'<div class="chs-sub"><h4>{sub["heading"]}</h4>{render_points(sub["points"])}</div>')
    if sec.get('tags'):
        blocks.append(f'<div class="chs-sub"><h4>주요 용어</h4><div class="chs-tags">{render_tags(sec["tags"])}</div></div>')

    return f'<div class="chs-block">{"".join(blocks)}</div>'


def render_chapter_card(ch):
    sections_html = ''.join(render_section(s) for s in ch['sections'])
    tables_html = ''.join(render_table(t) for t in ch.get('tables', []))
    first_page = ch.get('first_page')
    page_link = f'<a href="#page-{first_page}">페이지별 요약 보기 →</a>' if first_page else ''
    return f'''<div class="chs-card" id="{ch["id"]}">
    <div class="chs-card-header">
        <h2>{ch["title"]}</h2>
        <div class="chs-meta">{ch["range"]} {page_link}</div>
    </div>
    <div class="chs-body">
        <div class="chs-overview">{ch["overview"]}</div>
        {sections_html}
        {tables_html}
    </div>
</div>'''


def build_chapter_summary(chapters_data):
    cards = ''.join(render_chapter_card(ch) for ch in chapters_data['chapters'])
    return f'''<section class="chs" id="chapters-summary">
<div class="chs-banner">
    <h2>챕터별 종합 정리</h2>
    <p>4장 ~ 14장 (Part 2 후반 ~ Part 5) 전체 흐름. 사이드바의 챕터 제목을 클릭하면 해당 챕터 카드로 이동합니다.</p>
</div>
{cards}
</section>
<div class="chs-divider">아래는 페이지별 상세 요약입니다</div>'''


# ---------------- Page Cards ----------------

def build_page_card(page, prev_num, next_num):
    num = page['num']
    nav = []
    if prev_num:
        nav.append(f'<a href="#page-{prev_num}">&larr; 이전</a>')
    if next_num:
        nav.append(f'<a href="#page-{next_num}">다음 &rarr;</a>')
    nav_html = ''.join(nav)

    intro = ''
    if page.get('chapter_intro'):
        ci = page['chapter_intro']
        intro = f'<div class="chapter-intro"><h3>{ci["title"]}</h3><p>{ci["desc"]}</p></div>'

    topics = ''.join(f'<span class="tag">{t}</span>' for t in page.get('topics', []))
    terms = ''.join(f'<span class="tag">{t}</span>' for t in page.get('terms', []))
    summary = page.get('summary', '')
    points_html = ''
    if page.get('points'):
        items = ''.join(f'<li>{p}</li>' for p in page['points'])
        points_html = f'<div class="section"><div class="section-title">핵심 내용</div><ul>{items}</ul></div>'

    return f'''<div class="page-card" id="page-{num}">
    <div class="page-header">
        <h2>Page {num}</h2>
        <div class="page-nav">{nav_html}</div>
    </div>
    <div class="page-body">
        <div class="page-image"><img src="../{BOOK_TITLE}_{num}.png" alt="Page {num}" loading="lazy"></div>
        <div class="page-summary">
            {intro}
            <div class="section"><div class="section-title">주요 주제</div><div class="tag-list">{topics}</div></div>
            <div class="section"><div class="section-title">주요 용어</div><div class="tag-list">{terms}</div></div>
            <div class="section"><div class="section-title">강의 요약</div><p class="summary-text">{summary}</p></div>
            {points_html}
        </div>
    </div>
</div>'''


# ---------------- HTML ----------------

def build_html(pages_data, chapters_data):
    chapters = pages_data['chapters']
    pages = pages_data['pages']
    total_pages = len(pages)

    sidebar_html = build_sidebar(chapters)
    chs_html = build_chapter_summary(chapters_data)

    page_cards = []
    for i, page in enumerate(pages):
        prev_num = pages[i-1]['num'] if i > 0 else None
        next_num = pages[i+1]['num'] if i < len(pages) - 1 else None
        page_cards.append(build_page_card(page, prev_num, next_num))
    pages_html = '\n'.join(page_cards)

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{BOOK_TITLE} - 도서 요약</title>
<style>
html {{ font-size: 18px; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif; background: #f5f5f5; color: #333; display: flex; min-height: 100vh; font-size: 0.85rem; }}

/* Sidebar */
.sidebar {{ width: 320px; background: #1a2332; color: white; position: fixed; top: 0; left: 0; height: 100vh; overflow-y: auto; z-index: 100; display: flex; flex-direction: column; }}
.sidebar-header {{ padding: 18px 20px; border-bottom: 1px solid #2c3e50; }}
.sidebar-header h1 {{ font-size: 1.05rem; margin-bottom: 4px; }}
.sidebar-header .subtitle {{ font-size: 0.72rem; color: #8899aa; line-height: 1.5; }}
.tree {{ padding: 10px 0; flex: 1; overflow-y: auto; }}
.tree-chapter {{ padding: 0; margin-bottom: 2px; }}
.tree-chapter-title {{ display: block; padding: 11px 18px; font-size: 0.84rem; font-weight: 700; color: #7ee787; text-decoration: none; border-left: 3px solid transparent; transition: all 0.15s; cursor: pointer; }}
.tree-chapter-title:hover {{ background: #2c3e50; }}
.tree-chapter-title.active {{ background: #f1c40f; color: #1a2332 !important; border-left-color: #f39c12; }}
.tree-section {{ padding: 0; }}
.tree-section-title {{ display: block; padding: 6px 18px 6px 30px; font-size: 0.72rem; font-weight: 600; color: #95a5a6; cursor: default; }}
.tree-pages {{ padding: 0; }}
.tree-pages-intro {{ margin-bottom: 4px; }}
.tree-page {{ display: block; padding: 5px 18px 5px 42px; font-size: 0.7rem; color: #bdc3c7; text-decoration: none; transition: all 0.15s; border-left: 3px solid transparent; }}
.tree-page:hover {{ background: #2c3e50; color: white; }}
.tree-page.active {{ background: #f1c40f; color: #2c3e50 !important; font-weight: 700; border-left-color: #f39c12; }}
.tree-page .page-num {{ color: #7f8c8d; margin-right: 6px; font-size: 0.92em; }}
.tree-page.active .page-num {{ color: #1a2332; }}

/* Main */
.main {{ margin-left: 320px; flex: 1; padding: 24px 28px; max-width: calc(100vw - 360px); }}

/* Main Title */
.main-title {{ background: linear-gradient(135deg, #1a2332 0%, #2c3e50 100%); border-radius: 12px; padding: 28px 32px; margin-bottom: 28px; color: white; box-shadow: 0 4px 24px rgba(0,0,0,0.15); }}
.main-title h1 {{ font-size: 1.6rem; margin: 0 0 6px; font-weight: 800; }}
.main-title .mt-sub {{ font-size: 0.9rem; color: #8899aa; margin-bottom: 12px; }}
.main-title .mt-desc {{ font-size: 0.82rem; color: #bcc8d4; line-height: 1.7; margin-bottom: 14px; }}
.main-title .mt-tags {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.main-title .mt-tag {{ display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 0.72rem; font-weight: 600; color: white; }}
.mt-tag.tt-net {{ background: rgba(41,128,185,0.4); }}
.mt-tag.tt-arch {{ background: rgba(142,68,173,0.4); }}
.mt-tag.tt-rust {{ background: rgba(192,57,43,0.4); }}
.mt-tag.tt-ver {{ background: rgba(39,174,96,0.4); }}
.mt-tag.tt-files {{ background: rgba(149,165,166,0.4); }}
.mt-tag.tt-build {{ background: rgba(243,156,18,0.4); }}

/* Chapter Summary Cards */
.chs {{ margin-bottom: 50px; scroll-margin-top: 20vh; }}
.chs-banner {{ background: linear-gradient(135deg, #16a085 0%, #1abc9c 100%); color: white; padding: 20px 26px; border-radius: 12px; margin-bottom: 24px; }}
.chs-banner h2 {{ font-size: 1.25rem; margin-bottom: 6px; }}
.chs-banner p {{ font-size: 0.82rem; opacity: 0.94; line-height: 1.6; }}

.chs-card {{ background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); margin-bottom: 36px; overflow: hidden; scroll-margin-top: 20vh; }}
.chs-card.highlight {{ animation: cardFlash 2.5s ease-out; }}
@keyframes cardFlash {{
  0%   {{ box-shadow: 0 0 0 4px #f9e79f; }}
  40%  {{ box-shadow: 0 0 0 4px #f9e79f; }}
  100% {{ box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
}}
.chs-card-header {{ background: linear-gradient(135deg, #1abc9c 0%, #16a085 100%); color: white; padding: 22px 28px; }}
.chs-card-header h2 {{ font-size: 1.35rem; margin-bottom: 6px; }}
.chs-meta {{ font-size: 0.78rem; opacity: 0.92; }}
.chs-meta a {{ color: white; text-decoration: underline; margin-left: 10px; }}
.chs-body {{ padding: 26px 28px; }}

.chs-overview {{ background: #f0faf7; border-left: 4px solid #1abc9c; padding: 16px 20px; margin-bottom: 24px; border-radius: 0 8px 8px 0; font-size: 0.88rem; line-height: 1.8; color: #2c3e50; }}

.chs-block {{ margin-bottom: 26px; }}
.chs-block-title {{ font-size: 0.98rem; font-weight: 700; color: #1abc9c; margin-bottom: 12px; padding-bottom: 6px; border-bottom: 2px solid #1abc9c; display: inline-block; }}

.chs-sub {{ margin-bottom: 14px; }}
.chs-sub h4 {{ font-size: 0.88rem; color: #2c3e50; margin-bottom: 6px; font-weight: 700; }}

.chs-points {{ list-style: none; padding: 0; }}
.chs-points li {{ padding: 5px 0 5px 18px; position: relative; font-size: 0.84rem; line-height: 1.7; color: #444; }}
.chs-points li::before {{ content: "▸"; position: absolute; left: 0; color: #1abc9c; }}
.chs-points li strong {{ color: #2c3e50; }}
.chs-points code {{ background: #f4f4f4; padding: 1px 6px; border-radius: 3px; font-family: 'SF Mono', Consolas, Menlo, monospace; font-size: 0.92em; color: #c0392b; }}

.chs-tags {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.chs-tag {{ background: #e8f8f5; color: #16a085; padding: 5px 12px; border-radius: 14px; font-size: 0.76rem; font-weight: 600; }}
.chs-tag.core {{ background: #1abc9c; color: white; }}

.chs-table {{ width: 100%; border-collapse: collapse; margin: 6px 0; font-size: 0.8rem; }}
.chs-table thead {{ background: #2c3e50; color: white; }}
.chs-table th {{ padding: 9px 11px; text-align: left; font-weight: 600; border: 1px solid #2c3e50; }}
.chs-table td {{ padding: 9px 11px; border: 1px solid #e0e0e0; vertical-align: top; line-height: 1.6; color: #444; }}
.chs-table tfoot td {{ background: #f0faf7; font-size: 0.78rem; color: #2c3e50; }}
.chs-table tbody tr:nth-child(even) {{ background: #fafafa; }}
.chs-table tbody tr:hover {{ background: #f0faf7; }}
.chs-table td code {{ background: #f4f4f4; padding: 1px 5px; border-radius: 3px; font-family: 'SF Mono', Consolas, Menlo, monospace; font-size: 0.92em; color: #c0392b; }}
.chs-table td strong {{ color: #2c3e50; }}

.chs-divider {{ text-align: center; margin: 40px 0 30px; padding: 14px; background: white; border-radius: 8px; box-shadow: 0 1px 6px rgba(0,0,0,0.05); font-size: 0.88rem; color: #2c3e50; font-weight: 700; }}
.chs-divider::before {{ content: "▼ "; color: #1abc9c; }}

/* Page Cards */
.page-card {{ background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); margin-bottom: 30px; overflow: hidden; scroll-margin-top: 20vh; }}
.page-header {{ background: #1abc9c; color: white; padding: 14px 22px; display: flex; justify-content: space-between; align-items: center; }}
.page-header h2 {{ font-size: 1.05rem; }}
.page-nav {{ display: flex; gap: 8px; }}
.page-nav a {{ color: white; text-decoration: none; padding: 4px 12px; border: 1px solid rgba(255,255,255,0.5); border-radius: 4px; font-size: 0.74rem; }}
.page-nav a:hover {{ background: rgba(255,255,255,0.2); }}
.page-body {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; }}
.page-image {{ padding: 18px; background: #fafafa; border-right: 1px solid #eee; display: flex; align-items: flex-start; justify-content: center; }}
.page-image img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 4px; cursor: pointer; transition: transform 0.3s; }}
.page-image img:hover {{ transform: scale(1.02); }}
.page-summary {{ padding: 22px; }}
.section {{ margin-bottom: 18px; }}
.section-title {{ font-size: 0.82rem; font-weight: 700; color: #1abc9c; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 2px solid #1abc9c; display: inline-block; }}
.section ul {{ list-style: none; padding: 0; }}
.section li {{ padding: 4px 0 4px 16px; position: relative; font-size: 0.82rem; line-height: 1.6; }}
.section li::before {{ content: "\\25B8"; position: absolute; left: 0; color: #1abc9c; }}
.tag-list {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.tag {{ background: #e8f8f5; color: #1abc9c; padding: 4px 10px; border-radius: 12px; font-size: 0.74rem; font-weight: 600; }}
.summary-text {{ font-size: 0.82rem; line-height: 1.8; color: #555; }}
.chapter-intro {{ background: #f0faf7; border-left: 4px solid #1abc9c; padding: 14px 18px; margin-bottom: 18px; border-radius: 0 8px 8px 0; }}
.chapter-intro h3 {{ font-size: 0.95rem; color: #2c3e50; margin-bottom: 6px; }}
.chapter-intro p {{ font-size: 0.8rem; line-height: 1.7; color: #555; margin: 0; }}

.signature {{ margin-top: 40px; padding: 18px 22px; background: white; border-radius: 8px; border-left: 4px solid #1abc9c; font-size: 0.78rem; color: #555; }}
.signature strong {{ color: #2c3e50; }}

/* Modal */
.modal-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; justify-content: center; align-items: center; cursor: zoom-out; }}
.modal-overlay.active {{ display: flex; }}
.modal-overlay img {{ max-width: 95vw; max-height: 95vh; object-fit: contain; border-radius: 4px; box-shadow: 0 0 40px rgba(0,0,0,0.5); }}
.modal-close {{ position: fixed; top: 20px; right: 30px; color: white; font-size: 2em; cursor: pointer; z-index: 1001; line-height: 1; }}
.modal-close:hover {{ color: #1abc9c; }}

@media (max-width: 900px) {{
    .sidebar {{ width: 240px; }}
    .main {{ margin-left: 240px; max-width: calc(100vw - 260px); padding: 16px; }}
    .page-body {{ grid-template-columns: 1fr; }}
    .page-image {{ border-right: none; border-bottom: 1px solid #eee; }}
}}
</style>
</head>
<body>

<nav class="sidebar">
    <div class="sidebar-header">
        <h1>{BOOK_TITLE}</h1>
        <div class="subtitle">{BOOK_SUB}<br>도서 페이지별 요약 노트</div>
    </div>
    <div class="tree">
        <a href="#chapters-summary" class="tree-chapter-title" data-target="chapters-summary" style="color:#f1c40f;">[챕터 종합 정리]</a>
{sidebar_html}
    </div>
</nav>

<div class="main">

<div class="main-title">
    <h1>{BOOK_TITLE}</h1>
    <div class="mt-sub">{BOOK_SUB}</div>
    <div class="mt-desc">
        교보eBook 앱에서 캡처한 도서 이미지를 바탕으로 정리한 페이지별 요약 노트.
        좌측 사이드바의 <strong>챕터 제목</strong>을 클릭하면 해당 챕터의 종합 정리(개요·핵심 내용·주요 용어·비교 표)로 이동하고,
        하위 페이지 번호를 클릭하면 페이지별 상세 요약과 원본 이미지를 볼 수 있습니다.
    </div>
    <div class="mt-tags">
        <span class="mt-tag tt-net">Claude Code</span>
        <span class="mt-tag tt-arch">Codex CLI</span>
        <span class="mt-tag tt-rust">Gemini CLI</span>
        <span class="mt-tag tt-ver">{total_pages}페이지</span>
        <span class="mt-tag tt-build">5개 챕터</span>
        <span class="mt-tag tt-files">12개 비교 표</span>
    </div>
</div>

{chs_html}

{pages_html}

<div class="signature">
    작성: <strong>{SIGNATURE_NAME}</strong> · {SIGNATURE_DATE} · {SIGNATURE_DESC}
</div>

</div>

<div class="modal-overlay" id="imageModal">
    <span class="modal-close" id="modalClose">&times;</span>
    <img id="modalImg" src="" alt="">
</div>

<script>
// 이미지 모달
const modal = document.getElementById('imageModal');
const modalImg = document.getElementById('modalImg');
document.querySelectorAll('.page-image img').forEach(function(img) {{
    img.addEventListener('click', function() {{
        modalImg.src = img.src;
        modal.classList.add('active');
    }});
}});
modal.addEventListener('click', function() {{ modal.classList.remove('active'); }});
document.getElementById('modalClose').addEventListener('click', function() {{ modal.classList.remove('active'); }});
document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') modal.classList.remove('active');
}});

// 챕터 카드 클릭 시 하이라이트 애니메이션
function flashCard(id) {{
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('highlight');
    void el.offsetWidth;  // reflow
    el.classList.add('highlight');
}}

// 사이드바 클릭: 1초간 spy 비활성화 + 카드 하이라이트
var spyDisabled = false;
document.querySelectorAll('.tree-chapter-title, .tree-page').forEach(function(link) {{
    link.addEventListener('click', function(e) {{
        spyDisabled = true;
        setTimeout(function() {{ spyDisabled = false; }}, 1000);
        var href = link.getAttribute('href') || '';
        if (href.startsWith('#')) {{
            var target = href.slice(1);
            // 챕터 제목 클릭 시 카드 플래시
            if (target.startsWith('chs-')) {{
                setTimeout(function() {{ flashCard(target); }}, 300);
            }}
        }}
    }});
}});

// Scroll spy
var allSidebarLinks = document.querySelectorAll('.tree-chapter-title, .tree-page');
var linkMap = {{}};
allSidebarLinks.forEach(function(a) {{
    var h = a.getAttribute('href') || '';
    if (h.startsWith('#')) linkMap[h.slice(1)] = a;
}});

function setActive(id) {{
    allSidebarLinks.forEach(function(a) {{ a.classList.remove('active'); }});
    var link = linkMap[id];
    if (link) {{
        link.classList.add('active');
        link.scrollIntoView({{ block: 'center', behavior: 'smooth' }});
    }}
}}

var spyTargets = document.querySelectorAll('.chs-card, .page-card');
var observer = new IntersectionObserver(function(entries) {{
    if (spyDisabled) return;
    entries.forEach(function(entry) {{
        if (entry.isIntersecting) setActive(entry.target.id);
    }});
}}, {{ rootMargin: '-15% 0px -75% 0px', threshold: 0 }});
spyTargets.forEach(function(t) {{ observer.observe(t); }});
</script>

</body>
</html>'''


def main():
    pages_data = load_json(SCRIPT_DIR / 'pages_data.json')
    chapters_data = load_json(SCRIPT_DIR / 'chapters_data.json')
    html = build_html(pages_data, chapters_data)
    out = SCRIPT_DIR / 'index.html'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Generated {out}")
    print(f"  - Pages: {len(pages_data['pages'])}")
    print(f"  - Chapters (sidebar): {len(pages_data['chapters'])}")
    print(f"  - Chapter summary cards: {len(chapters_data['chapters'])}")


if __name__ == '__main__':
    main()
