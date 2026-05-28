# Kyobo Library (정적 도서 라이브러리 + 교보 e-Library 연동 예정)

교보문고에서 구매한 e-book을 페이지별 PNG → OCR → JSON → HTML 빌드 파이프라인으로
정리한 정적 웹 라이브러리. NAS 위 nginx 컨테이너에 배포되어 LAN/외부에서 열람.

> **인프라 참조**: NAS·SSH·Docker 공통 정보는 `../NAS.md`.
> **자매 프로젝트**: `../NasVideoTrimmer/` (Blazor) — 같은 NAS·Docker·배포 패턴.
> 이 문서는 **이 프로젝트의 컨벤션·빌드·배포·작업 로그**.

---

## GitHub 저장소·인증

| 항목 | 값 |
|---|---|
| 원격 저장소 | (미생성 — 로컬 git만 운용. 필요해지면 `ckidsm` 계정에 KyoboLibrary 생성 예정) |
| 인증 패턴 | `../NasVideoTrimmer/CLAUDE.md` 의 GitHub 인증 절 참고 (`github-com-ckidsm` host alias) |

---

## 커밋 메시지 작성 규칙

NasVideoTrimmer와 동일한 형식. **Co-Authored-By 라인 절대 금지**, `git push` 자동 실행 금지.

```
YYYY.MM.DD [범위] 한 줄 요약

1. 변경 파일/클래스명 (추가/수정/버그수정/리팩토링/삭제)
   1-1. 변경 내용

YUNDEOKSOO
```

자세한 규칙은 `../NasVideoTrimmer/CLAUDE.md` 의 "커밋 메시지 작성 규칙" 절 참고
(같은 워크스페이스에서 동일 규칙 적용).

---

## 1. 한 줄 개요

| 항목 | 값 |
|---|---|
| 형태 | 정적 사이트 (HTML/JS/JSON, 빌드 도구 없음) |
| 데이터 빌드 | Python 3 + tesseract OCR (kor+eng) — 로컬에서만 수행 |
| 미디어 처리 | 페이지 PNG → OCR → batch JSON → 통합 JSON → 도서 HTML |
| 서빙 | NAS 위 nginx 컨테이너 (`nginx:latest`, `:8080`) |
| 컨테이너명 | `kyobo-library-web` (이미 NAS에서 가동 중 · 2026-05-09 부터) |
| 마운트 | `/volume1/docker/web-apps/kyobo-library` → `/usr/share/nginx/html` (ro) |
| 접속 (LAN) | http://192.168.10.205:8080/ |
| 접속 (외부) | https://redcodeme.synology.me:8080/ (HTTPS 설정 시) |

**현재 상태 (2026-05-28)**: NAS 마운트 폴더에는 `"✅ 서버 정상 작동 중"` placeholder만 있고
실 콘텐츠는 한 번도 배포되지 않았다. Phase A 의 첫 배포로 실 데이터를 올린다.

---

## 2. 폴더 구조

```
NAS/KyoboLibrary/                            ← OneDrive 동기화 (어디서든 작업)
├── CLAUDE.md                                ← 이 문서
├── README.md                                ← (옛 버전, Phase A에서 갱신 예정)
├── .gitignore · .editorconfig · .dockerignore
├── deploy.sh                                ← ★ 새 배포 진입점 (rsync → NAS)
├── index.html                               ← 메인 (도서 카드 목록, 책 배열 하드코딩)
├── viewer.html                              ← 공통 뷰어 템플릿
├── add_book.sh                              ← 새 도서 추가 헬퍼 (수동)
├── books/
│   └── CLI_완전활용/
│       ├── viewer.html                      ← 도서별 뷰어 사본
│       └── summary/
│           ├── index.html                   ← ★ 도서 본문 (498KB, generate_html.py 산출)
│           ├── pages_data.json              ← 페이지 메타 (286KB)
│           ├── chapters_data.json           ← 챕터 메타
│           ├── batch_*.json (6개)           ← 원본 batch (수동/AI 입력)
│           ├── generate_html.py             ← JSON → index.html 빌드
│           ├── merge_batches.py             ← batch → pages_data.json 통합
│           ├── verify_ocr.py                ← PNG → OCR → 검증
│           ├── verification_report.{json,md}
│           └── ocr_text/page_NNN.txt        ← OCR 캐시 (.gitignore)
└── _archive/                                 ← 옛 스크립트 보관 (NAS 미전송)
    ├── deploy_to_nas.sh                      ⚠️ NAS IP 오타 (192.168.10.250)
    ├── 빠른_배포_가이드.md
    ├── 수동_실행_명령어.md
    └── 지금_바로_실행.sh
```

옛 스크립트들은 NAS IP 오타·구버전 워크플로라 새 `deploy.sh`로 대체.
완전 삭제는 사용자 승인 후 (`_archive/` 째로 git에는 들어감, NAS는 안 감 — `.dockerignore`).

---

## 3. 어디서든 작업·배포 (NasVideoTrimmer 패턴)

