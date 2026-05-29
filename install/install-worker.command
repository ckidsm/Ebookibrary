#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Kyobo Library Worker — 자동 설치 (macOS, 더블클릭)
#
# 다운로드 후 더블클릭 → Terminal 이 자동으로 이 파일을 실행
# 첫 실행 시 macOS Gatekeeper 가 막으면:
#   파일 우클릭 → "열기" → 경고 무시하고 "열기" 한 번
#   (이후 더블클릭으로 정상 동작)
# ─────────────────────────────────────────────────────────────

clear
cat <<'BANNER'
╔════════════════════════════════════════════════════════════╗
║                                                            ║
║       📚  Kyobo Library Worker · 자동 설치                  ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝

이 스크립트가 자동으로 처리합니다:
  ① OneDrive 안 book-capture 폴더 자동 탐색
  ② Python venv 생성 + Pillow/pytesseract 설치
  ③ Homebrew 가 있으면 tesseract 자동 설치
  ④ launchd 자동 등록 (재부팅해도 자동 시작)
  ⑤ 즉시 백그라운드 시작

설치 후엔 메인 페이지 카드의 [📊 분석 시작] 으로
바로 분석이 시작됩니다.

BANNER

set -e

# 1) OneDrive 안 book-capture 자동 탐색
CANDIDATES=(
    "$HOME/Library/CloudStorage/OneDrive-개인/Claude/NAS/KyoboLibrary/book-capture"
    "$HOME/Library/CloudStorage/OneDrive-Personal/Claude/NAS/KyoboLibrary/book-capture"
    "$HOME/OneDrive/Claude/NAS/KyoboLibrary/book-capture"
    "$HOME/OneDrive - Personal/Claude/NAS/KyoboLibrary/book-capture"
)

BC_DIR=""
for c in "${CANDIDATES[@]}"; do
    if [[ -d "$c" ]]; then
        BC_DIR="$c"
        break
    fi
done

if [[ -z "$BC_DIR" ]]; then
    echo "✗ book-capture 폴더를 찾지 못했습니다."
    echo "  다음 경로 후보를 확인했지만 모두 없음:"
    for c in "${CANDIDATES[@]}"; do echo "    - $c"; done
    echo ""
    echo "OneDrive 동기화가 완료됐는지, 또는 NAS/KyoboLibrary 가 실제로 다운된 상태인지 확인해주세요."
    echo ""
    read -n 1 -s -r -p "엔터를 누르면 창이 닫힙니다... "
    exit 1
fi

echo "✓ book-capture 폴더 발견:"
echo "  $BC_DIR"
echo ""

# 2) install-worker-macos.sh 호출
INSTALLER="$BC_DIR/scripts/install-worker-macos.sh"
if [[ ! -x "$INSTALLER" ]]; then
    echo "✗ 설치 스크립트가 없습니다: $INSTALLER"
    echo "  OneDrive 동기화 누락 가능성. 잠시 후 다시 시도하세요."
    read -n 1 -s -r -p "엔터를 누르면 창이 닫힙니다... "
    exit 1
fi

echo "▶ 메인 설치 스크립트 실행: $INSTALLER"
echo ""
"$INSTALLER"

echo ""
echo "════════════════════════════════════════════════════════"
echo "✓ 설치 완료. 이 터미널 창은 닫아도 됩니다."
echo "  메인 페이지로 돌아가 카드 클릭 → [📊 분석 시작] 누르면"
echo "  worker 가 자동으로 잡아 진행합니다."
echo "════════════════════════════════════════════════════════"
echo ""
read -n 1 -s -r -p "엔터를 누르면 창이 닫힙니다... "
