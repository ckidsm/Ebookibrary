#!/usr/bin/env bash
# 교보 라이브러리 워커 — macOS 원클릭 설치
# 사용:  curl -fsSL https://redcodeme.synology.me/kyobo/setup-mac.sh | bash
set -e
BASE="https://redcodeme.synology.me/kyobo"
echo "===== 교보 라이브러리 워커 설치 (macOS) ====="

command -v python3 >/dev/null || { echo "✗ python3 필요 — brew install python@3.13"; exit 1; }

# 최신 워커 코드 다운로드 + 압축해제
echo "▶ 최신 워커 코드 다운로드"
mkdir -p "$HOME/kyobo"
curl -fsSL -o /tmp/book-capture.zip "$BASE/book-capture.zip"
rm -rf "$HOME/kyobo/book-capture"
unzip -oq /tmp/book-capture.zip -d "$HOME/kyobo"

# launchd 설치 스크립트 실행 (venv·deps·plist·자동시작)
echo "▶ 워커 설치 (venv · launchd 자동시작)"
bash "$HOME/kyobo/book-capture/scripts/install-worker-macos.sh"

echo ""
echo "===== ✅ 완료 ====="
echo "남은 것: Tampermonkey 유저스크립트 + 교보 [바로보기] 화면에 띄우기"
echo "관리: launchctl list | grep kyobolibrary · 로그는 설치 스크립트 안내 참고"
