#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# KyoboCapture.app 배포용 재서명(하드런타임) + Apple 공증 + 스테이플.
#
# 로컬 실행용 서명은 build_app.sh(하드런타임 X). 이 스크립트는 **다른 맥 배포**용:
#   1) Developer ID + 하드런타임(--options runtime) + 보안 타임스탬프 + 엔타이틀먼트 재서명
#   2) zip 으로 묶어 notarytool 제출(--wait)
#   3) 승인되면 stapler 로 티켓 첨부(오프라인 Gatekeeper 통과)
#
# 선행: xcrun notarytool store-credentials KYOBO_NOTARY (앱 암호 등록) — README 참고.
# 사용: bash desktop/notarize.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."            # book-capture/
BOOKCAP="$(pwd)"
APP="desktop/KyoboCapture.app"
ENT="desktop/entitlements.plist"
PROFILE="${NOTARY_PROFILE:-KYOBO_NOTARY}"
IDENTITY="${SIGN_IDENTITY:-Developer ID Application: deok soo yun (RRTB256N59)}"
ZIP="desktop/KyoboCapture.zip"

[ -d "$APP" ] || { echo "❌ 앱 없음: $APP — 먼저 build_app.sh 실행" >&2; exit 1; }

echo "① 하드런타임 재서명: $IDENTITY"
codesign --force --deep --timestamp --options runtime \
  --entitlements "$ENT" \
  --sign "$IDENTITY" "$APP"
codesign --verify --strict --verbose=2 "$APP" 2>&1 | tail -3
echo "  하드런타임 플래그:"; codesign -dvv "$APP" 2>&1 | grep -i "flags\|runtime\|timestamp" | head -3

echo "② zip 생성 → 공증 제출(승인까지 대기)"
rm -f "$ZIP"
/usr/bin/ditto -c -k --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait 2>&1 | tee /tmp/kyobo_notary.log

# 제출 실패/거부 시 로그 안내
if grep -qi "Invalid\|Rejected" /tmp/kyobo_notary.log; then
  SID=$(grep -o 'id: [0-9a-f-]*' /tmp/kyobo_notary.log | head -1 | awk '{print $2}')
  echo "⚠️ 공증 거부/실패. 상세 로그:"
  echo "   xcrun notarytool log $SID --keychain-profile $PROFILE"
  exit 1
fi

echo "③ 스테이플(티켓 첨부)"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP" 2>&1 | tail -2
spctl -a -vvv --type execute "$APP" 2>&1 | tail -3 || true
rm -f "$ZIP"
echo "✅ 공증 완료: $BOOKCAP/$APP (다른 맥에서 다운로드해도 Gatekeeper 경고 없음)"
