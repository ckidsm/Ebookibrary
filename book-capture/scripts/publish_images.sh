#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 책 이미지(page_*.png + thumbs/) 를 NAS 웹폴더에 발행 — tar 스트리밍.
# 접속은 nas_conn.sh(LAN→외부2200 자동, SSH키 무비번, sudo 없음).
# 사용: ./scripts/publish_images.sh <SLUG> [--raws]
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
source "scripts/nas_conn.sh"

SLUG="${1:-}"; shift || true
WITH_RAWS=0; [ "${1:-}" = "--raws" ] && WITH_RAWS=1
[ -n "$SLUG" ] || { echo "사용: $0 <SLUG> [--raws]" >&2; exit 2; }

BOOK="books/$SLUG"
[ -d "$BOOK" ] || { echo "❌ 책 폴더 없음: $BOOK" >&2; exit 1; }
DST="/volume1/web/kyobo/books/$SLUG"
TMP="~/.pubimg_$SLUG.tar"

cd "$BOOK"
LIST=(); ls page_*.png >/dev/null 2>&1 && LIST+=(page_*.png)
[ -d thumbs ] && LIST+=(thumbs)
[ "$WITH_RAWS" = 1 ] && [ -d source_raws ] && LIST+=(source_raws)
[ ${#LIST[@]} -gt 0 ] || { echo "❌ 발행할 이미지 없음"; exit 1; }
echo "📦 tar 스트리밍: ${LIST[*]}  →  $DST"
cd - >/dev/null

# 1) 스트리밍 업로드
tar cf - -C "$BOOK" "${LIST[@]}" | nas_ssh "cat > $TMP"
# 2) 추출(sudo 없음 — RedCode 소유). 대상 없으면 생성.
nas_ssh "mkdir -p '$DST'
  tar xpf $TMP -C '$DST'
  chmod -R a+rX '$DST'
  rm -f $TMP
  echo '  추출 완료:'; ls '$DST'/page_001.png '$DST'/thumbs/page_001.png 2>/dev/null" || true

echo "✅ 이미지 발행 완료: $SLUG"
