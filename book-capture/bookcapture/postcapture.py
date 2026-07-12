"""캡처 후처리 규칙 엔진 — 품질·오염 검사(QC) · 중복 꼬리 정리 · 챕터 자동 감지.

2026-07-12 '이미지 처리 바이블'(277장) 발행 과정에서 확립한 규칙을 클래스·함수로 정규화.
(그 전엔 매번 손으로 md5 비교·컨택트시트·구분페이지 찾기를 반복했음.)

왜 필요한가 (규칙 근거):
  1) **중복 꼬리**: 교보 앱은 마지막 페이지에서 →키가 안 먹혀 같은 화면을 반복 캡처.
     캡처의 dup-hash 정지가 이 경우 안 걸려 마지막 장이 수백 장 복제됨 → trim_duplicate_tail 로 제거.
  2) **오염**: 창 특정 실패 시 (구버전) 메인 디스플레이(터미널)를 찍는 사고가 있었음.
     게시 전 CaptureQC 로 해상도 일관성·터미널해상도·블랙/블랭크·중복을 정량 검증.
  3) **챕터 경계**: 각 장은 '베이지 표지' 구분 페이지로 시작하며 OCR 이 거의 비어 있음.
     이 빈-OCR 페이지가 챕터/섹션 경계 → ChapterDetector 로 자동 감지(제목은 이미지에서 확정).

모두 순수 파일 연산(md5·PIL·텍스트) — 외부 API 불필요.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# ── 규칙 상수 (KyoboCaptureStandard 후처리) ──────────────────────────────
# 하드코딩 금지: 모든 임계·픽스처는 이 클래스 한 곳에서만 관리(유지보수·리소스화).
# 값 튜닝이 필요하면 여기(또는 QCRules.load_overrides 로 외부 JSON)만 고친다.
class QCRules:
    """캡처 후처리 규칙 상수(단일 관리처). 인스턴스 X — 클래스 상수로 참조."""
    # '메인 디스플레이 통째' 캡처로 오염됐을 때 나오는 흔한 외장/노트북 해상도.
    # 책 페이지는 교보 창 크롭이라 이 값과 일치하지 않음(일치하면 오염 의심).
    TERMINAL_DIMS = frozenset({(2560, 1440), (2560, 1600), (1920, 1080), (3456, 2234)})
    MIN_PAGE_KB = 80            # 이 미만이면 블랙/블랭크 의심
    DIVIDER_MAX_OCR_CHARS = 40  # OCR 공백 제거 후 이 미만이면 챕터/섹션 구분 페이지 후보
    OFF_DIM_RATIO = 0.05        # 주 해상도 외 페이지가 이 비율 초과면 '해상도 불일치'
    OFF_DIM_MIN = 3             # (또는 이 장수 초과) — 표지 등 소수 예외 허용
    TAIL_MIN_RUN = 2            # 꼬리 반복 최소 연속 수
    DIVIDER_MERGE_GAP = 2       # 인접 구분페이지 병합 간격(±)

    @classmethod
    def load_overrides(cls, path):
        """외부 JSON 으로 임계 오버라이드(리소스화). 예: {"MIN_PAGE_KB":100}. 없으면 무시."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(cls, k) and not k.startswith("_"):
                    setattr(cls, k, frozenset(map(tuple, v)) if k == "TERMINAL_DIMS" else v)
        except Exception:
            pass

    # 테스트/합성 픽스처 규격도 상수로(하드코딩 방지)
    FIXTURE_PAGE_SIZE = (700, 500)      # 합성 '내용' 페이지 크기
    FIXTURE_TERMINAL_SIZE = (2560, 1440)  # 합성 '터미널 오염' 크기(TERMINAL_DIMS 중 하나)


