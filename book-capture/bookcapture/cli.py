"""통합 CLI — `python -m bookcapture <subcommand>`.

서브커맨드:
  settings          현재 백엔드 설정 출력
  capture           기존 kyobo_app.py 호출(인터랙티브, 옵션 1/2/3)
  ocr               <book_dir> 내 *.png OCR → summary/ocr_text/
  build             <book_dir> 캡처+OCR 결과로 summary/index.html (Phase C-2 placeholder)
  run               전 단계 일괄: capture → ocr → build

옵션 공통:
  --slug NAME       도서 폴더명 (output/<slug>/)
  --bridge URL      백엔드 URL 오버라이드 (기본: $KYOBO_BRIDGE_URL)
  --refresh         OCR 캐시 무시
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import settings as cfg
from . import ocr as ocr_mod
from . import build_html
from . import merge as merge_mod
from . import summarize as summarize_mod
from . import extract_code as code_mod
from . import worker as worker_mod


def cmd_settings(args) -> int:
    s = cfg.load(bridge_url=args.bridge)
    print(f"bookcapture v{__version__}")
    print(cfg.explain(s))
    if not s.ai.api_key:
        print("\n⚠ AI 키 없음 — 환경변수 ANTHROPIC_API_KEY 또는 OPENAI_API_KEY 설정 권장")
    return 0


def cmd_capture(args) -> int:
    # 기존 kyobo_app.py 의 main() 을 그대로 호출 (인터랙티브 메뉴)
    from . import kyobo_app
    s = cfg.load(bridge_url=args.bridge)
    out_dir = Path(s.output.books_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[capture] 출력 베이스: {out_dir}")
    print(f"[capture] 설정: {cfg.explain(s)}")
    # kyobo_app.main() 은 sys.argv 를 보므로 옵션 주입
    mode = args.mode or "3"  # 기본 = 연속 캡처
    sys.argv = ["kyobo_app", mode]
    kyobo_app.main()
    return 0


def cmd_capture_auto(args) -> int:
    """비대화형 자동 캡처 — worker 가 호출하는 진입점.
    --book-id 가 있으면 deep link 로 책 자동 열기 시도.
    OS 분기: Windows 는 KyoboWinCapture(앱 자동설치·실행 + ImageGrab 캡처).
    """
    import platform
    s = cfg.load(bridge_url=args.bridge)
    if not args.slug:
        print("✗ --slug 필수 (도서 폴더명)", file=sys.stderr); return 2
    out_dir = Path(s.output.books_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[capture-auto] 출력: {out_dir}/{args.slug}")
    print(f"[capture-auto] count={args.count} interval={args.interval}s use_ocr={not args.no_ocr}")

    # ── Windows: 앱 경로 고정 → 미설치 시 자동설치 + 실행 후 캡처 ──
    if platform.system() == "Windows":
        from . import win_app
        bot = win_app.KyoboWinCapture(output_dir=str(out_dir), book_folder=args.slug)
        if getattr(args, "no_app", False):
            # 브라우저 캡처 모드: 데스크탑 앱(=DRM 파란화면) 대신 포그라운드(브라우저 wviewer)를
            # 그대로 화면캡처. 단, 캡처 전에 교보 웹뷰어(그 책)가 실제로 열려 있는지 확인.
            book_hint = args.slug.replace("_", " ").strip()
            win_title = win_app.find_kyobo_browser_window(book_hint)
            if not win_title:
                print(f"✗ 브라우저에 교보 웹뷰어가 보이지 않습니다.\n"
                      f"   「{book_hint}」 [바로보기]를 브라우저로 열어 화면에 띄운 뒤(전체화면) 다시 시작하세요.",
                      file=sys.stderr)
                return 1
            _n = lambda x: x.lower().replace(" ", "").replace("_", "")
            toks = [t for t in book_hint.split() if len(t) >= 2]
            book_ok = bool(toks) and sum(1 for t in toks if _n(t) in _n(win_title)) >= max(1, (len(toks) + 1) // 2)
            if book_ok:
                print(f"[capture-auto] ✓ 교보 웹뷰어(해당 책) 감지: {win_title}")
            else:
                print(f"[capture-auto] ⚠ 교보 웹뷰어 감지됨(책 제목 확인은 불가): {win_title} — 그대로 진행")
        else:
            # 검증: 교보 앱 실행 + 올바른 책이 열려 있는지 (창 제목으로)
            win_title = win_app.get_app_window_title()
            book_hint = args.slug.replace("_", " ").strip()
            if not bot.is_app_running():
                print(f"✗ 교보 eLibrary 앱이 실행 중이 아닙니다. 앱을 먼저 실행하고 "
                      f"「{book_hint}」 책을 펼친 뒤 다시 시작하세요.", file=sys.stderr)
                return 1
            if not win_title:
                print(f"✗ 교보 앱 창을 찾지 못했습니다(최소화/숨김?). 「{book_hint}」 책 창을 "
                      f"화면에 띄운 뒤 다시 시작하세요.", file=sys.stderr)
                return 1
            # 책 제목 일치 검사(느슨) — 핵심 토큰이 창 제목에 있는지
            _norm = lambda x: x.lower().replace(" ", "").replace("_", "")
            if _norm(book_hint) and _norm(book_hint) not in _norm(win_title):
                print(f"✗ 교보 앱에 다른 책이 열려 있습니다.\n"
                      f"   현재 창: {win_title}\n"
                      f"   필요한 책: {book_hint}\n"
                      f"   앱에서 「{book_hint}」 를 펼친 뒤 다시 시작하세요.", file=sys.stderr)
                return 1
            print(f"[capture-auto] ✓ 검증 통과 — 교보 창: {win_title}")
        bot.take_multiple_screenshots(
            count=args.count, interval=args.interval, auto_page_turn=True,
            start_page=args.start_page, continue_from_last=args.continue_from_last,
            use_ocr=not args.no_ocr, noninteractive=True,
            region=s.capture.region,
            next_key=(getattr(args, "next_key", None) or s.capture.next_key),
            no_crop=getattr(args, "no_app", False),   # 브라우저 전체화면 → 크롭 없이
        )
        return 0

    # ── Linux(X11): scrot 캡처 + xdotool →키 (브라우저 웹뷰어 전용) ──
    if platform.system() == "Linux":
        from . import linux_app
        if not getattr(args, "no_app", False):
            print("✗ Linux는 브라우저 웹뷰어 캡처(--no-app)만 지원합니다. "
                  "교보 [바로보기]를 Chrome 전체화면으로 띄운 뒤 시작하세요.", file=sys.stderr)
            return 1
        print("[capture-auto] 🐧 Linux X11 캡처 (scrot + xdotool) → 포그라운드(브라우저 웹뷰어)")
        linux_app.capture_book(
            str(out_dir), args.slug, args.count, args.interval,
            next_key=(getattr(args, "next_key", None) or s.capture.next_key or "right"),
            no_crop=True,
        )
        return 0

    # ── macOS: 기존 KyoboAppScreenshot ──
    from . import kyobo_app
    bot = kyobo_app.KyoboAppScreenshot(output_dir=str(out_dir), book_folder=args.slug)
    # 1. 책 + 창 이미 있으면 deep link 스킵 (다이얼로그 trigger 회피)
    has_window = bot.is_app_running() and bot.has_app_window()
    if has_window:
        print("[capture-auto] 책 창 이미 있음 — deep link 스킵 (다이얼로그 회피)")
    else:
        # 책 자동 열기 시도 (deep link) — 책 안 떠있는 경우만
        if getattr(args, "book_id", None):
            print(f"[capture-auto] book_id={args.book_id} deep link 시도")
            bot.open_book_by_id(args.book_id)
        # 본체 + 창 확보 fallback
        if not (bot.is_app_running() and bot.has_app_window()):
            print("[capture-auto] 교보eBook 창 확보 시도...")
            bot.launch_app()
    bot.take_multiple_screenshots(
        count=args.count,
        interval=args.interval,
        auto_page_turn=True,
        start_page=args.start_page,
        continue_from_last=args.continue_from_last,
        use_ocr=not args.no_ocr,
        noninteractive=True,
    )
    return 0


def _resolve_book_dir(args) -> Path:
    s = cfg.load(bridge_url=args.bridge)
    base = Path(s.output.books_dir).expanduser().resolve()
    if args.slug:
        return base / args.slug
    if args.book_dir:
        return Path(args.book_dir).expanduser().resolve()
    print("✗ --slug 또는 --book-dir 중 하나 필요", file=sys.stderr)
    sys.exit(2)


def cmd_ocr(args) -> int:
    s = cfg.load(bridge_url=args.bridge)
    book_dir = _resolve_book_dir(args)
    if not book_dir.exists():
        print(f"✗ 폴더 없음: {book_dir}", file=sys.stderr); return 2
    ocr_mod.ocr_book(book_dir, cfg=s.ocr, refresh=args.refresh)
    return 0


def cmd_merge(args) -> int:
    """batch_*.json 들 → pages_data.json + 챕터/섹션 트리."""
    book_dir = _resolve_book_dir(args)
    summary_dir = book_dir / "summary"
    if not summary_dir.exists():
        print(f"✗ summary 폴더 없음: {summary_dir}", file=sys.stderr); return 2
    try:
        merge_mod.merge_batches(summary_dir, fallback_title=args.slug or book_dir.name)
        return 0
    except Exception as e:
        print(f"✗ merge 실패: {e}", file=sys.stderr); return 1


def cmd_build(args) -> int:
    book_dir = _resolve_book_dir(args)
    if not book_dir.exists():
        print(f"✗ 폴더 없음: {book_dir}", file=sys.stderr); return 2
    build_html.build_index(book_dir, title=args.slug or book_dir.name)
    return 0


def cmd_summarize(args) -> int:
    """OCR 결과 → batch JSON (Claude/OpenAI API)."""
    s = cfg.load(bridge_url=args.bridge)
    book_dir = _resolve_book_dir(args)
    if not book_dir.exists():
        print(f"✗ 폴더 없음: {book_dir}", file=sys.stderr); return 2

    ocr_dir = book_dir / "summary" / "ocr_text"
    if not ocr_dir.exists():
        print(f"✗ OCR 결과 없음: {ocr_dir} — 먼저 `ocr` 서브커맨드 실행", file=sys.stderr); return 2

    # ocr_text/page_NNN.txt → {num: path}
    import re
    files: dict[int, "Path"] = {}
    for p in sorted(ocr_dir.glob("page_*.txt")):
        m = re.search(r"page_(\d+)\.txt$", p.name)
        if m:
            files[int(m.group(1))] = p
    if not files:
        print(f"✗ {ocr_dir} 에 page_*.txt 없음", file=sys.stderr); return 2

    page_range = None
    if args.pages:
        try:
            lo, hi = args.pages.split("-")
            page_range = (int(lo), int(hi))
        except Exception:
            print(f"✗ --pages 형식: 127-155 (받은 값: {args.pages})", file=sys.stderr); return 2

    out_path = book_dir / "summary" / (args.out or f"batch_{min(files):03d}.json")
    print(f"[summarize] 시작 · {len(files)} 페이지 · model={s.ai.model}")
    res = summarize_mod.summarize_pages(files, cfg=s.ai, out_path=out_path, page_range=page_range)
    print(f"\n결과: {res['pages_done']}건 성공, {len(res['errors'])}건 실패, "
          f"입력 {res['in_tok']} / 출력 {res['out_tok']} 토큰, ${res['cost_usd']:.3f}")
    return 0 if not res["errors"] else 1


def cmd_code(args) -> int:
    """페이지 이미지 → 언어별 소스코드 비전 추출 → summary/code_blocks.json (팝업 코드 패널용)."""
    s = cfg.load(bridge_url=args.bridge)
    book_dir = _resolve_book_dir(args)
    if not book_dir.exists():
        print(f"✗ 폴더 없음: {book_dir}", file=sys.stderr); return 2
    pages = None
    if getattr(args, "pages", None):
        pages = [int(x) for x in str(args.pages).replace("-", ",").split(",") if x.strip().isdigit()]
    res = code_mod.extract_code_blocks(book_dir, s.ai, pages=pages)
    return 0 if res.get("done") else 1


def cmd_worker(args) -> int:
    """백엔드 jobs 큐 polling — 한 번 띄워두면 [분석 시작] 클릭마다 자동 처리."""
    return worker_mod.run_worker(bridge=args.bridge, interval=args.interval)


def cmd_wviewer(args) -> int:
    """Phase #47 — 교보 e-library 웹뷰어 캡처 (매크로 화면 점유 X).

    sub-command:
      login    — 1회 헤드풀 Chromium 로 로그인 → 세션 저장
      status   — 저장된 세션 정보
      capture  — 저장된 세션으로 책 페이지 캡처 (--url 또는 --slug)
    """
    from . import wviewer as wv_mod

    if args.sub == "login":
        return wv_mod.login_interactive()

    if args.sub == "status":
        info = wv_mod.session_info()
        if info.get("ok"):
            print(f"✓ 세션 OK")
            print(f"  경로: {info['path']}")
            print(f"  저장: {info['saved_at']} ({info['age_days']}일 전)")
            print(f"  쿠키: {info['cookie_count']}개")
        else:
            print(f"✗ 세션 없음 또는 손상: {info.get('reason')}")
            print(f"  먼저: bookcapture wviewer login")
        return 0 if info.get("ok") else 1

    if args.sub == "capture":
        from pathlib import Path
        if not args.url:
            print("✗ --url 필요 (교보 e-library 책 뷰어 URL)", file=__import__('sys').stderr)
            return 1
        slug = args.slug or "untitled"
        out_dir = Path(args.out_dir) if args.out_dir else Path("books") / slug
        res = wv_mod.capture_book(
            book_url=args.url,
            out_dir=out_dir,
            max_pages=args.max_pages,
            delay_sec=args.delay,
            headless=not args.headful,
            progress=lambda i, n, msg: print(f"  [{i}/{n}] {msg}"),
        )
        print(f"\n결과: {res}")
        return 0 if res.get("ok") else 1

    if args.sub == "capture-lib":
        # Phase #47 정공법: e-library 통과 흐름
        from pathlib import Path
        if not args.salecmdtid:
            print("✗ --salecmdtid 필요 (책 식별자, 예: E000002921391)", file=__import__('sys').stderr)
            return 1
        slug = args.slug or args.salecmdtid
        out_dir = Path(args.out_dir) if args.out_dir else Path("books") / slug
        res = wv_mod.capture_via_library(
            salecmdtid=args.salecmdtid,
            slug=slug,
            out_dir=out_dir,
            max_pages=args.max_pages,
            delay_sec=args.delay,
            headless=not args.headful,
            progress=lambda i, n, msg: print(f"  [{i}/{n}] {msg}"),
        )
        print(f"\n결과: {res}")
        return 0 if res.get("ok") else 1

    if args.sub == "set-credentials":
        import getpass, sys as _sys
        email = args.email
        if not email:
            email = input("교보문고 이메일/ID: ").strip()
        if not email:
            print("✗ 이메일 필수", file=_sys.stderr); return 1

        if args.visible:
            # 평문 표시 모드 — 입력 한 번 (오타 확인 가능)
            print()
            print("⚠ 비밀번호가 화면에 표시됩니다 (--visible 모드)")
            pw = input(f"비밀번호 ({email}): ")
            if not pw:
                print("✗ 비밀번호 빈 값", file=_sys.stderr); return 1
        else:
            # 기본 안전 모드 — 안 보임 + 2회 확인
            print()
            print("(비밀번호 입력은 화면에 안 보입니다 — 평문 표시는 --visible 옵션)")
            pw = getpass.getpass(f"비밀번호 ({email}): ")
            if not pw:
                print("✗ 비밀번호 빈 값", file=_sys.stderr); return 1
            pw2 = getpass.getpass(f"비밀번호 확인 (다시): ")
            if pw != pw2:
                print("✗ 두 입력 불일치 — 다시 시도해주세요", file=_sys.stderr); return 1

        print()
        print("⏳ macOS Keychain 에 저장 중...")
        print("   (권한 팝업이 뜨면 [항상 허용] 클릭 — 다음부턴 launchd 워커도 자동 사용)")
        res = wv_mod.set_credentials(email, pw)
        if res.get("ok"):
            print(f"✓ 저장 완료: {res['email']} → Keychain '{res['keychain_service']}'")
            return 0
        print(f"✗ 실패: {res.get('reason')}", file=_sys.stderr); return 1

    if args.sub == "creds-status":
        s = wv_mod.credentials_status()
        if s.get("ok"):
            print(f"✓ 자격증명 등록됨")
            print(f"  email:           {s['email']}")
            print(f"  password length: {s['password_length']}자")
            print(f"  password:        {s['password_masked']} (마스킹)")
            print(f"  keychain:        {s['keychain_service']}")
            return 0
        print(f"✗ {s.get('reason')}"); return 1

    if args.sub == "clear-credentials":
        email = args.email if hasattr(args, 'email') else None
        res = wv_mod.clear_credentials(email)
        if res.get("ok"):
            print(f"✓ 삭제 완료: {res['email']}")
            return 0
        print(f"✗ {res.get('reason')}"); return 1

    if args.sub == "grant-permissions":
        # macOS 자동화 + 화면 기록 권한 트리거 (launchd 워커도 같은 Python binary 사용 → 권한 공유)
        import subprocess, os
        print("=" * 60)
        print("macOS 권한 트리거 (1회만)")
        print("=" * 60)
        print()
        print("▶ 1/2: System Events 자동화 권한 요청...")
        print("   (팝업 뜨면 [확인] 클릭)")
        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of every application process'],
                check=False, timeout=20, capture_output=True,
            )
            print("   ✓ osascript 호출 완료")
        except Exception as e:
            print(f"   ⚠ {e}")
        print()
        print("▶ 2/2: 화면 기록 권한 요청...")
        print("   (시스템 설정 → 개인정보 보호 및 보안 → 화면 기록 에서 Python 체크)")
        tmp = "/tmp/.kyobo-permcheck.png"
        try:
            subprocess.run(["/usr/sbin/screencapture", "-t", "png", "-x", tmp],
                           check=False, timeout=10, capture_output=True)
            if os.path.exists(tmp):
                os.remove(tmp)
            print("   ✓ screencapture 호출 완료")
        except Exception as e:
            print(f"   ⚠ {e}")
        print()
        print("─" * 60)
        print("권한 부여 후 한 번 더 이 명령 실행해서 ✓ 두 줄 모두 뜨면 OK")
        print("그 후 launchd 워커도 동일 권한 사용 가능")
        return 0

    print("sub-command 가 필요합니다: login / status / capture / capture-lib / set-credentials / creds-status / clear-credentials")
    return 1


def cmd_run(args) -> int:
    """capture → ocr → (summarize) → merge → build 일괄 (대화형)."""
    rc = cmd_capture(args)
    if rc != 0: return rc
    rc = cmd_ocr(args)
    if rc != 0: return rc
    if not getattr(args, "no_summarize", False):
        rc = cmd_summarize(args)
        if rc != 0: print(f"[run] summarize 일부 실패 (계속 진행)")
    if not getattr(args, "no_code", False):
        try:
            cmd_code(args)
        except Exception as e:
            print(f"[run] code 추출 실패 (계속 진행): {e}")
    rc = cmd_merge(args)
    if rc != 0: print(f"[run] merge 실패 (batch JSON 없음 가능) — placeholder HTML 만 생성")
    rc = cmd_build(args)
    return rc


def cmd_upload(args) -> int:
    """책 폴더의 PNG 들을 백엔드(/api/books/<slug>/upload)로 업로드.
    백엔드가 upload-process job 을 만들어 OCR/요약/빌드까지 처리한다.
    원격(Windows 등)에서 캡처만 하고 처리는 NAS 가 하는 하이브리드 핵심."""
    import sys as _sys, uuid, urllib.request
    from urllib.parse import quote
    book_dir = _resolve_book_dir(args)
    if not book_dir.exists():
        print(f"✗ 책 폴더 없음: {book_dir}", file=_sys.stderr); return 1
    exts = (".png", ".jpg", ".jpeg", ".webp")
    imgs = sorted(p for p in book_dir.iterdir() if p.suffix.lower() in exts)
    if not imgs:
        print(f"✗ 업로드할 이미지 없음: {book_dir}", file=_sys.stderr); return 1
    bridge = (args.bridge or cfg.DEFAULT_BRIDGE_URL).rstrip("/")
    slug = args.slug or book_dir.name
    url = f"{bridge}/api/books/{quote(slug)}/upload"
    print(f"[upload] {len(imgs)}장 → {url}")

    boundary = "----kyobo" + uuid.uuid4().hex
    body = bytearray()
    if getattr(args, "title", None):
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="title"\r\n\r\n'
        body += args.title.encode("utf-8") + b"\r\n"
    ctmap = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    for i, p in enumerate(imgs, 1):
        body += f"--{boundary}\r\n".encode()
        body += (f'Content-Disposition: form-data; name="files"; filename="{p.name}"\r\n'
                 f'Content-Type: {ctmap.get(p.suffix.lower(),"application/octet-stream")}\r\n\r\n').encode()
        body += p.read_bytes() + b"\r\n"
        if i % 10 == 0 or i == len(imgs):
            print(f"[upload] {i}/{len(imgs)} 인코딩")
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url, data=bytes(body), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            import json as _j
            r = _j.loads(resp.read().decode("utf-8"))
            print(f"[upload] ✓ {r.get('uploaded')}장 업로드 · 백엔드 job #{(r.get('job') or {}).get('id')} 등록 "
                  f"(이후 OCR/요약/빌드는 백엔드가 처리)")
            return 0
    except Exception as e:
        print(f"[upload] ✗ 실패: {e}", file=_sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bookcapture", description="교보 e-book 캡처·OCR·요약·빌드 파이프라인")
    p.add_argument("--bridge", help="백엔드 URL (기본: $KYOBO_BRIDGE_URL)")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("settings", help="현재 설정 출력").set_defaults(func=cmd_settings)

    pc = sub.add_parser("capture", help="기존 kyobo_app 캡처 인터랙티브")
    pc.add_argument("--mode", choices=["1", "2", "3"], help="1=전체 / 2=윈도우 / 3=연속")
    pc.set_defaults(func=cmd_capture)

    pca = sub.add_parser("capture-auto", help="비대화형 자동 캡처 (worker용)")
    pca.add_argument("--slug", required=True)
    pca.add_argument("--count", type=int, default=300)
    pca.add_argument("--interval", type=float, default=2.0)
    pca.add_argument("--start-page", type=int, default=1)
    pca.add_argument("--no-ocr", action="store_true")
    pca.add_argument("--continue-from-last", action="store_true")
    pca.add_argument("--book-id", help="salecmdtid — deep link 로 책 자동 열기")
    pca.add_argument("--no-app", action="store_true",
                     help="데스크탑 앱 검증/실행 스킵 → 포그라운드(브라우저 웹뷰어) 캡처. "
                          "교보 데스크탑 앱은 화면캡처 DRM 차단이지만 wviewer 웹뷰어는 캡처됨.")
    pca.add_argument("--next-key", default=None,
                     help="페이지 넘김 키 (right/left/space/pagedown/pageup/down). 미지정 시 설정값.")
    pca.set_defaults(func=cmd_capture_auto)

    pu = sub.add_parser("upload", help="책 폴더 PNG 를 백엔드로 업로드(원격 캡처→백엔드 처리)")
    pu.add_argument("--slug")
    pu.add_argument("--book-dir")
    pu.add_argument("--title")
    pu.set_defaults(func=cmd_upload)

    po = sub.add_parser("ocr", help="책 폴더 OCR")
    po.add_argument("--slug")
    po.add_argument("--book-dir")
    po.add_argument("--refresh", action="store_true")
    po.set_defaults(func=cmd_ocr)

    pm = sub.add_parser("merge", help="batch_*.json → pages_data.json (챕터/섹션 트리)")
    pm.add_argument("--slug")
    pm.add_argument("--book-dir")
    pm.set_defaults(func=cmd_merge)

    pb = sub.add_parser("build", help="HTML 빌드 (pages_data.json 있으면 본격, 없으면 placeholder)")
    pb.add_argument("--slug")
    pb.add_argument("--book-dir")
    pb.set_defaults(func=cmd_build)

    ps = sub.add_parser("summarize", help="OCR 결과 → batch JSON (Claude API)")
    ps.add_argument("--slug")
    ps.add_argument("--book-dir")
    ps.add_argument("--pages", help="페이지 범위 (예: 127-155)")
    ps.add_argument("--out", help="출력 파일명 (기본: batch_<첫페이지>.json)")
    ps.set_defaults(func=cmd_summarize)

    pc = sub.add_parser("code", help="페이지 이미지 → 언어별 소스코드 (Claude 비전) → code_blocks.json")
    pc.add_argument("--slug")
    pc.add_argument("--book-dir")
    pc.add_argument("--pages", help="페이지 목록 (예: 24,26,33) 또는 범위. 기본: 코드 자동감지")
    pc.set_defaults(func=cmd_code)

    pw = sub.add_parser("worker", help="백엔드 jobs 큐 polling (한 번 띄워두면 [분석 시작] 자동 처리)")
    pw.add_argument("--interval", type=float, default=2.0, help="polling 간격(초, 기본 2)")
    pw.set_defaults(func=cmd_worker)

    # Phase #47 — 웹뷰어 캡처
    pwv = sub.add_parser("wviewer", help="교보 e-library 웹뷰어 캡처 (매크로 없이, 화면 점유 X)")
    pwv_sub = pwv.add_subparsers(dest="sub")

    pwv_login = pwv_sub.add_parser("login", help="1회 헤드풀 Chromium 로 로그인 → 세션 저장")
    pwv_login.set_defaults(func=cmd_wviewer)

    pwv_status = pwv_sub.add_parser("status", help="저장된 세션 정보 표시")
    pwv_status.set_defaults(func=cmd_wviewer)

    pwv_cap = pwv_sub.add_parser("capture", help="세션 재사용 캡처 (--url 또는 --slug)")
    pwv_cap.add_argument("--url", required=True, help="책 뷰어 URL")
    pwv_cap.add_argument("--slug", help="책 슬러그 (기본 출력 폴더명)")
    pwv_cap.add_argument("--out-dir", help="출력 디렉토리 (기본: books/<slug>)")
    pwv_cap.add_argument("--max-pages", type=int, default=300)
    pwv_cap.add_argument("--delay", type=float, default=1.5, help="페이지 넘김 대기(초)")
    pwv_cap.add_argument("--headful", action="store_true", help="브라우저 창 보이기 (디버그용)")
    pwv_cap.set_defaults(func=cmd_wviewer)

    # 정공법: e-library 통과 흐름
    pwv_lib = pwv_sub.add_parser("capture-lib", help="e-library 페이지에서 [바로보기] 자동 클릭 → 캡처 (정공법, 화면 점유 X)")
    pwv_lib.add_argument("--salecmdtid", required=True, help="책 식별자 (예: E000002921391)")
    pwv_lib.add_argument("--slug", help="출력 폴더명 (기본: salecmdtid)")
    pwv_lib.add_argument("--out-dir")
    pwv_lib.add_argument("--max-pages", type=int, default=300)
    pwv_lib.add_argument("--delay", type=float, default=1.5)
    pwv_lib.add_argument("--headful", action="store_true", help="브라우저 창 보이기 (디버그용)")
    pwv_lib.set_defaults(func=cmd_wviewer)

    # 자격증명 (Keychain)
    pwv_set = pwv_sub.add_parser("set-credentials", help="교보 ID/PW 를 macOS Keychain 에 저장 (자동 재로그인용)")
    pwv_set.add_argument("--email", help="교보문고 이메일 (없으면 대화형 입력)")
    pwv_set.add_argument("--visible", action="store_true", help="비밀번호 입력 시 평문 표시 (오타 확인용)")
    pwv_set.set_defaults(func=cmd_wviewer)

    pwv_cs = pwv_sub.add_parser("creds-status", help="저장된 자격증명 정보 (마스킹)")
    pwv_cs.set_defaults(func=cmd_wviewer)

    pwv_cc = pwv_sub.add_parser("clear-credentials", help="Keychain 에서 자격증명 삭제")
    pwv_cc.add_argument("--email", help="대상 이메일 (없으면 default)")
    pwv_cc.set_defaults(func=cmd_wviewer)

    pwv_gp = pwv_sub.add_parser("grant-permissions", help="macOS 자동화·화면 기록 권한 트리거 (1회만, launchd 워커도 자동 사용)")
    pwv_gp.set_defaults(func=cmd_wviewer)

    pr = sub.add_parser("run", help="capture → ocr → summarize → build 일괄")
    pr.add_argument("--slug")
    pr.add_argument("--book-dir")
    pr.add_argument("--mode", choices=["1", "2", "3"], default="3")
    pr.add_argument("--refresh", action="store_true")
    pr.add_argument("--no-summarize", action="store_true", help="AI 요약 단계 스킵 (비용 0)")
    pr.add_argument("--no-code", action="store_true", help="소스코드 추출 단계 스킵 (비용 0)")
    pr.add_argument("--pages")
    pr.add_argument("--out")
    pr.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
