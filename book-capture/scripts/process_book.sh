#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 이북 처리 최종 파이프라인 — 한 번에 (2026-07-12 확정)
#
# source_raws(캡처 원본)부터 발행까지 전 과정을 한 명령으로 실행한다.
#   crop → qc → trim-tail → ocr → summarize → merge → build
#        → code(코드추출) → book_overview(책 개요) → finalize(챕터트리+표)
#        → [--publish] NAS 발행(index/code_blocks/book_overview + page/thumbs)
#
# 사람이 채울 유일한 입력: summary/chapters.json (장 제목·경계 = 목차에서).
#   없으면 chapters-detect 로 뼈대 자동 생성(제목은 '(제목 확인 필요)') 후 계속.
#   → 책 개요·챕터트리 품질을 위해 발행 전 chapters.json 제목 채우는 것을 권장.
#
# 사용:
#   ./scripts/process_book.sh <SLUG> [--chrome L,T,R,B] [--publish] [--from STAGE]
#     --chrome  : 고정 크롭(앱 raw=20,20,20,20 권장, 웹뷰어=생략=기본). 기본 20,20,20,20.
#     --publish : 로컬 빌드 후 NAS 발행까지(요약파일 + 이미지 tar 스트리밍). NAS_PASS 필요.
#     --from    : 특정 단계부터(crop|ocr|summarize|merge|build|code|overview|finalize|publish)
#   예) NAS_PASS=... ./scripts/process_book.sh 이미지_처리_바이블 --chrome 20,20,20,20 --publish
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."                        # book-capture/
PY=".venv/bin/python3"; [ -x "$PY" ] || PY="python3"

SLUG=""; CHROME="20,20,20,20"; PUBLISH=0; FROM="crop"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --chrome) CHROME="$2"; shift 2;;
    --publish) PUBLISH=1; shift;;
    --from) FROM="$2"; shift 2;;
    -*) echo "알 수 없는 옵션: $1" >&2; exit 2;;
    *) SLUG="$1"; shift;;
  esac
done
[ -n "$SLUG" ] || { echo "사용: $0 <SLUG> [--chrome L,T,R,B] [--publish] [--from STAGE]" >&2; exit 2; }

BOOK="books/$SLUG"; SUM="$BOOK/summary"
[ -d "$BOOK" ] || { echo "❌ 책 폴더 없음: $BOOK" >&2; exit 1; }

# 단계 순서 인덱스(--from 이후만 실행)
STAGES=(crop ocr summarize merge build code overview finalize publish)
idx() { local i=0; for s in "${STAGES[@]}"; do [ "$s" = "$1" ] && { echo $i; return; }; i=$((i+1)); done; echo 99; }
FROM_I=$(idx "$FROM"); run_stage() { [ "$(idx "$1")" -ge "$FROM_I" ]; }
# 비용 로그 초기화 — 처음부터(crop/ocr) 실행할 때만(부분 --from 은 누적 유지)
[ "$FROM" = crop ] || [ "$FROM" = ocr ] && $PY -c "from bookcapture import cost; cost.reset('$BOOK')" 2>/dev/null || true
say() { echo; echo "━━━ $* ━━━"; }

# 1) 크롭 (source_raws → page/thumbs)
if run_stage crop; then
  if [ -d "$BOOK/source_raws" ]; then
    say "① 크롭 (chrome=$CHROME)"
    $PY scripts/crop_book.py "$BOOK/source_raws" "$BOOK" --chrome "$CHROME"
    say "① QC"; $PY -m bookcapture qc --book-dir "$BOOK" || true
    say "① 중복 꼬리 정리"; $PY -m bookcapture trim-tail --book-dir "$BOOK" || true
  else
    echo "⚠ source_raws 없음 — 크롭 건너뜀(이미 page_*.png 가정)"
  fi
fi

# 2) OCR(비전 전사) → 요약 → merge → build
#    교보 이북은 tesseract 가 mojibake → --vision(Gemini 전사, Claude 폴백)으로 깨끗한 본문 확보.
#    요약은 그 깨끗한 텍스트를 저비용 Haiku(summarize_model)로 처리 → 비용 대폭 절감.
run_stage ocr      && { say "② 본문전사(비전)"; $PY -m bookcapture ocr --vision --book-dir "$BOOK" || true; }
run_stage summarize&& { say "③ 요약(AI)";  $PY -m bookcapture summarize --book-dir "$BOOK" || echo "요약 일부 실패(계속)"; }
run_stage merge    && { say "④ merge";     $PY -m bookcapture merge     --book-dir "$BOOK" || echo "merge 실패(계속)"; }
run_stage build    && { say "⑤ build";     $PY -m bookcapture build     --book-dir "$BOOK"; }

# 3) 코드 추출
run_stage code && { say "⑥ 코드 추출(비전)"; $PY -m bookcapture code --book-dir "$BOOK" || echo "코드추출 일부 실패(계속)"; }

# 4) 챕터 자동 감지(비전) + 책 개요
if run_stage overview; then
  if [ ! -f "$SUM/chapters.json" ]; then
    say "⑦ 챕터 자동 감지(비전 — 장 표지)"
    $PY -m bookcapture chapters-auto --book-dir "$BOOK" || echo "챕터 감지 실패(계속)"
  fi
  if [ -f "$SUM/chapters.json" ]; then
    say "⑦ 책 개요(전체요약+장별 1장)"
    $PY -m bookcapture overview --book-dir "$BOOK" --title "${SLUG//_/ }" || echo "책개요 실패(계속)"
  else
    echo "⚠ chapters.json 없어 책 개요 건너뜀"
  fi
fi

# 5) 최종화 (챕터트리 + 표 정리본)
run_stage finalize && { say "⑧ 최종화(챕터트리+표)"; $PY -m bookcapture finalize --book-dir "$BOOK" || echo "최종화 실패(계속)"; }

# 6) 발행
if run_stage publish && [ "$PUBLISH" = 1 ]; then
  [ -n "${NAS_PASS:-${SSHPASS:-}}" ] || { echo "❌ 발행하려면 NAS_PASS 필요"; exit 2; }
  say "⑨ 발행 — 요약 파일"
  FILES=("$SUM/index.html")
  [ -f "$SUM/code_blocks.json" ]  && FILES+=("$SUM/code_blocks.json")
  [ -f "$SUM/book_overview.json" ]&& FILES+=("$SUM/book_overview.json")
  ./scripts/publish_book.sh "$SLUG" "${FILES[@]}"

  say "⑨ 발행 — 이미지(page+thumbs, tar 스트리밍)"
  ./scripts/publish_images.sh "$SLUG"
elif [ "$PUBLISH" = 1 ]; then
  echo "(publish 단계는 --from 로 스킵됨)"
fi

echo; $PY -m bookcapture cost --book-dir "$BOOK" 2>/dev/null || true
echo; echo "✅ 완료: $SLUG"
if [ "$PUBLISH" = 1 ]; then
  echo "   라이브: https://redcodeme.synology.me/kyobo/books/$SLUG/summary/index.html"
fi
