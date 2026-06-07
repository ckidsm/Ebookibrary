#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Kyobo Library Worker — 다시 시작 (macOS, 더블클릭)
#
# 이미 한 번 설치된 워커가 멈췄을 때 더블클릭 → 자동 재시작
# Gatekeeper 경고: 파일 우클릭 → "열기" 한 번
# ─────────────────────────────────────────────────────────────

clear
cat <<'BANNER'
╔════════════════════════════════════════════════════════════╗
║       ▶  Kyobo Library Worker · 다시 시작                   ║
╚════════════════════════════════════════════════════════════╝

이미 등록된 워커를 다시 시작합니다.
한 번도 설치한 적 없다면 install-worker.command 를 받으세요.

BANNER

LABEL="com.kyobolibrary.worker"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_GUI="gui/$(id -u)"

if [[ ! -f "$PLIST_PATH" ]]; then
    echo "✗ plist 파일이 없습니다: $PLIST_PATH"
    echo "  처음이라면 install-worker.command 부터 받으세요."
    echo ""
    read -n 1 -s -r -p "엔터를 누르면 창이 닫힙니다... "
    exit 1
fi

echo "✓ plist 발견: $PLIST_PATH"

# 이미 등록되어 있으면 한 번 떼고 다시
if launchctl print "$UID_GUI/$LABEL" >/dev/null 2>&1; then
    echo "▶ 기존 등록 해제 (bootout)"
    launchctl bootout "$UID_GUI/$LABEL" 2>/dev/null || true
fi

echo "▶ 다시 등록 (bootstrap)"
if launchctl bootstrap "$UID_GUI" "$PLIST_PATH" 2>/dev/null; then
    echo "✓ 워커 시작됨"
else
    echo "! bootstrap 실패 — legacy load 시도"
    launchctl load -w "$PLIST_PATH" || {
        echo "✗ 모든 등록 방식 실패. 진단:"
        echo "    launchctl print $UID_GUI/$LABEL"
        read -n 1 -s -r -p "엔터를 누르면 창이 닫힙니다... "
        exit 1
    }
fi

sleep 1

# 상태 확인
if launchctl print "$UID_GUI/$LABEL" >/dev/null 2>&1; then
    pid=$(launchctl print "$UID_GUI/$LABEL" 2>/dev/null | awk '/pid =/ {print $3; exit}')
    echo "✓ 동작 중 (PID: ${pid:-unknown})"
elif launchctl list 2>/dev/null | grep -q "$LABEL"; then
    pid=$(launchctl list | awk -v l="$LABEL" '$3==l {print $1}')
    echo "✓ 동작 중 (PID: ${pid:-unknown}, legacy 모드)"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "✓ 메인 페이지로 돌아가 새로고침하면 워커 살아있음 표시."
echo "════════════════════════════════════════════════════════"
echo ""
read -n 1 -s -r -p "엔터를 누르면 창이 닫힙니다... "
