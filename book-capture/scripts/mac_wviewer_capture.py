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

def grab_crop(wid):
    raw = OUT / "_raw.png"
    subprocess.run(['screencapture', f'-l{wid}', '-x', str(raw)], capture_output=True)
    if not raw.exists() or raw.stat().st_size < 2000:
        return None
    im = Image.open(raw); W, H = im.size
    top = int(H * 0.075); b = 16
    return im.crop((b, top, W - b, H - b)).convert("RGB")

def h_of(im): return hashlib.md5(im.tobytes()).hexdigest()

# 차단 화면 휴리스틱: 대부분 흰색 + 가운데 회색 아이콘 (텍스트 거의 없음) → 평균 밝기 매우 높고 분산 낮음
def looks_blocked(im):
    g = im.convert("L").resize((64, 64))
    px = list(g.getdata()); n = len(px)
    avg = sum(px) / n
    dark = sum(1 for p in px if p < 120) / n   # 본문은 글자(어두운 픽셀) 비율 꽤 됨
    return avg > 235 and dark < 0.02            # 거의 백지(차단/빈페이지)

wid = find_wid()
print("WID", wid, flush=True)
if not wid:
    print("✗ Chrome 책창 못찾음"); sys.exit(1)
activate(); time.sleep(0.8)

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
    im.save(OUT / f"page_{n:03d}.png")
    if n % 10 == 0: print(f"  {n}장...", flush=True)
    key(124)
    # 사람처럼: 보통 5~9초, 12~18장마다 25~50초 휴식
    if n % random.randint(12, 18) == 0:
        pause = random.uniform(25, 50); print(f"  ...휴식 {int(pause)}s", flush=True); time.sleep(pause)
    else:
        time.sleep(random.uniform(5, 9))
print(f"DONE 총 {n}장 → {OUT}", flush=True)
