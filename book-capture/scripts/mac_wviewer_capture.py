"""Mac 교보 wviewer 전체 캡처 v2 — 창ID(screencapture -l) + osascript →키.
교보 anti-bot 회피: 사람처럼 랜덤 간격(5~9초) + 가끔 긴 휴식. 책은 1페이지에 둔 채 시작.
/tmp/kcap/page_NNN.png 로 저장."""
import subprocess, time, hashlib, sys, random
from pathlib import Path
import Quartz
from PIL import Image

OUT = Path("/tmp/kcap"); OUT.mkdir(exist_ok=True)
for p in OUT.glob("*.png"):
    p.unlink()

# 차단 페이지(정상 접근 아님) 감지용 — 이 텍스트가 있는 화면이면 중단
def find_wid():
    wl = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
    cands = []
    for w in wl:
        if w.get('kCGWindowOwnerName') == 'Google Chrome':
            h = w.get('kCGWindowBounds', {}).get('Height', 0)
            if h > 800 and (w.get('kCGWindowName') or ''):
                cands.append((h, w.get('kCGWindowNumber')))
    cands.sort(reverse=True)
    return cands[0][1] if cands else None

def osa(s): subprocess.run(['osascript', '-e', s], capture_output=True)
def activate(): osa('tell application "Google Chrome" to activate')
def key(code): osa(f'tell application "System Events" to key code {code}')

def kyobo_tab_open():
    """Chrome 탭 중 교보 사이트(kyobobook.co.kr)가 열려있는지 — AppleScript URL 확인."""
    s = ('tell application "Google Chrome"\n'
         '  set f to false\n'
         '  repeat with w in windows\n'
         '    repeat with t in tabs of w\n'
         '      if (URL of t) contains "kyobobook.co.kr" then set f to true\n'
         '    end repeat\n'
         '  end repeat\n'
         '  return f\n'
         'end tell')
    r = subprocess.run(['osascript', '-e', s], capture_output=True, text=True)
    return 'true' in (r.stdout or '').lower()

