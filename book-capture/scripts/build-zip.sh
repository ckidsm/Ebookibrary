#!/bin/bash
# 워커 배포 zip + 버전 파일 생성 (자동 업데이트용).
# version = 소스(.py)+requirements 해시 → 코드 바뀌면 버전 바뀜 → 워커 자동 업데이트.
set -e
SD="$(cd "$(dirname "$0")" && pwd)"
BC="$(cd "$SD/.." && pwd)"          # book-capture/
ROOT="$(cd "$BC/.." && pwd)"        # KyoboLibrary/
cd "$BC"

# 버전 = .py + requirements 해시 (_version.txt 자신은 제외)
SRC="$(cat bookcapture/*.py requirements.txt 2>/dev/null)"
if command -v md5 >/dev/null 2>&1; then
    VER="$(printf '%s' "$SRC" | md5 -q)"
else
    VER="$(printf '%s' "$SRC" | md5sum | cut -d' ' -f1)"
fi
VER="${VER:0:12}"

echo "$VER" > bookcapture/_version.txt
rm -f "$ROOT/install/bookcapture.zip"
zip -rq "$ROOT/install/bookcapture.zip" bookcapture requirements.txt scripts \
    -x '*/__pycache__/*' '*.pyc' '*/.DS_Store'
echo "$VER" > "$ROOT/install/worker-version.txt"
echo "[build-zip] version=$VER  -> install/bookcapture.zip + worker-version.txt"
