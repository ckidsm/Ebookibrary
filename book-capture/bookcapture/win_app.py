"""Windows 교보 eLibrary 앱 관리 + 화면 캡처.

macOS 의 kyobo_app.KyoboAppScreenshot 와 같은 인터페이스를 제공해
cmd_capture_auto 가 OS 에 따라 골라 쓰도록 한다.

Windows 는 앱 경로가 고정이라 (설치 위치 명확):
  C:\\Program Files (x86)\\Kyobobook\\eLibrary\\KyoboBook.Ebook.ELibrary.exe
없으면 공식 설치파일을 받아 설치하고, 분석 시 앱을 실행한다.

캡처: Pillow ImageGrab(전 영역 또는 설정 region) + ctypes SendInput 페이지 넘김.
(추가 의존성 없음 — Pillow 는 이미 OCR 용으로 들어감)
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

KYOBO_WIN_EXE = r"C:\Program Files (x86)\Kyobobook\eLibrary\KyoboBook.Ebook.ELibrary.exe"
INSTALLER_URL = "https://contents.kyobobook.co.kr/digital/download/elibrary/b2c/KyoboeBook_Setup.exe"
_EXE_NAME = "KyoboBook.Ebook.ELibrary.exe"

# 페이지 넘김 키 → Windows Virtual-Key Code
_VK = {"right": 0x27, "left": 0x25, "space": 0x20, "pagedown": 0x22, "pageup": 0x21, "down": 0x28}

# 교보 Windows 앱 크롬 크롭 기본값(px). 전체화면에서 상단(제목+툴바)·하단(음성/페이지 컨트롤바)
# ·좌우 여백을 잘라 책 본문만 캡처 → OCR 깨끗. region(절대좌표) 설정 시엔 그쪽 우선.
# 해상도/배율 다르면 조정 필요(여유 있게 잡아도 책 본문은 가운데라 안 잘림).
_WIN_CROP = {"top": 80, "bottom": 70, "left": 0, "right": 0}


def is_installed() -> bool:
    return os.path.isfile(KYOBO_WIN_EXE)


def get_app_window_title() -> str:
    """교보 eLibrary 앱 창의 제목을 반환(없으면 ''). 예: '교보eBook - HTTP 완벽 가이드'.
    win32 의존성 없이 ctypes EnumWindows 로 보이는 창들을 훑어 교보 창을 찾는다."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _l):
            if not user32.IsWindowVisible(hwnd):
                return True
            ln = user32.GetWindowTextLengthW(hwnd)
            if ln and ln > 0:
                buf = ctypes.create_unicode_buffer(ln + 1)
                user32.GetWindowTextW(hwnd, buf, ln + 1)
                t = buf.value or ""
                tl = t.lower()
                if ("교보" in t) or ("ebook" in tl) or ("elibrary" in tl) or ("kyobo" in tl):
                    found.append(t)
            return True

        user32.EnumWindows(_cb, 0)
        # '교보eBook - <책>' 패턴 우선
        for t in found:
            if "-" in t and "교보" in t:
                return t
        return found[0] if found else ""
    except Exception:
        return ""


