"""bookcapture — 교보 e-book 캡처 → OCR → 요약 → HTML 빌드 파이프라인.

기존 자산 이식:
- kyobo_app.py     ← SRC/python/kyobo_screenshot/kyobo_app_screenshot.py (817줄)
- ocr.py           ← books/CLI_완전활용/summary/verify_ocr.py 패턴
- build_html.py    ← books/CLI_완전활용/summary/generate_html.py 패턴 (Phase C-3에서 채움)

신규:
- settings.py      ← /api/settings HTTP 로드 + 환경변수 우선
- cli.py           ← 통합 진입점 (python -m bookcapture ...)
- summarize.py     ← AI 요약 (Phase C-3)
- worker.py        ← 백엔드 큐 polling (Phase C-3)
"""

__version__ = "0.1.0"
