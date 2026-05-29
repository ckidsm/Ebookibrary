#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# macOS launchd 로 bookcapture worker 자동 등록.
# 한 번 실행하면:
#   1) venv 자동 생성·deps 설치 (없을 때만)
#   2) tesseract 설치 권유 (Homebrew 가 있으면 자동)
#   3) ~/Library/LaunchAgents/com.kyobolibrary.worker.plist 생성
#   4) launchctl load → 즉시 백그라운드 시작
#   5) Mac 재부팅 시에도 자동 시작 (KeepAlive)
#
# 정지·제거: uninstall-worker-macos.sh
# ─────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOK_CAPTURE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

LABEL="com.kyobolibrary.worker"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/kyobo-library"
VENV_DIR="$BOOK_CAPTURE_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"

c_g="\033[1;32m"; c_y="\033[1;33m"; c_r="\033[1;31m"; c_x="\033[0m"
step() { echo -e "${c_g}▶${c_x} $*"; }
warn() { echo -e "${c_y}!${c_x} $*"; }
die()  { echo -e "${c_r}✗${c_x} $*" >&2; exit 1; }

# 0) 사전 점검
[[ "$(uname)" == "Darwin" ]] || die "macOS 전용 (uname=$(uname))"
command -v python3 >/dev/null || die "python3 필요 (Homebrew: brew install python@3.13)"

# 1) venv
if [[ ! -x "$VENV_PY" ]]; then
    step "venv 생성: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
    "$VENV_PY" -m pip install --quiet --upgrade pip
    step "의존성 설치 (Pillow, pytesseract)"
    "$VENV_PY" -m pip install --quiet -r "$BOOK_CAPTURE_DIR/requirements.txt"
else
    step "venv 이미 존재: $VENV_DIR"
fi

# 2) tesseract 점검
if ! command -v tesseract >/dev/null; then
    if command -v brew >/dev/null; then
        warn "tesseract 미설치 — Homebrew 로 설치 시도 (시간 좀 걸림)"
        brew install tesseract tesseract-lang || warn "tesseract 설치 실패 (수동: brew install tesseract tesseract-lang)"
    else
        warn "tesseract 미설치. OCR 기능 안 됨. 'brew install tesseract tesseract-lang' 권장"
    fi
fi

# 3) launchd plist 생성
step "launchd plist 생성: $PLIST_PATH"
mkdir -p "$PLIST_DIR" "$LOG_DIR"
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PY</string>
        <string>-m</string>
        <string>bookcapture</string>
        <string>worker</string>
        <string>--interval</string>
        <string>2</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$BOOK_CAPTURE_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/worker.out.log</string>

    <key>StandardErrorPath</key>
    <string>$LOG_DIR/worker.err.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>LANG</key>
        <string>ko_KR.UTF-8</string>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
EOF

# 4) 기존 등록 정리 후 로드
if launchctl list | grep -q "$LABEL"; then
    step "기존 등록 해제"
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi
step "launchd 등록 + 즉시 시작"
launchctl load -w "$PLIST_PATH"

sleep 1
step "상태"
if launchctl list | grep -q "$LABEL"; then
    pid=$(launchctl list | awk -v l="$LABEL" '$3==l {print $1}')
    echo "   PID: ${pid:-unknown}"
    echo "   로그: $LOG_DIR/worker.out.log"
    echo "   plist: $PLIST_PATH"
    echo
    echo -e "${c_g}✓ worker 백그라운드 등록 완료${c_x}"
    echo "   Mac 재부팅 시에도 자동 시작됩니다."
    echo "   정지·제거: $SCRIPT_DIR/uninstall-worker-macos.sh"
else
    die "등록 실패 — launchctl list | grep $LABEL"
fi
