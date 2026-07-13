#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 워커 zip + 버전 파일을 NAS install/ 에 발행 → 워커가 5분 내 자동 업데이트.
# build-zip.sh 로 만든 install/bookcapture.zip·worker-version.txt 를 올린다.
#
# ⚠️ NAS LAN(192.168.10.x)에서만 됨 — 외부 SSH 22 미개방.
# 사용: NAS_PASS=... ./scripts/publish_worker.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(cd .. && pwd)"
ZIP="$ROOT/install/bookcapture.zip"
VER="$ROOT/install/worker-version.txt"
[ -f "$ZIP" ] && [ -f "$VER" ] || { echo "❌ install/ 산출물 없음 — 먼저 scripts/build-zip.sh 실행" >&2; exit 1; }
PASS="${NAS_PASS:-${SSHPASS:-}}"
[ -n "$PASS" ] || { echo "❌ NAS_PASS 필요 (인증서/나스인증/)" >&2; exit 2; }
command -v sshpass >/dev/null || { echo "❌ sshpass 필요" >&2; exit 2; }

HOST="RedCode@192.168.10.205"; DST="/volume1/web/kyobo/install"
O=(-o ConnectTimeout=20 -o StrictHostKeyChecking=no -o PubkeyAuthentication=no
   -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1)
echo "📦 워커 발행: $(cat "$VER")  →  $DST"
SSHPASS="$PASS" sshpass -e ssh "${O[@]}" "$HOST" "cat > ~/.bcw.zip" < "$ZIP"
SSHPASS="$PASS" sshpass -e ssh "${O[@]}" "$HOST" "cat > ~/.bcw.ver" < "$VER"
SSHPASS="$PASS" sshpass -e ssh "${O[@]}" "$HOST" "P='$PASS'
  echo \"\$P\" | sudo -S mkdir -p '$DST' 2>/dev/null
  echo \"\$P\" | sudo -S cp ~/.bcw.zip '$DST/bookcapture.zip' 2>/dev/null
  echo \"\$P\" | sudo -S cp ~/.bcw.ver '$DST/worker-version.txt' 2>/dev/null
  echo \"\$P\" | sudo -S chmod 644 '$DST/bookcapture.zip' '$DST/worker-version.txt' 2>/dev/null
  rm -f ~/.bcw.zip ~/.bcw.ver
  echo '서버 버전:'; cat '$DST/worker-version.txt'" 2>&1 | grep -v '^\[sudo\]' || true
echo "✅ 워커 발행 완료 — Mac 워커가 5분 내 자동 업데이트(또는 즉시: launchctl kickstart -k gui/\$UID/com.kyobolibrary.worker)"