```
[Mac A] 소스 수정 → OneDrive sync
                       ↓
                  ☁ OneDrive
                       ↓
[Mac B] 동일 폴더에서 자동 풀 → ./deploy.sh
                                      ↓
                      rsync → NAS 마운트 폴더
                                      ↓
                docker restart kyobo-library-web
                (정적 파일이라 빠르게 반영)
```

**OneDrive sync 부담 메모**: OCR 텍스트 (`ocr_text/page_*.txt`, 200+개)와 PNG는
`.gitignore` 에 포함되어 OneDrive에는 올라가도 git 추적은 안 함.
필요하면 OneDrive 폴더 동기화 제외도 가능.

---

## 4. 데이터 빌드 파이프라인 (로컬 1회성)

```
원본 PDF 또는 책 페이지 PNG
    │
    │  (1) 수동/AI로 페이지별 요약 JSON 작성
    ▼
batch_127.json, batch_156.json, ... (6개, 페이지 범위별)
    │
    │  (2) merge_batches.py
    ▼
pages_data.json  +  chapters_data.json
    │
    │  (3) (선택) verify_ocr.py — tesseract로 OCR 후 요약 검증
    ▼
verification_report.{json,md} + ocr_text/page_*.txt
    │
    │  (4) generate_html.py — 사이드바·챕터 카드·scroll spy 포함 본문 생성
    ▼
books/<slug>/summary/index.html (498KB 단일 파일)
```

**전제 요구사항**:
- Python 3.9+
- `tesseract` (kor+eng 언어팩) — macOS: `brew install tesseract tesseract-lang`
- `Pillow`, `pytesseract` — `pip install pillow pytesseract`

빌드 자체는 NAS에서 안 한다 (NAS에는 빌드 결과물만 올림).

---

## 5. 로컬 미리보기 (Mac)

정적 사이트라 Python 내장 서버로 충분.

```bash
cd /path/to/NAS/KyoboLibrary
python3 -m http.server 8765
# 브라우저: http://localhost:8765/
```

`file://` 로 직접 열면 `fetch('summary/pages_data.json')` 이 CORS로 막히므로
반드시 HTTP 서버 경유.

---

## 6. NAS 배포

### 6.1 진입점
```bash
./deploy.sh
```
내부 동작:
1. `rsync -avz --delete --exclude-from=.dockerignore` 로 NAS 마운트 폴더 동기화
   - 대상: `RedCode@192.168.10.205:/volume1/docker/web-apps/kyobo-library/`
2. `ssh ... docker restart kyobo-library-web` (정적 파일이지만 캐시 비우기·확실성)
3. `curl http://192.168.10.205:8080/` 헬스체크

### 6.2 SSH·docker 절대경로
DSM의 docker가 PATH 밖이라 `/usr/local/bin/docker` 절대경로 사용
(NasVideoTrimmer와 동일 컨벤션, `../NAS.md` 참조).

### 6.3 8080 컨테이너는 이미 떠 있음
새로 띄울 필요 없음. 마운트 폴더만 업데이트 + restart 하면 끝.
컨테이너 자체 변경(이미지·포트)은 NAS 측 Container Manager에서 별도 처리.

---

## 7. Phase B 계획 (다음 메시지부터)

### 7.1 9000 포트 추가 서비스
- 사용자 요구: 기존 8080은 그대로, 새로 **:9000** 서비스 추가
- 같은 도커 인스턴스/컨테이너 안에서 포함 (별도 컨테이너 띄우지 않음 — 사용자 요청)
- 가능한 형태: 새 nginx server 블록을 같은 컨테이너 안에 추가 + 호스트 9000 → 컨테이너 9000 매핑
- 또는 별도 컨테이너가 더 깔끔할 수도 — 사용자 의도 재확인 필요

### 7.2 교보 e-Library 연동
- 정보 소스: `https://elibrary.kyobobook.co.kr/dig/elb/elibrary`
- 메인 페이지 로그인: `https://ebook.kyobobook.co.kr/dig/pnd/welcome`
- 기술적 제약:
  - 교보문고는 공개 API 없음 — 스크래핑 필요
  - 로그인은 보통 X-Frame-Options/CSP로 iframe 거부
  - e-book 본문은 DRM 보호 → 직접 다운로드 불가
- 가능한 접근:
  - **링크 모음** (가장 단순): 메인에 "교보 e-Library 열기" 버튼만
  - **백엔드 프록시** (복잡): 별도 컨테이너에 Python/Node 백엔드 + 사용자 세션 보관
  - **확장 도우미** (특수): 브라우저 확장으로 데이터 추출
- Phase B 시작 시 사용자와 정확한 의도 정렬 필요

### 7.3 옛 스크립트 정리
- `deploy_to_nas.sh` (IP 오타), `빠른_배포_가이드.md`, `수동_실행_명령어.md`,
  `지금_바로_실행.sh` 삭제 또는 `_archive/` 로 이동 — 사용자 승인 후

---

