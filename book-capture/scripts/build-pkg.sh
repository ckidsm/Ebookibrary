#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# build-pkg.sh — KyoboLibrary worker .pkg 빌드·사인·공증·staple
#
# 한 번 실행 → install/install-worker.pkg 산출
# 사용자는 .pkg 더블클릭 → 표준 macOS 인스톨러 UI → Gatekeeper 0회 차단
#
# 필요한 것 (사전 1회 설정):
#   1. Developer ID Application 인증서 (codesign)
#   2. Developer ID Installer 인증서 (productbuild --sign)
#   3. notarytool keychain profile "KYOBO_NOTARY"
#      → xcrun notarytool store-credentials "KYOBO_NOTARY" \
#           --apple-id <email> --team-id RRTB256N59
# ─────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOK_CAPTURE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$BOOK_CAPTURE_DIR/.." && pwd)"

PKG_DIR="$BOOK_CAPTURE_DIR/pkg"
PAYLOAD_ROOT="$PKG_DIR/payload-root"
SCRIPTS_DIR="$PKG_DIR/scripts"
RESOURCES_DIR="$PKG_DIR/resources"
DIST_XML="$PKG_DIR/distribution.xml"

VERSION="${PKG_VERSION:-1.0.0}"
IDENTIFIER="com.kyobolibrary.worker"
COMPONENT_PKG="/tmp/install-worker-component.pkg"

OUTPUT_DIR="$PROJECT_ROOT/install"
SIGNED_PKG="$OUTPUT_DIR/install-worker.pkg"

INSTALLER_CERT="Developer ID Installer: deok soo yun (RRTB256N59)"
NOTARY_PROFILE="${NOTARY_PROFILE:-KYOBO_NOTARY}"

c_g="\033[1;32m"; c_y="\033[1;33m"; c_r="\033[1;31m"; c_d="\033[2m"; c_x="\033[0m"
step() { echo -e "${c_g}▶${c_x} $*"; }
warn() { echo -e "${c_y}!${c_x} $*"; }
die()  { echo -e "${c_r}✗${c_x} $*" >&2; exit 1; }

# ─── 사전 점검 ────────────────────────────────────────────────
step "사전 점검"
[[ "$(uname)" == "Darwin" ]] || die "macOS 전용 (uname=$(uname))"
command -v pkgbuild >/dev/null     || die "pkgbuild 없음 (Xcode CLT 필요)"
command -v productbuild >/dev/null || die "productbuild 없음"
command -v xcrun >/dev/null         || die "xcrun 없음"

# Installer 인증서 확인 (basic policy 에 있어야 productbuild --sign 동작)
if ! security find-identity -v -p basic | grep -q "Developer ID Installer:"; then
    die "Developer ID Installer 인증서가 키체인에 없음"
fi

# notarytool profile 확인
if ! xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
    warn "notarytool profile '$NOTARY_PROFILE' 미확인 — 공증 단계에서 실패할 수 있음"
fi

# ─── 1) payload root 준비 ────────────────────────────────────
step "[1] payload root 준비"
mkdir -p "$PAYLOAD_ROOT/Library/Application Support/KyoboLibrary"
cat > "$PAYLOAD_ROOT/Library/Application Support/KyoboLibrary/INSTALLED_BY.txt" <<EOF
KyoboLibrary Worker installer marker.
Installed: $(date)
Version: $VERSION

The actual worker code lives in your OneDrive sync folder:
  ~/Library/CloudStorage/OneDrive-개인/Claude/NAS/KyoboLibrary/book-capture/

postinstall script registered the worker via launchd (com.kyobolibrary.worker).
To uninstall:
  ~/.../book-capture/scripts/uninstall-worker-macos.sh
EOF

# ─── 2) postinstall 실행권 보장 ───────────────────────────────
step "[2] postinstall 실행권"
chmod +x "$SCRIPTS_DIR/postinstall"

# ─── 3) install-worker-macos.sh 실행권 보장 (OneDrive 동기화 후 chmod) ───
step "[3] install-worker-macos.sh 실행권"
chmod +x "$BOOK_CAPTURE_DIR/scripts/install-worker-macos.sh"
chmod +x "$BOOK_CAPTURE_DIR/scripts/uninstall-worker-macos.sh"

# ─── 4) component .pkg 빌드 ──────────────────────────────────
step "[4] pkgbuild → $COMPONENT_PKG"
pkgbuild \
    --root "$PAYLOAD_ROOT" \
    --identifier "$IDENTIFIER" \
    --version "$VERSION" \
    --scripts "$SCRIPTS_DIR" \
    --install-location "/" \
    "$COMPONENT_PKG"

# ─── 5) distribution .pkg + 사인 ─────────────────────────────
mkdir -p "$OUTPUT_DIR"
step "[5] productbuild + Installer 사인 → $SIGNED_PKG"
# productbuild 는 component.pkg 를 같은 디렉토리에서 찾음
cp "$COMPONENT_PKG" "/tmp/install-worker-component.pkg" >/dev/null 2>&1 || true
productbuild \
    --distribution "$DIST_XML" \
    --package-path "/tmp" \
    --resources "$RESOURCES_DIR" \
    --sign "$INSTALLER_CERT" \
    "$SIGNED_PKG"

# ─── 6) 공증 (notarytool submit --wait) ──────────────────────
step "[6] notarytool submit (Apple 서버, 보통 1~5분)"
xcrun notarytool submit "$SIGNED_PKG" \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait

# ─── 7) staple (공증 결과를 .pkg 에 박기) ────────────────────
step "[7] stapler staple"
xcrun stapler staple "$SIGNED_PKG"

# ─── 8) 최종 검증 ────────────────────────────────────────────
step "[8] 최종 검증 (spctl)"
spctl --assess --type install -v "$SIGNED_PKG" 2>&1 | head -5

echo ""
echo -e "${c_g}✓ 완료${c_x}"
echo "   파일: $SIGNED_PKG"
echo "   크기: $(du -h "$SIGNED_PKG" | cut -f1)"
echo "   서명: $INSTALLER_CERT"
echo ""
echo "   배포: ./deploy.sh --static 로 install/install-worker.pkg 가 함께 동기화됩니다."
