#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Kyobo Library — e2e 자동 테스트
#
# 사용:
#   bash tests/e2e_test.sh           # 빠른 체크 (무료, ~20초)
#   bash tests/e2e_test.sh --full    # 업로드→OCR→요약→빌드 end-to-end 포함 (AI 비용 ~$0.02)
#
# 전제: NAS 백엔드 가동 중(192.168.10.205 LAN). SSH(RedCode) 키 인증.
# ─────────────────────────────────────────────────────────────
set -uo pipefail

API="http://192.168.10.205:9000"
WEB="http://192.168.10.205:8080"
EXT="https://redcodeme.synology.me/kyobo"
NAS="RedCode@192.168.10.205"
SSH="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 $NAS"
DOCKER="/usr/local/bin/docker"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PASS=0; FAIL=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }
sect() { echo; echo "── $1 ──"; }

# 1) 엔드포인트 헬스
sect "1) 엔드포인트 헬스"
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$WEB/")" = "200" ] && ok "정적 8080 200" || bad "정적 8080"
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$API/health")" = "200" ] && ok "백엔드 9000/health 200" || bad "백엔드 9000/health"

# 2) 설치 자산 서빙 + 인코딩
sect "2) 설치 자산 서빙/인코딩"
for f in install/install-worker.ps1 install/install-worker.cmd install/update-worker.ps1 install/bookcapture.zip install/worker-version.txt; do
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$WEB/$f")" = "200" ] && ok "서빙 $f" || bad "서빙 $f"
done
# 부트스트랩 ps1 은 BOM 없어야(irm|iex 안전)
b3=$(curl -s --max-time 10 "$WEB/install/install-worker.ps1" | head -c3 | od -An -tx1 | tr -d ' ')
[ "$b3" != "efbbbf" ] && ok "install-worker.ps1 BOM 없음" || bad "install-worker.ps1 에 BOM(irm|iex 깨질 수 있음)"
# .cmd 는 CRLF
curl -s --max-time 10 "$WEB/install/install-worker.cmd" | file - | grep -q "CRLF" && ok ".cmd CRLF 줄바꿈" || bad ".cmd LF (cmd.exe 파싱 실패 위험)"

# 3) 버전 일치 (서버 worker-version.txt == zip 내 _version.txt)
sect "3) 워커 버전 일치(자동업데이트 정합성)"
sv=$(curl -s --max-time 10 "$WEB/install/worker-version.txt" | tr -d '[:space:]')
zt=$(mktemp); curl -s --max-time 20 "$WEB/install/bookcapture.zip" -o "$zt"
zv=$(unzip -p "$zt" bookcapture/_version.txt 2>/dev/null | tr -d '[:space:]')
rm -f "$zt"
[ -n "$sv" ] && [ "$sv" = "$zv" ] && ok "버전 일치 ($sv)" || bad "버전 불일치 server=$sv zip=$zv"

# 4) 워커 status 스키마
sect "4) 워커 status 스키마"
st=$(curl -s --max-time 10 "$API/api/worker/status")
for k in alive worker_version server_version up_to_date app_title; do
  echo "$st" | python3 -c "import sys,json;d=json.load(sys.stdin);exit(0 if '$k' in d else 1)" 2>/dev/null \
    && ok "status.$k 존재" || bad "status.$k 누락"
done

# 5) nginx no-cache 헤더 (책 HTML 은 no-cache, PNG 는 캐시)
sect "5) nginx 캐시 헤더"
hc=$(curl -sI --max-time 10 "$WEB/index.html" | tr -d '\r' | grep -i '^cache-control:')
echo "$hc" | grep -qi "no-cache" && ok "HTML no-cache ($hc)" || bad "HTML no-cache 누락 ($hc)"

# 6) reaper — heartbeat 끊긴 running job 자동 failed (컨테이너 내부)
sect "6) reaper (좀비 job 회수)"
rr=$($SSH "$DOCKER exec -i kyobo-bridge python -c \"
import app.db as db
with db.cursor() as c:
    c.execute(\\\"INSERT INTO jobs(slug,title,mode,status,started_at,heartbeat) VALUES('__t__','t','auto','running',datetime('now'),datetime('now','-2 hours'))\\\")
    tid=c.lastrowid
r=db.reap_stale_jobs()
j=db.get_job(tid)
with db.cursor() as c: c.execute('DELETE FROM jobs WHERE id=?',(tid,))
print('OK' if j['status']=='failed' else 'NO:'+j['status'])
\"" 2>/dev/null | tr -d '[:space:]')
[ "$rr" = "OK" ] && ok "reaper 가 2h-stale running → failed" || bad "reaper 동작 안 함 ($rr)"

# 7) (옵션) 업로드→처리 end-to-end
if [ "${1:-}" = "--full" ]; then
  sect "7) 업로드→OCR→요약→빌드 end-to-end (--full)"
  SRC="$ROOT/book-capture/books/HTTP_완벽_가이드"
  SLUG="__e2e_test__"
  imgs=$(ls "$SRC"/page_00[12].png 2>/dev/null)
  if [ -z "$imgs" ]; then bad "샘플 PNG 없음 ($SRC) — 캡처본 필요"; else
    args=(); for p in $imgs; do args+=(-F "files=@$p"); done
    jid=$(curl -s --max-time 60 -X POST "$API/api/books/$SLUG/upload" -F "title=e2e 테스트" "${args[@]}" \
          | python3 -c "import sys,json;print(json.load(sys.stdin)['job']['id'])" 2>/dev/null)
    if [ -z "$jid" ]; then bad "업로드 실패"; else
      echo "  업로드 OK job #$jid — 처리 대기..."
      done=""
      for i in $(seq 1 30); do
        sleep 6
        s=$(curl -s --max-time 8 "$API/api/jobs/$jid" | python3 -c "import sys,json;print(json.load(sys.stdin)['job']['status'])" 2>/dev/null)
        [ "$s" = "done" ] && { done="1"; break; }
        [ "$s" = "failed" ] && break
      done
      [ "$done" = "1" ] && ok "처리 완료(done)" || bad "처리 미완료/실패"
      [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$WEB/books/$SLUG/summary/index.html")" = "200" ] \
        && ok "결과 index.html 서빙" || bad "결과 서빙 안 됨"
      curl -s --max-time 10 "$API/api/books/analyzed" | grep -q "$SLUG" && ok "analyzed 등록" || bad "analyzed 미등록"
      # 정리
      curl -s -X DELETE "$API/api/jobs/$jid" >/dev/null 2>&1
      $SSH "$DOCKER exec kyobo-bridge rm -rf /mnt/library-rw/books/$SLUG" >/dev/null 2>&1
      echo "  (테스트 데이터 정리 완료)"
    fi
  fi
fi

echo
echo "════════════════════════════════════"
echo "  결과: PASS=$PASS  FAIL=$FAIL"
echo "════════════════════════════════════"
[ "$FAIL" = "0" ] && exit 0 || exit 1