## 8. 작업 로그

### 2026-05-28: Phase A — 폴더 이동·인프라 정비

**한 일**
- `Claude/kyobo-library/` → `NAS/KyoboLibrary/` 이동 (`mv`, OneDrive sync는 자동)
- 옛 파이썬 3개 분석 (`generate_html.py`/`merge_batches.py`/`verify_ocr.py`) → 워크플로 정리
- 옛 `deploy_to_nas.sh` 에서 NAS IP 오타(`192.168.10.250` → 실제 `205`) 발견 → 사용 금지 메모
- NAS 컨테이너 상태 확인: `kyobo-library-web` (nginx:latest), 마운트 ro, 8080 LISTEN, 실데이터는 placeholder 한 줄

**추가된 파일**
- `CLAUDE.md` (이 문서)
- `.gitignore` (ocr_text, PNG, .DS_Store, verification_report, __pycache__)
- `.editorconfig`
- `.dockerignore` (rsync exclude 겸용)
- `deploy.sh` (rsync + restart + 헬스체크)

**Phase A 마무리 (같은 날 진행)**
- 로컬 `git init -b main` + 초기 커밋 (26개 파일, 규칙 형식, Co-Authored-By 트레일러 없음)
- **첫 실배포 성공** — `./deploy.sh` → http://192.168.10.205:8080/ HTTP 200, 본문에 "CLI 완전활용" 확인. placeholder 한 줄 → 867KB 실 콘텐츠로 교체됨.

**핫픽스 #1 (배포 권한)**
- rsync `-a` 가 로컬 권한(`700`)을 그대로 NAS로 전송 → nginx 워커가 못 읽어 HTTP 403.
- `deploy.sh` 의 rsync 라인에 `--chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r` 추가하여 NAS 측 권한을 디렉토리 `755`·파일 `644` 로 통일.

**다음 (Phase B)**
- 9000 포트 추가 서비스 구조 (별도 컨테이너 권장 — 이유는 Phase B 설계서)
- 교보 e-Library 연동 (현실적 옵션 비교)
- README.md 갱신, opt-in 검색·다크 모드 등 To-Do 처리

---

### 2026-05-28: Phase B-0 — 메인에 교보 외부 링크 카드 추가

**사용자 결정 사항 (Phase B 전체)**
- "같은 도커 내" 해석: **별도 컨테이너** (같은 `docker-compose.yml`의 두 service) ✅
- 별도 교보 크롤링 파이썬 보유 여부: **없음** → 백엔드는 0부터 새로 작성
- Phase B-2 데이터 수집 방식: **백엔드 프록시(옵션 C)** 채택 (Userscript 보조 가능)
- Tampermonkey 확장 설치 거부감: 없음

**한 일**
- `index.html` 에 글래스 카드 2개 추가 — `🔑 교보문고 로그인`, `📖 내 e-Library`
  - 새 탭(`target="_blank" rel="noopener noreferrer"`)으로 외부 URL 열기
  - 보라 그라데이션 배경 위 반투명 흰 카드(`backdrop-filter: blur(8px)`) — 기존 톤과 일관
- `.section-label` 추가하여 "교보 e-서비스" / "내 도서 라이브러리" 두 구역 시각 구분
- 모바일 반응형(`@media max-width: 768px`)에서 quick-grid 1열로 collapse

**핫픽스**
- `docs/PHASE_B_PROPOSAL.md` 가 `.dockerignore` 누락으로 NAS에 따라감 → `/docs/` 룰 추가, NAS의 docs/ 폴더 수동 삭제

**검증**
- 배포: `./deploy.sh` HTTP 200
- 본문에 `href="https://ebook.kyobobook.co.kr/dig/pnd/welcome"` / `href="https://elibrary.kyobobook.co.kr/dig/elb/elibrary"` 정상 출력

**다음 (Phase B-1, 다음 메시지에서)**
- `docker-compose.yml` 새로 작성 (두 service: `library-web`(기존 nginx) + `kyobo-bridge`(신규 FastAPI))
- FastAPI 백엔드 스캐폴드 — `/health`, `/api/library/books`, SQLite 저장
- 9000 포트 매핑, NAS 마운트 추가
- 그 후 Phase B-2: 백엔드 프록시 — 교보 로그인 폼 대행 + 세션 보관 + e-Library API 호출

---

### 2026-05-28: Phase B-1 — 9000 포트 FastAPI 백엔드·compose 통합

**추가된 폴더·파일**
- `kyobo-bridge/` — FastAPI 백엔드
  - `Dockerfile` (python:3.12-slim + httpx + curl, HEALTHCHECK 내장)
  - `requirements.txt` (fastapi 0.115.5, uvicorn[standard] 0.34.0, httpx 0.27.2)
  - `app/__init__.py` (__version__ = 0.1.0)
  - `app/main.py` (FastAPI, lifespan, CORS, /health, /api/library/books, B-2 placeholders)
  - `app/db.py` (SQLite WAL 모드, books 테이블)
  - `README.md`
