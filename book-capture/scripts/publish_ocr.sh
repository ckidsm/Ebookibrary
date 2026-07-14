#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# summary/ocr_text/ 폴더를 NAS 에 발행 — 뷰어 모달의 '📄 OCR 텍스트' 패널이 fetch 하는 파일.
# (index/code_blocks 만 올리고 ocr_text 폴더를 빠뜨려 OCR 패널이 404 로 비던 버그 수정, 2026-07-14.)
# tar 스트리밍(Synology rsync 불안정 회피). NAS_PASS 필요.
# 사용: NAS_PASS=... ./scripts/publish_ocr.sh <SLUG>
#   외부: NAS_SSH_HOST=redcode@redcodeme.synology.me NAS_SSH_PORT=2200
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
SLUG="${1:-}"
[ -n "$SLUG" ] || { echo "사용: NAS_PASS=... $0 <SLUG>" >&2; exit 2; }
SRC="books/$SLUG/summary/ocr_text"
[ -d "$SRC" ] || { echo "ℹ ocr_text 없음(스킵): $SRC"; exit 0; }
PASS="${NAS_PASS:-${SSHPASS:-}}"
[ -n "$PASS" ] || { echo "❌ NAS_PASS 필요" >&2; exit 2; }
command -v sshpass >/dev/null || { echo "❌ sshpass 필요" >&2; exit 2; }

HOST="${NAS_SSH_HOST:-RedCode@192.168.10.205}"; PORT="${NAS_SSH_PORT:-22}"
DST="/volume1/web/kyobo/books/$SLUG/summary"
O=(-p "$PORT" -o ConnectTimeout=20 -o StrictHostKeyChecking=no -o PubkeyAuthentication=no
   -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1)
n=$(ls "$SRC"/*.txt 2>/dev/null | wc -l | tr -d ' ')
echo "📄 OCR 텍스트 발행: ${n}개 → $DST/ocr_text"
tar cf - -C "books/$SLUG/summary" ocr_text | SSHPASS="$PASS" sshpass -e ssh "${O[@]}" "$HOST" "cat > ~/.ocr_$SLUG.tar"
SSHPASS="$PASS" sshpass -e ssh "${O[@]}" "$HOST" "P='$PASS'
  echo \"\$P\" | sudo -S mkdir -p '$DST' 2>/dev/null
  echo \"\$P\" | sudo -S tar xpf ~/.ocr_$SLUG.tar -C '$DST' 2>/dev/null
  echo \"\$P\" | sudo -S chmod -R a+rX '$DST/ocr_text' 2>/dev/null
  rm -f ~/.ocr_$SLUG.tar" 2>&1 | grep -v '^\[sudo\]' || true
echo "✅ OCR 텍스트 발행 완료: $SLUG"
