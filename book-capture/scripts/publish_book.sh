#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 개별 도서 산출물을 NAS 웹폴더에 발행 (root 소유 → sudo cp)
#
# 배경: 웹 이미지·HTML 은 도커/이전 배포가 만든 root 소유 →
#       RedCode 계정이 직접 덮어쓰지 못함. RedCode 홈에 올린 뒤 sudo cp.
#       (RedCode 는 root sudo 가능, 비번 동일)
#
# 접속: SSH 키가 에이전트에 없을 때가 많아 password 인증 고정.
#       비번은 NAS_PASS 환경변수(없으면 SSHPASS)로 전달 — 스크립트에 하드코딩 안 함.
#       비번 출처: 인증서/나스인증/NAS_RedCode_접속정보.md (메모리 reference_nas_ssh_deploy)
#
# 사용:
#   export NAS_PASS='...'                     # RedCode 비밀번호
#   ./publish_book.sh <BOOK_SLUG> <FILE>...   # FILE 들을 summary/ 에 발행
#   예) ./publish_book.sh 클로드_코드로_시작하는_실전_에이전틱_코딩 \
#         /path/index.html /path/page_extras.json /path/chapters.json
#
# 옵션: FILE 이 .html/.json 이면 summary/ 로. 그 외(page_*.png 등)는 --images 로 책 루트.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

NAS_HOST="RedCode@192.168.10.205"
WEB_ROOT="/volume1/web/kyobo/books"
PASS="${NAS_PASS:-${SSHPASS:-}}"

if [[ $# -lt 2 ]]; then
  echo "사용: NAS_PASS=... $0 <BOOK_SLUG> <FILE>..." >&2; exit 2
fi
if [[ -z "$PASS" ]]; then
  echo "❌ NAS_PASS(또는 SSHPASS) 환경변수에 RedCode 비밀번호를 넣으세요." >&2
  echo "   비번: 인증서/나스인증/NAS_RedCode_접속정보.md" >&2; exit 2
fi
command -v sshpass >/dev/null || { echo "❌ sshpass 필요 (brew install sshpass)" >&2; exit 2; }

BOOK="$1"; shift
SUMMARY="$WEB_ROOT/$BOOK/summary"

SSH_OPTS=(-o ConnectTimeout=15 -o StrictHostKeyChecking=no
          -o PubkeyAuthentication=no -o PreferredAuthentications=password
          -o NumberOfPasswordPrompts=1)
run_ssh() { SSHPASS="$PASS" sshpass -e ssh "${SSH_OPTS[@]}" "$NAS_HOST" "$@"; }

echo "📖 발행 대상: $SUMMARY"
# 대상 폴더 존재 확인
run_ssh "test -d '$SUMMARY'" || { echo "❌ 원격 폴더 없음: $SUMMARY" >&2; exit 1; }

for f in "$@"; do
  [[ -f "$f" ]] || { echo "⚠ 로컬 파일 없음, 건너뜀: $f"; continue; }
  base="$(basename "$f")"
  # 발행 파일명 그대로 원격에 반영됨 → 오타 파일 방지 경고
  case "$base" in
    index.html|page_extras.json|chapters.json|batch_*.json|pages_data.json) ;;
    *.html) echo "  ⚠ '$base' 로 발행됨(index.html 아님). 의도한 이름인지 확인." >&2 ;;
  esac
  remote_tmp="~/.publish_$base"
  dst="$SUMMARY/$base"
  echo "  → $base ($(wc -c <"$f") bytes)"
  # 1) 홈에 업로드
  SSHPASS="$PASS" sshpass -e ssh "${SSH_OPTS[@]}" "$NAS_HOST" "cat > $remote_tmp" < "$f"
  # 2) 백업 + sudo cp + 권한
  run_ssh "P='$PASS'
    [ -f '$dst' ] && echo \"\$P\" | sudo -S cp '$dst' '$dst.bak' 2>/dev/null
    echo \"\$P\" | sudo -S cp $remote_tmp '$dst' 2>/dev/null
    echo \"\$P\" | sudo -S chown root:root '$dst' 2>/dev/null
    echo \"\$P\" | sudo -S chmod 644 '$dst' 2>/dev/null
    rm -f $remote_tmp" 2>&1 | grep -v '^\[sudo\]' || true
done

# 검증
echo "── 검증 ──"
run_ssh "F='$SUMMARY/index.html'
  printf 'index size: '; wc -c <\"\$F\"
  printf 'tables(.ptable): '; grep -o 'class=\"ptable\"' \"\$F\" | wc -l
  printf 'chapters: '; grep -o 'chapter-summary\"' \"\$F\" | wc -l" 2>&1 | grep -v '^\[sudo\]' || true
echo "✅ 발행 완료. 라이브: https://redcodeme.synology.me/kyobo/books/$BOOK/summary/index.html"