def _content_crop(im):
    """브라우저 크롬·작업표시줄·여백 제거 → 본문만 꽉 차게. 상단 크롬 높이를
    '색상(채도) 행'으로 자동 감지(탭·파비콘·북마크)해 딱 그만큼 잘라 본문 첫 줄 보존.
    고정 % 는 레이아웃마다 과/소 크롭 → 적응형. (같은 페이지→결정적 결과=해시 안정)"""
    rgb = im.convert("RGB"); W, H = im.size
    SS = 8; sw, sh = max(1, W // SS), max(1, H // SS)
    px = rgb.resize((sw, sh)).load()
    last_color = -1
    for y in range(int(sh * 0.12)):
        c = 0
        for x in range(sw):
            r, g, b = px[x, y]
            if max(r, g, b) > 50 and (max(r, g, b) - min(r, g, b)) > 30:
                c += 1
        if c > max(2, sw * 0.015):
            last_color = y
    top = int((last_color + 2) * SS) if last_color >= 0 else 0
    bottom = H - int(H * 0.035)
    rgb = rgb.crop((0, top, W, bottom))
    W2, H2 = rgb.size; e = int(min(W2, H2) * 0.015)
    rgb = rgb.crop((e, e, W2 - e, H2 - e))
    bw = rgb.convert("L").point(lambda p: 255 if p < 115 else 0)
    bbox = bw.getbbox()
    if bbox:
        pad = 16; l, t, r, b = bbox
        rgb = rgb.crop((max(0, l - pad), max(0, t - pad),
                        min(rgb.size[0], r + pad), min(rgb.size[1], b + pad)))
    return rgb.convert("RGB")

def grab_crop(wid):
    raw = OUT / "_raw.png"
    subprocess.run(['screencapture', f'-l{wid}', '-x', str(raw)], capture_output=True)
    if not raw.exists() or raw.stat().st_size < 2000:
        return None
    return _content_crop(Image.open(raw))

def h_of(im): return hashlib.md5(im.tobytes()).hexdigest()

# 차단 화면 휴리스틱: 대부분 흰색 + 가운데 회색 아이콘 (텍스트 거의 없음) → 평균 밝기 매우 높고 분산 낮음
def looks_blocked(im):
    g = im.convert("L").resize((64, 64))
    px = list(g.getdata()); n = len(px)
    avg = sum(px) / n
    dark = sum(1 for p in px if p < 120) / n   # 본문은 글자(어두운 픽셀) 비율 꽤 됨
    return avg > 235 and dark < 0.02            # 거의 백지(차단/빈페이지)

if not kyobo_tab_open():
    print("✗ Chrome에 교보 사이트(kyobobook.co.kr)가 안 열렸습니다. [바로보기]로 책을 연 뒤 다시 시작하세요.")
    sys.exit(1)
wid = find_wid()
print("WID", wid, flush=True)
if not wid:
    print("✗ Chrome 책창 못찾음"); sys.exit(1)
print("✓ 교보 탭 감지됨", flush=True)
activate(); time.sleep(0.8)

# ── 캡처 표준 사전점검(최대화·스프레드·해상도) ─────────────────
# 규칙: 최대화 안 됨 or 표준 미충족이면 중단. KYOBO_ALLOW_SUBSTANDARD=1 이면 경고만.
def _preflight_gate(wid):
    try:
        import os as _os, sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "bookcapture"))
        import capture_standard as _cs
        # 창 bounds + 소속 디스플레이 scale
        wl = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
        wb = next((w.get('kCGWindowBounds', {}) for w in wl
                   if w.get('kCGWindowNumber') == wid), None)
        if not wb:
            return True
        x, y, W, H = wb['X'], wb['Y'], wb['Width'], wb['Height']
        err, ids, cnt = Quartz.CGGetActiveDisplayList(8, None, None)
        dpw = dph = scale = None
        for did in ids[:cnt]:
            b = Quartz.CGDisplayBounds(did)
            if b.origin.x <= x < b.origin.x + b.size.width and b.origin.y <= y < b.origin.y + b.size.height:
                m = Quartz.CGDisplayCopyDisplayMode(did)
                ptw = Quartz.CGDisplayModeGetWidth(m)
                dpw, dph = ptw, Quartz.CGDisplayModeGetHeight(m)
                scale = Quartz.CGDisplayModeGetPixelWidth(m) / ptw if ptw else 1.0
                break
        if scale is None:
            return True
        # 스프레드 판정 + 실측 페이지당 픽셀(줌·여백 반영): 지금 화면 1장 크롭
        im = grab_crop(wid)
        pages = 2 if (im and im.size[0] > im.size[1]) else 1
        measured = (im.size[0] // pages) if im else None
        pf = _cs.capture_preflight(W, H, dpw, dph, scale, pages_per_spread=pages,
                                   measured_page_px=measured)
        print(f"[사전점검] 모니터 {dpw:.0f}x{dph:.0f}pt {scale:.0f}x · 창 {W:.0f}x{H:.0f}pt · "
              f"{'스프레드2p' if pages==2 else '단면1p'} · 최대화 "
              f"{'O' if pf['maximized'] else 'X'}({pf['coverage_w']*100:.0f}%) · "
              f"예상 페이지당 {pf['page_px']}px → {'OK' if pf['meets_standard'] else '미달'}", flush=True)
        for a in pf['advice']:
            print(f"[사전점검]   • {a}", flush=True)
        if not pf['ok']:
            if _os.environ.get("KYOBO_ALLOW_SUBSTANDARD") == "1":
                print("[사전점검] ⚠ 표준 미충족이지만 KYOBO_ALLOW_SUBSTANDARD=1 → 계속 진행", flush=True)
                return True
            print("[사전점검] ✗ 표준 미충족 — 중단. (조치 후 재시도 / 강제하려면 KYOBO_ALLOW_SUBSTANDARD=1)", flush=True)
            return False
        return True
    except Exception as e:
        print(f"[사전점검] (건너뜀: {e})", flush=True)
        return True

if not _preflight_gate(wid):
    sys.exit(3)

last = None; n = 0; same = 0; blank = 0
for i in range(700):
    if i % 15 == 0: activate()
    im = grab_crop(wid)
    if im is None:
        wid = find_wid() or wid; time.sleep(0.4); continue
    hh = h_of(im)
    if hh == last:
        same += 1
        if same >= 2:
            print("→ 책 끝 도달", flush=True); break
        key(124); time.sleep(random.uniform(5, 8)); continue
    same = 0; last = hh; n += 1
    try:
        import capture_standard as _csn  # gate 에서 sys.path 등록됨
        im = _csn.safe_normalize(im)
    except Exception:
        pass
    im.save(OUT / f"page_{n:03d}.png")   # 표준 폭 1600px 정규화(균일)
    if n % 10 == 0: print(f"  {n}장...", flush=True)
    key(124)
    # 사람처럼: 보통 5~9초, 12~18장마다 25~50초 휴식
    if n % random.randint(12, 18) == 0:
        pause = random.uniform(25, 50); print(f"  ...휴식 {int(pause)}s", flush=True); time.sleep(pause)
    else:
        time.sleep(random.uniform(5, 9))
print(f"DONE 총 {n}장 → {OUT}", flush=True)
