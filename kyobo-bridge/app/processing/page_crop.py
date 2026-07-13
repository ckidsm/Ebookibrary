"""도서 페이지 크롭 표준 — 교보 앱/뷰어 전체창 raw → 책 페이지만 (여백 유지, 안 잘림).

규칙 (2026-07-05 확정, "클로드 코드" 책 246장에 검증):
  1. 콘텐츠 감지: 채도>18 또는 어두움<155 인 픽셀 = 콘텐츠(흰·회색 배경 제외).
  2. 열/행별 밀도 + 연속블록(union) → 세로로 짧은 내용(코드블록 등)도 안 잘림.
     (낮은 임계 sh*0.012, gap 16, 최소폭 6 → 가장자리선 배제)
  3. **여백 유지**: 스프레드(landscape)는 콘텐츠 폭 6%·높이 5% 여백 추가(책 본문 여백 복원 → 안 빡빡).
     표지 등 portrait 는 여백 최소(1%) — 안 그러면 좌우 회색 빈칸이 붙음.
  4. 앞단 고정 크롭(135/150/155px)으로 앱 타이틀바·창 그림자·페이지표시 제거.

캡처(mac_wviewer/win_app/linux_app/앱)든 오프라인 재크롭이든 이 함수로 통일.
OCR 도 이 크롭 결과에 돌리면 깨끗(가장자리 잘림·크롬 오염 없음).

⚠️ 크롬(chrome) 기본값은 **웹뷰어용**이다. 캡처 방식마다 다르므로 crop_book.py --chrome 로 지정할 것.
   교보 데스크탑 앱 raw 는 상·하 크롬이 거의 없어(흰 여백만) 큰 top 값이 **본문(섹션 헤더)을 잘라먹는다.**
   → 앱 raw 는 chrome=(20,20,20,20). content_crop 이 여백·하단 진행표시를 자동 처리.
⚠️ 반복 실수 경고: 뷰어에서 "이미지 잘림/마진 없음" 신고의 진짜 원인은 **모달 CSS 가 아니라 여기(크롭)** 인
   경우가 대부분이다. 모달만 고치지 말고 이 크롬값을 먼저 점검. (build_html.ViewerLayout 진단 규칙 참조)
"""
from __future__ import annotations


# ── 페이지 크롭 규칙 상수 (단일 관리처) ──────────────────────────────────
# 하드코딩 금지: 크롭 임계·여백·썸네일 등을 여기 한 곳에서만 관리(2026-07-05 확정, 클로드코드 246장 검증).
class CropRules:
    """페이지 크롭/썸네일 규칙 상수. 인스턴스 X — 클래스 상수로 참조. (2026-07-13 규칙화)"""
    # ── 고정 크롬 크롭 (L,T,R,B) px ──
    CHROME_WVIEWER = (135, 150, 135, 155)  # 웹뷰어 캡처용(기본). 앱 raw 엔 과함 → CHROME_APP 쓸 것
    CHROME_APP = (20, 20, 20, 20)          # 교보 데스크탑 앱 raw(상하 크롬 거의 없음 → 작게)

    # ── 여백(콘텐츠 대비 비율) = (가로, 세로) ──
    MARGIN_SPREAD = (0.06, 0.05)   # 스프레드(landscape): 본문 여백 복원 → 안 빡빡
    MARGIN_PORTRAIT = (0.01, 0.01)  # portrait(표지): 최소(좌우 회색 빈칸 방지)

    # ── 콘텐츠 픽셀 판정: 채도 > SAT_MIN 또는 밝기 < DARK_MAX (흰·회색 배경 제외) ──
    SAT_MIN = 18
    DARK_MAX = 155

    # ── 콘텐츠 밀도 분석 ──
    DOWNSCALE = 4          # 분석용 축소 배수(속도). 크롭 좌표는 ×DOWNSCALE 로 원본 복원
    DENSITY_RATIO = 0.012  # 열/행 콘텐츠 밀도 임계(반대축 길이 대비)
    DENSITY_MIN = 2        # 밀도 임계 최소값(0 방지)
    RUN_GAP = 16           # 연속블록 병합 간격(짧은 여백 이어붙임 → 세로 짧은 코드블록도 안 잘림)
    RUN_MIN = 6            # 최소 연속블록 길이(가장자리 선·노이즈 배제)

    # ── 썸네일 ──
    THUMB_MAX_W = 1800     # 썸네일 최대 폭(px) — 카드 그리드/모달 프리뷰용


