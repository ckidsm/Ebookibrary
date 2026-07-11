"""macOS 디스플레이 감지 (Quartz) → capture_standard.DisplaySpec 리스트.

로컬 매크로(교보 데스크탑 앱 캡처) 전에 "어느 모니터가 캡처 표준을 만족하는지"
판정하기 위한 실측 소스. 내장/외장·해상도·scale(1x/2x)을 CoreGraphics 에서 읽는다.

Quartz(pyobjc) 는 macOS 전용 → 이 모듈은 mac 에서만 import.
규칙 판정은 capture_standard.CaptureStandardV1 이 담당(이 모듈은 감지만).
"""
from __future__ import annotations

try:
    import Quartz  # pyobjc-framework-Quartz (requirements.txt, darwin 전용)
except Exception:  # pragma: no cover
    Quartz = None

from . import capture_standard as cs


def detect_displays() -> list[cs.DisplaySpec]:
    """연결된 모든 활성 디스플레이를 DisplaySpec 리스트로 반환.

    각 디스플레이의 논리 해상도(pt)·실제 픽셀(px)·scale·내장/주 여부를 읽는다.
    Quartz 없으면 빈 리스트(호출측이 게이트 스킵/폴백).
    """
    if Quartz is None:
        return []
    err, ids, cnt = Quartz.CGGetActiveDisplayList(16, None, None)
    out = []
    for did in list(ids[:cnt]):
        mode = Quartz.CGDisplayCopyDisplayMode(did)
        ptw = Quartz.CGDisplayModeGetWidth(mode)
        pth = Quartz.CGDisplayModeGetHeight(mode)
        pxw = Quartz.CGDisplayModeGetPixelWidth(mode)
        scale = (pxw / ptw) if ptw else 1.0
        builtin = bool(Quartz.CGDisplayIsBuiltin(did))
        main = bool(Quartz.CGDisplayIsMain(did))
        name = ("내장 디스플레이" if builtin else "외장 모니터")
        out.append(cs.DisplaySpec(
            name=name, width_pt=ptw, height_pt=pth, scale=scale,
            builtin=builtin, main=main, display_id=int(did)))
    return out


def display_id_at(x: float, y: float, displays=None) -> int | None:
    """주어진 전역 좌표(pt)가 속한 디스플레이 id. 창 위치로 '지금 어느 모니터'인지 판정용."""
    if Quartz is None:
        return None
    if displays is None:
        displays = detect_displays()
    for d in displays:
        b = Quartz.CGDisplayBounds(d.display_id)
        if (b.origin.x <= x < b.origin.x + b.size.width and
                b.origin.y <= y < b.origin.y + b.size.height):
            return d.display_id
    return None


def kyobo_app_display_id() -> int | None:
    """교보 eBook 데스크탑 앱 창이 현재 떠 있는 디스플레이 id (없으면 None).

    로컬 매크로 캡처 대상 = 이 창이 있는 모니터. plan(prefer_id=...) 에 넘겨
    '사용자가 앱을 띄운 그 모니터'를 우선 존중/판정한다.
    """
    if Quartz is None:
        return None
    wl = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
    best = None  # (area, x, y)
    for w in wl or []:
        owner = (w.get('kCGWindowOwnerName') or '')
        if '교보' not in owner and 'Kyobo' not in owner and 'eBook' not in owner:
            continue
        b = w.get('kCGWindowBounds', {})
        area = b.get('Width', 0) * b.get('Height', 0)
        if area < 100000:   # 툴팁/작은 창 제외
            continue
        if best is None or area > best[0]:
            best = (area, b.get('X', 0), b.get('Y', 0))
    if best is None:
        return None
    return display_id_at(best[1], best[2])


def _fmt_eval(e, star=False) -> str:
    mark = " ⭐추천" if star else ""
    return (f"[{e['kind']}] {e['name']}  {e['width_pt']}x{e['height_pt']}pt "
            f"{e['scale']:.1f}x  백킹{e['backing_width']}px  "
            f"페이지당 {e['page_px']}px  {'✅충족' if e['meets'] else '❌미달'}"
            f"  best={e['best_layout']}{mark}")


def capture_readiness(pages_per_spread=cs.DEFAULT_PAGES_PER_SPREAD) -> dict:
    """현재 모니터 + 교보 앱 위치로 로컬 매크로 캡처 준비 상태 판정(규칙 엔진 적용).

    Returns dict(ok, reason, plan, app_display_id, app_eval, lines[]).
      ok=False 면 캡처 대상 화면이 양면 표준 미달 → 게이트가 차단(또는 override).
    """
    disps = detect_displays()
    std = cs.CaptureStandardV1()
    if not disps:
        return {"ok": True, "reason": "디스플레이 감지 불가(Quartz 없음) — 게이트 스킵",
                "plan": None, "app_display_id": None, "app_eval": None, "lines": []}
    app_id = kyobo_app_display_id()
    plan = std.plan(disps, pages_per_spread, prefer_id=app_id)
    app_eval = next((e for e in plan["evaluations"] if e["display_id"] == app_id),
                    None) if app_id else None
    if app_eval is not None:
        ok = app_eval["meets"]
        reason = ("교보 앱이 있는 모니터가 양면 표준 충족" if ok else
                  f"교보 앱이 있는 모니터('{app_eval['name']}')가 양면 표준 미달"
                  f"({app_eval['page_px']}px < {std.MIN_PAGE_PX}px)")
    else:
        ok = plan["any_meets"]
        reason = ("교보 앱 미감지 — 표준 충족 모니터가 있으니 거기에 앱을 띄우세요" if ok else
                  "교보 앱 미감지 + 표준을 만족하는 모니터가 없음")

    layout_kr = "양면" if pages_per_spread >= 2 else "단면"
    lines = [f"{layout_kr}({pages_per_spread}p) 표준 = 페이지당 ≥ {std.MIN_PAGE_PX}px "
             f"(백킹 ≥ {std.required_backing_width(pages_per_spread)}px)"]
    for e in plan["evaluations"]:
        is_app = (app_id is not None and e["display_id"] == app_id)
        is_pick = (plan["chosen"] and e["display_id"] == plan["chosen"]["display_id"])
        tag = " ←교보앱 위치" if is_app else ""
        lines.append("  " + _fmt_eval(e, star=is_pick) + tag)
        for a in e["advice"]:
            lines.append("       → " + a)
    if plan["chosen"]:
        lines.append(f"추천 캡처 모니터: {plan['chosen']['name']} ({plan['chosen_reason']})")
    for a in plan["advice"]:
        lines.append("조치: " + a)
    return {"ok": ok, "reason": reason, "plan": plan,
            "app_display_id": app_id, "app_eval": app_eval, "lines": lines}
