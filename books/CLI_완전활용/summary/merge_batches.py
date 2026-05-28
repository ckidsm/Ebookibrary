#!/usr/bin/env python3
"""
batch JSON 파일들을 합쳐서 pages_data.json을 생성하는 스크립트.

각 챕터/Part에 사이드바 클릭 시 사용할 chapter_id를 부여하고,
챕터 시작 페이지가 만든 첫 섹션의 title이 챕터 title과 같으면
중복으로 보지 않고 그 페이지를 챕터 직속(no-section) 항목으로 묶는다.
"""
import json
import re
from pathlib import Path

script_dir = Path(__file__).parent

batch_files = [
    'batch_127.json',
    'batch_156.json',
    'batch_186.json',
    'batch_216.json',
    'batch_251.json',
    'batch_286.json',
]

# 모든 페이지 데이터 합치기
all_pages = []
for bf in batch_files:
    path = script_dir / bf
    if not path.exists():
        print(f"WARNING: {bf} not found, skipping")
        continue
    with open(path, 'r', encoding='utf-8') as f:
        pages = json.load(f)
    print(f"Loaded {len(pages)} pages from {bf}")
    all_pages.extend(pages)

# 페이지 번호 정렬 + 중복 제거
all_pages.sort(key=lambda p: p['num'])
seen = set()
unique_pages = []
for p in all_pages:
    if p['num'] not in seen:
        seen.add(p['num'])
        unique_pages.append(p)
all_pages = unique_pages

print(f"\nTotal unique pages: {len(all_pages)}")
print(f"Page range: {all_pages[0]['num']} - {all_pages[-1]['num']}")


def make_chapter_id(sid: str, ci_title: str) -> str:
    """
    section_id에서 챕터 ID 생성. 'chs-chapter-4' 또는 'chs-part-3' 형태.
    """
    s = (sid or '').strip()
    if s.startswith('Part'):
        m = re.search(r'Part\s*(\d+)', s)
        if m:
            return f"chs-part-{m.group(1)}"
    if s.endswith('장'):
        m = re.match(r'(\d+)', s)
        if m:
            return f"chs-chapter-{m.group(1)}"
    # ci_title fallback
    if ci_title:
        m = re.match(r'(\d+)장', ci_title)
        if m:
            return f"chs-chapter-{m.group(1)}"
        m = re.match(r'Part\s*(\d+)', ci_title)
        if m:
            return f"chs-part-{m.group(1)}"
    return ""


# 챕터/섹션 구조 자동 생성
chapters = []
current_chapter = None
current_section = None

for page in all_pages:
    sid = page.get('section_id', '')
    ci = page.get('chapter_intro')

    is_new_chapter = False
    if '장' in sid and '.' not in sid:
        is_new_chapter = True
    elif 'Part' in sid or 'part' in sid:
        is_new_chapter = True

    if is_new_chapter:
        # 이전 섹션/챕터 마무리
        if current_section and current_chapter:
            current_chapter['sections'].append(current_section)
        if current_chapter:
            chapters.append(current_chapter)

        ch_title = ci['title'] if ci else sid
        ch_id = make_chapter_id(sid, ch_title)
        current_chapter = {
            'title': ch_title,
            'id': ch_id,
            'sections': [],
            # 챕터 시작 페이지를 직속 페이지로 보관 (별도 섹션 없이)
            'intro_page': {'num': page['num'], 'label': sid}
        }
        current_section = None
    elif ci and '.' in sid:
        # 새 절(section) 시작
        if current_section and current_chapter:
            current_chapter['sections'].append(current_section)
        current_section = {
            'title': ci['title'] if ci else sid,
            'pages': [{'num': page['num'], 'label': sid}]
        }
    else:
        # 기존 섹션에 페이지 추가
        if current_section is None:
            if current_chapter is None:
                current_chapter = {'title': sid, 'id': '', 'sections': [], 'intro_page': None}
            current_section = {'title': sid or '기타', 'pages': []}
        label = sid if sid else f"p.{page['num']}"
        current_section['pages'].append({'num': page['num'], 'label': label})

if current_section and current_chapter:
    current_chapter['sections'].append(current_section)
if current_chapter:
    chapters.append(current_chapter)

if not chapters:
    print("WARNING: Could not auto-detect chapter structure, using flat structure")
    chapters = [{
        'title': 'CLI 완전활용',
        'id': '',
        'sections': [{
            'title': '전체 페이지',
            'pages': [{'num': p['num'], 'label': f"p.{p['num']}"} for p in all_pages]
        }],
        'intro_page': None
    }]

data = {
    'chapters': chapters,
    'pages': all_pages
}

output_path = script_dir / 'pages_data.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"\nGenerated {output_path}")
print(f"Chapters: {len(chapters)}")
for ch in chapters:
    intro_marker = " (intro p." + str(ch['intro_page']['num']) + ")" if ch.get('intro_page') else ""
    print(f"  [{ch.get('id','-')}] {ch['title']}{intro_marker} ({len(ch['sections'])} sections)")