- `docker-compose.yml` (루트) — `library-web` + `kyobo-bridge` 두 service
- `deploy.sh` 전면 재작성 — 정적 rsync + buildx amd64 + save+scp+load + compose up + 두 포트 헬스체크. `--static` / `--backend` / `--dry` / `--logs` 옵션
- `.dockerignore` 보강 — `/kyobo-bridge/`, `/docker-compose.yml` 추가 (정적 rsync에 안 따라가도록)

**기존 인프라 인계**
- DSM Container Manager로 떠 있던 `kyobo-library-web` 컨테이너를 **compose 통제로 자동 인계**
  (`deploy.sh` 의 stop/rm + compose up 흐름). 다운타임 ~5초.
- NAS compose 위치: `/volume1/docker/kyobo-stack/docker-compose.yml`
- 새 NAS 볼륨: `/volume1/docker/web-apps/kyobo-bridge/data` (SQLite WAL)

**검증**
- ✅ `kyobo-bridge:latest` 이미지 67MB (buildx amd64)
- ✅ 두 컨테이너 모두 `com.docker.compose.project=kyobo-stack` 라벨로 통제
- ✅ `GET /health` → `{"status":"ok","service":"kyobo-bridge","version":"0.1.0","books":0}`
- ✅ `GET /api/library/books` → `{"books":[],"version":"0.1.0"}`
- ✅ Phase B-2 placeholders: `POST /api/auth/kyobo/login` `POST /api/library/sync` → **501**
- ✅ 기존 `http://192.168.10.205:8080/` 정상 (compose 인계 후에도)

**다음 (Phase B-2, 다음 메시지)**
- `httpx.AsyncClient(cookies=...)` 로 교보 로그인 폼 대행
- 사용자 세션 보관 (서버 메모리 또는 SQLite, 보안 모드 결정 필요)
- `POST /api/auth/kyobo/login {id, pw}` → JSESSIONID 받아 저장
- `POST /api/library/sync` → 저장된 세션으로 e-Library 도서 메타 페이지 가져와 파싱·SQLite 적재
- `GET /api/library/books` 가 sync된 책 반환
- 메인 페이지에 도서함 뷰 추가 (정적 라이브러리 + sync된 e-Library 둘 다 표시)

---

### 2026-05-28: Phase B-2 — sync receiver + Userscript + 도서함 뷰

**큰 결정 변경 (분석 후)**
- 교보의 두 페이지(`mmbr.kyobobook.co.kr/login`, `elibrary.kyobobook.co.kr`) 모두 **SPA**.
  HTML 정적 분석에서 `<form>`·`<input type="password">`·로그인 endpoint 모두 발견 불가.
- 백엔드 자동 로그인 프록시(원래 옵션 C 본격)는 JS 번들 reverse engineering 없이는 불가능.
- 변경된 접근: **Userscript(옵션 B)를 주축**으로 진행. cURL 캡처가 있으면 향후 프록시 추가.

**추가/수정된 파일**
- `kyobo-bridge/app/db.py` — `upsert_books()`/`clear_books()` 추가. kyobo_id 우선 / 없으면 (title,author) 키로 upsert. 미정의 필드는 `meta_json` 으로 보존.
- `kyobo-bridge/app/main.py` — `/api/library/sync` 활성화(pydantic 모델), `/api/library/books DELETE` 추가, CORS에 교보 도메인 포함, `/api/auth/kyobo/login` 은 SPA 안내 메시지로 501.
- `userscript/sync-kyobo-library.user.js` (신규) — Tampermonkey Userscript. `elibrary.kyobobook.co.kr` 페이지에 우측 하단 floating 패널 주입 → [미리보기]/[동기화] 버튼 → `GM_xmlhttpRequest` 로 9000으로 POST. 셀렉터 후보 8종 자동 시도 + 가장 많이 매치되는 것 선택.
- `index.html` — `📥 내 e-Library 동기화` 안내 카드 + `내 e-Library 도서함` 섹션. 페이지 로드 시 백엔드 `/health` + `/api/library/books` 자동 호출. 표지 깨지면 placeholder.

**검증 (end-to-end)**
- ✅ `http://192.168.10.205:8080/userscript/sync-kyobo-library.user.js` — 10KB, MIME `application/javascript` (Tampermonkey 자동 인식 OK)
- ✅ `POST /api/library/sync` 가짜 2건 → `{ok:true, inserted:2, updated:0, total:2}`
- ✅ `GET /api/library/books` JSON 정상 (id, kyobo_id, title, author, cover_url, synced_at)
- ✅ `DELETE /api/library/books` → 2건 비우기

**사용자가 실제로 시도하는 방법**
1. Tampermonkey 확장 설치(한 번)
2. http://192.168.10.205:8080/userscript/sync-kyobo-library.user.js 열기 → 설치
3. 메인의 `[📖 내 e-Library]` 카드 클릭 → 교보 로그인 → 도서함 페이지
4. 우측 하단 패널의 [미리보기] → F12 콘솔에서 잘 추출됐는지 확인
5. [동기화] 클릭 → 메인 페이지의 `[내 e-Library 도서함]` 섹션에 도서 카드 표시