def _runs(flags, gap):
    idx = [i for i, v in enumerate(flags) if v]
    if not idx:
        return []
    out = []; s = idx[0]; p = idx[0]
    for i in idx[1:]:
        if i - p <= gap + 1:
            p = i
        else:
            out.append((s, p)); s = i; p = i
    out.append((s, p))
    return out


def crop_page(im, chrome=CropRules.CHROME_WVIEWER, margin_spread=CropRules.MARGIN_SPREAD,
              margin_portrait=CropRules.MARGIN_PORTRAIT):
    """전체창 raw(PIL Image) → 책 페이지 크롭(PIL Image). 안 잘리고 여백 유지.

    chrome: (left, top, right, bottom) 고정 제거 px (앱 창 그림자/타이틀/페이지표시).
    margin_spread/portrait: (가로, 세로) 콘텐츠 대비 여백 비율.
    """
    im = im.convert("RGB"); W0, H0 = im.size
    cl, ct, cr_, cb = chrome
    im = im.crop((cl, ct, W0 - cr_, H0 - cb))
    return content_crop(im, margin_spread=margin_spread, margin_portrait=margin_portrait)


def content_crop(im, margin_spread=CropRules.MARGIN_SPREAD, margin_portrait=CropRules.MARGIN_PORTRAIT):
    """크롬 제거가 끝난 이미지에서 책 페이지 콘텐츠만 크롭(여백 유지, 안 잘림).

    브라우저 캡처 경로(win/linux/mac 웹뷰어)는 각자 크롬을 먼저 제거한 뒤 이걸 호출.
    앱 raw 는 crop_page()가 고정 크롬 제거 후 이걸 호출.
    규칙: 콘텐츠(채도>18 or 어두움<155) 열/행 밀도+연속블록 → 세로 짧은 내용도 안 잘림 + 여백.
    """
    im = im.convert("RGB"); W, H = im.size
    ds = CropRules.DOWNSCALE
    sw, sh = max(1, W // ds), max(1, H // ds)
    s = im.resize((sw, sh)); d = list(s.getdata())

    def isc(p):  # 콘텐츠 픽셀?(채도 or 어두움)
        return (max(p) - min(p)) > CropRules.SAT_MIN or max(p) < CropRules.DARK_MAX
    mask = [isc(p) for p in d]
    colc = [0] * sw; rowc = [0] * sh
    for i, m in enumerate(mask):
        if m:
            y = i // sw; colc[i - y * sw] += 1; rowc[y] += 1
    cth = max(CropRules.DENSITY_MIN, sh * CropRules.DENSITY_RATIO)
    rth = max(CropRules.DENSITY_MIN, sw * CropRules.DENSITY_RATIO)
    cr = [r for r in _runs([c > cth for c in colc], CropRules.RUN_GAP) if r[1] - r[0] >= CropRules.RUN_MIN]
    rr = [r for r in _runs([c > rth for c in rowc], CropRules.RUN_GAP) if r[1] - r[0] >= CropRules.RUN_MIN]
    if not cr or not rr:
        return im
    x0, x1 = min(r[0] for r in cr), max(r[1] for r in cr)
    y0, y1 = min(r[0] for r in rr), max(r[1] for r in rr)
    cw, ch = x1 - x0, y1 - y0
    mh, mv = margin_spread if cw > ch else margin_portrait
    mx, my = cw * mh, ch * mv
    l = max(0, int((x0 - mx) * ds)); r = min(W, int((x1 + mx) * ds))
    t = max(0, int((y0 - my) * ds)); b = min(H, int((y1 + my) * ds))
    return im.crop((l, t, r, b))
