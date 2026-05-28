#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Kyobo Library Stack · NAS 일괄 배포
#
# 두 서비스를 한 방에 배포:
#   1) library-web   — 정적 HTML rsync → /volume1/docker/web-apps/kyobo-library
#   2) kyobo-bridge  — Docker 이미지 빌드 → save → scp → load
#   3) compose up -d 로 두 서비스 동시 (재)기동
#   4) 헬스체크 (8080, 9000)
#
# 옵션:
#   ./deploy.sh                # 풀 배포 (정적+백엔드+compose)
#   ./deploy.sh --static       # 정적만 (백엔드 변경 없을 때 빠른 배포)
#   ./deploy.sh --backend      # 백엔드만 (정적 변경 없을 때)
#   ./deploy.sh --dry          # rsync 미리보기만 (백엔드 빌드는 안 함)
#   ./deploy.sh --logs         # 배포 후 두 컨테이너 로그 tail
# ─────────────────────────────────────────────────────────────

set -euo pipefail

NAS_HOST="RedCode@192.168.10.205"
NAS_DOCKER="/usr/local/bin/docker"
NAS_COMPOSE="/usr/local/bin/docker-compose"

STATIC_PATH="/volume1/docker/web-apps/kyobo-library"
BRIDGE_DATA_PATH="/volume1/docker/web-apps/kyobo-bridge/data"
COMPOSE_DIR="/volume1/docker/kyobo-stack"

BRIDGE_IMAGE="kyobo-bridge:latest"
BRIDGE_TAR_LOCAL="/tmp/kyobo-bridge.tar.gz"
BRIDGE_TAR_REMOTE="/tmp/kyobo-bridge.tar.gz"

HEALTH_WEB="http://192.168.10.205:8080/"
HEALTH_BRIDGE="http://192.168.10.205:9000/health"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

c_g="\033[1;32m"; c_y="\033[1;33m"; c_r="\033[1;31m"; c_d="\033[2m"; c_x="\033[0m"
step()  { echo -e "${c_g}▶${c_x} $*"; }
warn()  { echo -e "${c_y}!${c_x} $*"; }
die()   { echo -e "${c_r}✗${c_x} $*" >&2; exit 1; }

DRY=""; LOGS=""; DO_STATIC=1; DO_BACKEND=1
for arg in "$@"; do
    case "$arg" in
        --dry)     DRY="--dry-run" ;;
        --logs)    LOGS=1 ;;
        --static)  DO_BACKEND=0 ;;
        --backend) DO_STATIC=0 ;;
    esac
done

# ── 사전 점검 ────────────────────────────────────────────────
command -v rsync >/dev/null || die "rsync 없음"
if [[ "$DO_BACKEND" == "1" && -z "$DRY" ]]; then
    command -v docker >/dev/null || die "docker 없음"
    docker buildx version >/dev/null 2>&1 || die "docker buildx 없음"
fi

# ── 1) 정적: rsync ───────────────────────────────────────────
if [[ "$DO_STATIC" == "1" ]]; then
    step "[1] 정적 라이브러리 rsync → $NAS_HOST:$STATIC_PATH"
    rsync -avz $DRY --delete \
        --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
        --exclude-from=.dockerignore \
        --exclude='/kyobo-bridge/' \
        --exclude='/docker-compose.yml' \
        -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15" \
        ./ "$NAS_HOST:$STATIC_PATH/"
fi

# DRY-RUN 이면 여기까지만
if [[ -n "$DRY" ]]; then
    step "DRY-RUN 끝 (실제 전송·빌드 안 함)"
    exit 0
fi

# ── 2) 백엔드: buildx amd64 → save → scp → load ─────────────
if [[ "$DO_BACKEND" == "1" ]]; then
    step "[2] Bridge 이미지 buildx (linux/amd64)"
    docker buildx build \
        --platform linux/amd64 \
        -t "$BRIDGE_IMAGE" \
        --load \
        kyobo-bridge/

    step "[2-1] Bridge 이미지 → tar.gz"
    docker save "$BRIDGE_IMAGE" | gzip -1 > "$BRIDGE_TAR_LOCAL"
    ls -lh "$BRIDGE_TAR_LOCAL" | awk '{print "   크기: " $5}'

    step "[2-2] scp → $NAS_HOST:$BRIDGE_TAR_REMOTE"
    scp -O -o StrictHostKeyChecking=no -o ConnectTimeout=15 \
        "$BRIDGE_TAR_LOCAL" "$NAS_HOST:$BRIDGE_TAR_REMOTE"

    step "[2-3] NAS docker load"
    ssh "$NAS_HOST" "$NAS_DOCKER load -i $BRIDGE_TAR_REMOTE && rm -f $BRIDGE_TAR_REMOTE"
fi

# ── 3) compose up -d ─────────────────────────────────────────
step "[3] compose 동기화·기동"
ssh -o StrictHostKeyChecking=no "$NAS_HOST" \
    "mkdir -p $COMPOSE_DIR $BRIDGE_DATA_PATH"
scp -O -o StrictHostKeyChecking=no docker-compose.yml \
    "$NAS_HOST:$COMPOSE_DIR/docker-compose.yml"
ssh "$NAS_HOST" bash <<EOF
set -euo pipefail
cd $COMPOSE_DIR
echo "  · 기존 같은 이름 컨테이너 정리(있으면)…"
# Container Manager로 띄운 옛 kyobo-library-web 인계 (있을 때만)
if $NAS_DOCKER ps -a --format '{{.Names}}' | grep -q '^kyobo-library-web\$'; then
    if ! $NAS_DOCKER ps --filter 'label=com.docker.compose.project' \
        --format '{{.Names}}' | grep -q '^kyobo-library-web\$'; then
        echo "    옛 컨테이너(Container Manager) 발견 → stop/rm"
        $NAS_DOCKER stop kyobo-library-web >/dev/null 2>&1 || true
        $NAS_DOCKER rm   kyobo-library-web >/dev/null 2>&1 || true
    fi
fi
echo "  · compose up -d"
$NAS_COMPOSE up -d
EOF

# ── 4) 헬스체크 ──────────────────────────────────────────────
step "[4] 헬스체크"
sleep 3
web_code="$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$HEALTH_WEB" || echo "000")"
brg_code="$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$HEALTH_BRIDGE" || echo "000")"
[[ "$web_code" == "200" ]] \
    && echo -e "   ${c_g}HTTP $web_code${c_x}  library-web  $HEALTH_WEB" \
    || warn "library-web HTTP $web_code  $HEALTH_WEB"
[[ "$brg_code" == "200" ]] \
    && echo -e "   ${c_g}HTTP $brg_code${c_x}  kyobo-bridge $HEALTH_BRIDGE" \
    || warn "kyobo-bridge HTTP $brg_code  $HEALTH_BRIDGE"

if [[ "$brg_code" != "200" ]]; then
    warn "kyobo-bridge 로그 (마지막 30줄):"
    ssh "$NAS_HOST" "$NAS_DOCKER logs --tail 30 kyobo-bridge" || true
fi

# ── 5) 옵션: 로그 tail ───────────────────────────────────────
if [[ -n "$LOGS" ]]; then
    step "로그 tail (Ctrl+C로 종료) — bridge만"
    ssh -t "$NAS_HOST" "$NAS_DOCKER logs -f --tail 50 kyobo-bridge"
fi

step "완료"
