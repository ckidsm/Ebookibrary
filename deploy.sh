#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Kyobo Library · NAS 배포 (정적 사이트, rsync 기반)
#
# 흐름: 로컬 → rsync (HTML/JSON만, 빌드 도구·캐시 제외)
#       → NAS 마운트 폴더
#       → docker restart kyobo-library-web
#       → curl 헬스체크
#
# 전제: ssh agent 키가 RedCode 계정에 등록 (../NAS.md 2장 참고)
#
# 사용: ./deploy.sh            # 동기화 + 재기동 + 헬스체크
#       ./deploy.sh --dry      # rsync 미리보기만 (실전송 X)
#       ./deploy.sh --logs     # 배포 후 컨테이너 로그 tail
# ─────────────────────────────────────────────────────────────

set -euo pipefail

NAS_HOST="RedCode@192.168.10.205"
NAS_DOCKER="/usr/local/bin/docker"
NAS_PATH="/volume1/docker/web-apps/kyobo-library"
CONTAINER="kyobo-library-web"
HEALTH_URL="http://192.168.10.205:8080/"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

c_g="\033[1;32m"; c_y="\033[1;33m"; c_r="\033[1;31m"; c_x="\033[0m"
step()  { echo -e "${c_g}▶${c_x} $*"; }
warn()  { echo -e "${c_y}!${c_x} $*"; }
die()   { echo -e "${c_r}✗${c_x} $*" >&2; exit 1; }

DRY=""
LOGS=""
for arg in "$@"; do
    case "$arg" in
        --dry)  DRY="--dry-run" ;;
        --logs) LOGS="1" ;;
    esac
done

# 0. 사전 점검
command -v rsync >/dev/null || die "rsync가 PATH에 없음"

# 1. rsync 동기화
step "rsync 동기화 → $NAS_HOST:$NAS_PATH"
# --chmod: 로컬 파일이 700이어도 NAS에서는 디렉토리 755·파일 644로 통일
# (nginx 워커가 read 가능해야 함, 안 그러면 HTTP 403)
rsync -avz $DRY --delete \
    --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    --exclude-from=.dockerignore \
    -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15" \
    ./ "$NAS_HOST:$NAS_PATH/"

if [[ -n "$DRY" ]]; then
    step "DRY-RUN 끝 (실제 전송 안 함)"
    exit 0
fi

# 2. 컨테이너 재기동 (정적이지만 캐시 비우기·확실성)
step "컨테이너 재기동: $CONTAINER"
ssh -o StrictHostKeyChecking=no "$NAS_HOST" \
    "$NAS_DOCKER restart $CONTAINER >/dev/null && echo '  · 재기동 OK'"

# 3. 헬스체크
step "헬스체크"
sleep 1
code="$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$HEALTH_URL" || echo "000")"
if [[ "$code" == "200" ]]; then
    echo -e "   ${c_g}HTTP $code${c_x}  $HEALTH_URL"
else
    warn "HTTP $code · 컨테이너 로그 확인:"
    ssh "$NAS_HOST" "$NAS_DOCKER logs --tail 30 $CONTAINER" || true
fi

# 4. 옵션: 로그 tail
if [[ -n "$LOGS" ]]; then
    step "컨테이너 로그 tail (Ctrl+C로 종료)"
    ssh -t "$NAS_HOST" "$NAS_DOCKER logs -f --tail 50 $CONTAINER"
fi

step "완료"
