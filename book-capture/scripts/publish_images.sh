#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 책 이미지(page_*.png + thumbs/) 를 NAS 웹폴더에 발행 — tar 스트리밍.
#
# rsync/scp 는 Synology 에서 자주 끊김 → tar 를 ssh 로 스트리밍 후 sudo 로 추출.
# 웹파일은 root 소유라 sudo 필요(RedCode 는 같은 비번으로 root sudo).
# 비번은 NAS_PASS(또는 SSHPASS) 환경변수 — 하드코딩 금지.
#
# 사용: NAS_PASS=... ./scripts/publish_images.sh <SLUG> [--raws]
#   기본: page_*.png + thumbs/*.png 발행(뷰어가 쓰는 이미지).
#   --raws: source_raws/*.png 도 함께(원본 서버 보관 규칙, 대용량).
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

SLUG="${1:-}"; shift || true
WITH_RAWS=0; [ "${1:-}" = "--raws" ] && WITH_RAWS=1
[ -n "$SLUG" ] || { echo "사용: NAS_PASS=... $0 <SLUG> [--raws]" >&2; exit 2; }
PASS="${NAS_PASS:-${SSHPASS:-}}"
[ -n "$PASS" ] || { echo "❌ NAS_PASS(또는 SSHPASS) 필요 (비번: 인증서/나스인증/)" >&2; exit 2; }
command -v sshpass >/dev/null || { echo "❌ sshpass 필요 (brew install sshpass)" >&2; exit 2; }

BOOK="books/$SLUG"
[ -d "$BOOK" ] || { echo "❌ 책 폴더 없음: $BOOK" >&2; exit 1; }
NAS_HOST="RedCode@192.168.10.205"
DST="/volume1/web/kyobo/books/$SLUG"
TMP="~/.pubimg_$SLUG.tar"

ssh_pw() { SSHPASS="$PASS" sshpass -e ssh -o ConnectTimeout=20 -o StrictHostKeyChecking=no \
  -o PubkeyAuthentication=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 "$NAS_HOST" "$@"; }

# tar 목록(존재하는 것만)
cd "$BOOK"
LIST=(); ls page_*.png >/dev/null 2>&1 && LIST+=(page_*.png)
[ -d thumbs ] && LIST+=(thumbs)
[ "$WITH_RAWS" = 1 ] && [ -d source_raws ] && LIST+=(source_raws)
[ ${#LIST[@]} -gt 0 ] || { echo "❌ 발행할 이미지 없음"; exit 1; }
echo "📦 tar 스트리밍: ${LIST[*]}  →  $DST"
cd - >/dev/null

# 1) 스트리밍 업로드
tar cf - -C "$BOOK" "${LIST[@]}" | SSHPASS="$PASS" sshpass -e ssh \
  -o ConnectTimeout=20 -o StrictHostKeyChecking=no -o PubkeyAuthentication=no \
  -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 "$NAS_HOST" "cat > $TMP"

# 2) sudo 추출 + 권한 (대상 폴더 없으면 생성 — 새 책 발행 대응)
ssh_pw "P='$PASS'
  echo \"\$P\" | sudo -S mkdir -p '$DST' 2>/dev/null
  echo \"\$P\" | sudo -S tar xpf $TMP -C '$DST' 2>/dev/null
  echo \"\$P\" | sudo -S chown -R root:root '$DST' 2>/dev/null
  echo \"\$P\" | sudo -S chmod -R a+rX '$DST' 2>/dev/null
  rm -f $TMP
  echo '  추출 완료:' ; ls '$DST'/page_001.png '$DST'/thumbs/page_001.png 2>/dev/null" 2>&1 | grep -v '^\[sudo\]' || true

echo "✅ 이미지 발행 완료: $SLUG"
