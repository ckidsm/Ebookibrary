"""교보 e-library 웹뷰어 캡처 — Playwright 기반.

매크로(System Events) 의존성 제거 → 화면 점유 0.

흐름:
  1) login_interactive() — 사용자가 1회 헤드풀 Chromium 으로 로그인 → storage_state.json 저장
  2) capture_book() — 저장된 세션 재사용 (헤드리스 또는 헤드풀) → 책 페이지 자동 넘김·캡처
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable, Iterator

# 캡처 표준(모니터 무관 규격 + 정규화). 패키지/단독 실행 양쪽 대비.
try:
    from . import capture_standard as _cs
except Exception:  # 단독 실행
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import capture_standard as _cs


def _finalize_shot(path):
    """Playwright 스크린샷을 표준 폭(1600px)으로 정규화 저장. 실패해도 원본 유지."""
    try:
        from PIL import Image
        _cs.safe_normalize(Image.open(path)).save(path)
    except Exception:
        pass

# Playwright 는 worker 첫 import 시 ImportError 가능 (설치 안 됨) — 지연 import
def _ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


# ── 경로 ────────────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".config" / "kyobo-library"
SESSION_PATH = CONFIG_DIR / "wviewer-session.json"
DEBUG_LOG = CONFIG_DIR / "wviewer-debug.log"

KYOBO_ELIBRARY_URL = (
    "https://elibrary.kyobobook.co.kr/dig/elb/elibrary"
    "?page=1&categoryYn=Y&mainCategoryYn=Y&subCategoryYn=N&dgctSaleCmdtDvsnCode=EBK"
)
KYOBO_LOGIN_URL = "https://mmbr.kyobobook.co.kr/login"

# macOS Keychain (keyring) 서비스 이름
KEYCHAIN_SERVICE = "kyobo-library"
# 기본 이메일 저장용 plaintext (config dir)
DEFAULT_EMAIL_FILE = CONFIG_DIR / "default-email.txt"
# Persistent Chrome 프로필 디렉토리 (한 번 로그인하면 쿠키 영구 유지)
CHROME_PROFILE_DIR = CONFIG_DIR / "chrome-profile"

# 자동화 감지 우회 강화 init script
STEALTH_INIT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    delete Object.getPrototypeOf(navigator).webdriver;
    Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR','ko','en-US','en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [
        { name: 'Chrome PDF Plugin' },
        { name: 'Chrome PDF Viewer' },
        { name: 'Native Client' },
    ]});
    // window.chrome 존재 (일반 Chrome 처럼)
    if (!window.chrome) window.chrome = { runtime: {} };
    // permissions 쿼리 패치
    const orig = window.navigator.permissions?.query;
    if (orig) {
        window.navigator.permissions.query = (p) =>
            p.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : orig(p);
    }
"""

CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-infobars",
    "--disable-notifications",
    "--start-maximized",
]


# ── 자격증명 (Keychain) ─────────────────────────────────────
def _import_keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def set_credentials(email: str, password: str) -> dict:
    """macOS Keychain 에 ID/PW 저장. 기본 이메일은 평문 파일에 저장."""
    kr = _import_keyring()
    if not kr:
        return {"ok": False, "reason": "keyring 미설치"}
    _ensure_dir()
    try:
        kr.set_password(KEYCHAIN_SERVICE, email, password)
        DEFAULT_EMAIL_FILE.write_text(email, encoding="utf-8")
        # 즉시 검증 (macOS 가 권한 팝업 띄울 수 있음)
        got = kr.get_password(KEYCHAIN_SERVICE, email)
        if got == password:
            return {"ok": True, "email": email, "keychain_service": KEYCHAIN_SERVICE}
        return {"ok": False, "reason": "저장 직후 검증 실패"}
    except Exception as e:
        return {"ok": False, "reason": f"Keychain 저장 실패: {e}"}


def get_credentials(email: str | None = None) -> tuple[str | None, str | None]:
    """저장된 이메일·비밀번호 반환 (없으면 None, None)."""
    kr = _import_keyring()
    if not kr:
        return None, None
    if not email:
        if DEFAULT_EMAIL_FILE.exists():
            email = DEFAULT_EMAIL_FILE.read_text(encoding="utf-8").strip()
        else:
            return None, None
    try:
        pw = kr.get_password(KEYCHAIN_SERVICE, email)
        return (email, pw) if pw else (email, None)
    except Exception:
        return email, None


