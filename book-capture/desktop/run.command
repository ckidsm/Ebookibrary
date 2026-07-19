#!/bin/bash
# 교보 캡처 앱 — 더블클릭 실행. book-capture/.venv 로 desktop.main 구동.
cd "$(dirname "$0")/.." || exit 1          # → book-capture/
PY=".venv/bin/python3"; [ -x "$PY" ] || PY="python3"
exec "$PY" -m desktop.main
