#!/bin/bash

# 새 도서 추가 자동화 스크립트
# 사용법: ./add_book.sh "도서명" "/원본/summary/폴더/경로"

set -e

# 색상 정의
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

if [ $# -lt 2 ]; then
    echo -e "${RED}사용법: $0 \"도서명\" \"/원본/summary/폴더/경로\"${NC}"
    echo ""
    echo "예시:"
    echo "  $0 \"파이썬 마스터\" \"/Users/name/kyobo_app_screenshots/파이썬 마스터/summary\""
    exit 1
fi

BOOK_NAME="$1"
SOURCE_SUMMARY_PATH="$2"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BOOKS_DIR="$SCRIPT_DIR/books"

# 슬러그 생성 (공백을 언더스코어로 변환)
BOOK_SLUG=$(echo "$BOOK_NAME" | sed 's/ /_/g')
BOOK_DIR="$BOOKS_DIR/$BOOK_SLUG"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}교보 라이브러리 - 새 도서 추가${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "도서명: $BOOK_NAME"
echo "슬러그: $BOOK_SLUG"
echo "대상 폴더: $BOOK_DIR"
echo ""

# 1. 도서 폴더 생성
echo -e "${GREEN}[1/4]${NC} 도서 폴더 생성 중..."
if [ -d "$BOOK_DIR" ]; then
    echo -e "${RED}경고: 이미 존재하는 도서입니다. 덮어쓰시겠습니까? (y/N)${NC}"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "취소되었습니다."
        exit 0
    fi
    rm -rf "$BOOK_DIR"
fi

mkdir -p "$BOOK_DIR"
echo "✓ 폴더 생성 완료"

# 2. viewer.html 복사
echo -e "${GREEN}[2/4]${NC} viewer.html 복사 중..."
if [ -f "$SCRIPT_DIR/viewer.html" ]; then
    cp "$SCRIPT_DIR/viewer.html" "$BOOK_DIR/"
    echo "✓ viewer.html 복사 완료"
else
    echo -e "${RED}✗ viewer.html을 찾을 수 없습니다${NC}"
    exit 1
fi

# 3. summary 폴더 복사
echo -e "${GREEN}[3/4]${NC} summary 데이터 복사 중..."
if [ -d "$SOURCE_SUMMARY_PATH" ]; then
    cp -r "$SOURCE_SUMMARY_PATH" "$BOOK_DIR/"
    echo "✓ summary 폴더 복사 완료"

    # 파일 개수 확인
    FILE_COUNT=$(find "$BOOK_DIR/summary" -type f | wc -l | tr -d ' ')
    echo "  - 복사된 파일: $FILE_COUNT 개"
else
    echo -e "${RED}✗ summary 폴더를 찾을 수 없습니다: $SOURCE_SUMMARY_PATH${NC}"
    exit 1
fi

# 4. index.html 업데이트 안내
echo -e "${GREEN}[4/4]${NC} 다음 단계 안내"
echo ""
echo -e "${BLUE}index.html을 수동으로 업데이트해주세요:${NC}"
echo ""
echo "books 배열에 다음 객체를 추가:"
echo ""
echo "{"
echo "    id: '$(echo $BOOK_SLUG | tr '[:upper:]' '[:lower:]' | sed 's/_/-/g')',"
echo "    title: '$BOOK_NAME',"
echo "    slug: '$BOOK_SLUG',"
echo "    chapters: X,  // 챕터 개수"
echo "    pages: XXX,   // 페이지 수"
echo "    description: '도서 설명',"
echo "    icon: '📚'    // 아이콘 선택"
echo "}"
echo ""

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ 도서 추가 완료!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "접속 경로: books/$BOOK_SLUG/viewer.html"
echo ""
