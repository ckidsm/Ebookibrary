#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# NAS 접속 공용 헬퍼 — publish_*.sh 가 `source` 해서 nas_ssh / nas_put 사용.
#
# 자동 폴백:  LAN(192.168.10.205:22) 먼저 시도 → 안 되면(VPN/외부망) **외부 2200**
#             (redcodeme.synology.me:2200). 둘 다 같은 SSH 키(id_ed25519_kyobo_nas).
# 인증:      NAS_PASS(또는 SSHPASS) 있으면 비번(sshpass), 없으면 **SSH 키(무비번, 기본)**.
# 강제 지정: NAS_SSH_HOST / NAS_SSH_PORT 로 오버라이드(예 다른 머신·프록시).
# 소유권:    웹 books 폴더 RedCode 소유(2026-07-19 정규화) → **sudo 불필요**.
# ─────────────────────────────────────────────────────────────
_NAS_USER="RedCode"
_NAS_KEY="${NAS_SSH_KEY:-$HOME/.ssh/id_ed25519_kyobo_nas}"
_NAS_HAS_PASS=""; [ -n "${NAS_PASS:-${SSHPASS:-}}" ] && _NAS_HAS_PASS=1
_NAS_PASSV="${NAS_PASS:-${SSHPASS:-}}"

# 한 번 접속되는지 probe (host port) — 키 또는 비번
_nas_probe() {
  local h="$1" p="$2"
  if [ -n "$_NAS_HAS_PASS" ]; then
    command -v sshpass >/dev/null || return 1
    SSHPASS="$_NAS_PASSV" sshpass -e ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
      -o PubkeyAuthentication=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 \
      -p "$p" "$_NAS_USER@$h" true 2>/dev/null
  else
    ssh -i "$_NAS_KEY" -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
      -p "$p" "$_NAS_USER@$h" true 2>/dev/null
  fi
}

# 호스트 선택: 강제 지정 > LAN > 외부 2200
if [ -n "${NAS_SSH_HOST:-}" ]; then
  _NAS_H="$NAS_SSH_HOST"; _NAS_P="${NAS_SSH_PORT:-22}"
elif _nas_probe 192.168.10.205 22; then
  _NAS_H="192.168.10.205"; _NAS_P="22"
else
  _NAS_H="redcodeme.synology.me"; _NAS_P="2200"
fi

# 접속 함수 (키/비번 분기, 둘 다 sudo 없음)
if [ -n "$_NAS_HAS_PASS" ]; then
  nas_ssh() { SSHPASS="$_NAS_PASSV" sshpass -e ssh -o ConnectTimeout=20 -o StrictHostKeyChecking=no \
      -o PubkeyAuthentication=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 \
      -p "$_NAS_P" "$_NAS_USER@$_NAS_H" "$@"; }
  nas_put() { SSHPASS="$_NAS_PASSV" sshpass -e ssh -o ConnectTimeout=20 -o StrictHostKeyChecking=no \
      -o PubkeyAuthentication=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 \
      -p "$_NAS_P" "$_NAS_USER@$_NAS_H" "cat > $1"; }
  _NAS_AUTH="비번"
else
  nas_ssh() { ssh -i "$_NAS_KEY" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=no \
      -p "$_NAS_P" "$_NAS_USER@$_NAS_H" "$@"; }
  nas_put() { ssh -i "$_NAS_KEY" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=no \
      -p "$_NAS_P" "$_NAS_USER@$_NAS_H" "cat > $1"; }
  _NAS_AUTH="SSH키"
fi

echo "[nas] 접속: $_NAS_USER@$_NAS_H:$_NAS_P ($_NAS_AUTH, sudo 없음)" >&2
