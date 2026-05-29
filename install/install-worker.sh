#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Kyobo Library Worker · 원클릭 설치 (curl | bash)
#
# 사용:
#   curl -fsSL http://192.168.10.205:8080/install/install-worker.sh | bash
#
# (read 없음 → pipe 안전. .command 파일과 달리 stdin 닫혀도 OK)
# ─────────────────────────────────────────────────────────────

set -e

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  📚  Kyobo Library Worker · 자동 설치                       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# 1) OneDrive 안 book-capture 자동 탐색
CANDIDATES=(
    "$HOME/Library/CloudStorage/OneDrive-개인/Claude/NAS/KyoboLibrary/book-capture"
    "$HOME/Library/CloudStorage/OneDrive-Personal/Claude/NAS/KyoboLibrary/book-capture"
    "$HOME/OneDrive/Claude/NAS/KyoboLibrary/book-capture"
    "$HOME/OneDrive - Personal/Claude/NAS/KyoboLibrary/book-capture"
)

BC_DIR=""
for c in "${CANDIDATES[@]}"; do
    if [[ -d "$c" ]]; then BC_DIR="$c"; break; fi
done

if [[ -z "$BC_DIR" ]]; then
    echo "✗ book-capture 폴더를 못 찾았습니다. 시도한 경로:"
    for c in "${CANDIDATES[@]}"; do echo "    - $c"; done
    echo ""
    echo "OneDrive 동기화 완료 또는 NAS/KyoboLibrary 다운로드 확인 후 다시 시도."
    exit 1
fi

echo "✓ book-capture 발견: $BC_DIR"

# 2) 실행권 확인 (OneDrive·rsync 후 권한 손실 가능)
INSTALLER="$BC_DIR/scripts/install-worker-macos.sh"
if [[ ! -x "$INSTALLER" ]]; then
    chmod +x "$INSTALLER" 2>/dev/null || true
fi
if [[ ! -x "$INSTALLER" ]]; then
    echo "✗ 실행권한 부여 실패: $INSTALLER"
    echo "  수동으로 한 번: chmod +x \"$INSTALLER\""
    exit 1
fi

# 3) 메인 설치
echo "▶ 메인 설치 스크립트 실행"
echo ""
"$INSTALLER"

echo ""
echo "════════════════════════════════════════════════════════"
echo "✓ 설치 완료. 메인 페이지로 가서 [📊 분석 시작] 누르면 자동 처리됩니다."
echo "  http://192.168.10.205:8080/"
echo "════════════════════════════════════════════════════════"
