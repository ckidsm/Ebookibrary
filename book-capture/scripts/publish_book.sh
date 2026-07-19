#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 개별 도서 산출물(index.html·book_overview·code_blocks 등)을 NAS 웹폴더에 발행.
# 접속·인증은 nas_conn.sh(LAN→외부2200 자동, SSH키 무비번 기본, sudo 없음).
# 사용:  ./publish_book.sh <BOOK_SLUG> <FILE>...
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."                        # book-capture/
source "scripts/nas_conn.sh"

WEB_ROOT="/volume1/web/kyobo/books"
[[ $# -lt 2 ]] && { echo "사용: $0 <BOOK_SLUG> <FILE>..." >&2; exit 2; }
BOOK="$1"; shift
SUMMARY="$WEB_ROOT/$BOOK/summary"

echo "📖 발행 대상: $SUMMARY"
nas_ssh "mkdir -p '$SUMMARY'"

for f in "$@"; do
  [[ -f "$f" ]] || { echo "⚠ 로컬 파일 없음, 건너뜀: $f"; continue; }
  base="$(basename "$f")"
  case "$base" in
    index.html|page_extras.json|chapters.json|batch_*.json|pages_data.json|book_overview.json|code_blocks.json) ;;
    *.html) echo "  ⚠ '$base' 로 발행됨(index.html 아님). 의도 확인." >&2 ;;
  esac
  dst="$SUMMARY/$base"; tmp="~/.publish_$base"
  echo "  → $base ($(wc -c <"$f") bytes)"
  nas_put "$tmp" < "$f"
  nas_ssh "[ -f '$dst' ] && cp '$dst' '$dst.bak' 2>/dev/null; mv -f $tmp '$dst'; chmod 644 '$dst'"
done

echo "── 검증 ──"
nas_ssh "F='$SUMMARY/index.html'; if [ -f \"\$F\" ]; then printf 'index size: '; wc -c <\"\$F\"; printf 'chapters: '; grep -o 'chapter-summary\"' \"\$F\" | wc -l; fi" || true
echo "✅ 발행 완료. 라이브: https://redcodeme.synology.me/kyobo/books/$BOOK/summary/index.html"
