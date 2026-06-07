#!/usr/bin/env bash
# bookcapture worker launchd 등록 해제 + plist 제거.
set -euo pipefail
LABEL="com.kyobolibrary.worker"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

c_g="\033[1;32m"; c_y="\033[1;33m"; c_x="\033[0m"

UID_GUI="gui/$(id -u)"
if launchctl print "$UID_GUI/$LABEL" >/dev/null 2>&1; then
    echo -e "${c_g}▶${c_x} launchctl bootout"
    launchctl bootout "$UID_GUI/$LABEL" 2>/dev/null || launchctl unload "$PLIST_PATH" 2>/dev/null || true
elif [[ -f "$PLIST_PATH" ]]; then
    echo -e "${c_g}▶${c_x} launchctl unload (legacy)"
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi
if [[ -f "$PLIST_PATH" ]]; then
    echo -e "${c_g}▶${c_x} plist 삭제: $PLIST_PATH"
    rm -f "$PLIST_PATH"
    echo -e "${c_g}✓${c_x} worker 등록 해제 완료"
else
    echo -e "${c_y}!${c_x} plist 없음: $PLIST_PATH (이미 해제됨)"
fi

# 혹시 직접 떠 있는 프로세스도 정리
if pkill -f "bookcapture.*worker" 2>/dev/null; then
    echo -e "${c_g}▶${c_x} 잔여 프로세스 종료"
fi
