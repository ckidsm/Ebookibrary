"""교보 앱에서 전체창 raw만 저장 (크롭 없음 → 캡처 견고). 표지로 복귀 후 끝까지.
raws/raw_NNN.png. 크롭은 이후 오프라인."""
import Quartz, subprocess, time, hashlib, json
from pathlib import Path
from PIL import Image
SP=Path("/private/tmp/claude-501/-Users-deoksooyun-Library-CloudStorage-OneDrive----Claude-NAS/047bde8f-0eb7-4d7b-b51a-8a515cd8fdd1/scratchpad")
R=SP/"raws"; R.mkdir(exist_ok=True)
for f in R.glob("raw_*.png"): f.unlink()
LOG=R/"raws.log"; open(LOG,"w").close()
wid=int((SP/"app_wid.txt").read_text())
def log(m):
    line=f"[{time.strftime('%H:%M:%S')}] {m}"; print(line,flush=True); open(LOG,"a").write(line+"\n")
def key(c):
    # 매번 앱 재활성화(포커스 보장) 후 키 전송 — 포커스 유실로 멈추는 것 방지
    subprocess.run(['osascript','-e','tell application id "kr.co.kyobobook.iPadB2C" to activate'],capture_output=True)
    subprocess.run(['osascript','-e',f'tell application "System Events" to key code {c}'],capture_output=True)
def move(x,y): pass  # 커서 이동 안 함(screencapture는 커서 미포함, 이동이 포커스 방해)
def shot(path):
    subprocess.run(['screencapture',f'-l{wid}','-x',str(path)],capture_output=True)
    return Image.open(path)
def phash(im):  # 전체창 축소 해시
    return hashlib.md5(im.convert("L").resize((64,40)).tobytes()).hexdigest()
subprocess.run(['osascript','-e','tell application id "kr.co.kyobobook.iPadB2C" to activate'],capture_output=True)
time.sleep(1.0); move(2,2)
# 1) 표지로 복귀: 왼쪽 반복(앱 anti-bot 없음), 해시 안 변하면 도착
log("표지로 복귀 중...")
last=None; stable=0
for i in range(300):
    im=shot(R/"_nav.png"); h=phash(im)
    if h==last:
        stable+=1
        if stable>=3: log(f"표지 도착 (i={i})"); break
    else: stable=0
    last=h; key(123); time.sleep(0.28); move(2,2)
time.sleep(1)
# 2) 표지부터 raw 저장, 오른쪽 진행, 끝(해시 반복) 감지
log("raw 저장 시작")
n=0; last=None; same=0
for i in range(400):  # 캡 상향(528p 등 긴 책 대비; 끝 감지로 실제 종료)
    im=shot(R/"_cur.png"); h=phash(im)
    if h==last:
        same+=1
        if same>=2: log(f"📕 끝 (총 {n}장)"); break
        key(124); time.sleep(1.2); move(2,2); continue
    same=0; last=h; n+=1
    im.save(R/f"raw_{n:03d}.png")
    if n%15==0: log(f"  raw {n}장")
    key(124); time.sleep(1.5); move(2,2)
log(f"DONE raw {n}장")
json.dump({"count":n},open(R/"result.json","w"))
