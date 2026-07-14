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

    # ── 콘텐츠/종이 픽셀 판정 ──
    # 종이(흰) 또는 내용은 유지, 앱 회색 여백만 제외 = "가장자리에 내용이 드물어도 안 잘림"(2026-07-14 확정).
    SAT_MIN = 18           # 채도 > 이 값 = 유채색(내용·베이지 표지). 회색 여백(sat=0) 제외
    DARK_MAX = 155         # 밝기 < 이 값 = 어두운 내용(텍스트). 회색 여백(~235) 제외
    PAPER_WHITE_MIN = 245  # min(RGB) ≥ 이 값 = **흰 종이**(255). 앱 회색 여백(~235)과 구분 → 내용 드물어도 종이째 유지
    PAPER_RATIO = 0.30     # 열/행에서 '종이or내용' 픽셀이 반대축의 이 비율 이상이면 그 열/행은 페이지(=유지)

    DOWNSCALE = 4          # 분석용 축소 배수(속도). 크롭 좌표는 ×DOWNSCALE 로 원본 복원

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
    """크롬 제거가 끝난 이미지에서 **책 페이지(종이) 영역**을 크롭 — 앱 회색 여백만 제거, 내용 안 잘림.

    규칙(2026-07-14 확정, '혼자 공부하는 머신러닝' p31 우측 코드 잘림 사고 후):
      옛 방식은 **내용(어두운 텍스트) 밀도**로 경계를 잡아, 가장자리에 **드문 코드블록**(회색박스+적은
      글자)이 있으면 밀도 미달로 **잘렸다**(이미지바이블은 내용이 빽빽해 우연히 안 걸렸을 뿐).
      → 이제 **'종이(흰 255) 또는 내용(유채색/어두움)' 픽셀이 있는 열/행을 유지**하고, 앱 회색 여백
      (~235, 흰색도 내용도 아님)만 제거한다. 종이 위 내용은 밀도와 무관하게 다 포함 → 절대 안 잘림.
      베이지 표지(유채색)도 '내용'으로 유지됨. margin_* 인자는 호환용(미사용 — 종이 경계가 곧 여백).
    """
    im = im.convert("RGB"); W, H = im.size
    ds = CropRules.DOWNSCALE
    sw, sh = max(1, W // ds), max(1, H // ds)
    s = im.resize((sw, sh)); d = list(s.getdata())

    def keep(p):  # 종이(흰) 또는 내용(유채색/어두움) = 유지. 앱 회색 여백만 제외.
        return ((max(p) - min(p)) > CropRules.SAT_MIN or max(p) < CropRules.DARK_MAX
                or min(p) >= CropRules.PAPER_WHITE_MIN)
    colc = [0] * sw; rowc = [0] * sh
    for i, p in enumerate(d):
        if keep(p):
            y = i // sw; colc[i - y * sw] += 1; rowc[y] += 1
    col_th = sh * CropRules.PAPER_RATIO; row_th = sw * CropRules.PAPER_RATIO
    kc = [x for x in range(sw) if colc[x] >= col_th]
    kr = [y for y in range(sh) if rowc[y] >= row_th]
    if not kc or not kr:
        return im  # 종이 못 찾으면 원본 유지(안전)
    return im.crop((kc[0] * ds, kr[0] * ds, (kc[-1] + 1) * ds, (kr[-1] + 1) * ds))
