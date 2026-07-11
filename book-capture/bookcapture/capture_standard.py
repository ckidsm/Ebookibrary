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


# ══════════════════════════════════════════════════════════════════════════
#  로컬 매크로(물리 화면 캡처) 디스플레이 규칙 엔진 — 기기·모니터 무관 상대 판정
#  ------------------------------------------------------------------------
#  규칙: 물리 화면 캡처는 페이지당_픽셀 = 창폭(pt) × scale ÷ 페이지수.
#  양면(스프레드) 표준 = 페이지당 ≥ MIN_SOURCE_WIDTH(1400px) → 백킹 폭 ≥ 2800px.
#  이 클래스가 "어느 모니터/기기든" 동일 규칙으로 판정·추천한다(11"·14"·16" 내장,
#  외장 1x/HiDPI 무관). Quartz 비의존(순수 계산) → Win/Linux 에서도 import 가능.
#  실제 모니터 감지(Quartz)는 mac_displays.detect_displays() 가 DisplaySpec 리스트로 공급.
# ══════════════════════════════════════════════════════════════════════════

DEFAULT_PAGES_PER_SPREAD = 2   # 교보 데스크탑 앱 기본 = 두 페이지 보기(양면). 런북 §1.


class DisplaySpec:
    """한 모니터의 캡처 능력(물리 화면 캡처 기준). 순수 데이터 + 판정."""

    def __init__(self, name, width_pt, height_pt, scale,
                 builtin=False, main=False, display_id=None):
        self.name = name
        self.width_pt = float(width_pt)
        self.height_pt = float(height_pt)
        self.scale = float(scale)
        self.builtin = bool(builtin)
        self.main = bool(main)
        self.display_id = display_id

    @property
    def backing_width(self) -> int:
        """최대화(창=화면 폭) 시 캡처되는 실제 픽셀 폭 = 창폭(pt) × scale."""
        return int(round(self.width_pt * self.scale))

    def page_px(self, pages_per_spread=DEFAULT_PAGES_PER_SPREAD, coverage=1.0) -> int:
        """이 모니터에서 최대화·coverage 시 페이지당 픽셀 폭."""
        return int(self.width_pt * self.scale * coverage / max(1, pages_per_spread))

    def meets(self, pages_per_spread=DEFAULT_PAGES_PER_SPREAD) -> bool:
        return self.page_px(pages_per_spread) >= MIN_SOURCE_WIDTH

    def best_layout(self) -> str | None:
        """이 모니터가 표준을 만족하는 최선 레이아웃. 양면>단면>불가(None)."""
        if self.meets(2):
            return "spread"      # 양면 가능(최선 — 배포 표준과 동일 레이아웃)
        if self.meets(1):
            return "single"      # 단면만 가능
        return None              # 어떤 레이아웃도 표준 미달

    def kind(self) -> str:
        return "내장" if self.builtin else "외장"

    def __repr__(self):
        return (f"DisplaySpec({self.name!r} {self.kind()} "
                f"{self.width_pt:.0f}x{self.height_pt:.0f}pt {self.scale:.1f}x "
                f"backing={self.backing_width}px)")


