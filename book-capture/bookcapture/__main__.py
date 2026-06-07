"""python -m bookcapture 엔트리."""
# Windows 콘솔(cp949 등)에서 한글·em-dash·이모지 출력 시 UnicodeEncodeError 방지.
# stdout/stderr 를 UTF-8 로 강제 (워커는 자식 출력을 UTF-8 로 파이프로 읽음).
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .cli import main

raise SystemExit(main())
