"""캡처 해상도 표준 (KyoboCaptureStandard v1) — OS·모니터 무관 정량 규격.

문제: Mac(screencapture)/Windows(dxcam)/Ubuntu(scrot)는 물리 화면 픽셀을 찍어
모니터 해상도·DPI·창 크기마다 결과가 달라짐(2026-07 "클로드 코드" 책 스프레드 저해상 사고).

해법: 해상도 규격을 물리 화면과 분리한다.
  - **권장 경로**: Playwright `page.screenshot()` — 출력 = VIEWPORT × DEVICE_SCALE_FACTOR.
    모니터 종류·해상도·DPI와 무관하게 항상 동일 픽셀. (오프스크린 렌더)
  - **폴백 경로**(물리 화면 캡처): 창을 규격대로 강제 + 아래 검증 게이트 통과 필수.

모든 경로의 최종 산출물은 `normalize_page()`로 정규화하고 `validate_page()`로 검증한다.
"""
from __future__ import annotations

# ── 정량 규격 (v1) ─────────────────────────────────────────
STANDARD_VERSION = "v1"

# 레이아웃: 반드시 단면(1페이지). 스프레드(양면)는 페이지당 픽셀이 절반 → 금지.
LAYOUT = "single-page"

# Playwright 렌더 규격 (모니터 무관 — 이 두 값이 출력 픽셀을 결정)
VIEWPORT_CSS = (960, 1440)      # 단면 세로 2:3 (W, H, CSS px)
DEVICE_SCALE_FACTOR = 2         # 픽셀 밀도 2배 → 원시 스크린샷 1920×2880

# 정규화 목표 (크롭 후 본문을 이 폭으로 리샘플, 종횡비 유지)
TARGET_WIDTH = 1600             # 국판 책 폭 152mm 기준 ≈ 268 DPI (tesseract 300DPI 근접)
TARGET_WIDTH_TOLERANCE = 0.10   # ±10% 허용

# 검증 게이트 (미달 시 재캡처 경고)
MIN_SOURCE_WIDTH = 1400         # 크롭 후 원본 폭이 이 미만이면 저해상 → 재캡처
PORTRAIT_ONLY = True            # W >= H (가로) 이면 스프레드 의심 → 실패

# 파일 포맷
IMAGE_FORMAT = "PNG"
IMAGE_MODE = "RGB"

# ── DPI 근거 (문서용) ──────────────────────────────────────
# 국판 책 폭 ≈ 152mm = 5.98in.  TARGET_WIDTH 1600px / 5.98in ≈ 268 DPI.
# 2000px면 ≈ 334 DPI. tesseract 권장 300 DPI 부근이라 OCR·열람 모두 양호.


# ── 물리 화면 캡처(screencapture/dxcam/scrot) 정량 모델 ──────
# 실측(2026-07-05, Mac 3모니터, 동일 Chrome 창 1728pt):
#   내장 Retina 2x → 원시 3592x2304 → 크롭 3530x2050 → 스프레드 페이지당 1765px ✅
#   LG ULTRAGEAR 1x → 원시 1840x1196 → 크롭 1810x997  → 페이지당  905px ❌ (같은 창인데 절반!)
# 결론: 물리 화면 캡처 픽셀 = 창_폭(pt) × 디스플레이_scale.  모니터마다 scale(1x/2x)이 달라 편차 발생.
#   → 표준화하려면 (a) 단면(스프레드 금지)으로 폭 전체를 한 페이지에 쓰고,
#      (b) 이 모니터 scale에서 필요한 창 폭을 자동 계산해 강제한다.

# 최대화 판정: 창이 디스플레이 point 크기를 이만큼 덮으면 "최대화"로 간주.
# (Mac은 엄격한 maximized 상태가 없어 커버리지로 판정. 메뉴바~25pt·Dock 여유 반영)
MAXIMIZE_WIDTH_MIN = 0.95    # 폭 95% 이상
MAXIMIZE_HEIGHT_MIN = 0.90   # 높이 90% 이상


def expected_page_px(window_width_pt: int, display_scale: float, pages_per_spread: int = 1) -> int:
    """물리 화면 캡처 시 페이지당 실제 픽셀 폭 예측."""
    return int(window_width_pt * display_scale / max(1, pages_per_spread))


def is_maximized(win_w_pt: float, win_h_pt: float, disp_w_pt: float, disp_h_pt: float) -> bool:
    """창이 디스플레이를 거의 꽉 채웠는지(=최대화). 물리 화면 캡처 전 필수 체크."""
    return (win_w_pt >= disp_w_pt * MAXIMIZE_WIDTH_MIN and
            win_h_pt >= disp_h_pt * MAXIMIZE_HEIGHT_MIN)


# 뷰어 줌(보기 비율) 규칙: 줌이 낮으면 페이지가 작게 렌더돼 캡처 픽셀 손해.
# 실측 페이지당 픽셀이 이론 최대치(창×scale)의 이 비율 미만이면 "줌/맞춤 낮음"으로 판정.
ZOOM_EFFICIENCY_MIN = 0.85


