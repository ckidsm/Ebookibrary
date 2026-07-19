#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# summary/ocr_text/ 폴더를 NAS 에 발행 — 뷰어 모달 '📄 OCR 텍스트' 패널이 fetch.
# 접속은 nas_conn.sh(LAN→외부2200 자동, SSH키 무비번, sudo 없음).
# 사용: ./scripts/publish_ocr.sh <SLUG>
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
source "scripts/nas_conn.sh"

SLUG="${1:-}"
[ -n "$SLUG" ] || { echo "사용: $0 <SLUG>" >&2; exit 2; }
SRC="books/$SLUG/summary/ocr_text"
[ -d "$SRC" ] || { echo "ℹ ocr_text 없음(스킵): $SRC"; exit 0; }
DST="/volume1/web/kyobo/books/$SLUG/summary"

n=$(ls "$SRC"/*.txt 2>/dev/null | wc -l | tr -d ' ')
echo "📄 OCR 텍스트 발행: ${n}개 → $DST/ocr_text"
tar cf - -C "books/$SLUG/summary" ocr_text | nas_ssh "cat > ~/.ocr_$SLUG.tar"
nas_ssh "mkdir -p '$DST'
  tar xpf ~/.ocr_$SLUG.tar -C '$DST'
  chmod -R a+rX '$DST/ocr_text'
  rm -f ~/.ocr_$SLUG.tar" || true
echo "✅ OCR 텍스트 발행 완료: $SLUG"