**다음 (Phase B-3 후보)**
- 사용자 첫 시도 결과 받고 **셀렉터 조정** (실제 DOM 보면 더 정확한 selector·필드 매핑)
- 백엔드 프록시 옵션: 사용자가 본인 브라우저 devtools에서 로그인 XHR `Copy as cURL` → 그 cURL 우리에게 → httpx 로 그대로 흉내
- README.md 새로 작성 (Phase A의 옛 README 대체)
- sync 인증 (지금은 LAN 누구나 호출 가능, secret token 추가 가능)
- 페이지 검색·다크 모드·즐겨찾기 등 정적 라이브러리 To-Do

---

## Phase C — 도서 분석 파이프라인 (캡처 → OCR → AI 요약 → HTML)

### 결정 사항
- **언어**: Python (macOS 자동화·OCR·AI 모두 Python 자산 풍부)
- **기존 자산**: `/Users/deoksooyun/Library/CloudStorage/OneDrive-개인/SRC/python/kyobo_screenshot/`
  - `kyobo_app_screenshot.py` (817줄) — macOS 교보eBook.app 자동 캡처
  - `kyobo_screenshot.py` (264줄) — Playwright 웹뷰어 캡처
  - `kyobo_capture.sh` — 대화형 CLI 메뉴 (앱 실행·캡처 모드 선택)
  - `verify_ocr.py` / `merge_batches.py` / `generate_html.py` — 이미 books/CLI_완전활용/summary/ 에 복사돼 있음
  - `CLAUDE.md` — 요약 JSON 스키마·HTML 패턴 (1800px 썸네일·사이드바 트리·페이지 카드)
- **아키텍처**: 8080 정적 UI + 9000 FastAPI 백엔드 + Mac 로컬 worker (polling)
- **동작 시작점**: 웹 (도서 카드 클릭 → 분석 시작)

### 단계
- **C-1** ✅ 메인 우상단 톱니바퀴 + 설정 모달 + `/api/settings` 백엔드 (DONE)
- **C-2** ⏳ `KyoboLibrary/book-capture/` Python 패키지 신설, 기존 자산 이식·통합 CLI
- **C-3** ⏳ AI 요약 모듈 (Claude/OpenAI), 백엔드 `/api/jobs` 큐, poll_worker.py
- **C-4** ⏳ 메인 도서 카드에 분석 상태 + [분석 시작]/[보기] 버튼

### 2026-05-28: Phase C-1 — 톱니바퀴 + 설정 모달

**추가**
- `kyobo-bridge/app/db.py` — `settings` 테이블 + `get_setting`/`set_setting`/`get_all_settings`/`set_all_settings`
- `kyobo-bridge/app/main.py` — `GET /api/settings` (기본값 머지 + api_key 마스킹 응답) / `PUT /api/settings` (부분 업데이트 + api_key 빈 값은 기존 유지)
- `index.html` — 헤더 우상단 ⚙ 버튼, 다크 톤 설정 모달 (캡처/OCR/AI/출력 4그룹, 17개 필드), 백엔드 API 호출 + 저장 status

**설정 4그룹**
1. **캡처** — 영역 x/y/w/h, 페이지 넘김 대기, 최대 페이지 수, 넘김 키, 첫 페이지 로딩 대기, 중복 해시 중단
2. **OCR** — 언어(`kor+eng` 등), 썸네일 사용 여부
3. **AI** — 공급자(claude/openai/none), 모델, API 키(마스킹), 출력 언어, temperature
4. **출력** — 책 폴더(Mac 로컬), 썸네일 최대 px

**보안 메모**
- `api_key`는 SQLite에 평문 저장(향후 암호화 검토). GET 응답에는 빈 문자열 + `api_key_masked: "sk-...1234"` 형식.
- PUT 시 `api_key=""` 면 기존 값 유지 (사용자가 마스킹 상태에서 안 건드린 경우).

**검증**
- GET `/api/settings` 기본값 정상
- PUT `/api/settings` 부분 업데이트 정상 (`updated_keys: N`)
- region 저장·복원 OK
- api_key 마스킹 OK, 평문 응답 안 함

**다음 (C-2)**
- `KyoboLibrary/book-capture/` 폴더 신설
- 기존 `kyobo_app_screenshot.py`·`verify_ocr.py`·`generate_html.py` 이식 + venv 정리
- 통합 CLI: `python -m bookcapture run --slug <도서명>`
- C-1 설정값 자동 로드 (`/api/settings` 호출)

---

### 2026-05-28: Phase C-2 — book-capture 패키지 + 기존 파이썬 이식