def _md5(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def _page_files(book_dir) -> list[Path]:
    d = Path(book_dir)
    return sorted(d.glob("page_*.png"), key=lambda p: p.name)


def _raw_files(book_dir) -> list[Path]:
    """QC·trim 은 '크롭 전 raw 캡처'를 대상으로 한다(해상도 일관·터미널 오염 판정은 raw 기준).
    크롭 후에는 source_raws/raw_*.png 에 원본 보존됨 → 그걸 우선, 없으면 page_*.png(=아직 raw)."""
    d = Path(book_dir)
    raws = sorted((d / "source_raws").glob("raw_*.png"), key=lambda p: p.name)
    return raws if raws else _page_files(book_dir)


class CaptureQC:
    """캡처 결과 품질·오염 검사(게시 전 게이트).

    검사 규칙:
      · 해상도 일관성 — 대부분 페이지가 같은 크기여야(표지 등 소수 예외 허용).
      · 오염(터미널) — TERMINAL_DIMS 해상도 페이지 = 메인 디스플레이 오염 의심.
      · 블랙/블랭크 — 파일 < MIN_PAGE_KB.
      · 중복 — 동일 해시 페이지(꼬리 반복 등).
    validate() → 구조화 리포트(ok/flags/…). ok=False 면 게시 보류·조치.
    """

    def __init__(self, book_dir):
        self.book_dir = Path(book_dir)

    def validate(self) -> dict:
        files = _raw_files(self.book_dir)
        from PIL import Image
        dims = {}
        small, terminal, hashes = [], [], {}
        for f in files:
            w, h = Image.open(f).size
            dims.setdefault((w, h), []).append(f.name)
            kb = f.stat().st_size // 1024
            if kb < QCRules.MIN_PAGE_KB:
                small.append((f.name, kb))
            if (w, h) in QCRules.TERMINAL_DIMS:
                terminal.append((f.name, (w, h)))
            hashes.setdefault(_md5(f), []).append(f.name)
        dup_groups = {h: ns for h, ns in hashes.items() if len(ns) > 1}
        # 주 해상도(최다) 외 페이지 — 표지 등 소수는 정상, 많으면 이상
        main_dim = max(dims, key=lambda d: len(dims[d])) if dims else None
        off_dim = sum(len(v) for d, v in dims.items() if d != main_dim)
        flags = []
        if terminal:
            flags.append(f"⛔ 터미널 해상도 의심 {len(terminal)}장 (오염): {terminal[:3]}")
        if small:
            flags.append(f"⚠ 블랙/블랭크 의심 {len(small)}장(<{QCRules.MIN_PAGE_KB}KB): {small[:3]}")
        if dup_groups:
            n = sum(len(v) for v in dup_groups.values())
            flags.append(f"⚠ 중복 페이지 {len(dup_groups)}그룹/{n}장 (꼬리 반복 등)")
        if main_dim and off_dim > max(QCRules.OFF_DIM_MIN, len(files) * QCRules.OFF_DIM_RATIO):
            flags.append(f"⚠ 해상도 불일치 {off_dim}장 (주 {main_dim[0]}x{main_dim[1]} 외)")
        return {
            "ok": not flags,
            "count": len(files),
            "main_dim": main_dim,
            "dim_distribution": {f"{w}x{h}": len(v) for (w, h), v in dims.items()},
            "unique_hashes": len(hashes),
            "duplicate_groups": len(dup_groups),
            "terminal_suspect": terminal,
            "blank_suspect": small,
            "flags": flags,
        }


def trim_duplicate_tail(book_dir, min_run: int = QCRules.TAIL_MIN_RUN, dry_run: bool = False) -> dict:
    """책 끝 반복 캡처(동일 해시 연속) 제거.

    규칙: 뒤에서부터 같은 해시가 min_run 이상 연속되면 그건 '마지막 페이지 재캡처'.
      마지막 unique 페이지 1장만 남기고 그 뒤 중복을 삭제.
    Returns {last_unique, trimmed[], kept} (dry_run 이면 삭제 안 하고 목록만).
    """
    files = _raw_files(book_dir)
    if len(files) < min_run + 1:
        return {"last_unique": files[-1].name if files else None, "trimmed": [], "kept": len(files)}
    hashes = [_md5(f) for f in files]
    tail = hashes[-1]
    # 뒤에서 연속으로 tail 과 같은 구간 길이
    run = 0
    for h in reversed(hashes):
        if h == tail:
            run += 1
        else:
            break
    trimmed = []
    if run >= min_run:
        # 마지막 unique(= 그 반복 페이지 1장)만 남기고 나머지 반복분 삭제
        # 반복 구간 files[-run:] 중 첫 1장 유지, 나머지 삭제
        for f in files[-run + 1:]:
            trimmed.append(f.name)
            if not dry_run:
                f.unlink()
    remaining = _raw_files(book_dir)
    return {
        "last_unique": remaining[-1].name if remaining else None,
        "tail_run": run,
        "trimmed": trimmed,
        "kept": len(remaining),
    }


class ChapterDetector:
    """빈-OCR 구분 페이지로 챕터/섹션 경계 자동 감지.

    규칙: 각 장은 '베이지 표지'(제목만 크게) 페이지로 시작 → OCR 공백제거 후 거의 0자.
      이 빈-OCR 페이지 = 구분 페이지 후보. 제목은 이미지에서 사람/비전으로 확정하고
      chapters.json(=[{num,title,start,end,summary,topics}]) 로 정리.
    detect() → 구분 페이지 리스트(경계). scaffold_chapters() → chapters.json 뼈대 생성.
    """

    def __init__(self, book_dir, max_ocr_chars: int = QCRules.DIVIDER_MAX_OCR_CHARS):
        self.book_dir = Path(book_dir)
        self.ocr_dir = self.book_dir / "summary" / "ocr_text"
        self.max_ocr_chars = max_ocr_chars

    def detect(self) -> list[int]:
        """빈-OCR 구분 페이지 번호 리스트(정렬). OCR 폴더 없으면 빈 리스트."""
        if not self.ocr_dir.is_dir():
            return []
        dividers = []
        for f in sorted(self.ocr_dir.glob("page_*.txt")):
            txt = "".join(f.read_text(encoding="utf-8", errors="ignore").split())
            if len(txt) < self.max_ocr_chars:
                num = int(f.stem.split("_")[1])
                dividers.append(num)
        return dividers

    def scaffold_chapters(self, last_page: int | None = None) -> list[dict]:
        """구분 페이지 경계로 chapters.json 뼈대 생성(title/summary 는 사람이 채움).

        연속된 빈-OCR(표지 다음 빈 페이지 등)은 하나의 경계로 병합.
        """
        divs = self.detect()
        if not divs:
            return []
        if last_page is None:
            files = _raw_files(self.book_dir)
            last_page = int(files[-1].stem.split("_")[1]) if files else (divs[-1])
        # 인접(±2) 구분 페이지 병합 → 대표 경계
        bounds = []
        for d in divs:
            if bounds and d - bounds[-1] <= QCRules.DIVIDER_MERGE_GAP:
                continue
            bounds.append(d)
        chapters = []
        for i, start in enumerate(bounds):
            end = (bounds[i + 1] - 1) if i + 1 < len(bounds) else last_page
            chapters.append({
                "num": i + 1, "title": "(제목 확인 필요)",
                "start": start, "end": end, "summary": "", "topics": [],
            })
        return chapters


def qc_report_text(rep: dict) -> str:
    lines = [f"[QC] {rep['count']}장 · unique {rep['unique_hashes']} · 주해상도 {rep['main_dim']}",
             f"     해상도분포: {rep['dim_distribution']}"]
    if rep["ok"]:
        lines.append("     ✅ 통과 — 오염/블랙/중복/불일치 없음")
    else:
        for fl in rep["flags"]:
            lines.append("     " + fl)
    return "\n".join(lines)