def clear_credentials(email: str | None = None) -> dict:
    """Keychain 에서 자격증명 삭제."""
    kr = _import_keyring()
    if not kr:
        return {"ok": False, "reason": "keyring 미설치"}
    if not email and DEFAULT_EMAIL_FILE.exists():
        email = DEFAULT_EMAIL_FILE.read_text(encoding="utf-8").strip()
    if not email:
        return {"ok": False, "reason": "이메일 없음"}
    try:
        kr.delete_password(KEYCHAIN_SERVICE, email)
        if DEFAULT_EMAIL_FILE.exists():
            DEFAULT_EMAIL_FILE.unlink()
        return {"ok": True, "email": email}
    except Exception as e:
        return {"ok": False, "reason": f"Keychain 삭제 실패: {e}"}


def credentials_status() -> dict:
    """자격증명 등록 여부 확인 (PW 값은 노출 X)."""
    kr = _import_keyring()
    if not kr:
        return {"ok": False, "reason": "keyring 미설치"}
    if not DEFAULT_EMAIL_FILE.exists():
        return {"ok": False, "reason": "등록된 자격증명 없음"}
    email = DEFAULT_EMAIL_FILE.read_text(encoding="utf-8").strip()
    try:
        pw = kr.get_password(KEYCHAIN_SERVICE, email)
        if pw:
            masked = pw[:1] + "*" * max(0, len(pw) - 2) + pw[-1:] if len(pw) >= 2 else "**"
            return {
                "ok": True, "email": email,
                "password_length": len(pw), "password_masked": masked,
                "keychain_service": KEYCHAIN_SERVICE,
            }
        return {"ok": False, "reason": f"Keychain 에서 비밀번호 못 가져옴 (email={email})"}
    except Exception as e:
        return {"ok": False, "reason": f"Keychain 조회 실패: {e}"}


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def session_exists() -> bool:
    return SESSION_PATH.exists() and SESSION_PATH.stat().st_size > 50


def session_info() -> dict:
    """저장된 세션 메타 (로그인 여부, 저장 시각). UI 표시용."""
    if not session_exists():
        return {"ok": False, "reason": "no_session"}
    try:
        mtime = SESSION_PATH.stat().st_mtime
        age_days = (time.time() - mtime) / 86400
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
        return {
            "ok": True,
            "path": str(SESSION_PATH),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
            "age_days": round(age_days, 1),
            "cookie_count": len(cookies),
        }
    except Exception as e:
        return {"ok": False, "reason": f"parse_error: {e}"}