class CaptureStandardV1:
    """KyoboCaptureStandard v1 규칙 엔진 — 디스플레이가 캡처 표준을 만족하는지
    상대적으로 판정하고, 여러 모니터 중 어디에 앱을 띄울지 계획한다.

    핵심 규칙(문서: docs/EBOOK_CAPTURE_STANDARD.md §1.5):
      - 양면 표준: 페이지당 ≥ MIN_PAGE_PX(1400px) → 백킹 폭 ≥ 2*MIN_PAGE_PX.
      - 외장 사용은 강제 아님: 표준 충족 모니터를 '추천'하되 강요하지 않는다.
      - 미달이면 조치 안내(단면 전환 / 해상도 올리기 / 내장 Retina).
    """
    MIN_PAGE_PX = MIN_SOURCE_WIDTH   # 1400
    STANDARD = STANDARD_VERSION      # "v1"

    def required_backing_width(self, pages_per_spread=DEFAULT_PAGES_PER_SPREAD) -> int:
        """이 페이지수(양면=2)로 표준을 채우는 데 필요한 백킹 폭(px)."""
        return self.MIN_PAGE_PX * max(1, pages_per_spread)

    def evaluate(self, disp: DisplaySpec,
                 pages_per_spread=DEFAULT_PAGES_PER_SPREAD) -> dict:
        """한 디스플레이 판정. Returns dict(name, kind, builtin, page_px,
        meets, backing_width, need_backing, best_layout, advice[])."""
        page_px = disp.page_px(pages_per_spread)
        meets = page_px >= self.MIN_PAGE_PX
        need = self.required_backing_width(pages_per_spread)
        best = disp.best_layout()
        advice = []
        if not meets:
            if disp.meets(1):
                advice.append(
                    f"단면(1페이지) 보기로 전환하면 페이지당 {disp.page_px(1)}px 로 충족")
            advice.append(
                f"양면 표준(백킹 ≥{need}px)에 {need - disp.backing_width}px 부족"
                f" — 해상도를 더 높은 HiDPI로 올리면 개선"
                if disp.backing_width < need else "")
            if not disp.meets(1):
                advice.append("이 모니터로는 단면조차 미달 — 내장 Retina 등 고해상 디스플레이 권장")
        return {
            "name": disp.name,
            "kind": disp.kind(),
            "builtin": disp.builtin,
            "main": disp.main,
            "display_id": disp.display_id,
            "width_pt": int(disp.width_pt),
            "height_pt": int(disp.height_pt),
            "scale": disp.scale,
            "backing_width": disp.backing_width,
            "page_px": page_px,
            "single_page_px": disp.page_px(1),   # 단면(1p) 전환 시 페이지당 픽셀
            "need_backing": need,
            "meets": meets,
            "meets_single": disp.meets(1),
            "best_layout": best,
            "advice": [a for a in advice if a],
        }

    def plan(self, displays, pages_per_spread=DEFAULT_PAGES_PER_SPREAD,
             prefer_id=None) -> dict:
        """여러 모니터 중 어디에 교보 앱을 띄워 캡처할지 계획.

        prefer_id: 사용자가 이미 앱을 띄운(또는 원하는) 디스플레이 id.
          그게 표준을 만족하면 그대로 존중(외장 강제 아님).
        Returns dict(evaluations[], any_meets, chosen(dict|None), chosen_reason,
                     override_needed, advice[]).
        """
        evals = [self.evaluate(d, pages_per_spread) for d in displays]
        meeting = [e for e in evals if e["meets"]]
        any_meets = bool(meeting)

        chosen = None
        reason = ""
        if prefer_id is not None:
            pe = next((e for e in evals if e["display_id"] == prefer_id), None)
            if pe and pe["meets"]:
                chosen, reason = pe, "사용자가 선택한 모니터가 표준 충족 — 그대로 사용"
        if chosen is None and meeting:
            # 표준 충족 중 페이지당 픽셀 최고 → 동률이면 내장 우선(안정)
            chosen = max(meeting, key=lambda e: (e["page_px"], e["builtin"]))
            reason = "표준을 만족하는 모니터 중 페이지당 픽셀이 가장 큰 화면을 추천"

        advice = []
        if not any_meets:
            # 아무 모니터도 양면 미달 → 단면 가능 화면/조치 제시
            single_ok = [e for e in evals if e["meets_single"]]
            if single_ok:
                best_single = max(single_ok, key=lambda e: e["single_page_px"])
                advice.append(
                    f"양면 표준을 만족하는 모니터가 없습니다. "
                    f"단면(1페이지)이면 '{best_single['name']}'({best_single['kind']}) 에서 "
                    f"페이지당 {best_single['single_page_px']}px 로 가능 — 앱을 단면 보기로 전환하세요.")
            advice.append(
                "또는 외장 모니터 해상도를 더 높은 HiDPI(백킹 ≥"
                f"{self.required_backing_width(pages_per_spread)}px)로 올리거나, "
                "내장 Retina 디스플레이에서 캡처하세요.")
        return {
            "pages_per_spread": pages_per_spread,
            "evaluations": evals,
            "any_meets": any_meets,
            "chosen": chosen,
            "chosen_reason": reason,
            "override_needed": not any_meets,   # 표준 충족 화면 없음 → 진행하려면 override
            "advice": advice,
        }
