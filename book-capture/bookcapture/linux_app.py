"""Linux(X11) 캡처 워커 — scrot 로 화면 캡처 + xdotool 로 →키 페이지 넘김.

교보 웹뷰어를 브라우저 전체화면(F11)으로 띄워두면, X11 캡처(XGetImage)는 GDI 를
거치지 않아 교보의 GDI 화면캡처 차단(파란화면)에 막히지 않는다 — macOS screencapture,
Windows dxcam 과 같은 원리. 캡처 이미지는 books/<slug>/page_NNN.png 로 저장(워커가 업로드).

전제: DISPLAY 환경변수가 GUI 세션(예: :1)으로 설정돼 있어야 함. scrot·xdotool 설치 필요.
"""
from __future__ import annotations
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from PIL import Image
    HAS_PIL = True
except Exception:
    HAS_PIL = False

# AppleScript/일반 키 이름 → xdotool 키 이름
_KEYMAP = {
    "right": "Right", "left": "Left", "space": "space",
    "page_down": "Next", "pagedown": "Next", "down": "Down",
    "Right": "Right", "Left": "Left",
}


def _content_crop(im):
    """브라우저 크롬·여백 제거 → 본문만. win_app/mac 과 동일한 적응형 크롭."""
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


def has_display() -> bool:
    return bool(os.environ.get("DISPLAY"))


def _grab(tmp: Path):
    """scrot 로 현재 DISPLAY 화면 캡처 → PIL.Image (실패 None)."""
    subprocess.run(["scrot", "-z", "-o", str(tmp)], capture_output=True)
    if not tmp.exists() or tmp.stat().st_size < 2000:
        return None
    try:
        return Image.open(tmp)
    except Exception:
        return None


def _press(key_name: str):
    xk = _KEYMAP.get(key_name, "Right")
    subprocess.run(["xdotool", "key", "--clearmodifiers", xk], capture_output=True)


def capture_book(out_dir: str, slug: str, count: int, interval: float,
                 next_key: str = "right", no_crop: bool = True) -> int:
    """X11 화면을 count 장 캡처. 직전과 동일 해시 2회면 책 끝으로 보고 중단.
    반환: 저장한 페이지 수. 이미지는 out_dir/slug/page_NNN.png."""
    if not HAS_PIL:
        print("[linux] Pillow 미설치 — pip install Pillow", file=sys.stderr); return 0
    if not has_display():
        print("[linux] ✗ DISPLAY 환경변수 없음 — GUI 세션(예: DISPLAY=:1)으로 실행하세요", file=sys.stderr)
        return 0
    book_dir = Path(out_dir).expanduser() / slug
    book_dir.mkdir(parents=True, exist_ok=True)
    tmp = book_dir / "_raw.png"
    print(f"[linux] X11 캡처 시작 (DISPLAY={os.environ.get('DISPLAY')}) "
          f"count={count} interval={interval}s next_key={next_key}")
    last = None; n = 0; same = 0
    for i in range(count):
        im = _grab(tmp)
        if im is None:
            print(f"[linux] 캡처 실패/빈 화면 — 재시도 (p.{n})")
            time.sleep(0.5); continue
        if im.mode != "RGB":
            im = im.convert("RGB")
        if no_crop:
            im = _content_crop(im)
        h = hashlib.md5(im.tobytes()).hexdigest()
        if h == last:
            same += 1
            if same >= 2:
                print(f"[linux] 직전과 동일 화면 — 책 끝으로 보고 중단 (p.{n})")
                break
            _press(next_key); time.sleep(interval); continue
        same = 0; last = h; n += 1
        dst = book_dir / f"page_{n:03d}.png"
        im.save(dst)
        print(f"[{i+1}/{count}] 캡처 중... → {dst.name}")
        _press(next_key)
        time.sleep(interval)
    try:
        if tmp.exists():
            tmp.unlink()
    except Exception:
        pass
    print(f"[linux] 캡처 완료 — {n}장 ({book_dir})")
    return n