# ── 로그인 (헤드풀, 사용자 인터랙티브) ────────────────────────
def login_interactive(timeout_sec: int = 600) -> int:
    """1회 실행. 사용자가 브라우저에서 직접 로그인하면 세션 저장.

    timeout_sec: 최대 대기 시간 (기본 10분). 그 안에 로그인 + 도서함 진입까지.
    """
    if not _ensure_playwright():
        print("✗ playwright 미설치. pip install playwright 후 playwright install chromium", file=sys.stderr)
        return 1

    _ensure_dir()
    from playwright.sync_api import sync_playwright

    print("=" * 60)
    print("교보 e-library 로그인 (1회만)")
    print("=" * 60)
    print()
    print("1. Chromium 창이 열립니다.")
    print("2. 교보문고 ID/비밀번호로 로그인하세요.")
    print("3. 내 e-Library 페이지(도서함)까지 진입해 책 한 권 클릭해 뷰어가 뜨는지 확인.")
    print("4. 확인 끝나면 이 터미널에서 ENTER 키를 누르세요.")
    print()

    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[wviewer] Chrome 프로필: {CHROME_PROFILE_DIR}")
    print(f"[wviewer] (한 번 로그인하면 다음부터 자동 유지)\n")

    with sync_playwright() as p:
        # channel='chrome' — Playwright 자체 Chromium 대신 macOS 의 정식 Chrome 사용
        # (교보의 자동화 감지 우회 — 진짜 Chrome 으로 인식됨)
        launch_kwargs = dict(
            user_data_dir=str(CHROME_PROFILE_DIR),
            headless=False,
            args=CHROMIUM_ARGS,
            viewport={"width": 1400, "height": 900},
            locale="ko-KR",
        )
        try:
            launch_kwargs["channel"] = "chrome"
            context = p.chromium.launch_persistent_context(**launch_kwargs)
            print("[wviewer] ✓ 정식 Google Chrome 사용 중 (channel=chrome)")
        except Exception as e:
            print(f"[wviewer] ⚠ Chrome 채널 미가용 — Chromium 폴백: {e}")
            launch_kwargs.pop("channel", None)
            launch_kwargs["user_agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            )
            context = p.chromium.launch_persistent_context(**launch_kwargs)
        context.add_init_script(STEALTH_INIT)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(KYOBO_ELIBRARY_URL)

        try:
            input("\n>>> 로그인 + e-Library 진입 완료 후 ENTER (또는 Ctrl+C 취소): ")
        except KeyboardInterrupt:
            print("\n✗ 취소됨")
            context.close()
            return 130

        # storage_state 도 같이 저장 (옛 호환). 다만 이제 프로필 자체로 동작.
        try:
            context.storage_state(path=str(SESSION_PATH))
        except Exception as e:
            print(f"⚠ storage_state 저장 실패 (프로필은 유지됨): {e}")
        context.close()

    info = session_info()
    if info.get("ok"):
        print(f"\n✓ 세션 저장: {SESSION_PATH}")
        print(f"  쿠키 {info.get('cookie_count')}개, 저장 시각 {info.get('saved_at')}")
        return 0
    else:
        print(f"\n✗ 세션 저장 실패: {info}", file=sys.stderr)
        return 1


# ── 캡처 (헤드풀/헤드리스, 저장된 세션 재사용) ────────────────
def capture_book(
    book_url: str,
    out_dir: Path,
    max_pages: int = 300,
    delay_sec: float = 1.5,
    headless: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
    is_cancelling: Callable[[], bool] | None = None,
) -> dict:
    """저장된 세션으로 책 뷰어 열고 페이지 자동 캡처.

    Returns: {"ok": bool, "captured": N, "out_dir": "...", "reason": "..."}
    """
    if not _ensure_playwright():
        return {"ok": False, "reason": "playwright 미설치"}

    _ensure_dir()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    captured = 0
    last_hash = None

    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/130.0.0.0 Safari/537.36")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        ctx_kwargs = {
            # 표준 viewport(단면 세로) + device_scale_factor=2 → 모니터 무관 1920×2880
            **_cs.playwright_context_kwargs(),
            "locale": "ko-KR",
            "user_agent": UA,
            "extra_http_headers": {
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://elibrary.kyobobook.co.kr/",
            },
        }
        # 세션 있으면 재사용. 없어도 ticket 있는 wviewer URL 은 동작 가능
        if session_exists():
            ctx_kwargs["storage_state"] = str(SESSION_PATH)
        context = browser.new_context(**ctx_kwargs)
        # navigator.webdriver=false 스텔스 패치
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR','ko','en-US','en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        """)
        page = context.new_page()
        try:
            page.goto(book_url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            browser.close()
            return {"ok": False, "reason": f"goto 실패: {e}", "captured": captured}

        # 차단 페이지 감지 — 분리 사유
        try:
            body_text = page.evaluate("() => document.body.innerText.slice(0, 500)")
            current_url = page.url
        except Exception:
            body_text = ""
            current_url = ""

        if "duplicateUse" in current_url or "다른 곳에서" in body_text:
            browser.close()
            return {
                "ok": False,
                "reason": "duplicate_use",
                "detail": "이 책은 이미 다른 브라우저에서 보고 있습니다. 사용자 Chrome 의 e-library 탭을 닫고 다시 시도하세요.",
                "current_url": current_url,
                "captured": 0,
            }
        if "정상적인 접근이 아니므로" in body_text or "403" in body_text[:50]:
            browser.close()
            return {
                "ok": False,
                "reason": "blocked_403",
                "detail": "교보 자동화 차단 또는 ticket 만료. e-library 통과 흐름 필요.",
                "body_snippet": body_text[:200],
                "captured": 0,
            }
        time.sleep(2.0)  # 뷰어 초기화 대기

        for i in range(1, max_pages + 1):
            if is_cancelling and is_cancelling():
                browser.close()
                return {"ok": False, "reason": "cancelled", "captured": captured}

            png_path = out_dir / f"page_{i:03d}.png"
            try:
                page.screenshot(path=str(png_path), full_page=False)
                _finalize_shot(png_path)  # 표준 폭 1600px 정규화
                captured += 1
                if progress:
                    progress(i, max_pages, f"page_{i:03d}.png 저장")
            except Exception as e:
                if progress:
                    progress(i, max_pages, f"⚠ 캡처 실패: {e}")
                break

            # 페이지 변화 감지용 hash (현재 페이지 DOM 의 일부 hash)
            try:
                current_hash = page.evaluate(
                    "() => document.body.innerText.slice(0,200) + location.hash"
                )
            except Exception:
                current_hash = None

            if last_hash is not None and current_hash == last_hash:
                # 페이지 안 넘어감 = 책 마지막일 가능성
                if progress:
                    progress(i, max_pages, f"📕 마지막 페이지 도달 (i={i})")
                break
            last_hash = current_hash

            # 다음 페이지로 — Page Down 키 또는 → 키
            try:
                page.keyboard.press("ArrowRight")
            except Exception:
                pass
            time.sleep(delay_sec)

        browser.close()

    return {
        "ok": True,
        "captured": captured,
        "out_dir": str(out_dir),
    }


# ── e-library 통과 흐름 (Phase #47 정공법) ───────────────────
# 사용자 본인 Chrome 의 교보 탭이 닫혀 있어야 duplicateUse 안 발생.
# Playwright 가:
#   1) 도서함 진입 (세션 로드)
#   2) [바로보기] 버튼 셀렉터로 책 찾기 (페이지 순회 포함)
#   3) 클릭 → 새 탭에서 wviewer 자동 진입 (서버가 새 ticket 발급)
#   4) wviewer 페이지에서 자동 페이지 넘김·캡처

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


def _new_context(p, headless: bool):
    """공통 컨텍스트 — channel='chrome' (정식 Chrome) + persistent 프로필.

    교보가 Playwright Chromium 을 감지·차단하므로, macOS 의 실제 Chrome 본체 사용.
    """
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    launch_kwargs = dict(
        user_data_dir=str(CHROME_PROFILE_DIR),
        headless=headless,
        args=CHROMIUM_ARGS,
        # 표준 viewport(단면 세로) + device_scale_factor=2 → 모니터 무관 1920×2880
        **_cs.playwright_context_kwargs(),
        locale="ko-KR",
        extra_http_headers={
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    try:
        launch_kwargs["channel"] = "chrome"
        context = p.chromium.launch_persistent_context(**launch_kwargs)
        print("[wviewer] ✓ channel=chrome (정식 Chrome)")
    except Exception as e:
        print(f"[wviewer] ⚠ Chrome 채널 미가용 — Chromium 폴백: {e}")
        launch_kwargs.pop("channel", None)
        launch_kwargs["user_agent"] = UA
        context = p.chromium.launch_persistent_context(**launch_kwargs)

    context.add_init_script(STEALTH_INIT)
    return context, context


def _find_book_button(page, salecmdtid: str) -> bool:
    """현재 도서함 페이지에서 salecmdtid 의 [바로보기] 버튼이 있는지.

    SPA navigation 중 locator 가 파괴될 수 있어 evaluate 로 직접 + try/except.
    """
    js = f"""() => !!document.querySelector('button.clickDirectView[data-salecmdtid="{salecmdtid}"]')"""
    for attempt in range(3):
        try:
            return bool(page.evaluate(js))
        except Exception as e:
            if "Execution context was destroyed" in str(e) or "navigation" in str(e):
                page.wait_for_timeout(500)
                continue
            return False
    return False


# ── 자동 재로그인 ─────────────────────────────────────────
def _auto_relogin(context, page, log_fn=print) -> dict:
    """Keychain 의 ID/PW 로 자동 로그인. 성공 시 storage_state 갱신.

    Returns: {"ok": bool, "reason": "..."}
    """
    email, pw = get_credentials()
    if not email or not pw:
        return {"ok": False, "reason": "Keychain 자격증명 없음 — bookcapture wviewer set-credentials 먼저 실행"}

    log_fn(f"[wviewer] 🔐 자동 재로그인 시도 (email={email})")
    try:
        # 로그인 페이지로 명시 진입
        page.goto(KYOBO_LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500)

        # ID/PW 입력 필드 셀렉터 후보들 시도 (교보 변경 대비)
        id_sels = [
            'input[name="loginId"]',
            'input[name="userId"]',
            'input[name="email"]',
            'input[type="email"]',
            'input[id*="id" i]',
            '#userId, #loginId, #email',
        ]
        pw_sels = [
            'input[name="loginPw"]',
            'input[name="userPw"]',
            'input[name="password"]',
            'input[type="password"]',
        ]
        submit_sels = [
            'button[type="submit"]',
            'button.btn_login',
            'button:has-text("로그인")',
            'input[type="submit"]',
        ]

        filled_id = filled_pw = False
        for sel in id_sels:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.fill(email)
                    filled_id = True
                    log_fn(f"[wviewer]   ID 필드 매칭: {sel}")
                    break
            except Exception:
                continue
        for sel in pw_sels:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.fill(pw)
                    filled_pw = True
                    log_fn(f"[wviewer]   PW 필드 매칭: {sel}")
                    break
            except Exception:
                continue

        if not (filled_id and filled_pw):
            return {"ok": False, "reason": f"로그인 폼 못 찾음 (filled_id={filled_id} pw={filled_pw})"}

        # 제출
        submitted = False
        for sel in submit_sels:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.click()
                    submitted = True
                    log_fn(f"[wviewer]   제출: {sel}")
                    break
            except Exception:
                continue
        if not submitted:
            # 폼 자체 제출 fallback
            page.keyboard.press("Enter")

        # 로그인 완료 대기 — URL 이 mmbr 로 안 가면 성공으로 간주
        page.wait_for_timeout(3000)
        page.wait_for_load_state("networkidle", timeout=15000)
        cur = page.url
        log_fn(f"[wviewer]   로그인 후 URL: {cur}")
        if "login" in cur.lower():
            return {"ok": False, "reason": f"로그인 페이지 잔존 (PW 오류 또는 추가 인증 필요): {cur}"}

        # 세션 저장 갱신
        context.storage_state(path=str(SESSION_PATH))
        log_fn(f"[wviewer] ✓ 자동 재로그인 성공 + 세션 갱신")
        return {"ok": True, "current_url": cur}
    except Exception as e:
        return {"ok": False, "reason": f"자동 재로그인 예외: {e}"}


def _wait_book_list_ready(page, timeout_ms: int = 15000) -> bool:
    """ul#myBookList 가 실제 책 카드로 채워질 때까지 대기."""
    try:
        page.wait_for_selector('ul#myBookList input[name="mybookChk"]', timeout=timeout_ms)
        page.wait_for_timeout(500)  # 추가 안정화
        return True
    except Exception as e:
        print(f"[wviewer] ⚠ myBookList 로딩 대기 실패: {e}")
        return False


