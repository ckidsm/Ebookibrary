"""Mac 캡처 사전점검 — 교보 wviewer Chrome 창이 캡처 표준을 만족하는지 라이브 검증.

검사 항목:
  1) 창이 어느 모니터에 있고 그 모니터 scale(1x/2x)은?
  2) 창이 최대화(디스플레이 거의 꽉 참)됐는가?  ← 해상도 좌우 핵심
  3) 지금 화면이 스프레드(양면)인가 단면인가?  (실제 1장 캡처+크롭 종횡비로 판정)
  4) 이 조합에서 예상 페이지당 픽셀 → 표준(≥1400px) 충족 여부 + 조치 안내

사용: <venv>/bin/python scripts/mac_capture_preflight.py [창제목일부]
종료코드: 표준 충족 0, 미충족 1, 창 못찾음 2.
"""
import subprocess, sys, tempfile
from pathlib import Path
import Quartz
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bookcapture"))
import capture_standard as cs

TITLE_HINT = sys.argv[1] if len(sys.argv) > 1 else None


def _content_crop(im):  # mac_wviewer_capture.py 와 동일 로직 (import 시 캡처 실행 방지 위해 복제)
    rgb = im.convert("RGB"); W, H = im.size
    SS = 8; sw, sh = max(1, W // SS), max(1, H // SS)
    px = rgb.resize((sw, sh)).load(); last = -1
    for y in range(int(sh * 0.12)):
        c = sum(1 for x in range(sw)
                if max(px[x, y]) > 50 and (max(px[x, y]) - min(px[x, y])) > 30)
        if c > max(2, sw * 0.015): last = y
    top = int((last + 2) * SS) if last >= 0 else 0
    rgb = rgb.crop((0, top, W, H - int(H * 0.035)))
    W2, H2 = rgb.size; e = int(min(W2, H2) * 0.015)
    rgb = rgb.crop((e, e, W2 - e, H2 - e))
    bw = rgb.convert("L").point(lambda p: 255 if p < 115 else 0); bbox = bw.getbbox()
    if bbox:
        pad = 16; l, t, r, b = bbox
        rgb = rgb.crop((max(0, l - pad), max(0, t - pad),
                        min(rgb.size[0], r + pad), min(rgb.size[1], b + pad)))
    return rgb.convert("RGB")


def displays():
    err, ids, cnt = Quartz.CGGetActiveDisplayList(8, None, None)
    out = {}
    for did in ids[:cnt]:
        m = Quartz.CGDisplayCopyDisplayMode(did)
        ptw, pth = Quartz.CGDisplayModeGetWidth(m), Quartz.CGDisplayModeGetHeight(m)
        pxw = Quartz.CGDisplayModeGetPixelWidth(m)
        b = Quartz.CGDisplayBounds(did)
        out[did] = dict(bounds=b, pt=(ptw, pth), scale=(pxw / ptw if ptw else 1.0),
                        builtin=bool(Quartz.CGDisplayIsBuiltin(did)))
    return out


def find_window():
    wl = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
    cands = []
    for w in wl:
        if w.get('kCGWindowOwnerName') != 'Google Chrome':
            continue
        name = w.get('kCGWindowName') or ''
        b = w.get('kCGWindowBounds', {})
        if b.get('Height', 0) < 400:
            continue
        if TITLE_HINT and TITLE_HINT not in name:
            continue
        cands.append((b.get('Width', 0) * b.get('Height', 0), w.get('kCGWindowNumber'), name, b))
    cands.sort(reverse=True)
    return cands[0] if cands else None


def main():
    win = find_window()
    if not win:
        print("✗ Chrome 책 창을 못 찾음 (교보 wviewer 열려 있나요?)")
        return 2
    _, wid, name, b = win
    x, y, W, H = b['X'], b['Y'], b['Width'], b['Height']
    disp = displays()
    cur = None
    for did, d in disp.items():
        db = d['bounds']
        if db.origin.x <= x < db.origin.x + db.size.width and db.origin.y <= y < db.origin.y + db.size.height:
            cur = d; break
    if not cur:
        cur = next(iter(disp.values()))
    scale = cur['scale']; dpw, dph = cur['pt']

    # 실제 1장 캡처 → 크롭 → 스프레드 판정(가로면 2p) + 실측 페이지당 픽셀
    tmp = Path(tempfile.gettempdir()) / "kcap_preflight.png"
    subprocess.run(['screencapture', f'-l{wid}', '-x', str(tmp)], capture_output=True)
    pages = 1; crop_size = None; measured = None
    if tmp.exists() and tmp.stat().st_size > 2000:
        crop = _content_crop(Image.open(tmp))
        crop_size = crop.size
        pages = 2 if crop.size[0] > crop.size[1] else 1
        measured = crop.size[0] // pages   # 실측 페이지당 픽셀 폭(줌·여백 반영)

    pf = cs.capture_preflight(W, H, dpw, dph, scale, pages_per_spread=pages,
                              measured_page_px=measured)

    print(f"창: '{name[:40]}' (wid={wid})  {W:.0f}x{H:.0f}pt")
    print(f"모니터: {'내장' if cur['builtin'] else '외장'} {dpw:.0f}x{dph:.0f}pt  scale={scale:.0f}x")
    print(f"레이아웃: {'스프레드(양면 2p)' if pages == 2 else '단면(1p)'}"
          + (f"  실측크롭 {crop_size}" if crop_size else "  (캡처 실패 — 단면 가정)"))
    print(f"최대화: {'✅ 예' if pf['maximized'] else '❌ 아니오'}"
          f" (폭 {pf['coverage_w']*100:.0f}% · 높이 {pf['coverage_h']*100:.0f}%)")
    ze = pf['zoom_efficiency']
    print(f"페이지당 픽셀: 실측 {measured}px / 이론최대 {pf['page_px']}px"
          + (f" (줌효율 {ze*100:.0f}%)" if ze is not None else "")
          + f"  → 표준(≥{cs.MIN_SOURCE_WIDTH}px) {'✅ 충족' if pf['meets_standard'] else '❌ 미충족'}")
    print(f"종합: {'✅ 캡처 진행 OK' if pf['ok'] else '⚠ 아래 조치 후 재시도'}")
    for a in pf['advice']:
        print(f"   • {a}")
    return 0 if pf['ok'] else 1


if __name__ == "__main__":
    sys.exit(main())