**추가**
- `book-capture/` 신규 폴더 (NAS 미전송, `.dockerignore` 처리)
- `book-capture/bookcapture/` Python 패키지
  - `__init__.py` `__main__.py` `cli.py` — `python -m bookcapture <sub>` 엔트리
  - `settings.py` — `/api/settings` 로드(표준 `urllib`만 사용, 의존성 0). 환경변수 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 우선
  - `kyobo_app.py` — **기존 `kyobo_app_screenshot.py` 817줄 그대로 이식** (검증된 캡처 자산 보존)
  - `ocr.py` — `verify_ocr.py` 패턴 단순화 (검증 아닌 OCR 캐시만), `make_thumbnails()` 1800px 리사이즈
  - `build_html.py` — Phase C-2 placeholder 인덱스 (썸네일 그리드, OCR 유무 표시). C-3에서 사이드바·챕터 카드 본격
- `requirements.txt` — Pillow, pytesseract (HTTP는 표준 라이브러리)
- `README.md` — Mac venv 설정, tesseract 설치, macOS 권한, 5가지 서브커맨드 표
- `.gitignore` — venv, books/, *.png, ocr_text/, thumbs/ 제외
- `.dockerignore` 루트에 `/book-capture/` 추가 — NAS rsync 미전송

**서브커맨드 5개**
| 명령 | 동작 |
|---|---|
| `settings` | 현재 백엔드 설정 + AI 키 환경변수 점검 |
| `capture --mode 1/2/3` | `kyobo_app.py` 인터랙티브 캡처 (전체/윈도우/연속) |
| `ocr --slug X` | `<books_dir>/X/` *.png → `summary/ocr_text/page_NNN.txt` |
| `build --slug X` | C-2 placeholder 인덱스 HTML |
| `run --slug X --mode 3` | capture → ocr → build 일괄 |

**검증**
- `python3 -m bookcapture` help 정상
- `python3 -m bookcapture settings` 백엔드 값 정확 반영 (`capture[100,50 1800×1100] delay=2.0s ...`)
- httpx 없이 표준 라이브러리만으로 동작 — Mac 시스템 python3 즉시 사용 가능
- venv 만들 때만 `pip install -r requirements.txt` (Pillow·pytesseract)

**Mac 사용자 시작 흐름**
```bash
cd KyoboLibrary/book-capture
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install tesseract tesseract-lang
export ANTHROPIC_API_KEY="sk-ant-..."
python -m bookcapture run --slug "그림으로 이해하는 알고리즘"
```

**다음 (C-3)**
- `summarize.py` — Claude API(또는 OpenAI) 호출, OCR 텍스트 → `{ 주요주제, 주요용어, 강의요약, 핵심내용 }` batch JSON
- `merge.py` — `merge_batches.py` 이식 (pages_data.json + chapters_data.json 자동 생성)
- `build_html.py` 본격 — `generate_html.py` 패턴(사이드바 트리, 챕터 카드, scroll spy)
- `worker.py` — 백엔드 `/api/jobs` 큐 polling
- 백엔드: `/api/jobs` POST/GET, jobs 테이블 추가

---

### 2026-05-29: Phase C-3 (Part 1) — AI 요약 모듈 동작 검증

**한 일**
- `kyobo-bridge/app/main.py` — `/api/secrets/ai` 추가 (LAN-only IP 화이트리스트: loopback·private·link-local). book-capture가 평문 API 키를 안전하게 받는 endpoint
- `kyobo-bridge/app/main.py` — CORS `allow_methods` 에 PUT/OPTIONS 추가 (C-1 핫픽스, 별도 커밋)
- `book-capture/bookcapture/settings.py` — 키 조회 우선순위 추가: 환경변수(ANTHROPIC_API_KEY) → 백엔드 `/api/secrets/ai` → 마스킹 응답
- `book-capture/bookcapture/summarize.py` (신규) — 핵심 모듈
  - `summarize_page()` — OCR 1페이지 → batch JSON 1페이지 (Anthropic Messages API, urllib만)
  - `summarize_pages()` — 다수 페이지 일괄 + 진행률 + 비용 누적
  - SYSTEM_PROMPT — 한국어 학습 도서 요약 전문가
  - 재시도(429/5xx, exponential backoff 3회)
  - JSON 추출(`_extract_json`) — 코드펜스/잡담 제거
  - 비용 계산(`_PRICES`) — Sonnet/Haiku/Opus 토큰 단가 내장
- `book-capture/bookcapture/cli.py` — `summarize` 서브커맨드 (`--slug`, `--pages 127-155`, `--out`), `run` 흐름에 summarize 단계 통합(+ `--no-summarize` 스킵 옵션)

**검증 (실제 API 호출)**
- ping: `claude-sonnet-4-5`, `Reply: PONG`, in/out 14/6 토큰, $0.0001
- 1페이지 요약 (`books/CLI_완전활용/summary/ocr_text/page_127.txt`):
  - 결과: topics 3개 / terms 5개 / summary 4문장 (`<br>` 줄바꿈) / points 4개 (`<strong>·<code>` 활용)
  - 토큰: in 839 / out 590, 비용 **$0.011** (≈ 15원)
  - 품질: 기존 사용자 수동 작성본과 동등 수준

