#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# KyoboCapture.app 빌드 — 래퍼 .app(실행파일=venv python 런처).
#
# 왜 py2app 아님: run_pipeline 이 sys.executable -m bookcapture 로 subprocess 를 띄우는데,
#   py2app 번들의 sys.executable 은 일반 python 이 아니라 앱 실행파일 → -m bookcapture 불가.
#   래퍼 .app 은 sys.executable=venv python 이라 subprocess 정상 + 아이콘 더블클릭·Terminal 없음.
# 서명: Apple Development(로컬용, TCC 권한 안정). Developer ID 발급 시 공증·배포 가능.
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."            # book-capture/
BOOKCAP="$(pwd)"
APP="desktop/KyoboCapture.app"
# 서명 인증서(기본: Apple Development deok soo yun). SIGN_IDENTITY 로 오버라이드, "-" 면 ad-hoc.
IDENTITY="${SIGN_IDENTITY:-46FF8B80175EFC0070F050FB944764BF3F168757}"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>교보 캡처</string>
  <key>CFBundleDisplayName</key><string>교보 캡처</string>
  <key>CFBundleIdentifier</key><string>me.redcode.kyobocapture</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSAppleEventsUsageDescription</key><string>교보 eBook 앱을 제어해 페이지를 넘기고 캡처합니다.</string>
  <key>NSScreenCaptureUsageDescription</key><string>교보 eBook 화면을 캡처해 도서를 분석합니다.</string>
</dict></plist>
PLIST

# 런처 — venv python 으로 desktop.main 실행. GUI 실행 시 PATH 가 빈약하므로 보강(tesseract/homebrew 등).
cat > "$APP/Contents/MacOS/launch" <<LAUNCH
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:\$PATH"
cd "$BOOKCAP" || exit 1
PY="$BOOKCAP/.venv/bin/python3"; [ -x "\$PY" ] || PY="python3"
exec "\$PY" -m desktop.main
LAUNCH
chmod +x "$APP/Contents/MacOS/launch"

# 서명 (하드런타임 X — 로컬 python/dylib 로드 위해). 인증서 실패 시 ad-hoc 폴백.
echo "🔏 서명: $IDENTITY"
if ! codesign --force --deep --sign "$IDENTITY" "$APP" 2>/dev/null; then
  echo "  (인증서 서명 실패 → ad-hoc 서명)"; codesign --force --deep --sign - "$APP"
fi
codesign --verify --verbose=1 "$APP" 2>&1 | head -2 || true
echo "✅ 빌드 완료: $BOOKCAP/$APP"
echo "   Finder 에서 더블클릭 → 첫 실행 시 화면기록·자동화 권한 허용"