def _click_next_page(page, max_wait_ms: int = 10000) -> bool:
    """페이지네이션 [다음] 클릭 + 첫 책 ID 변화까지 대기. 성공 True."""
    # 디버그: 페이지네이션 구조 확인
    diag = page.evaluate("""
        () => {
            const pag = document.querySelector('div.pagination#pagi, div.pagination');
            if (!pag) return { has_pagination: false, html: '' };
            const active = pag.querySelector('.on, .active, [aria-current="page"]');
            const all_children = Array.from(pag.children).map(c => ({
                tag: c.tagName,
                cls: c.className,
                txt: (c.textContent || '').trim().slice(0, 30),
                aria: c.getAttribute('aria-current') || '',
            }));
            return {
                has_pagination: true,
                active_text: active ? (active.textContent || '').trim() : null,
                active_class: active ? active.className : null,
                children: all_children,
                outer: pag.outerHTML.slice(0, 400),
            };
        }
    """)
    print(f"[wviewer] pagination 진단: has={diag.get('has_pagination')} active='{diag.get('active_text')}' class='{diag.get('active_class')}'")
    print(f"[wviewer]   children: {diag.get('children')}")

    # 현재 페이지의 첫 책 ID
    before_id = page.evaluate("""
        () => {
            const inp = document.querySelector('ul#myBookList input[name="mybookChk"]');
            return inp ? inp.value : '';
        }
    """) or ''
    print(f"[wviewer]   before_first_id={before_id!r}")

    # 활성 페이지의 다음 형제 (a 또는 button) 클릭
    click_result = page.evaluate("""
        () => {
            const pag = document.querySelector('div.pagination#pagi, div.pagination');
            if (!pag) return { ok: false, why: 'no_pagination' };
            const active = pag.querySelector('.on, .active, [aria-current="page"]');
            if (!active) return { ok: false, why: 'no_active' };
            let sib = active.nextElementSibling;
            const candidates = [];
            while (sib) {
                candidates.push({ tag: sib.tagName, cls: sib.className, txt: (sib.textContent||'').trim().slice(0,20) });
                if (sib.tagName === 'A' || sib.tagName === 'BUTTON') {
                    sib.click();
                    return { ok: true, clicked: { tag: sib.tagName, txt: (sib.textContent||'').trim() }};
                }
                sib = sib.nextElementSibling;
            }
            return { ok: false, why: 'no_clickable_sibling', candidates };
        }
    """)
    print(f"[wviewer]   click 결과: {click_result}")

    if not click_result.get('ok'):
        return False

    # 첫 책 ID 변화 대기
    try:
        page.wait_for_function(
            """before => {
                const inp = document.querySelector('ul#myBookList input[name="mybookChk"]');
                return inp && inp.value && inp.value !== before;
            }""",
            arg=before_id,
            timeout=max_wait_ms,
        )
        page.wait_for_timeout(400)  # 추가 안정화
        after_id = page.evaluate("""() => document.querySelector('ul#myBookList input[name="mybookChk"]')?.value || ''""")
        print(f"[wviewer]   ✓ page 변경 OK (after_first_id={after_id!r})")
        return True
    except Exception as e:
        print(f"[wviewer]   ✗ wait_for_function timeout: {e}")
        return False


