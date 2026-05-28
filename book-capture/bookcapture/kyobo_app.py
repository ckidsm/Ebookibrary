#!/usr/bin/env python3
"""
교보문고 ebook 앱 스크린샷 자동화 스크립트 (macOS/Windows)
"""

import subprocess
import time
import os
import sys
import re
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

    def is_app_running(self):
        """교보문고 ebook 앱이 실행 중인지 확인"""
        if self.system == "Darwin":  # macOS
            try:
                # 교보문고 앱은 iPadB2C 프로세스로 실행됨
                result = subprocess.run(
                    ["pgrep", "-f", "iPadB2C"],
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0
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

    def launch_app(self):
        """교보문고 ebook 앱 실행 (이미 실행 중이면 스킵)"""
        # 이미 실행 중인지 확인
        if self.is_app_running():
            print("✓ 교보문고 ebook 앱이 이미 실행 중입니다.")
            return True

        print("📱 교보문고 ebook 앱 실행 중...")

        if self.system == "Darwin":  # macOS
            app_path = "/Applications/교보eBook.app"
            if not os.path.exists(app_path):
                print(f"❌ 앱을 찾을 수 없습니다: {app_path}")
                return False

            subprocess.run(["open", app_path], check=True)
            print("✓ 앱 실행 완료 (macOS)")

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

    def activate_app(self):
        """교보문고 앱을 활성화(포커스)"""
        if self.system == "Darwin":
            script = '''
            tell application "System Events"
                set appName to name of first application process whose name contains "iPadB2C"
                set frontmost of application process appName to true
            end tell
            '''
            subprocess.run(["osascript", "-e", script], check=True)
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

    def capture_app_window(self, filepath):
        """교보문고 앱 윈도우만 캡처 (macOS)"""
        if self.system == "Darwin":
            # 앱 활성화
            self.activate_app()

            # AppleScript로 앱 윈도우 캡처
            script = f'''
            tell application "System Events"
                set appName to name of first application process whose name contains "iPadB2C"
                set frontmost of application process appName to true
            end tell

            delay 0.3

            do shell script "screencapture -o -l$(osascript -e 'tell app \\"System Events\\" to get id of window 1 of application process \\"iPadB2C\\"') {filepath}"
            '''
            try:
                subprocess.run(["osascript", "-e", script], check=True)
                return True
            except:
                # 실패하면 전체 화면 캡처로 폴백
                print("⚠️  윈도우 캡처 실패, 전체 화면 캡처로 전환...")
                subprocess.run([
                    "screencapture",
                    "-x",
                    str(filepath)
                ], check=True)
                return True
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
                                  use_ocr=True):
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

            input(f"📚 도서를 열고 시작 페이지로 이동한 후 엔터를 누르세요...")
            print("\n⏳ 앱을 활성화하는 중...")

            # 앱 활성화
            self.activate_app()
            time.sleep(1)

            # 전체 화면 확인
            if not self.is_fullscreen():
                print("\n⚠️  경고: 교보문고 앱이 전체 화면 모드가 아닙니다!")
                if use_ocr:
                    print("      OCR 모드에서는 전체 화면 필수입니다!")
                else:
                    print("      윈도우 창 자체가 캡처될 수 있습니다.")
                user_input = input("전체 화면으로 전환하시겠습니까? (y/n, 기본값=y): ").strip().lower()

                if user_input != 'n':
                    print("🖥️  전체 화면으로 전환 중...")
                    if self.set_fullscreen(True):
                        print("✅ 전체 화면으로 전환되었습니다.")
                    else:
                        print("❌ 전체 화면 전환에 실패했습니다. 수동으로 전환해주세요.")
                        input("전체 화면으로 전환 후 엔터를 누르세요...")
            else:
                print("✅ 전체 화면 모드 확인 완료")

            print("\n⏳ 3초 후 캡처를 시작합니다...")
            time.sleep(3)
        else:
            print(f"⏳ 앱 로딩 대기 중...")
            time.sleep(5)

        results = []
        duplicates = []

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

                # 파일명 변경
                temp_filepath.rename(final_filepath)
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