def download_installer(dest: str | None = None, timeout: int = 300) -> str:
    """설치파일 다운로드. 받은 파일 경로 반환."""
    dest = dest or os.path.join(tempfile.gettempdir(), "KyoboeBook_Setup.exe")
    print(f"[win] 설치파일 다운로드: {INSTALLER_URL}\n      → {dest}")
    req = urllib.request.Request(INSTALLER_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        f.write(r.read())
    sz = os.path.getsize(dest)
    print(f"[win] 다운로드 완료 ({sz/1_000_000:.1f} MB)")
    return dest


def ensure_installed(wait_after_install: int = 180) -> bool:
    """앱 설치 보장. 없으면 설치파일 받아 실행.

    설치 관리자가 대화형일 수 있어 best-effort 무인 플래그(/S)도 시도한다.
    설치 완료까지 exe 출현을 폴링.
    """
    if is_installed():
        print(f"[win] 교보 eLibrary 이미 설치됨: {KYOBO_WIN_EXE}")
        return True
    print("[win] 교보 eLibrary 미설치 — 설치 진행")
    try:
        installer = download_installer()
    except Exception as e:
        print(f"[win] 설치파일 다운로드 실패: {e}", file=sys.stderr)
        return False
    # 무인 설치 시도(/S = NSIS silent). 실패/미지원이면 일반 실행으로 사용자가 진행.
    try:
        print("[win] 설치 실행 (무인 /S 시도)…")
        subprocess.Popen([installer, "/S"])
    except Exception as e:
        print(f"[win] /S 실행 실패({e}) — 일반 실행")
        try:
            os.startfile(installer)  # type: ignore[attr-defined]
        except Exception as e2:
            print(f"[win] 설치 실행 실패: {e2}", file=sys.stderr)
            return False
    # exe 출현 폴링
    for i in range(wait_after_install):
        if is_installed():
            print(f"[win] 설치 확인됨 ({i}s)")
            time.sleep(3)
            return True
        time.sleep(1)
    print(f"[win] {wait_after_install}s 내 설치 미확인 — 사용자가 설치 마법사를 끝냈는지 확인 필요",
          file=sys.stderr)
    return is_installed()


class KyoboWinCapture:
    """macOS KyoboAppScreenshot 와 같은 인터페이스(Windows 구현)."""

    def __init__(self, output_dir: str = "books", book_folder: str | None = None):
        self.book_dir = Path(output_dir) / (book_folder or "untitled")
        self.book_dir.mkdir(parents=True, exist_ok=True)

    # ── 앱 상태 ──────────────────────────────────────────────
    def is_app_running(self) -> bool:
        try:
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {_EXE_NAME}"],
                                 capture_output=True, text=True, timeout=10)
            return _EXE_NAME.lower() in out.stdout.lower()
        except Exception:
            return False

    def has_app_window(self) -> bool:
        # win32 없이 정확한 창 판별은 어려움 — 실행 여부로 근사
        return self.is_app_running()

    # ── 앱 실행/책 열기 ──────────────────────────────────────
    def open_book_by_id(self, sale_cmdt_id: str) -> None:
        """Windows 교보 앱은 kyoboebook:// URL 스킴을 등록하지 않는다.
        os.startfile('kyoboebook://...') 하면 '이 프로토콜 열 앱을 MS Store에서 찾기'
        창이 뜨고 책도 안 열린다. → Windows 는 딥링크 미사용.
        책은 사용자가 교보 앱에서 직접 펼친다(아래 안내 참조).
        """
        print("[win] (안내) Windows 는 책 자동 열기 미지원 — "
              "교보 eLibrary 앱에서 분석할 책을 직접 펼쳐 두세요(1페이지·뷰어 전체화면).")

    def launch_app(self, deep_link_first: bool = True) -> bool:
        if not ensure_installed():
            print("[win] 앱 설치 안 됨 — 캡처 불가", file=sys.stderr)
            return False
        if self.is_app_running():
            print("[win] 앱 이미 실행 중")
            return True
        try:
            print(f"[win] 앱 실행: {KYOBO_WIN_EXE}")
            subprocess.Popen([KYOBO_WIN_EXE])
            time.sleep(8)  # fresh launch 로딩 대기
            return True
        except Exception as e:
            print(f"[win] 앱 실행 실패: {e}", file=sys.stderr)
            return False

    # ── 키 입력 (ctypes, 추가 의존성 없음) ───────────────────
    @staticmethod
    def _press_key(vk: int) -> None:
        import ctypes
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    # ── 캡처 루프 ────────────────────────────────────────────
    def take_multiple_screenshots(
        self, count: int = 300, interval: float = 1.5,
        auto_page_turn: bool = True, start_page: int = 1,
        continue_from_last: bool = False, use_ocr: bool = False,
        noninteractive: bool = True, region: dict | None = None,
        next_key: str = "right",
    ) -> int:
        """ImageGrab 으로 count 장 캡처. 직전과 동일 해시면 책 끝으로 보고 중단."""
        try:
            from PIL import ImageGrab
        except ImportError:
            print("[win] Pillow 미설치 — 캡처 불가 (pip install pillow)", file=sys.stderr)
            return 0

        bbox = None
        if region and region.get("w") and region.get("h"):
            # 절대 좌표 region 명시 시 그대로 사용(고급)
            x, y, w, h = region["x"], region["y"], region["w"], region["h"]
            bbox = (x, y, x + w, y + h)
            print(f"[win] 캡처 영역(region 지정): {bbox}")
        else:
            # 기본: 전체화면에서 교보 앱 크롬(상/하/좌/우) 크롭 → 책 본문만
            try:
                _full = ImageGrab.grab()
                W, H = _full.size
                c = _WIN_CROP
                bbox = (c["left"], c["top"], W - c["right"], H - c["bottom"])
                print(f"[win] 캡처 영역(크롬 크롭): {bbox}  "
                      f"(전체 {W}x{H}, 상{c['top']}/하{c['bottom']}/좌{c['left']}/우{c['right']} 제거)")
            except Exception as e:
                print(f"[win] 화면 크기 측정 실패 — 전체화면 캡처: {e}")
                bbox = None
        vk = _VK.get((next_key or "right").lower(), 0x27)

        # ── 시작 페이지로 처음/이어서 결정 ──────────────────────
        #   start_page == 1 → 처음부터(잔여 삭제, 새로 시작)
        #   start_page  > 1 → 이어서(기존 유지, 그 번호부터 — 앱을 그 페이지로 직접 이동한 전제)
        #   ※ Windows 앱은 페이지 자동 이동 API 가 없어 위치는 사용자가 직접 맞춰야 함.
        exts = ("*.png", "*.jpg", "*.jpeg", "*.webp")
        existing = sorted(p for g in exts for p in self.book_dir.glob(g))
        if start_page and start_page > 1:
            n = start_page
            print(f"[win] ▶ 이어서 캡처: page {n:03d} 부터 (기존 {len(existing)}장 유지). "
                  f"교보 앱이 {n} 페이지에 있어야 합니다.")
        else:
            n = 1
            removed = 0
            for p in existing:
                try: p.unlink(); removed += 1
                except Exception: pass
            tdir = self.book_dir / "thumbs"
            if tdir.exists():
                for p in tdir.glob("page_*.png"):
                    try: p.unlink()
                    except Exception: pass
            print(f"[win] ▶ 처음부터 캡처: page 001 부터 "
                  + (f"(기존 {removed}장 삭제 — 새로 시작)" if removed else "(기존 캡처 없음)"))

        print(f"[win] 캡처 시작 count={count} interval={interval}s "
              f"region={'전체화면' if not bbox else bbox} next_key={next_key}")
        last_hash = None
        saved = 0
        for i in range(count):
            try:
                img = ImageGrab.grab(bbox=bbox)
            except Exception as e:
                print(f"[win] 캡처 실패({i}): {e}", file=sys.stderr)
                break
            h = hashlib.md5(img.tobytes()).hexdigest()
            if h == last_hash:
                print(f"[win] 직전과 동일 화면 — 책 끝으로 보고 중단 (p.{n})")
                break
            last_hash = h
            dst = self.book_dir / f"page_{n:03d}.png"
            img.save(dst)
            saved += 1
            # worker 가 진행률 파싱: "[N/M] 캡처"
            print(f"[{i+1}/{count}] 캡처 중... → {dst.name}")
            n += 1
            if auto_page_turn:
                self._press_key(vk)
            time.sleep(interval)
        print(f"[win] 캡처 완료 — {saved}장 ({self.book_dir})")
        return saved