**책 한 권 비용 추정** (280페이지 기준)
| 모델 | 한 권 비용 | $20 으로 |
|---|---|---|
| Claude Sonnet 4.5 | **$3.18** (≈ 4,400원) | ~6권 |
| Claude Haiku 4.5  | $1.06 (≈ 1,500원) | ~19권 |

**다음 (C-3 Part 2)**
- `merge.py` — `merge_batches.py` 이식 (batch_*.json → pages_data.json + chapters_data.json)
- `build_html.py` 본격 — `generate_html.py` 패턴 (사이드바·챕터 카드·scroll spy)
- 백엔드 `/api/jobs` 큐 + `worker.py` polling (선택, CLI 직접 호출로도 충분)
- C-4: 도서 카드에 [분석 시작]/[보기]/[원본] 버튼 + 분석 상태 배지

---

### 2026-05-29: Phase C-3 Part 2 — merge + 본격 HTML 빌드

**추가/수정**
- `book-capture/bookcapture/merge.py` (신규) — 기존 `merge_batches.py` 153줄을 함수로 이식
  - `merge_batches(summary_dir)` — `batch_*.json` glob → `pages_data.json` 생성
  - `_make_chapter_id()` — `chs-chapter-N` / `chs-part-N` 자동 부여
  - `_build_chapters()` — section_id 와 chapter_intro 로 챕터/섹션 트리 자동 구성
- `book-capture/bookcapture/build_html.py` 본격 (placeholder 대체) — 기존 `generate_html.py` 477줄의 핵심 로직 이식
  - 좌측 사이드바 트리 (320px, 챕터-섹션-페이지)
  - 페이지 카드 (좌: 이미지, 우: 주요주제/주요용어/강의요약/핵심내용)
  - 이미지 모달 (클릭 확대, ESC 닫기)
  - IntersectionObserver 기반 scroll spy (현재 페이지 사이드바 하이라이트)
  - `chs-card` 챕터 종합 카드는 스킵 (chapters_data.json 의존 — 후속에서 자동 생성 검토)
  - `build_index()` 하위 호환 유지 — `pages_data.json` 있으면 본격, 없으면 placeholder
- `book-capture/bookcapture/cli.py`
  - `merge` 서브커맨드 추가
  - `run` 흐름: capture → ocr → (summarize) → **merge** → build
- `.gitignore` / `.dockerignore` — `*.BAK`, `pages_data.json` 등 추가

**검증 (실제 CLI_완전활용 데이터)**
- `bookcapture merge --book-dir books/CLI_완전활용`
  → 6 batch 머지, 185 페이지, 5 챕터 자동 분리 ([chs-chapter-4], [chs-chapter-5], [chs-part-3], [chs-part-4], [chs-part-5])
- `bookcapture build --book-dir books/CLI_완전활용`
  → 439KB index.html (기존 487KB와 거의 동등, chs-card 빼서 살짝 작음)
  → 사이드바 5 챕터 + 페이지 카드 185개 정확
- 기존 `index.html.BAK` 보존 (사용자 비교용)

**Phase C 진행 상황**
- ✅ C-1: 톱니바퀴 + 설정 모달 + `/api/settings`
- ✅ C-2: book-capture 패키지 + 기존 캡처 스크립트 이식
- ✅ C-3 Part 1: AI 요약(`summarize.py`) + `/api/secrets/ai`
- ✅ C-3 Part 2: merge + build_html 본격
- ⏳ C-3 Part 3 (선택): 백엔드 `/api/jobs` 큐 + `worker.py` polling — CLI 직접 호출로 충분하면 생략
- ⏳ C-4: 메인 도서 카드 클릭 → [분석 시작]/[보기]/[원본] 모달 + 분석 상태 배지

**Mac 사용자 풀 워크플로 (현재 기준)**
```bash
cd KyoboLibrary/book-capture
source .venv/bin/activate            # (venv 없으면 한 번 생성)

# 한 책 전체 자동
python -m bookcapture run --slug "그림으로 이해하는 알고리즘" --mode 3
# = 캡처 → OCR → AI 요약 → merge → build → summary/index.html

# 또는 단계별
python -m bookcapture capture --mode 3
python -m bookcapture ocr      --slug "그림으로 이해하는 알고리즘"
python -m bookcapture summarize --slug "그림으로 이해하는 알고리즘" --pages 1-50
python -m bookcapture merge    --slug "그림으로 이해하는 알고리즘"
python -m bookcapture build    --slug "그림으로 이해하는 알고리즘"
```

---

### 2026-05-29: Phase C-4 — 도서 카드 클릭 모달 + 분석 상태 배지

**추가/수정**
- `docker-compose.yml` — kyobo-bridge 에 `/volume1/docker/web-apps/kyobo-library:/mnt/library:ro` 마운트, `LIBRARY_BOOKS_DIR=/mnt/library/books` 환경변수 추가
- `kyobo-bridge/app/main.py` — `GET /api/books/analyzed` 추가
  - `<LIBRARY_BOOKS_DIR>/<slug>/summary/index.html` 존재 폴더 스캔
  - `pages_data.json` 있으면 페이지 수도 응답에 포함
  - `[{slug, pages, url}]` 배열 반환
