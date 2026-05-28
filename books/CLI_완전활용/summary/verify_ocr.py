#!/usr/bin/env python3
"""
OCR 기반 요약 JSON 자동 검증 도구.

동작:
  1. 각 페이지 PNG를 tesseract(kor+eng)로 OCR → ocr_text/{num}.txt 캐싱
  2. batch_*.json의 각 페이지 요약과 OCR 결과를 비교
  3. 불일치(JSON엔 있으나 OCR엔 없는 용어, OCR에만 있는 헤더/키워드)를
     verification_report.md / .json 으로 리포트

실행:
  ./verify_ocr.py                  # 모든 batch 검증
  ./verify_ocr.py --pages 186-195  # 범위 지정
  ./verify_ocr.py --refresh        # OCR 캐시 무시하고 다시 OCR

출력:
  - ocr_text/page_NNN.txt          # OCR 원문 (캐시)
  - verification_report.json        # 구조화 리포트
  - verification_report.md          # 사람이 읽는 리포트
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pytesseract
from PIL import Image

SCRIPT_DIR = Path(__file__).parent
BOOK_DIR = SCRIPT_DIR.parent          # .../CLI 완전활용/
IMG_DIR = BOOK_DIR                    # 원본 PNG 위치
THUMB_DIR = BOOK_DIR / "thumbs"       # 썸네일(리사이즈된 이미지)
OCR_DIR = SCRIPT_DIR / "ocr_text"
OCR_DIR.mkdir(exist_ok=True)

BATCH_FILES = [
    "batch_127.json",
    "batch_156.json",
    "batch_186.json",
    "batch_216.json",
    "batch_251.json",
    "batch_286.json",
]

# -------- OCR --------

def ocr_page(num: int, refresh: bool = False) -> str:
    cache = OCR_DIR / f"page_{num:03d}.txt"
    if cache.exists() and not refresh:
        return cache.read_text(encoding="utf-8")

    # 원본 선호, 없으면 썸네일
    candidates = [
        IMG_DIR / f"CLI 완전활용_{num}.png",
        THUMB_DIR / f"CLI 완전활용_{num}.png",
    ]
    src = next((p for p in candidates if p.exists()), None)
    if src is None:
        return ""

    im = Image.open(src)
    txt = pytesseract.image_to_string(im, lang="kor+eng")
    cache.write_text(txt, encoding="utf-8")
    return txt


# -------- Text helpers --------

HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

def strip_html(s: str) -> str:
    return HTML_TAG_RE.sub(" ", s or "")

def normalize(s: str) -> str:
    """공백·줄바꿈 정리 + 하이픈/점 보존."""
    return WHITESPACE_RE.sub(" ", strip_html(s)).strip()

def tokenize(s: str) -> set[str]:
    """
    비교용 토큰 집합 — 공백/구두점으로 분리한 뒤 2글자 이상만 유지.
    영문은 소문자로, 한글은 그대로.
    """
    s = normalize(s).lower()
    parts = re.split(r"[\s,\.·•\[\]\(\)\{\}<>`\"'=+/|:;?!\\]+", s)
    return {p for p in parts if len(p) >= 2}

def ocr_contains(ocr: str, term: str) -> bool:
    """
    OCR 텍스트에 term이 존재하는지 — 부분 일치 허용(OCR 노이즈 고려).
    한글 4글자 이상이면 앞 2글자만 일치해도 통과, 영문/숫자는 전체 일치.
    """
    t = term.strip().lower()
    if not t:
        return True
    ocr_l = ocr.lower()
    if t in ocr_l:
        return True
    # 한글 용어는 2/3 정도 매칭 허용
    kor_only = "".join(ch for ch in t if "\uac00" <= ch <= "\ud7a3")
    if len(kor_only) >= 4:
        head = kor_only[: len(kor_only) // 2]
        if head and head in ocr_l:
            return True
    # 영문 명령어/식별자 — 하이픈/밑줄 제거 후 재비교
    alnum = re.sub(r"[^a-z0-9]", "", t)
    if len(alnum) >= 4 and alnum in re.sub(r"[^a-z0-9]", "", ocr_l):
        return True
    return False


# -------- Page analysis --------

HEADER_HINT_RE = re.compile(
    r"^(?:\d+\.\d+(?:\.\d+)?|\d+장|Part\s*\d+)\s*[\.\)]?\s*[^\n]{0,60}$",
    re.IGNORECASE,
)

def extract_ocr_headers(ocr: str) -> list[str]:
    """OCR 텍스트에서 절·장 제목으로 보이는 줄 추출."""
    out = []
    for line in (l.strip() for l in ocr.splitlines()):
        if not line or len(line) > 80:
            continue
        if HEADER_HINT_RE.match(line):
            out.append(line)
        elif re.match(r"^(\d{1,2})[\.\-]\s*[가-힣]", line):
            out.append(line)
    return out


def compare_page(page: dict, ocr: str) -> dict:
    """
    JSON 한 페이지와 OCR 텍스트를 비교해 불일치 항목을 반환.
    """
    num = page["num"]
    sid = page.get("section_id", "")
    summary_raw = page.get("summary", "")
    summary = normalize(summary_raw)
    points = [normalize(strip_html(p)) for p in page.get("points", [])]
    topics = list(page.get("topics", []))
    terms = list(page.get("terms", []))

    # 1) terms 중 OCR에 없는 것
    missing_terms = [t for t in terms if not ocr_contains(ocr, t)]

    # 2) topics 중 OCR에 없는 것 (부분 매칭)
    missing_topics = [t for t in topics if not ocr_contains(ocr, t)]

    # 3) summary 문장 중 OCR에 근거가 약한 문장
    weak_sentences = []
    for sent in re.split(r"[.?!]\s+|<br>|\n", summary_raw):
        plain = normalize(sent)
        if len(plain) < 15:
            continue
        # 문장에서 의미있는 토큰 추출
        tokens = [t for t in tokenize(plain) if len(t) >= 3]
        if not tokens:
            continue
        # OCR과 매칭되는 토큰 비율
        matched = sum(1 for tk in tokens if ocr_contains(ocr, tk))
        ratio = matched / len(tokens)
        if ratio < 0.35:
            weak_sentences.append({
                "sentence": plain[:120],
                "match_ratio": round(ratio, 2),
                "tokens_matched": matched,
                "tokens_total": len(tokens),
            })

    # 4) OCR에서 눈에 띄는 헤더 중 JSON 요약에 언급 안 된 것
    ocr_headers = extract_ocr_headers(ocr)
    json_blob = " ".join([summary, " ".join(points), " ".join(topics), " ".join(terms)]).lower()
    missing_headers = []
    for h in ocr_headers:
        # 제목의 한글/영문만 추출
        clean = re.sub(r"[^\w\s가-힣]", " ", h).strip().lower()
        if not clean:
            continue
        parts = [p for p in clean.split() if len(p) >= 2]
        if not parts:
            continue
        matched = sum(1 for p in parts if p in json_blob)
        if matched / len(parts) < 0.4:
            missing_headers.append(h)

    # 5) 품질 점수: terms+topics+sentences 점수를 평균
    total_items = len(terms) + len(topics)
    matched_items = (len(terms) - len(missing_terms)) + (len(topics) - len(missing_topics))
    term_score = (matched_items / total_items) if total_items else 1.0
    sent_score = 1.0 - min(1.0, len(weak_sentences) / 5)
    header_score = 1.0 - min(1.0, len(missing_headers) / 4)
    confidence = round(100 * (term_score * 0.4 + sent_score * 0.4 + header_score * 0.2))

    return {
        "num": num,
        "section_id": sid,
        "confidence": confidence,
        "missing_terms": missing_terms,
        "missing_topics": missing_topics,
        "weak_sentences": weak_sentences,
        "missing_headers_in_json": missing_headers,
        "ocr_excerpt": ocr[:600],
        "summary_excerpt": summary[:400],
    }


# -------- Runner --------

def load_pages(pages_filter: set[int] | None) -> list[dict]:
    pages = []
    for bf in BATCH_FILES:
        p = SCRIPT_DIR / bf
        if not p.exists():
            continue
        with open(p, encoding="utf-8") as f:
            for page in json.load(f):
                if pages_filter is None or page["num"] in pages_filter:
                    pages.append(page)
    pages.sort(key=lambda x: x["num"])
    return pages


def parse_range(s: str | None) -> set[int] | None:
    if not s:
        return None
    out: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def write_reports(results: list[dict]) -> None:
    json_path = SCRIPT_DIR / "verification_report.json"
    md_path = SCRIPT_DIR / "verification_report.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    md = ["# 요약 JSON ↔ OCR 검증 리포트", ""]
    md.append(f"- 총 {len(results)}페이지 분석")
    low = [r for r in results if r["confidence"] < 60]
    mid = [r for r in results if 60 <= r["confidence"] < 80]
    high = [r for r in results if r["confidence"] >= 80]
    md.append(f"- 신뢰도 <60: {len(low)}p · 60~79: {len(mid)}p · ≥80: {len(high)}p")
    md.append("")
    md.append("## 우선 검토 대상 (신뢰도 낮은 순)")
    md.append("")
    for r in sorted(results, key=lambda x: x["confidence"])[:40]:
        md.append(f"### p.{r['num']} (section {r['section_id']}, 신뢰도 {r['confidence']})")
        if r["missing_terms"]:
            md.append(f"- **OCR에 없는 terms**: {', '.join(r['missing_terms'])}")
        if r["missing_topics"]:
            md.append(f"- **OCR에 없는 topics**: {', '.join(r['missing_topics'])}")
        if r["missing_headers_in_json"]:
            md.append("- **OCR에 보이나 요약에 없는 헤더:**")
            for h in r["missing_headers_in_json"][:6]:
                md.append(f"  - `{h}`")
        if r["weak_sentences"]:
            md.append("- **OCR 근거가 약한 문장:**")
            for ws in r["weak_sentences"][:4]:
                md.append(f"  - ({ws['match_ratio']}) {ws['sentence']}")
        md.append("")
        md.append(f"<details><summary>OCR 앞부분</summary>\n\n```\n{r['ocr_excerpt']}\n```\n</details>")
        md.append("")

    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {json_path.name} and {md_path.name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", help="페이지 범위 (예: 186-195,200)")
    ap.add_argument("--refresh", action="store_true", help="OCR 캐시 무시")
    ap.add_argument("--limit", type=int, default=0, help="처음 N개만 처리 (디버그)")
    args = ap.parse_args()

    pages_filter = parse_range(args.pages)
    pages = load_pages(pages_filter)
    if args.limit:
        pages = pages[: args.limit]
    if not pages:
        print("검증할 페이지가 없습니다.", file=sys.stderr)
        return 1

    print(f"{len(pages)}페이지 검증 시작 (캐시: {'무시' if args.refresh else '사용'})")
    results = []
    for i, page in enumerate(pages, 1):
        num = page["num"]
        ocr = ocr_page(num, refresh=args.refresh)
        if not ocr:
            print(f"  [{i}/{len(pages)}] p.{num}: 이미지 없음, 건너뜀")
            continue
        res = compare_page(page, ocr)
        results.append(res)
        flag = "!" if res["confidence"] < 60 else " "
        print(f"  [{i}/{len(pages)}] {flag} p.{num} 신뢰도 {res['confidence']}")

    write_reports(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