def capture_via_library(
    salecmdtid: str,
    slug: str,
    out_dir: Path,
    max_pages: int = 300,
    delay_sec: float = 1.5,
    headless: bool = True,
    progress=None,
    is_cancelling=None,
) -> dict:
    """e-library 통과 흐름으로 책 자동 캡처.

    Returns: {"ok": bool, "captured": N, "reason": "...", "wviewer_url": "..."}
    """
    if not _ensure_playwright():
        return {"ok": False, "reason": "playwright 미설치"}
    if not session_exists():
        return {"ok": False, "reason": "세션 없음 — bookcapture wviewer login 먼저"}

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    captured = 0

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, context = _new_context(p, headless=headless)
        page = context.new_page()

        # 1) 도서함 페이지 진입 + SPA 데이터 로드 완전 대기
        if progress: progress(0, max_pages, "도서함 페이지 진입...")
        attempt_relogin_done = False
        for attempt in range(2):  # 1회 본진입 + 자동 재로그인 시 1회 재시도
            try:
                page.goto(KYOBO_ELIBRARY_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                cur = page.url
                print(f"[wviewer] 진입 후 URL: {cur}")

                # 로그인 페이지로 리다이렉트 = 세션 만료
                if "login" in cur.lower() or "mmbr.kyobobook.co.kr/login" in cur:
                    if attempt_relogin_done:
                        browser.close()
                        return {
                            "ok": False, "reason": "session_expired",
                            "detail": "자동 재로그인 후에도 로그인 페이지 잔존",
                            "current_url": cur, "captured": 0,
                        }
                    # 자동 재로그인 시도
                    if progress: progress(0, max_pages, "🔐 세션 만료 → 자동 재로그인 시도...")
                    relogin = _auto_relogin(context, page)
                    print(f"[wviewer] _auto_relogin 결과: {relogin}")
                    if not relogin.get("ok"):
                        browser.close()
                        return {
                            "ok": False, "reason": "auto_relogin_failed",
                            "detail": relogin.get("reason"),
                            "captured": 0,
                        }
                    attempt_relogin_done = True
                    continue  # 도서함 다시 진입

                # 도서함 정상 진입 — myBookList 로딩 대기
                ok = _wait_book_list_ready(page, timeout_ms=15000)
                if ok:
                    print(f"[wviewer] ✓ 도서함 로드 완료, 책 검색 시작")
                    break
                # 데이터 로딩 실패 — 세션이지만 인증 부족 가능
                if not attempt_relogin_done and get_credentials()[1]:
                    if progress: progress(0, max_pages, "🔐 myBookList 비어있음 → 자동 재로그인 시도...")
                    relogin = _auto_relogin(context, page)
                    if relogin.get("ok"):
                        attempt_relogin_done = True
                        continue
                browser.close()
                return {"ok": False, "reason": "도서함 myBookList 로딩 실패", "captured": 0}
            except Exception as e:
                browser.close()
                return {"ok": False, "reason": f"도서함 진입 실패: {e}", "captured": 0}

        # 2) salecmdtid 찾기 (페이지 순회)
        if progress: progress(0, max_pages, f"책 검색 (salecmdtid={salecmdtid})...")
        MAX_SEARCH_PAGES = 35
        found = False
        for i in range(MAX_SEARCH_PAGES):
            if is_cancelling and is_cancelling():
                browser.close()
                return {"ok": False, "reason": "cancelled", "captured": 0}
            cur_page = i + 1
            if _find_book_button(page, salecmdtid):
                found = True
                print(f"[wviewer] ✓ 책 발견 page {cur_page}")
                break
            print(f"[wviewer] page {cur_page}: 책 없음 → 다음 페이지 시도")
            if progress: progress(0, max_pages, f"책 검색 — page {cur_page} 통과")
            if not _click_next_page(page):
                print(f"[wviewer] ✗ 다음 페이지 클릭 실패 — 종료 (총 {cur_page} 페이지 검색)")
                break
        if not found:
            browser.close()
            return {"ok": False, "reason": f"책 못 찾음 (salecmdtid={salecmdtid}, 검색 {cur_page} 페이지)", "captured": 0}

        # 3) [바로보기] 클릭 → 새 탭에서 wviewer 진입
        if progress: progress(0, max_pages, "[바로보기] 클릭...")
        btn_sel = f'button.clickDirectView[data-salecmdtid="{salecmdtid}"]'
        try:
            with context.expect_page(timeout=10000) as new_page_info:
                page.locator(btn_sel).first.click()
            viewer = new_page_info.value
            viewer.wait_for_load_state("networkidle", timeout=20000)
        except Exception as e:
            browser.close()
            return {"ok": False, "reason": f"바로보기 클릭/탭 열림 실패: {e}", "captured": 0}

        wviewer_url = viewer.url
        # 차단 페이지 감지
        if "duplicateUse" in wviewer_url:
            browser.close()
            return {
                "ok": False, "reason": "duplicate_use",
                "detail": "본인 Chrome 의 교보 탭을 닫고 다시 시도하세요.",
                "wviewer_url": wviewer_url,
            }
        try:
            body = viewer.evaluate("() => document.body.innerText.slice(0,300)") or ''
        except Exception:
            body = ''
        if "정상적인 접근이 아니므로" in body:
            browser.close()
            return {"ok": False, "reason": "blocked_403", "wviewer_url": wviewer_url, "body": body[:200]}

        # 4) wviewer 페이지에서 캡처 루프
        if progress: progress(0, max_pages, f"캡처 시작 (viewer: {wviewer_url[:60]}...)")
        last_hash = None
        same_count = 0
        for i in range(1, max_pages + 1):
            if is_cancelling and is_cancelling():
                browser.close()
                return {"ok": False, "reason": "cancelled", "captured": captured}

            png = out_dir / f"page_{i:03d}.png"
            try:
                viewer.screenshot(path=str(png), full_page=False)
                _finalize_shot(png)  # 표준 폭 1600px 정규화
                captured += 1
                if progress: progress(i, max_pages, f"page_{i:03d}.png 저장")
            except Exception as e:
                if progress: progress(i, max_pages, f"⚠ 캡처 실패: {e}")
                break

            # 페이지 변화 감지 — DOM 내용 hash
            try:
                h = viewer.evaluate(
                    "() => document.body.innerText.slice(0,300) + '|' + location.hash"
                )
            except Exception:
                h = None

            if h is not None and h == last_hash:
                same_count += 1
                if same_count >= 2:
                    if progress: progress(i, max_pages, f"📕 마지막 페이지 도달 (i={i})")
                    break
            else:
                same_count = 0
            last_hash = h

            # 다음 페이지로 — ArrowRight 우선, fallback PageDown
            try:
                viewer.keyboard.press("ArrowRight")
            except Exception:
                try:
                    viewer.keyboard.press("PageDown")
                except Exception:
                    pass
            viewer.wait_for_timeout(int(delay_sec * 1000))

        browser.close()

    return {
        "ok": True,
        "captured": captured,
        "out_dir": str(out_dir),
        "wviewer_url": wviewer_url,
    }