def capture_preflight(win_w_pt, win_h_pt, disp_w_pt, disp_h_pt,
                      display_scale, pages_per_spread=1, measured_page_px=None) -> dict:
    """물리 화면 캡처 직전 사전점검 — 최대화 + 뷰어줌 + 예상/실측 해상도 + 표준 판정.

    measured_page_px: 실제 1장 캡처·크롭에서 잰 페이지당 픽셀 폭(있으면 이걸로 판정).
      줌(보기 비율)·여백이 그대로 반영됨 → 이론치보다 정확.
    Returns: {maximized, coverage_w, coverage_h, page_px, measured_page_px,
              zoom_efficiency, meets_standard, need_window_pt, ok, advice[]}
    """
    maxd = is_maximized(win_w_pt, win_h_pt, disp_w_pt, disp_h_pt)
    theoretical_px = expected_page_px(win_w_pt, display_scale, pages_per_spread)  # 줌100%·꽉참 가정 상한
    eff_px = measured_page_px if measured_page_px else theoretical_px
    meets = eff_px >= MIN_SOURCE_WIDTH
    need_pt = required_window_width_pt(display_scale, pages_per_spread)
    zoom_eff = round(measured_page_px / theoretical_px, 2) if (measured_page_px and theoretical_px) else None
    advice = []
    if not maxd:
        advice.append(f"창이 최대화 안 됨(폭 {win_w_pt:.0f}/{disp_w_pt:.0f}pt) — 최대화 후 재시도")
    if pages_per_spread >= 2:
        advice.append("스프레드(양면) 감지 — 단면(1페이지) 보기로 전환 권장(페이지당 픽셀 2배)")
    if zoom_eff is not None and zoom_eff < ZOOM_EFFICIENCY_MIN:
        advice.append(
            f"뷰어 줌/맞춤이 낮음(실측 {measured_page_px}px = 최대 {theoretical_px}px의 {zoom_eff*100:.0f}%) "
            f"— 줌을 올리거나 '폭 맞춤(fit-width)'으로 페이지를 화면에 꽉 채우세요")
    if not meets:
        advice.append(
            f"페이지당 {eff_px}px < 목표 {MIN_SOURCE_WIDTH}px. "
            f"이 scale({display_scale:.0f}x)·{pages_per_spread}p면 창폭 ≥{need_pt}pt 필요"
            + (" → 이 모니터 폭으론 부족, 단면 전환 또는 2x 모니터 사용" if need_pt > disp_w_pt else "")
        )
    return {
        "maximized": maxd,
        "coverage_w": round(win_w_pt / disp_w_pt, 3) if disp_w_pt else 0,
        "coverage_h": round(win_h_pt / disp_h_pt, 3) if disp_h_pt else 0,
        "page_px": theoretical_px,
        "measured_page_px": measured_page_px,
        "zoom_efficiency": zoom_eff,
        "meets_standard": meets,
        "need_window_pt": need_pt,
        "ok": maxd and meets and (zoom_eff is None or zoom_eff >= ZOOM_EFFICIENCY_MIN),
        "advice": advice,
    }


def required_window_width_pt(display_scale: float, pages_per_spread: int = 1) -> int:
    """이 디스플레이 scale에서 MIN_SOURCE_WIDTH를 채우려면 필요한 창 폭(pt).

    예) 1x 모니터·단면 → 1400pt 창 필요.  2x·단면 → 700pt면 충분.
        1x·스프레드 → 2800pt (2560 모니터엔 불가 → 단면 강제해야 함).
    """
    import math
    return math.ceil(MIN_SOURCE_WIDTH * max(1, pages_per_spread) / display_scale)


def playwright_context_kwargs() -> dict:
    """Playwright new_context()/launch_persistent_context() 에 넣을 규격 kwargs.

    사용 예:
        ctx = browser.new_context(**playwright_context_kwargs(), locale="ko-KR")
    """
    return {
        "viewport": {"width": VIEWPORT_CSS[0], "height": VIEWPORT_CSS[1]},
        "device_scale_factor": DEVICE_SCALE_FACTOR,
    }


def validate_page(size: tuple[int, int]) -> dict:
    """캡처/크롭된 한 페이지가 표준을 만족하는지. size=(W,H) 픽셀.

    Returns: {"ok": bool, "warns": [str], "spec": str}
    """
    w, h = size
    warns = []
    if PORTRAIT_ONLY and w >= h:
        warns.append(f"가로형({w}x{h}) — 스프레드(양면) 의심. 단면 보기로 재캡처 필요")
    if w < MIN_SOURCE_WIDTH:
        warns.append(f"폭 {w}px < 최소 {MIN_SOURCE_WIDTH}px — 저해상. 창 최대화/줌↑ 또는 device_scale_factor↑")
    return {
        "ok": len(warns) == 0,
        "warns": warns,
        "spec": f"KyoboCaptureStandard {STANDARD_VERSION} (단면·세로·폭≥{MIN_SOURCE_WIDTH}, 목표 {TARGET_WIDTH}px)",
    }


def normalize_page(im):
    """크롭 완료된 페이지를 표준 폭(TARGET_WIDTH)으로 리샘플. 종횡비 유지.

    ⚠️ 업스케일은 없는 픽셀을 못 만든다 — MIN_SOURCE_WIDTH 게이트를 먼저 통과해야
    실질 선명. 이 함수는 "책·OS 무관 동일 폭" 표시 일관성만 보장.
    Pillow Image 입력/반환.
    """
    from PIL import Image
    w, h = im.size
    if w == TARGET_WIDTH:
        return im.convert(IMAGE_MODE)
    new_h = round(h * TARGET_WIDTH / w)
    return im.convert(IMAGE_MODE).resize((TARGET_WIDTH, new_h), Image.LANCZOS)


def safe_normalize(im):
    """normalize_page 이지만 어떤 예외에도 원본을 반환(캡처 파이프라인 절대 안 깨짐).
    모든 캡처 경로(Playwright/mac/win/linux)의 저장 직전에 공통으로 호출 → 폭 1600 균일."""
    try:
        return normalize_page(im)
    except Exception:
        return im