- `index.html` — 도서 카드 + 모달 전면 개편
  - 카드: `<a>` → `<div>` (클릭 시 모달), 우상단 분석 상태 배지(`✓ 분석됨` / `미분석`)
  - 모달: 표지 + 슬러그 + 메타 + 3버튼 (`📊 분석 시작` / `📖 보기` / `↗ 원본`)
  - `📖 보기`는 분석 완료 시만 활성, 클릭 시 `books/<slug>/summary/index.html` 새 탭
  - `📊 분석 시작` 누르면 CLI 명령 박스 표시 (복사 버튼 포함) — Phase C-3 Part3 백엔드 큐 완성 전 임시 UX
  - `slugify(title)` — 선행 `[epub3.0]` prefix 제거 + 공백→_
- 카드 카운트 라벨: `280권 · 분석 N권` 로 갱신

**검증**
- 컨테이너 마운트: `/mnt/library/books/` 에 `CLI_완전활용` 폴더 인식
- `GET /api/books/analyzed` → `{ analyzed: [{slug:"CLI_완전활용", pages:185, url:"books/CLI_완전활용/summary/index.html"}], ... }`
- 메인 페이지 JS·CSS 모두 정상 (kyobo-badge, bmodal-bd, openBookModal, slugify, loadAnalyzed 모두 마크업에 포함)

**사용자 흐름 (브라우저)**
1. 카드에 호버 → 우상단 `미분석` 또는 `✓ 분석됨` 배지
2. 카드 클릭 → 다크 모달
3. 슬러그 자동 표시 (예: `IT_엔지니어를_위한_네트워크_입문`) — 복사 가능
4. **[📊 분석 시작]** 클릭 → CLI 명령 박스 등장:
   ```
   cd KyoboLibrary/book-capture && python -m bookcapture run --slug "IT_엔지니어를_위한_네트워크_입문" --mode 3
   ```
5. 사용자가 터미널에서 실행 → 결과는 Mac 로컬 `book-capture/books/<slug>/` 에 생성
6. NAS 반영: `./deploy.sh --static` → 메인 새로고침 → 배지 `✓ 분석됨` 으로 변경 → **[📖 보기]** 활성

**Phase C 진행 상황**
- ✅ C-1: 톱니바퀴 + 설정 모달 + `/api/settings`
- ✅ C-2: book-capture 패키지 + 기존 캡처 이식
- ✅ C-3 Part1: AI 요약(`summarize.py`) + `/api/secrets/ai`
- ✅ C-3 Part2: merge + build_html 본격 (사이드바·페이지 카드·scroll spy)
- ✅ **C-4: 도서 카드 모달 + 분석 상태 배지**
- ⏳ C-3 Part3 (선택): 백엔드 `/api/jobs` 큐 + `worker.py` polling — 현재는 CLI 직접 호출. 자동 트리거 원하면 추가

---

### 2026-05-28: Phase B-2.1 — Tampermonkey + Userscript 설치 가이드 페이지

**추가**
- `install.html` — 별도 가이드 페이지 (14.5KB). 4단계 + 트러블슈팅 1섹션
  - 번호 박스 디자인 (시안 배경 + 검정 테두리 + 3px 그림자 — 강한 시각 표식)
  - 각 단계마다 캡처 슬롯 (`shot-placeholder` 점선 박스 + 줄무늬 배경)
  - 단계 1: tampermonkey.net → Chrome Web Store 추가
  - 단계 2: chrome://extensions/ 개발자 모드 ON
  - 단계 3: Userscript URL 클릭 → Tampermonkey 자동 인식 → [설치] + `chrome-extension://...ask.html` 권한 허용
  - 단계 4: 교보 e-Library 로그인 → 다크 패널 [동기화]
- `install-img/` 폴더 + 캡처 받을 자리 안내 README (NAS에는 안 감)
- 메인 페이지에 `📖 자세한 설치 가이드` 버튼 추가 (sync-card 안)
- `.gitignore` 에 `!install-img/*.png` 예외 (캡처는 git 추적)
- `.dockerignore` 에 `/install-img/README.md` 추가

**사용자에게 받을 캡처 5장 (`install-img/0X-...png`)**
1. tampermonkey.net 홈에서 본인 브라우저 아이콘 클릭 화면
2. chrome://extensions/ 우상단 [개발자 모드] 토글
3. Tampermonkey 자동 인식 → [설치] 버튼 화면
4. `chrome-extension://...ask.html` 권한 요청 화면
5. 교보 e-Library 페이지 우측 하단 다크 동기화 패널

캡처에 ①②③ 번호 박스는 사용자가 미리 그려서 보내거나, 그대로 보내도 install.html 의 step-num 박스로 단계 식별 가능.