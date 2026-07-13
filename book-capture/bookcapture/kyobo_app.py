#!/usr/bin/env python3
"""
교보문고 ebook 앱 스크린샷 자동화 스크립트 (macOS/Windows)
"""

import subprocess
import time
import os
import sys
import re
import unicodedata
from pathlib import Path
from datetime import datetime
import platform

try:
    from PIL import Image
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False
    print("⚠️  OCR 기능을 사용하려면 Pillow와 pytesseract를 설치하세요.")


class KyoboAppScreenshot:
    def __init__(self, output_dir="kyobo_app_screenshots", book_folder=None):
        """
        Args:
            output_dir: 스크린샷을 저장할 기본 디렉토리
            book_folder: 도서별 하위 폴더명 (없으면 output_dir에 바로 저장)
        """
        self.base_output_dir = Path(output_dir)
        self.base_output_dir.mkdir(exist_ok=True)

        if book_folder:
            self.output_dir = self.base_output_dir / book_folder
            self.output_dir.mkdir(exist_ok=True)
        else:
            self.output_dir = self.base_output_dir

        self.system = platform.system()

    # 교보eBook deep link URL scheme (Info.plist 의 CFBundleURLSchemes 에서 확인)
    KYOBO_URL_SCHEME = "kyoboebook"
    KYOBO_BUNDLE_ID = "kr.co.kyobobook.iPadB2C"

    def is_app_running(self):
        """교보eBook 앱 본체가 실행 중인지 확인.
        Notifications helper(.appex) 만으로는 False 반환 — 본체 필수.
        """
        if self.system == "Darwin":  # macOS
            try:
                # pgrep -fl 로 전체 명령행 확인, Notifications 제외
                result = subprocess.run(
                    ["pgrep", "-fl", "iPadB2C"],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    return False
                lines = [l for l in (result.stdout or '').strip().split('\n') if l]
                main_only = [l for l in lines if 'Notifications' not in l and 'PlugIns' not in l]
                return len(main_only) > 0
            except Exception:
                return False
        elif self.system == "Windows":
            try:
                result = subprocess.run(
                    ["tasklist"],
                    capture_output=True,
                    text=True
                )
                return "교보eBook" in result.stdout or "KyoboEbook" in result.stdout
            except Exception:
                return False
        return False

    def has_app_window(self):
        """교보eBook 의 사용 가능한 큰 창이 있는지 확인 (Quartz).
        본체는 떠있지만 창이 hide 된 상태도 False 반환.
        """
        return self._find_kyobo_window_id() is not None

    def open_deep_link(self, url):
        """Deep link 호출 (`kyoboebook://...`).
        창 hide 상태에서 새 창 띄우거나 책 열기 시도.
        Returns: True 호출 성공 (앱 응답 여부는 별도).
        """
        if self.system != "Darwin":
            return False
        try:
            subprocess.run(["open", url], check=False, timeout=5)
            return True
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def open_book_by_id(self, sale_cmdt_id):
        """salecmdtid 로 책 자동 열기 (Deep link 패턴 best-effort).
        교보eBook 앱이 책 deep link 받으면 그 책 viewer 열림.
        URL 패턴은 교보가 내부 정의 — 흔한 후보 순차 시도.
        Returns: True 호출했음 (성공 보장 X), False 아예 못 시도.
        """
        if self.system != "Darwin" or not sale_cmdt_id:
            return False
        # 흔한 deep link URL 패턴 후보 — 가장 표준적인 것부터
        candidates = [
            f"{self.KYOBO_URL_SCHEME}://book/{sale_cmdt_id}",
            f"{self.KYOBO_URL_SCHEME}://open/{sale_cmdt_id}",
            f"{self.KYOBO_URL_SCHEME}://view/{sale_cmdt_id}",
            f"{self.KYOBO_URL_SCHEME}://ebook/{sale_cmdt_id}",
            f"{self.KYOBO_URL_SCHEME}://detail/{sale_cmdt_id}",
        ]
        for url in candidates:
            self.open_deep_link(url)
            time.sleep(1.5)
            if self.has_app_window():
                print(f"   ✓ Deep link 책 열기 성공: {url}")
                return True
        # 후보 모두 실패 — 단순 앱 activate 라도
        self.open_deep_link(f"{self.KYOBO_URL_SCHEME}://")
        return False

    def launch_app(self, deep_link_first=True):
        """교보eBook 앱 launch + activate.
        Quartz CGWindowList 의 창 확인은 best-effort (System Events 와 불일치 가능).
        무조건 True 반환 — 진짜 캡처 실패는 capture_app_window 의 폴백으로 처리.
        """
        if self.system == "Darwin":  # macOS
            # 본체 + 큰 창 다 있으면 deep link / open -a 안 함
            if self.is_app_running() and self.has_app_window():
                print("✓ 교보eBook 앱이 정상 실행 중 (창 있음)")
                return True

            print("📱 교보eBook 앱 실행 / activate 시도...")

            # Deep link (창 hide 복구 효과 있을 수 있음)
            if deep_link_first:
                self.open_deep_link(f"{self.KYOBO_URL_SCHEME}://")
                time.sleep(2)

            # open -a (이미 떠있으면 activate, 아니면 launch)
            app_path = "/Applications/교보eBook.app"
            if os.path.exists(app_path):
                subprocess.run(["open", app_path], check=False)
                # 짧은 대기 — fresh launch 면 7초, 이미 떠있으면 즉시 OK
                wait_s = 7 if not self.is_app_running() else 2
                print(f"✓ open -a 호출 — {wait_s}초 대기")
                time.sleep(wait_s)
            else:
                print(f"⚠ 앱 경로 없음: {app_path}")

            # 창 확인은 안내용 (실패해도 진행)
            if self.has_app_window():
                print("✓ 창 확보 (Quartz 확인됨)")
            else:
                print("ℹ Quartz 창 확인 X — capture_app_window 가 폴백 캡처로 진행")
            return True  # 무조건 진행 (창 hide 정책 우회)

        elif self.system == "Windows":
            # Windows의 일반적인 설치 경로들
            possible_paths = [
                r"C:\Program Files\Kyobobook\교보eBook.exe",
                r"C:\Program Files (x86)\Kyobobook\교보eBook.exe",
                os.path.expanduser(r"~\AppData\Local\Kyobobook\교보eBook.exe"),
            ]

            app_found = False
            for path in possible_paths:
                if os.path.exists(path):
                    subprocess.Popen([path])
                    app_found = True
                    print(f"✓ 앱 실행 완료 (Windows): {path}")
                    break

            if not app_found:
                print("❌ 앱을 찾을 수 없습니다. 수동으로 경로를 지정해주세요.")
                return False
        else:
            print(f"❌ 지원하지 않는 운영체제입니다: {self.system}")
            return False

        return True

    def take_screenshot(self, custom_name=None, wait_time=5):
        """
        화면 스크린샷 캡처

        Args:
            custom_name: 커스텀 파일명 (없으면 자동 생성)
            wait_time: 앱 실행 후 대기 시간(초)

        Returns:
            저장된 파일 경로
        """
        # 앱 실행
        if not self.launch_app():
            return None

        # 앱이 완전히 로딩될 때까지 대기
        print(f"⏳ {wait_time}초 대기 중... (앱 로딩)")
        time.sleep(wait_time)

        # 파일명 생성
        if custom_name:
            filename = f"{custom_name}.png"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"kyobo_app_{timestamp}.png"

        filepath = self.output_dir / filename

        try:
            if self.system == "Darwin":  # macOS
                # macOS screencapture 명령 사용
                subprocess.run([
                    "screencapture",
                    "-x",  # 소리 끄기
                    str(filepath)
                ], check=True)
                print(f"📸 스크린샷 저장: {filepath}")

            elif self.system == "Windows":
                # Windows에서는 pyautogui 필요
                try:
                    import pyautogui
                    screenshot = pyautogui.screenshot()
                    screenshot.save(filepath)
                    print(f"📸 스크린샷 저장: {filepath}")
                except ImportError:
                    print("❌ pyautogui가 필요합니다: pip install pyautogui")
                    return None

            return filepath

        except Exception as e:
            print(f"❌ 스크린샷 캡처 실패: {e}")
            return None

    def take_window_screenshot(self, custom_name=None, wait_time=5, interactive=True):
        """
        특정 윈도우만 캡처 (macOS만 지원)

        Args:
            custom_name: 커스텀 파일명
            wait_time: 앱 실행 후 대기 시간(초)
            interactive: True면 사용자가 윈도우를 선택, False면 자동

        Returns:
            저장된 파일 경로
        """
        if self.system != "Darwin":
            print("⚠️  윈도우 캡처는 macOS에서만 지원됩니다.")
            return self.take_screenshot(custom_name, wait_time)

        # 앱 실행
        if not self.launch_app():
            return None

        print(f"⏳ {wait_time}초 대기 중... (앱 로딩)")
        time.sleep(wait_time)

        # 파일명 생성
        if custom_name:
            filename = f"{custom_name}.png"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"kyobo_window_{timestamp}.png"

        filepath = self.output_dir / filename

        try:
            if interactive:
                print("👆 캡처할 윈도우를 클릭하세요...")
                # -w: 윈도우 선택 모드
                subprocess.run([
                    "screencapture",
                    "-x",  # 소리 끄기
                    "-w",  # 윈도우 선택
                    str(filepath)
                ], check=True)
            else:
                # -o: 그림자 제거
                subprocess.run([
                    "screencapture",
                    "-x",
                    "-o",
                    str(filepath)
                ], check=True)

            print(f"📸 스크린샷 저장: {filepath}")
            return filepath

        except Exception as e:
            print(f"❌ 스크린샷 캡처 실패: {e}")
            return None

    def press_key(self, key_code):
        """
        키보드 이벤트 전송 (페이지 넘기기용)

        Args:
            key_code: 키 코드 (예: 124=오른쪽 화살표, 125=왼쪽 화살표)
        """
        if self.system == "Darwin":  # macOS
            # AppleScript를 사용하여 키 입력
            script = f'''
            tell application "System Events"
                key code {key_code}
            end tell
            '''
            subprocess.run(["osascript", "-e", script], check=True)
        elif self.system == "Windows":
            try:
                import pyautogui
                if key_code == 124:  # 오른쪽 화살표
                    pyautogui.press('right')
                elif key_code == 123:  # 왼쪽 화살표
                    pyautogui.press('left')
            except ImportError:
                print("⚠️  pyautogui가 필요합니다: pip install pyautogui")

    def set_focus_mode(self, on: bool) -> bool:
        """캡처 중 집중모드(방해금지) 켜기/끄기 — 알림 배너·포커스 뺏김 원천 차단(싱글 모니터 대비).
        macOS 최신(Sequoia)은 DND 를 CLI 로 직접 못 켜므로 **Shortcuts** 를 쓴다.
        단축어 이름: 환경변수 KYOBO_FOCUS_ON/OFF, 기본 'KyoboFocusOn'/'KyoboFocusOff'.
        단축어가 없으면 조용히 skip(캡처는 WID occlusion-safe 라 알림 안 찍힘 — 집중모드는 보너스).
        반환: 성공 여부."""
        if self.system != "Darwin":
            return False
        import os as _os
        name = _os.environ.get("KYOBO_FOCUS_ON" if on else "KYOBO_FOCUS_OFF",
                               "KyoboFocusOn" if on else "KyoboFocusOff")
        try:
            r = subprocess.run(["shortcuts", "run", name], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                print(f"🌙 집중모드 {'ON' if on else 'OFF'} (shortcut '{name}')")
                return True
            # 단축어 없음 등 — 조용히 skip
            print(f"ℹ 집중모드 단축어 '{name}' 없음/실패 → 생략(WID 캡처는 알림 무관). "
                  f"자동 원하면 Shortcuts 앱에 '{name}' 생성.")
        except Exception:
            pass
        return False

    def activate_app(self):
        """교보eBook 앱 활성화 (포커스).
        iPadB2C 프로세스가 없어도 crash 하지 않고 silent fail.
        """
        if self.system == "Darwin":
            script = '''
            tell application "System Events"
                set procs to (every application process whose name contains "iPadB2C")
                if (count of procs) > 0 then
                    set frontmost of item 1 of procs to true
                end if
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", script],
                               check=False, timeout=5,
                               capture_output=True)
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.5)

    def get_current_book_title(self):
        """교보문고 앱에서 현재 열린 도서명 추출 (macOS만 지원)"""
        if self.system != "Darwin":
            print("⚠️  도서명 자동 추출은 macOS에서만 지원됩니다.")
            return None

        try:
            # AppleScript로 윈도우 타이틀 가져오기
            script = '''
            tell application "System Events"
                set appName to name of first application process whose name contains "iPadB2C"
                tell application process appName
                    if (count of windows) > 0 then
                        return name of window 1
                    else
                        return ""
                    end if
                end tell
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=True
            )
            title = result.stdout.strip()

            if title:
                # "교보eBook" 또는 "eBook"만 있으면 도서가 열려있지 않은 것
                if title in ["교보eBook", "eBook", "Kyobo eBook"]:
                    return None

                # "교보eBook - " 같은 접두사 제거
                title = re.sub(r'^교보eBook\s*-\s*', '', title)
                title = re.sub(r'^eBook\s*-\s*', '', title)
                title = re.sub(r'^Kyobo eBook\s*-\s*', '', title)

                # 빈 문자열이면 None 반환
                if not title.strip():
                    return None

                # 파일명으로 사용할 수 없는 문자 제거
                title = re.sub(r'[<>:"/\\|?*]', '_', title)
                return title.strip()

            return None

        except Exception as e:
            print(f"⚠️  도서명 추출 실패: {e}")
            return None

    def is_fullscreen(self):
        """교보문고 앱이 전체 화면 모드인지 확인 (macOS만 지원)"""
        if self.system != "Darwin":
            return True  # Windows는 체크 안 함

        try:
            script = '''
            tell application "System Events"
                set appName to name of first application process whose name contains "iPadB2C"
                tell application process appName
                    if (count of windows) > 0 then
                        get value of attribute "AXFullScreen" of window 1
                    else
                        return false
                    end if
                end tell
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip() == "true"

        except Exception as e:
            print(f"⚠️  전체 화면 상태 확인 실패: {e}")
            return False

    def set_fullscreen(self, enable=True):
        """교보문고 앱을 전체 화면 모드로 설정 (macOS만 지원)"""
        if self.system != "Darwin":
            print("⚠️  전체 화면 전환은 macOS에서만 지원됩니다.")
            return False

        try:
            value = "true" if enable else "false"
            script = f'''
            tell application "System Events"
                set appName to name of first application process whose name contains "iPadB2C"
                tell application process appName
                    if (count of windows) > 0 then
                        set value of attribute "AXFullScreen" of window 1 to {value}
                    end if
                end tell
            end tell
            '''
            subprocess.run(["osascript", "-e", script], check=True)
            time.sleep(1)  # 전체 화면 전환 대기
            return True

        except Exception as e:
            print(f"⚠️  전체 화면 전환 실패: {e}")
            return False

    def get_last_page_number(self, folder_path=None):
        """지정된 폴더에서 마지막 페이지 번호 찾기

        Args:
            folder_path: 검색할 폴더 경로 (기본값: self.output_dir)

        Returns:
            마지막 페이지 번호 (없으면 0)
        """
        if folder_path is None:
            folder_path = self.output_dir

        folder_path = Path(folder_path)
        if not folder_path.exists():
            return 0

        max_page = 0
        # 폴더 내 모든 PNG 파일 검색
        for file in folder_path.glob("*.png"):
            # 파일명에서 숫자 패턴 찾기 (예: page_001.png, 책이름_042.png)
            numbers = re.findall(r'_(\d{3,4})(?:_|\.|$)', file.stem)
            if numbers:
                # 가장 큰 숫자를 페이지 번호로 간주
                page_num = max([int(n) for n in numbers])
                max_page = max(max_page, page_num)

        return max_page

    def get_existing_page_numbers(self, folder_path=None):
        """폴더 내 모든 페이지 번호 리스트 반환

        Args:
            folder_path: 검색할 폴더 경로 (기본값: self.output_dir)

        Returns:
            페이지 번호 set
        """
        if folder_path is None:
            folder_path = self.output_dir

        folder_path = Path(folder_path)
        if not folder_path.exists():
            return set()

        page_numbers = set()
        for file in folder_path.glob("*.png"):
            numbers = re.findall(r'_(\d{3,4})(?:_|\.|$)', file.stem)
            if numbers:
                for n in numbers:
                    page_numbers.add(int(n))

        return page_numbers

    def extract_page_number_from_image(self, image_path):
        """이미지의 하단에서 페이지 정보를 OCR로 추출

        Args:
            image_path: 스크린샷 이미지 경로

        Returns:
            페이지 번호 (int) 또는 None
        """
        if not HAS_OCR:
            return None

        try:
            # 이미지 열기
            img = Image.open(image_path)
            width, height = img.size

            # 전체 하단 영역 crop (하단 10%)
            # 페이지 정보는 중앙 하단에 위치
            left = 0
            top = int(height * 0.90)
            right = width
            bottom = height

            bottom_region = img.crop((left, top, right, bottom))

            # OCR 수행 (한글+영어+숫자)
            text = pytesseract.image_to_string(
                bottom_region,
                lang='kor+eng',
                config='--psm 6'
            )

            # 페이지 정보 파싱
            page_num = self.parse_page_info(text)

            if page_num:
                print(f"   📄 OCR 텍스트: {text.strip()[:80]}...")
                print(f"   ✓ 추출된 페이지 번호: {page_num}")

            return page_num

        except Exception as e:
            print(f"   ⚠️  OCR 실패: {e}")
            return None

    def parse_page_info(self, text):
        """OCR 텍스트에서 페이지 번호 추출

        Args:
            text: OCR로 추출한 텍스트

        Returns:
            페이지 번호 (int) 또는 None

        예시:
            '49%(251/508p)' → 251
            '20%(102/508p)' → 102
        """
        # 패턴: 숫자%(숫자/숫자p)
        pattern = r'(\d+)%.*?(\d+)/(\d+)p'
        match = re.search(pattern, text)

        if match:
            current_page = int(match.group(2))
            total_pages = int(match.group(3))
            print(f"   📖 현재: {current_page}p / 전체: {total_pages}p")
            return current_page

        # 대체 패턴: 숫자/숫자p 만
        pattern2 = r'(\d+)/(\d+)p'
        match2 = re.search(pattern2, text)

        if match2:
            current_page = int(match2.group(1))
            return current_page

        return None

    def _is_kyobo_frontmost(self):
        """교보 앱이 최전면(frontmost)인지 — -R 영역 캡처 오염(터미널 등) 방지 게이트."""
        if self.system != "Darwin":
            return False
        try:
            r = subprocess.run([
                "osascript", "-e",
                'tell application "System Events" to name of first application process whose frontmost is true',
            ], capture_output=True, text=True, timeout=3)
            name = unicodedata.normalize("NFC", (r.stdout or "").strip())
            return "교보" in name or "iPadB2C" in name or "kyobo" in name.lower()
        except Exception:
            return False

    def _find_kyobo_window_id(self, retries=3, retry_delay=0.7, debug=False):
        """Quartz CGWindowList 로 교보eBook 메인 창의 WindowID 찾기.
        frontmost / 디스플레이 / Space 무관. retry + 2-tier fallback.
        Returns: int WID, 또는 못 찾으면 None.
        """
        if self.system != "Darwin":
            return None
        try:
            import Quartz  # type: ignore
        except ImportError:
            return None

        # macOS OnScreenOnly 옵션이 onScreen=True 인 창을 가끔 누락하는 버그/이슈가 있음
        # → 1차 OnScreenOnly (정확) → 2차 OptionAll + onScreen 필드 필터 (확실한 우회)
        opt_passes = [
            ('OnScreenOnly',
             Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
             False),  # 추가 onScreen 필터 X (OnScreenOnly 가 이미 함)
            ('OptionAll',
             Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements,
             True),   # onScreen=True 필드 명시 필터 (stale 캐시 제외)
        ]
        for pass_label, opts, require_onscreen in opt_passes:
            for attempt in range(retries):
                cands = []
                for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID):
                    # ⚠️ 교보eBook(iPad앱)의 owner 이름은 NFD(분해형 자모)로 온다 → NFC 정규화 안 하면
                    #    리터럴 '교보'(NFC)와 substring 매칭 실패해서 창을 영영 못 찾음(2026-07-13 근본원인).
                    owner = unicodedata.normalize('NFC', w.get('kCGWindowOwnerName', '') or '')
                    if '교보' not in owner and 'iPadB2C' not in owner:
                        continue
                    if w.get('kCGWindowLayer', 99) != 0:
                        continue
                    if require_onscreen and not w.get('kCGWindowIsOnscreen', False):
                        continue
                    b = w.get('kCGWindowBounds', {})
                    if int(b.get('Width', 0)) < 800 or int(b.get('Height', 0)) < 500:
                        continue
                    cands.append(w)
                if debug:
                    print(f"   [DEBUG] pass={pass_label} attempt={attempt+1} cands={len(cands)}")
                if cands:
                    main = max(cands,
                               key=lambda x: x['kCGWindowBounds']['Width']
                                             * x['kCGWindowBounds']['Height'])
                    return int(main['kCGWindowNumber'])
                if attempt < retries - 1:
                    time.sleep(retry_delay)
        return None

    def _get_bounds_via_system_events(self):
        """System Events 로 교보eBook 창 좌표 가져옴.
        Quartz CGWindowList 가 못 잡을 때 폴백 (실제 검증: System Events 는 잡음).
        Returns: (x, y, w, h) 또는 None.
        """
        if self.system != "Darwin":
            return None
        script = '''
        tell application "System Events"
            try
                set p to first process whose name contains "iPadB2C"
                if (count of windows of p) > 0 then
                    set pos to position of window 1 of p
                    set sz to size of window 1 of p
                    return ((item 1 of pos) as string) & "," & ((item 2 of pos) as string) & "," & ((item 1 of sz) as string) & "," & ((item 2 of sz) as string)
                end if
            end try
            return ""
        end tell
        '''
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True, text=True, timeout=5,
            )
            out = (result.stdout or '').strip()
            if out and ',' in out:
                parts = out.split(',')
                if len(parts) == 4:
                    x, y, w, h = (int(p) for p in parts)
                    if w >= 500 and h >= 300:  # 의미 있는 크기
                        return x, y, w, h
        except Exception:
            pass
        return None

    def _find_kyobo_window_bounds(self):
        """Quartz 로 교보eBook 창의 좌표 (x, y, w, h) 반환.
        screencapture -R 영역 캡처 폴백 용도. 못 찾으면 None.
        """
        if self.system != "Darwin":
            return None
        try:
            import Quartz  # type: ignore
        except ImportError:
            return None
        opts = (Quartz.kCGWindowListOptionAll
                | Quartz.kCGWindowListExcludeDesktopElements)
        cands = []
        for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID):
            owner = unicodedata.normalize('NFC', w.get('kCGWindowOwnerName', '') or '')  # NFD→NFC (교보 자모)
            if '교보' not in owner and 'iPadB2C' not in owner:
                continue
            if w.get('kCGWindowLayer', 99) != 0:
                continue
            b = w.get('kCGWindowBounds', {})
            if int(b.get('Width', 0)) < 800 or int(b.get('Height', 0)) < 500:
                continue
            cands.append(w)
        if not cands:
            return None
        main = max(cands,
                   key=lambda x: x['kCGWindowBounds']['Width']
                                 * x['kCGWindowBounds']['Height'])
        b = main['kCGWindowBounds']
        return int(b['X']), int(b['Y']), int(b['Width']), int(b['Height'])

    def _finalize_page(self, page_path):
        """확정된 page_NNN.png(raw)를 표준 정규화: (1) source_raws/raw_NNN.png 원본 보존,
        (2) page_crop.crop_page(chrome=20,20,20,20) content-aware 크롭(헤더 안 잘림·크롬 제거).
        ⚠️ **페이지 번호 확정(rename) 후** 호출해야 raw_NNN 이 올바르게 붙는다(temp 이름이면 오번호).
        실패해도 원본 유지(캡처 자체는 성공)."""
        try:
            import re
            import shutil
            from PIL import Image
            from . import page_crop
            fp = Path(page_path)
            m = re.search(r"(\d+)", fp.stem)
            raws = fp.parent / "source_raws"
            raws.mkdir(exist_ok=True)
            if m:
                shutil.copy2(fp, raws / f"raw_{int(m.group(1)):03d}.png")
            cropped = page_crop.crop_page(Image.open(fp), chrome=(20, 20, 20, 20))
            cropped.save(fp)
        except Exception as e:
            print(f"⚠ 크롭 후처리 실패(원본 유지): {e}")

    def capture_app_window(self, filepath):
        """교보eBook 앱 창만 캡처 (Quartz WID + screencapture -l).
        외장 모니터·다른 Space 도 OK. frontmost 무관.
        캡처 성공 시 _postprocess_capture 로 raw 보존 + 표준 크롭.
        """
        if self.system == "Darwin":
            self._last_capture_method = None
            # ⭐ WID(-l) 를 **우선 3회** 시도 — WID 캡처는 occlusion-safe(창 내용만, 알림·다른 창 제외)라
            #    항상 깨끗하다. 교보 최전면이면 성공. -R 영역 폴백은 알림/터미널 오염 위험이라 **최후에 1회만**.
            #    (2026-07-13: -R 로 18~25p 에 알림·터미널 섞임 → WID 우선으로 오염 최소화.)
            for attempt in range(3):
                self.activate_app()
                time.sleep(0.6 if attempt == 0 else 1.1)  # 재시도일수록 백킹 안정 대기 ↑
                wid = self._find_kyobo_window_id(retries=1)
                if wid:
                    try:
                        subprocess.run([
                            "/usr/sbin/screencapture", "-l", str(wid),
                            "-x", "-o", "-t", "png", str(filepath),
                        ], check=True)
                        if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                            self._last_capture_method = "wid"  # 깨끗(occlusion-safe)
                            return True  # raw 반환 — 크롭/raw보존은 _finalize_page 에서
                    except subprocess.CalledProcessError as e:
                        print(f"⚠️  WID({wid}) 캡처 실패: {e}")

            # WID 3회 실패 → **최후 1회** 영역(-R). ⚠️ **교보가 최전면일 때만** — 아니면 그 화면 좌표엔
            # 다른 창(터미널·알림)이 있어 오염됨(page_369 사고). 최전면 아니면 -R 생략(오염 방지).
            if self._is_kyobo_frontmost():
                bounds = self._find_kyobo_window_bounds() or self._get_bounds_via_system_events()
                if bounds:
                    x, y, w, h = bounds
                    TITLE_BAR_H = 28  # macOS 타이틀바 자동 크롭
                    if h > TITLE_BAR_H + 200:
                        y += TITLE_BAR_H; h -= TITLE_BAR_H
                    try:
                        subprocess.run([
                            "/usr/sbin/screencapture", "-R", f"{x},{y},{w},{h}",
                            "-x", "-t", "png", str(filepath),
                        ], check=True)
                        if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                            self._last_capture_method = "region"  # ⚠ 오염 가능(알림/오버레이) → 인라인 QC 확인
                            return True
                    except subprocess.CalledProcessError as e:
                        print(f"⚠️  영역 캡처 실패: {e}")
            else:
                print("   ⚠ 교보가 최전면 아님 → -R 영역 캡처 생략(터미널 등 오염 방지)")

            print("⛔ 교보 창 특정 실패(WID 3회·영역) → 이 페이지 건너뜀. "
                  "교보 앱을 '창 모드(비-전체화면)'로 **최전면 유지**하세요.")
            return False
        else:
            # Windows
            try:
                import pyautogui
                screenshot = pyautogui.screenshot()
                screenshot.save(filepath)
                return True
            except ImportError:
                print("❌ pyautogui가 필요합니다: pip install pyautogui")
                return False

    def take_multiple_screenshots(self, count=1, interval=3, custom_prefix=None,
                                  auto_page_turn=True, start_page=1, continue_from_last=False,
                                  use_ocr=True, noninteractive=False, contam_check=None):
        """
        여러 장의 스크린샷을 간격을 두고 캡처 (자동 페이지 넘김 포함)

        Args:
            count: 캡처할 개수
            interval: 캡처 간격(초)
            custom_prefix: 파일명 접두사
            auto_page_turn: True면 자동으로 페이지 넘김
            start_page: 시작 페이지 번호
            continue_from_last: True면 폴더의 마지막 페이지 다음부터 계속
            use_ocr: True면 OCR로 실제 페이지 번호를 추출하여 파일명 지정
            noninteractive: True면 input() 프롬프트 모두 스킵 (worker 호출용)

        Returns:
            저장된 파일 경로 리스트
        """
        # 앱 실행 확인
        if not self.launch_app():
            return []

        # OCR 사용 가능 여부 확인
        if use_ocr and not HAS_OCR:
            print("⚠️  OCR 라이브러리가 설치되지 않아 OCR 기능을 사용할 수 없습니다.")
            print("   파일명은 순차 번호로 지정됩니다.")
            use_ocr = False

        # 기존 페이지 번호 확인 (중복 체크용)
        existing_pages = self.get_existing_page_numbers() if use_ocr else set()

        # 이전 파일 이어서 저장하기
        if continue_from_last:
            last_page = self.get_last_page_number()
            if last_page > 0:
                start_page = last_page + 1
                print(f"📄 이전 캡처의 마지막 페이지: {last_page}")
                print(f"📄 {start_page}페이지부터 캡처를 시작합니다.")

        # 사용자가 도서를 열고 준비할 시간 제공
        if auto_page_turn:
            print("\n" + "=" * 60)
            print("⚠️  중요: 교보문고 앱에서 캡처할 도서를 열어주세요!")
            print("=" * 60)

            if use_ocr:
                print("📖 OCR 모드: 캡처 후 자동으로 페이지 번호를 추출합니다.")
                print("   전체 화면 모드에서 좌하단 페이지 정보가 보여야 합니다!")

            if noninteractive:
                # 권한 다이얼로그 / 알림 등 floating UI 닫을 시간 충분히 확보
                print("📚 비대화형 모드: 10초 후 캡처 시작 — 권한 다이얼로그/알림 다 닫으세요")
                for i in range(10, 0, -1):
                    print(f"   ⏳ {i}초 남음...", end='\r', flush=True)
                    time.sleep(1)
                print("                                       ")  # 한 줄 비우기
            else:
                input(f"📚 도서를 열고 시작 페이지로 이동한 후 엔터를 누르세요...")
            print("\n⏳ 앱을 활성화하는 중...")

            # 앱 활성화
            self.activate_app()
            time.sleep(1)

            # 전체 화면 확인 — Phase #68 (WID 캡처) 이후엔 fullscreen 불필요·역효과
            # (fullscreen 시 Quartz CGWindowList 에서 일반 창 목록 빠짐 → 검색 실패)
            if not self.is_fullscreen():
                if use_ocr:
                    print("ℹ️  OCR 사용 — 좌하단 페이지 정보가 보이는 큰 창 상태 권장")
                else:
                    print("ℹ️  창 상태로 진행 (WID 캡처는 창 영역만 정밀 캡처)")
            else:
                print("ℹ️  fullscreen 모드 — WID 캡처 안 잡힐 수 있음 → ESC 로 일반 창 모드 권장")

            print("\n⏳ 3초 후 캡처를 시작합니다...")
            time.sleep(3)
        else:
            print(f"⏳ 앱 로딩 대기 중...")
            time.sleep(5)

        results = []
        duplicates = []
        prev_sig = None  # 직전 raw 이미지 축소본(마지막 페이지 perceptual 감지용)
        self.set_focus_mode(True)  # 🌙 캡처 동안 집중모드 ON(알림·포커스 뺏김 차단) — finally 에서 OFF

      # (아래 for 는 try 로 감싸 finally 에서 집중모드 해제)
        try:
         for i in range(count):
            fallback_page = start_page + i
            print(f"\n[{i+1}/{count}] 캡처 중...")

            # 임시 파일명으로 먼저 저장
            temp_filename = f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            temp_filepath = self.output_dir / temp_filename

            try:
                # 앱 윈도우만 캡처
                if not self.capture_app_window(str(temp_filepath)):
                    print(f"❌ 캡처 실패")
                    results.append(None)
                    continue

                print(f"📸 임시 저장: {temp_filepath.name}")

                # 🧹 오염 인라인 재캡처: WID(-l) 캡처는 occlusion-safe(깨끗)라 스킵, **영역(-R)만** 검사.
                #    오염(커서·알림·비책)이면 같은 페이지 재활성화+재캡처(최대 2회). 재캡처가 WID 로 성공하면 깨끗.
                #    사용자 요청(2026-07-13): 오염 시 삭제만 말고 그 자리에서 다시 시도.
                if contam_check is not None and getattr(self, "_last_capture_method", None) == "region":
                    bad, reasons = contam_check(str(temp_filepath))
                    tries = 0
                    while bad and tries < 2:
                        print(f"   🧹 오염 감지({reasons}, -R) → 같은 페이지 재캡처 {tries + 1}/2")
                        self.activate_app(); time.sleep(1.0)
                        if not self.capture_app_window(str(temp_filepath)):
                            break
                        if getattr(self, "_last_capture_method", None) == "wid":
                            bad = False; break  # WID 로 재캡처 성공 = 깨끗
                        bad, reasons = contam_check(str(temp_filepath))
                        tries += 1
                    if bad:
                        print(f"   ⚠ 재캡처 후에도 오염({reasons}) → 이 페이지 스킵(배치 QC 가 최종 정리)")
                        temp_filepath.unlink(missing_ok=True)
                        results.append(None)
                        if i < count - 1 and auto_page_turn:
                            self.press_key(124); time.sleep(interval)
                        continue

                # 🔚 마지막 페이지 감지 (OCR 무관, perceptual): 직전 캡처와 **거의 동일**하면
                #    →키가 안 먹힌 것 = 책 끝. 축소 grayscale MAD 로 비교(같은 페이지=0, 다른 페이지≥9 검증).
                #    옛 방식(OCR 페이지번호 중복)은 OCR 깨지는 책에서 순차번호가 늘 unique 라 끝을 못 잡고
                #    무한 캡처했음(2026-07-13 근본원인). 정확한 exact-hash 도 프레임 미세차로 매번 달라 부적합.
                cur_sig = None
                try:
                    from PIL import Image as _I, ImageChops as _IC
                    cur_sig = _I.open(temp_filepath).convert("L").resize((100, 100))
                except Exception:
                    cur_sig = None
                def _mad_vs_prev(sig):
                    return sum(_i * _n for _i, _n in enumerate(
                        _IC.difference(sig, prev_sig).histogram())) / 10000.0
                if cur_sig is not None and prev_sig is not None:
                    _mad = _mad_vs_prev(cur_sig)
                    if _mad < 4.0:
                        # 같은 페이지 = →키가 **일시적으로 안 먹혔을** 수도, **진짜 책 끝**일 수도.
                        # 오탐(242p 조기종료) 방지: →키 재전송+재캡처로 확인. 바뀌면 계속, 계속 같으면 끝.
                        confirmed_end = True
                        for _rt in range(3):
                            print(f"   … 같은 페이지(MAD={_mad:.1f}) — →키 재전송 후 확인 {_rt + 1}/3")
                            self.activate_app(); self.press_key(124); time.sleep(max(interval, 1.5))
                            if not self.capture_app_window(str(temp_filepath)):
                                continue
                            try:
                                re_sig = _I.open(temp_filepath).convert("L").resize((100, 100))
                            except Exception:
                                continue
                            _mad = _mad_vs_prev(re_sig)
                            if _mad >= 4.0:          # 페이지가 바뀜 → 일시적 미스였음, 계속 진행
                                print(f"   ▶ 페이지 넘어감(MAD={_mad:.1f}) — 일시적 →키 미스, 계속")
                                cur_sig = re_sig
                                confirmed_end = False
                                break
                        if confirmed_end:
                            print(f"   🔚 →키 3회 재전송에도 동일 → 책 끝 확정, 종료 "
                                  f"(수집 {len([r for r in results if r])}장)")
                            temp_filepath.unlink(missing_ok=True)
                            break
                prev_sig = cur_sig

                # OCR로 페이지 번호 추출
                actual_page_num = None
                if use_ocr:
                    print(f"   🔍 OCR 처리 중...")
                    actual_page_num = self.extract_page_number_from_image(temp_filepath)

                # 최종 파일명 결정
                if actual_page_num:
                    # OCR 성공
                    final_page_num = actual_page_num

                    # 중복 체크
                    if final_page_num in existing_pages:
                        print(f"   ⚠️  경고: 페이지 {final_page_num}는 이미 캡처되었습니다!")
                        duplicates.append(final_page_num)
                else:
                    # OCR 실패 또는 미사용 시 순차 번호
                    final_page_num = fallback_page
                    if not use_ocr:
                        print(f"   ✓ 순차 페이지 번호: {final_page_num}")
                    else:
                        print(f"   ⚠️  OCR 실패, 순차 번호 사용: {final_page_num}")

                # 최종 파일명 생성
                if custom_prefix:
                    final_filename = f"{custom_prefix}_{final_page_num:03d}.png"
                else:
                    final_filename = f"page_{final_page_num:03d}.png"

                final_filepath = self.output_dir / final_filename

                # 파일명 변경 (raw 상태) → raw 보존 + 표준 크롭 (페이지번호 확정 후라 raw_NNN 정확)
                temp_filepath.rename(final_filepath)
                self._finalize_page(final_filepath)
                print(f"   ✅ 최종 저장: {final_filepath.name}")

                # 기존 페이지 목록에 추가
                existing_pages.add(final_page_num)
                results.append(final_filepath)

            except Exception as e:
                print(f"❌ 캡처 실패: {e}")
                # 임시 파일 정리
                if temp_filepath.exists():
                    temp_filepath.unlink()
                results.append(None)

            # 다음 캡처 전 페이지 넘김 및 대기
            if i < count - 1:
                if auto_page_turn:
                    print(f"📄 다음 페이지로 이동...")
                    self.press_key(124)  # 오른쪽 화살표 (다음 페이지)
                print(f"⏳ {interval}초 대기 중...")
                time.sleep(interval)
        finally:
            self.set_focus_mode(False)  # 🌙 캡처 종료(정상/오류 무관) → 집중모드 해제

        # 결과 요약
        success_count = len([r for r in results if r])
        print(f"\n{'=' * 60}")
        print(f"✅ 총 {success_count}/{count}장 캡처 완료")

        if duplicates:
            print(f"⚠️  중복 페이지 감지: {sorted(duplicates)}")
            print(f"   → 이미 존재하는 페이지를 다시 캡처했습니다.")

        print(f"{'=' * 60}\n")

        return results


def main():
    """CLI 인터페이스"""
    if len(sys.argv) < 2:
        print("사용법: python kyobo_app_screenshot.py <옵션>")
        print("옵션:")
        print("  1 - 단일 스크린샷 (전체 화면)")
        print("  2 - 윈도우만 캡처 (macOS)")
        print("  3 - 여러 장 연속 캡처 (자동 페이지 넘김)")
        sys.exit(1)

    option = sys.argv[1]

    # 옵션 3번일 경우 도서 폴더 설정
    book_folder = None
    if option == "3":
        # 임시 봇 생성하여 도서명 추출 시도
        temp_bot = KyoboAppScreenshot()
        if temp_bot.is_app_running():
            auto_title = temp_bot.get_current_book_title()
            if auto_title:
                print(f"\n📚 현재 열린 도서: {auto_title}")
                use_auto = input("이 도서명을 폴더명으로 사용하시겠습니까? (y/n, 기본값=y): ").strip().lower()
                if use_auto != 'n':
                    book_folder = auto_title
                else:
                    book_folder = input("도서명(폴더명)을 입력하세요: ").strip()
            else:
                book_folder = input("도서명(폴더명)을 입력하세요: ").strip()
        else:
            book_folder = input("도서명(폴더명)을 입력하세요: ").strip()

        if not book_folder:
            print("❌ 도서명을 입력해야 합니다.")
            sys.exit(1)

    bot = KyoboAppScreenshot(output_dir="kyobo_app_screenshots", book_folder=book_folder)

    if option == "1":
        print("\n📸 전체 화면 스크린샷 캡처...")
        custom_name = input("파일명을 입력하세요 (엔터=자동 생성): ").strip()
        bot.take_screenshot(
            custom_name=custom_name if custom_name else None,
            wait_time=5
        )

    elif option == "2":
        print("\n📸 교보 앱 윈도우만 캡처...")
        custom_name = input("파일명을 입력하세요 (엔터=자동 생성): ").strip()
        bot.take_window_screenshot(
            custom_name=custom_name if custom_name else None,
            wait_time=5
        )

    elif option == "3":
        print("\n📚 여러 장 연속 캡처 (자동 페이지 넘김)")
        try:
            # OCR 사용 여부
            if HAS_OCR:
                ocr_choice = input("OCR로 실제 페이지 번호 추출하시겠습니까? (y/n, 기본값=y): ").strip().lower()
                use_ocr = (ocr_choice != 'n')
            else:
                print("⚠️  OCR 라이브러리 미설치, 순차 번호로 저장됩니다.")
                use_ocr = False

            # 이어서 캡처 옵션
            continue_choice = input("이전 캡처에 이어서 저장하시겠습니까? (y/n, 기본값=n): ").strip().lower()
            continue_from_last = (continue_choice == 'y')

            # 시작 페이지
            if continue_from_last:
                start_page = 1  # 자동으로 마지막 페이지 다음부터 시작됨
            else:
                if use_ocr:
                    start_page = 1  # OCR 모드에서는 자동 추출되므로 의미 없음
                else:
                    start_input = input("시작 페이지 번호 (엔터=1): ").strip()
                    start_page = int(start_input) if start_input else 1

            # 캡처할 페이지 수
            count = int(input("캡처할 페이지 수를 입력하세요: "))

            # 간격
            interval = int(input("페이지 간 대기 시간(초, 권장 3초): ") or "3")

            # 파일명 접두사
            custom_prefix = input("파일명 접두사 (엔터=기본값 'page'): ").strip()

            bot.take_multiple_screenshots(
                count=count,
                interval=interval,
                custom_prefix=custom_prefix if custom_prefix else None,
                auto_page_turn=True,
                start_page=start_page,
                continue_from_last=continue_from_last,
                use_ocr=use_ocr
            )
        except ValueError:
            print("❌ 올바른 숫자를 입력하세요.")
            sys.exit(1)

    else:
        print("❌ 올바르지 않은 옵션입니다. 1, 2, 3 중 선택하세요.")
        sys.exit(1)

    print("\n✅ 완료!")


if __name__ == "__main__":
    main()
