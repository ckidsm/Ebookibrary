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

# ⚠️ install/ 은 두 곳(워커가 bridge 에 따라 다른 base 에서 받음) — 둘 다 발행해야 함:
#   1) /volume1/web/kyobo/install         → 외부 https://redcodeme.synology.me/kyobo/install (Web Station)
#   2) /volume1/docker/web-apps/kyobo-library/install → LAN http://192.168.10.205:8080/install (nginx)
# 외부 SSH 는 -p 2200 redcode@redcodeme.synology.me (포트 22 미개방). VPN LAN 은 192.168.10.205:22.
HOST="${NAS_SSH_HOST:-RedCode@192.168.10.205}"; PORT="${NAS_SSH_PORT:-22}"
DSTS=("/volume1/web/kyobo/install" "/volume1/docker/web-apps/kyobo-library/install")
O=(-p "$PORT" -o ConnectTimeout=20 -o StrictHostKeyChecking=no -o PubkeyAuthentication=no
   -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1)
echo "📦 워커 발행: $(cat "$VER")  →  $HOST:$PORT (install ×${#DSTS[@]})"
SSHPASS="$PASS" sshpass -e ssh "${O[@]}" "$HOST" "cat > ~/.bcw.zip" < "$ZIP"
SSHPASS="$PASS" sshpass -e ssh "${O[@]}" "$HOST" "cat > ~/.bcw.ver" < "$VER"
for DST in "${DSTS[@]}"; do
  SSHPASS="$PASS" sshpass -e ssh "${O[@]}" "$HOST" "P='$PASS'
    echo \"\$P\" | sudo -S mkdir -p '$DST' 2>/dev/null
    echo \"\$P\" | sudo -S cp ~/.bcw.zip '$DST/bookcapture.zip' 2>/dev/null
    echo \"\$P\" | sudo -S cp ~/.bcw.ver '$DST/worker-version.txt' 2>/dev/null
    echo \"\$P\" | sudo -S chmod 644 '$DST/bookcapture.zip' '$DST/worker-version.txt' 2>/dev/null
    echo '  $DST →' \$(cat '$DST/worker-version.txt')" 2>&1 | grep -v '^\[sudo\]' || true
done
SSHPASS="$PASS" sshpass -e ssh "${O[@]}" "$HOST" "rm -f ~/.bcw.zip ~/.bcw.ver" 2>&1 | grep -v '^\[sudo\]' || true
echo "✅ 워커 발행 완료(양쪽) — 워커가 5분 내 자동 업데이트(즉시: launchctl kickstart -k gui/\$UID/com.kyobolibrary.worker)"
