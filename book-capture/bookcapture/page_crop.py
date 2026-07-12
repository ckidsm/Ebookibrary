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


def crop_page(im, chrome=(135, 150, 135, 155), margin_spread=(0.06, 0.05),
              margin_portrait=(0.01, 0.01)):
    """전체창 raw(PIL Image) → 책 페이지 크롭(PIL Image). 안 잘리고 여백 유지.

    chrome: (left, top, right, bottom) 고정 제거 px (앱 창 그림자/타이틀/페이지표시).
    margin_spread/portrait: (가로, 세로) 콘텐츠 대비 여백 비율.
    """
    im = im.convert("RGB"); W0, H0 = im.size
    cl, ct, cr_, cb = chrome
    im = im.crop((cl, ct, W0 - cr_, H0 - cb))
    return content_crop(im, margin_spread=margin_spread, margin_portrait=margin_portrait)


def content_crop(im, margin_spread=(0.06, 0.05), margin_portrait=(0.01, 0.01)):
    """크롬 제거가 끝난 이미지에서 책 페이지 콘텐츠만 크롭(여백 유지, 안 잘림).

    브라우저 캡처 경로(win/linux/mac 웹뷰어)는 각자 크롬을 먼저 제거한 뒤 이걸 호출.
    앱 raw 는 crop_page()가 고정 크롬 제거 후 이걸 호출.
    규칙: 콘텐츠(채도>18 or 어두움<155) 열/행 밀도+연속블록 → 세로 짧은 내용도 안 잘림 + 여백.
    """
    im = im.convert("RGB"); W, H = im.size
    sw, sh = max(1, W // 4), max(1, H // 4)
    s = im.resize((sw, sh)); d = list(s.getdata())

    def isc(p):
        return (max(p) - min(p)) > 18 or max(p) < 155
    mask = [isc(p) for p in d]
    colc = [0] * sw; rowc = [0] * sh
    for i, m in enumerate(mask):
        if m:
            y = i // sw; colc[i - y * sw] += 1; rowc[y] += 1
    cth = max(2, sh * 0.012); rth = max(2, sw * 0.012)
    cr = [r for r in _runs([c > cth for c in colc], 16) if r[1] - r[0] >= 6]
    rr = [r for r in _runs([c > rth for c in rowc], 16) if r[1] - r[0] >= 6]
    if not cr or not rr:
        return im
    x0, x1 = min(r[0] for r in cr), max(r[1] for r in cr)
    y0, y1 = min(r[0] for r in rr), max(r[1] for r in rr)
    cw, ch = x1 - x0, y1 - y0
    mh, mv = margin_spread if cw > ch else margin_portrait
    mx, my = cw * mh, ch * mv
    l = max(0, int((x0 - mx) * 4)); r = min(W, int((x1 + mx) * 4))
    t = max(0, int((y0 - my) * 4)); b = min(H, int((y1 + my) * 4))
    return im.crop((l, t, r, b))
