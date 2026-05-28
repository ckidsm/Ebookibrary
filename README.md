# 📚 교보 전자책 라이브러리

수백 권의 교보 전자책을 웹에서 편리하게 열람할 수 있는 라이브러리 시스템입니다.

## 📁 폴더 구조

```
kyobo-library/
├── index.html              # 메인 페이지 (도서 목록)
├── viewer.html             # 도서 뷰어 템플릿
├── add_book.sh            # 새 도서 추가 스크립트
├── books/                  # 도서 데이터 폴더
│   ├── CLI_완전활용/
│   │   ├── viewer.html    # 도서 뷰어
│   │   └── summary/       # 챕터 데이터
│   │       ├── chapters_data.json
│   │       ├── pages_data.json
│   │       └── ...
│   └── [다른_도서]/
└── README.md
```

## 🚀 사용 방법

### 1. 로컬에서 테스트

```bash
# Python 웹 서버 실행
cd kyobo-library
python3 -m http.server 8080

# 브라우저에서 접속
http://localhost:8080
```

### 2. 새 도서 추가

```bash
# 스크립트에 실행 권한 부여
chmod +x add_book.sh

# 새 도서 추가
./add_book.sh "도서명" "/원본/summary/폴더/경로"

# 예시
./add_book.sh "파이썬 마스터" "/Users/name/kyobo_app_screenshots/파이썬 마스터/summary"
```

스크립트 실행 후 `index.html`을 편집하여 도서 정보를 추가하세요.

### 3. index.html 업데이트

`index.html` 파일에서 `books` 배열에 새 도서 정보 추가:

```javascript
const books = [
    {
        id: 'cli-complete',
        title: 'CLI 완전활용',
        slug: 'CLI_완전활용',
        chapters: 8,
        pages: 311,
        description: 'Claude Code, Codex CLI, Gemini CLI 완전 가이드',
        icon: '💻'
    },
    // 여기에 새 도서 추가
    {
        id: 'python-master',
        title: '파이썬 마스터',
        slug: '파이썬_마스터',
        chapters: 12,
        pages: 450,
        description: '파이썬 완전 정복',
        icon: '🐍'
    }
];
```

## 🌐 NAS 배포

### Synology NAS에 배포하기

#### 방법 1: Docker로 배포 (권장)

```bash
# 1. NAS에 폴더 생성
ssh RedCode@192.168.10.250
mkdir -p /volume1/docker/web-apps/kyobo-library

# 2. 로컬에서 파일 복사
scp -r kyobo-library/* RedCode@192.168.10.250:/volume1/docker/web-apps/kyobo-library/

# 3. Docker 컨테이너 실행
ssh RedCode@192.168.10.250
docker run -d \
  --name kyobo-library-web \
  --restart always \
  -p 8282:80 \
  -v /volume1/docker/web-apps/kyobo-library:/usr/share/nginx/html:ro \
  nginx:latest

# 4. 컨테이너 확인
docker ps | grep kyobo
```

#### 방법 2: Web Station 사용

1. DSM → 패키지 센터 → Web Station 설치
2. Web Station 실행 → "웹 서비스 포털" → "생성"
3. 포트: 8282
4. 문서 루트: `/volume1/docker/web-apps/kyobo-library`

### 외부 접속 설정

#### 1. 방화벽 설정

- DSM → 제어판 → 보안 → 방화벽
- 규칙 편집 → 생성 → 포트 8282 허용

#### 2. 포트 포워딩 (공유기)

- 외부 포트 8282 → 192.168.10.250:8282

#### 3. 접속

- **내부**: `http://192.168.10.250:8282`
- **외부**: `http://miruanyang.iptime.org:8282`

## 🎯 주요 기능

### 1. 3단계 네비게이션

```
홈 (도서 목록)
  ↓
도서 뷰어 (챕터 트리뷰)
  ↓
챕터/섹션 상세
```

### 2. 트리뷰 인터페이스

- 챕터를 펼치면 섹션 목록 표시
- 섹션 클릭하면 상세 내용 표시
- 챕터 overview, 표, 태그 등 자동 렌더링

### 3. 반응형 디자인

- 데스크톱: 사이드바 + 콘텐츠 영역
- 모바일: 상하 분할 레이아웃

## 🔧 문제 해결

### 도서가 표시되지 않을 때

1. `books/[도서슬러그]/summary/chapters_data.json` 파일 확인
2. 브라우저 개발자 도구 콘솔 확인
3. 경로가 정확한지 확인

### Docker 컨테이너 관리

```bash
# 로그 확인
docker logs kyobo-library-web

# 재시작
docker restart kyobo-library-web

# 중지
docker stop kyobo-library-web

# 삭제
docker rm -f kyobo-library-web
```

### 파일 업데이트

```bash
# 새 버전 복사
scp -r kyobo-library/* RedCode@192.168.10.250:/volume1/docker/web-apps/kyobo-library/

# 컨테이너 재시작 (캐시 제거)
ssh RedCode@192.168.10.250 "docker restart kyobo-library-web"

# 또는 브라우저에서 Ctrl+F5 (강제 새로고침)
```

## 📋 To-Do

- [ ] 도서 검색 기능
- [ ] 북마크/즐겨찾기
- [ ] 다크 모드
- [ ] 페이지 이미지 뷰어 통합
- [ ] 진행 상황 저장 (localStorage)
- [ ] OCR 텍스트 검색

## 📄 라이선스

개인 사용 목적으로만 사용하세요.
