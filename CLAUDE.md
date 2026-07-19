
- 2026.06.08 [로그] access_log(전체 접속 비콘)·admin_log(보안이벤트) 테이블+API(`/api/track` 공개, `/api/admin/access-log·log` 관리자). _client_info 재사용(IP/OS/브라우저/MAC best-effort), 기기 PC/모바일 판별. 이미지 재빌드 영구반영.

- 2026.06.08 [이미지/env] kyobo-bridge 이미지 재빌드(buildx amd64)로 car/admin 코드 영구 반영(그동안 docker cp 였음 — 재생성 위험 해소). client_secret 을 `/volume1/docker/kyobo-stack/.env`(OIDC_CLIENT_SECRET, 600, git제외) → compose env 주입. `_oidc_cfg` env>파일>DB. DB secret 빈값, /data 파일은 폴백 유지.

- 2026.06.08 [admin SSO] Synology SSO Server(OIDC) 관리자 로그인 — `/api/admin/sso/login·callback·me·logout` + `/api/admin/car-code`(세션필요). well-known 5560 엔드포인트, client_id/secret/admin_users=settings, 세션 인메모리8h. CORS allow_credentials=True. main.py cp+restart.

- 2026.06.08 [car API] `/api/car/profile` GET/POST(키필요, settings car_profile) 추가 + `_check_car_key` IP rate-limit(5분8회 429)·실패로깅. redcodeme-nas-portal 내차정보 민감데이터(차량번호·차대번호·할부) 백엔드 이전용. main.py cp+restart 배포.

- 2026.06.08 [car API] kyobo-bridge 에 `car_log` 테이블 + `/api/car/log` GET/POST/DELETE 추가 (redcodeme-nas-portal portal '내 차 정보' 엔진오일 기록 DB 저장용). `CAR_API_KEY` 옵션 토큰(_check_car_key). docker cp+restart 배포(소스 db.py/main.py 갱신, 미커밋). 현재 키 미설정=개방.

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
| 원격 저장소 | **`git@github-com-ckidsm:ckidsm/Ebookibrary.git`** (개인 ckidsm 계정, **Private**, 2026-07-05 생성·최초 push) |
| 인증 패턴 | `github-com-ckidsm` SSH host alias (개인 키 `~/.ssh/id_ed25519_ckidsm`). ⚠️ gh CLI 는 회사 `Redocde` 로 인증돼 있으니 리포 생성/API 는 계정 주의 |
| ⚠️ 비밀 금지 | **NAS 비밀번호·API 키를 스크립트에 하드코딩 절대 금지.** 배포는 `book-capture/scripts/publish_book.sh`(비번=`NAS_PASS` 환경변수)로. 비번 출처는 `인증서/나스인증/`(repo 밖). |

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

### 2026-06-09: iPad 인식 버그 + 팝업 z-index 수정

- **버그1(핵심)**: iPadOS Safari UA 가 'Macintosh' 로 표기 → `isMac` 오인 → 로컬 매크로(macOS 전용)가 기본 선택돼 분석 시작 시 앱 안 열림·캡처 안 됨. → `isIOS = /iPhone|iPad|iPod/ || (Macintosh && maxTouchPoints>1)`, `isMac = Macintosh && !isIOS`. iPad → canMacro=false → 캡처 업로드 기본·Recommended + iPad 업로드 안내(스크린샷→업로드, 자동캡처 불가 명시).
- **버그2(공통)**: `.confirm-bd/.confirm`(캡처-준비·confirm 다이얼로그) z-index 250/251 < 책모달(bmodal) 920/921 → 팝업이 책 모달 뒤로 숨음. → 950/951 로 상향.
- iPad는 iOS 샌드박스로 앱 자동열기·자동캡처 불가(Mac/Win 만 로컬워커). 모바일은 스크린샷→업로드(openUploadFlow, bmodal-extra 주입이라 안 숨음).
- 배포: /volume1/web/kyobo + docker(8080) scp.


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
---

### 2026-05-29: Phase C-3 Part3 — 백엔드 작업 큐 + worker polling

**추가/수정**
- `kyobo-bridge/app/db.py` — `jobs` 테이블 (id, slug, title, mode, status, progress, error...), `cancel_job()` (running→cancelling 비파괴 전이), `claim_next_job()` 원자 transition
- `kyobo-bridge/app/main.py` — POST/GET/PATCH/DELETE `/api/jobs`, `/api/jobs/next/claim` (LAN-only), `/api/jobs/{jid}` DELETE → cancel
- `book-capture/bookcapture/worker.py` (신규) — polling 워커, progress JSON 보고, is_cancelling 체크 후 subprocess.terminate, heartbeat
- `book-capture/bookcapture/cli.py` — `worker` 서브커맨드, `capture-auto` (비대화형)
- `book-capture/bookcapture/kyobo_app.py` — `noninteractive=True` 파라미터 추가 (input() 우회)

### 2026-05-29: Phase C-4 보강 — 폴링·진행률·중단·다이얼로그

**추가/수정**
- `index.html` — 분석 모달에 progress bar, stage 박스, 중단 버튼, 워커 상태 표시
- 분석 시작 → 백엔드 큐 등록 → 즉시 폴링 → 모달 안 박스 갱신
- 모달 X 닫기 → 백그라운드 폴링 유지 (작업 안 죽임)
- Job 상태 라이프사이클: pending → running → done/failed/cancelled. cancelling 은 비파괴 (워커가 graceful terminate)

### 2026-05-29: 외부 노출 — Web Station + DSM Reverse Proxy

**문제**: Synology DSM 의 Reverse Proxy 는 **URL Path 분기 미지원**. 같은 호스트 443 안에서 `/api/*` 만 따로 라우팅 불가.

**해결**: 백엔드를 다른 포트(9443)로 매핑.
- `https://redcodeme.synology.me/` → Web Station (메인)
- `https://redcodeme.synology.me/kyobo/` → Web Station (KyoboLibrary 정적)
- `https://redcodeme.synology.me:9443/` → Reverse Proxy → localhost:9000 (백엔드 API)

**라우터·방화벽 (2026-05-29 적용 완료)**:
- DSM Reverse Proxy: `Kyobo Bridge API`, 소스 HTTPS `redcodeme.synology.me:9443`, 대상 HTTP `localhost:9000`
- 공유기 NAT 9443 외부 포워딩 (외부 포트 오타 9433→9443 수정)
- Synology 방화벽: 비활성 (NAS 자체 방화벽 OFF)
- 검증: 외부 `https://redcodeme.synology.me:9443/health` → 200 OK

**추가**
- `index.html` — `BRIDGE_URL` 자동 분기: LAN(8080/IP)→`:9000`, 외부(redcodeme)→`:9443`
- `deploy.sh` — 정적 rsync 두 곳 (`/volume1/docker/web-apps/kyobo-library` + `/volume1/web/kyobo`) + 백엔드 데이터 snapshot (`api-cache/*.json` Reverse Proxy 미설정 시 fallback)
- `docs/EXTERNAL_ACCESS.md` — 외부 노출 매뉴얼

### 2026-05-29: UX 개선 모듈 — confirm·카드 오버레이·worker 추적

**1) 책 모달 X 닫기 — 커스텀 confirm**
- `index.html` — `showCustomConfirm({title, body, options})` Promise 모달
- 분석 진행 중일 때 모달 X → 사이트 톤 다이얼로그: [작업 계속 (창만 닫기)] / [작업 중단하고 나가기]
- 백드롭 클릭 = 취소. 후자 선택 시 백엔드 cancel 호출.

**2) 메인 카드 — 진행 중 도서 progress + 중단**
- `_activeJobs` 글로벌 Map (slug → {jobId, status, pct, stageName})
- 카드 하단 그라데이션 오버레이: stage 이름 + % + bar + [상세][⏹ 중단]
- 단일 timer 가 모든 active jobs 폴링. 종료 잡 모두 빠지면 timer 자동 해제.
- 페이지 새로고침 시 `restoreActiveJobs()` 가 `GET /api/jobs` 호출 → pending/running/cancelling 복원

**3) 워커 client 추적 (worker_clients 테이블)**
- `db.py` — `worker_clients(client_ip, hostname, platform, first_seen, last_seen, ping_count)`, `upsert_worker_client()`, `get_worker_client_by_ip()`
- `main.py` — `POST /api/worker/ping` 가 hostname/platform 받아 자동 저장 (pydantic `WorkerPing` 모델)
- `GET /api/worker/status` 응답에 `previously_seen`, `known.{hostname, platform, last_seen_ago_sec}` 추가
- `worker.py` — `_ping_meta()` 가 socket.gethostname() + platform.system() 보냄

**4) 워커 안내 톤 분기**
- `index.html` — `buildWorkerInstallHint(ws)` 가 `ws.previously_seen` 분기
  - 처음 (false): 🛑 빨강 + ⬇ "워커 인스톨러 다운로드" 큰 초록 버튼 primary
  - 이전 설치됨 (true): 🔵 청록 + "워커가 멈췄어요 (hostname)" + ▶ "워커 다시 시작" 큰 청록 버튼
- `install/restart-worker.command` (신규) — bootout + bootstrap 재시작 전용 더블클릭

**5) 매크로 무한 루프 사고 — plist PATH 누락**
- 사고: 워커 launchctl 등록 후 매크로 무한 시도 (screencapture command not found)
- 원인: `~/Library/LaunchAgents/com.kyobolibrary.worker.plist` EnvironmentVariables PATH 에 `/usr/sbin` 누락
  → `screencapture` 가 `/usr/sbin/screencapture` 에 있음 → 매번 실패 → KeepAlive 재시작 → 무한 루프
- 처리: 워커 unload (`launchctl bootout`), 쌓인 pending/running 6개 모두 cancel
- 수정: `install-worker-macos.sh` PATH 에 `/usr/sbin:/sbin` 추가, `launchctl load` → `launchctl bootstrap gui/$UID` 로 현대화 (실패 시 legacy 폴백)
- 현재 plist 도 즉시 sed patch 완료

**6) backendUnreachableHint 문구 갱신**
- 9443 외부 노출 완료된 지금, 이전 "외부 노출 안 됨" 문구는 사실과 다름
- "백엔드 API 일시 미응답 + 새로고침 권유 + LAN 직접 접속 대안" 으로 변경

### 2026-05-29: 진행 중 — Developer ID 사인 + .pkg 인스톨러

**배경**
- 사용자: "터미널 명령 자주 보여주는 게 일반 사용자에게 과하다. JS 등으로 처리"
- JS 로 시스템 명령 실행은 보안상 절대 불가
- 사인 없는 .command/.pkg/.app 은 macOS Gatekeeper 가 1회 차단 (시스템 설정 → '그래도 허용' 가능)
- 사용자가 "Apple Developer ID 있다" 라고 함 → 사인 + 공증으로 Gatekeeper 완전 우회 가능

**현재 인증서 점검 결과 (2026-05-29)**
- ✅ Apple Development (개발 빌드)
- ✅ Apple Distribution (App Store 업로드)
- ❌ **Developer ID Application** (외부 배포 .app 사인) — **추가 발급 필요**
- ❌ **Developer ID Installer** (외부 배포 .pkg 사인) — **추가 발급 필요**
- ❌ notarytool credential 프로필 없음

**Apple ID 후보**
- ckidsm@nate.com / "Apple Development: deok soo yun" (Team: RRTB256N59) — 개인
- kkidsm@mirusystems.com — 회사
- 이 프로젝트는 개인 계정 (Team `RRTB256N59`) 사용 예정

**사용자 액션 대기 중 (Developer ID 발급)**
1. https://developer.apple.com/account → Certificates → +
   - Developer ID Application 발급
   - Developer ID Installer 발급
   - CSR 은 Keychain Access → 인증서 도우미에서 생성
2. https://appleid.apple.com → 로그인 및 보안 → 앱 암호 → `notarytool` 생성 (xxxx-xxxx 형식)
3. Team ID 확인

**발급 후 자동화 단계 (claude 작업)**
1. `xcrun notarytool store-credentials "KYOBO_NOTARY" --apple-id ... --team-id RRTB256N59 --password xxxx` 으로 keychain 등록
2. `scripts/build-pkg.sh` 작성:
   - payload root 구조 (`/Library/Application Support/KyoboLibrary/...`)
   - postinstall 스크립트 (`install-worker-macos.sh` 자동 호출)
   - `pkgbuild --root ... --identifier com.kyobolibrary.worker --version 1.0`
   - `productbuild --distribution dist.xml --sign "Developer ID Installer: ..."`
   - `xcrun notarytool submit --keychain-profile KYOBO_NOTARY --wait`
   - `xcrun stapler staple`
3. `install/install-worker.pkg` 배포
4. UI 안내 갱신: .command 대신 .pkg 다운로드 버튼 (큰 파란색)

### 진행 상황 요약 (Phase 별)

**완료**
- ✅ Phase A: 폴더 이동 + nginx 컨테이너 + 기존 데이터 배포
- ✅ Phase B-0: 교보 외부 링크 카드
- ✅ Phase B-1: 9000 FastAPI + docker-compose
- ✅ Phase B-2: Tampermonkey Userscript + 도서함 동기화 (40/280권 매칭)
- ✅ Phase B-2.1: install.html 가이드 페이지 (Gatekeeper 우회 가이드 #gatekeeper 섹션 추가)
- ✅ Phase C-1: 톱니바퀴 + 설정 모달 + `/api/settings`
- ✅ Phase C-2: book-capture 패키지 + 기존 캡처 이식
- ✅ Phase C-3 Part 1: AI 요약 (Claude Sonnet 4.5)
- ✅ Phase C-3 Part 2: merge + build_html 본격
- ✅ Phase C-3 Part 3: 백엔드 큐 + worker polling
- ✅ Phase C-4: 카드 모달 + 진행률 박스 + 중단 버튼
- ✅ 외부 노출: redcodeme.synology.me + 9443 Reverse Proxy
- ✅ UX 모듈: 커스텀 confirm + 카드 오버레이 + worker_clients 추적 + 톤 분기
- ✅ 매크로 무한 루프 사고 수습 (plist PATH 수정, install 스크립트 현대화)

**진행 중 (사용자 액션 대기)**
- ⏳ Developer ID Application/Installer 인증서 발급 (사용자)
- ⏳ App-specific password 생성 (사용자)
- → 받으면 .pkg 사인 + 공증 + 배포 (claude)

**대기 중 (#47 등)**
- ⏳ 웹뷰어(wviewer) Playwright 캡처 모드 — 매크로 자체 제거, 화면 점유 X
- ⏳ brew tap 저장소 (ckidsm/homebrew-kyobo) — Developer ID 발급 후 옵션
- ⏳ 280권 재동기화 (현재 40권만 SQLite. Userscript v0.5 셀렉터 추가 보정)
- ⏳ 동일 slug 중복 pending job 차단 (백엔드)

---

### 2026-06-04: 좀비 job 복구 + heartbeat reaper (재발 방지)

**사고**
- job #51 (HTTP_완벽_가이드, mode=auto) 가 `summarize` 단계 "시작..." 40% 에서 ~24시간 박제.
- 원인: capture+OCR(30p) 정상 완료 직후 **워커가 죽음**(Mac 슬립/네트워크 단절 추정). DB 는 `running` 인데 실제 처리 주체 없음. 새 워커는 `pending` 만 claim 하므로 영원히 안 잡힘 = 좀비.

**복구 (수동)**
- OCR 30개 그대로 살아있어 재캡처 불필요. `summarize`(30p, $0.507) → `merge` → `build` 수동 실행.
- worker 산출물(`book-capture/books/HTTP_완벽_가이드`)을 정적 `books/` 로 승격(index.html + pages_data.json + thumbs/). `book-capture/` 는 `.dockerignore` 제외라 deploy 에 안 실려 수동 복사 필요.
- `./deploy.sh --static` → 8080·9000 200, `/api/books/analyzed` 에 30p 등록. job #51 → `done` PATCH.

**재발 방지 (코드)**
- `kyobo-bridge/app/db.py`
  - jobs 에 `heartbeat` 컬럼 멱등 추가(ALTER). `claim_next_job`·`update_job` 이 매 보고마다 `heartbeat=now` 갱신.
  - `reap_stale_jobs(stale_seconds=600)` 신규 — heartbeat 끊긴 running/cancelling → `failed` + 안내 error. (컨테이너 내부 라이브 테스트로 2h-old running → failed 확인)
- `kyobo-bridge/app/main.py` — `POST /api/jobs/next/claim`(워커 2s 폴링 = 주 트리거) + `GET /api/jobs`(UI 복원) 에서 `reap_stale_jobs()` 호출. 별도 백그라운드 태스크 불필요.
- `book-capture/bookcapture/worker.py` — `_CURRENT_JID` 추적 + SIGTERM 핸들러·KeyboardInterrupt 에서 `_fail_current_job()` (in-flight job 이 아직 running 이면 즉시 failed). launchctl 정지 시 graceful 정리. 강제 종료/슬립은 백엔드 reaper 가 커버.
- 임계 600s 근거: 정상 작업은 progress 보고가 수 초 간격(요약 1p 재시도 누적 최대 ~180s) → false positive 없음. 어제 좀비는 ~24h 라 확실히 걸림.

**캡처 오염(콘솔 화면 혼입) 방지 — page17 사고**
- 증상: HTTP 완벽 가이드 page_017 이 책이 아니라 **내 Claude Code 터미널 스크린샷**(rsync/deploy.sh/grep 검증 명령)이 찍힘 → AI 가 콘솔을 책 내용으로 요약. 원인: 화면영역 캡처 도중 모니터링 터미널이 그 순간 위로 올라옴.
- 전수 조사: 육안+필터로 **013·017·018 세 장**이 콘솔(같은 모니터링 TUI) 임을 확인. 나머지 27장은 정상. (육안으론 017만 봤는데 필터가 013·018 추가 검출 → 필터가 더 신뢰성 높음)
- 처리: 세 장 batch/PNG/OCR/thumbs 제거 → merge/build/deploy. 27페이지로 정리.
- 방지: `book-capture/bookcapture/summarize.py` 에 `is_contaminated_ocr()` 추가. **책엔 절대 없고 이 환경에서만 나오는 지문**만 사용 — `/Users/deoksooyun`, `OneDrive`, `KyoboLibrary`, `deploy.sh`, `192.168.10.205`(풀 IP), `kyobo-bridge`, `page_NNN.png`/`batch_NNN.json` 정규식 등. 일반 셸 단어(curl/grep)는 HTTP 책 예제 오탐 우려로 **제외**. `summarize_pages()` 가 오염 페이지를 요약 전에 skip + 로그 + 반환값에 `skipped` 포함.
- 검증: 실제 책 OCR 27장 오탐 0, 콘솔 샘플 4종 모두 검출. (근본 해결은 로드맵 #47 wviewer 헤드리스 캡처 — 화면 점유 자체가 없음)
- 후속: 필터가 육안으로 놓친 **013·018 추가 검출** → 셋 다 제거, 27페이지로 재배포. (HTTP 완벽 가이드는 30장 부분 테스트본이라 전권 재캡처는 Mac 한가할 때 별도 진행 예정)

**브라우저 캐시로 옛 페이지 보이는 문제 → nginx no-cache**
- 증상: 13·17·18 제거·재배포 후에도 사용자 화면엔 콘솔 페이지가 남아 보임. 원인은 서버가 아니라 **브라우저 캐시**(서버 파일은 mtime·ETag·cache-bust fetch 로 깨끗함 확인).
- 조치: `nginx-default.conf` 신규 — `*.html|*.json` 에 `Cache-Control: no-cache, must-revalidate` (이미지 PNG 는 캐시 유지). `docker-compose.yml` library-web 에 `./nginx-default.conf:/etc/nginx/conf.d/default.conf:ro` 마운트, `deploy.sh` step[3] 에 conf scp 한 줄 추가.
- 적용: scp → `nginx -t`(throwaway 컨테이너) 통과 → `docker-compose up -d library-web` 재기동. 검증: 책 HTML `Cache-Control: no-cache` / PNG 기본캐시 / 사이트 200. 이후 재분석 시 브라우저가 ETag 로 자동 재검증 → 강력 새로고침 불필요.

**웹 분석 시작 시 클라이언트 접속 정보 로깅 (어느 OS에서 걸었나 추적)**
- `kyobo-bridge/app/db.py` — jobs 에 `client_info` 컬럼(JSON) 멱등 추가. `create_job(client_info=...)` 저장.
- `kyobo-bridge/app/main.py` — `_parse_ua()`(UA→OS/브라우저), `_best_effort_mac()`(LAN ARP 시도), `_client_info(request)` 추가. `POST /api/jobs` 가 `request: Request` 받아 접속 정보 수집·로그·job 저장.
- 수집 항목: os/browser(UA 파싱·확실), ip(XFF 우선), peer_ip, lang, user_agent / mac(best-effort).
- **제약**: 백엔드가 Docker bridge 라 LAN 직접(:9000) 접속은 peer_ip 가 **게이트웨이 172.x** 로 보임 → 실제 IP 는 외부 reverse proxy(9443, XFF 추가) 경유 때만 정확. **MAC 은 HTTP 로 수집 불가**(L2 정보·브라우저 샌드박스). OS/브라우저는 항상 정확.
- 보강 관점: 실제 "매크로 도는 머신" 은 worker_clients(hostname/platform/IP)가 더 정확 — 웹 client_info 는 "누가 큐에 넣었나" 용도. 검증: Windows UA 테스트 → `os=Windows 10/11 browser=Chrome` 로그·저장 확인.

### 2026-06-04: #67 완성 — 백엔드 업로드 처리(멀티 OS) + OS-aware UI

**배경**: Windows 에서 분석하려는데 (1) 모달이 Mac 전용 "로컬 매크로" 를 기본·추천으로 띄움, (2) 업로드 모드가 NAS 에 저장만 하고 원격 워커는 자기 로컬 디스크를 봐서 처리 불가(구조적 공백).

**Phase 1 — OS-aware UI** (`index.html`)
- `navigator.userAgent` 로 isMac 판별. 비-Mac 이면 🖥 로컬 매크로 **비활성(⛔ macOS 전용)**, 📤 캡처 업로드를 **checked + Recommended** 로. 캡처방식 제목에 `(macOS/non-Mac 감지)` 표시.
- `deploy.sh --static` 배포.

**Phase 2 — 백엔드가 upload-process 직접 처리**
- 처리 모듈 vendoring: `book-capture/bookcapture/{ocr,summarize,merge,build_html,settings}.py` → `kyobo-bridge/app/processing/`. (오염필터 든 summarize 도 함께 → 백엔드 처리도 콘솔페이지 자동 제외)
- `kyobo-bridge/Dockerfile` — `tesseract-ocr` + `tesseract-ocr-kor/eng` 설치. `requirements.txt` — Pillow, pytesseract. 이미지 67MB→111MB.
- `app/upload_processor.py` (신규) — 데몬 스레드가 `claim_next_upload_job()` 폴링 → 업로드 폴더(`LIBRARY_BOOKS_WRITE_DIR/<slug>`)에서 OCR→요약→merge→build, 진행률·상태 보고. 산출물이 곧 서빙 폴더라 별도 배포 불필요. cfg 는 db 설정(ai/ocr)에서 직접 구성.
- `app/db.py` — `claim_next_upload_job()` 추가, `claim_next_job()` 은 `mode != 'upload-process'` 로 원격 워커가 업로드 잡 못 잡게 분리.
- `app/main.py` — lifespan 에서 `start_processor()`/`stop_processor()`.
- **검증(end-to-end)**: 실제 책 PNG 3장 업로드 → job #57 → OCR→요약(25%)→done(100%) ~55초. index.html·썸네일 200, 요약 내용 삽입, analyzed 등록 확인 후 정리. tesseract 5.5.0(kor/eng) 컨테이너 동작 확인.
- **효과**: OS 무관(Windows/Linux/모바일) 브라우저에서 PNG 업로드만으로 분석 완료. 워커·tesseract 로컬 설치 불필요.
- 메모: 컨테이너가 만든 파일은 SSH 유저로 못 지움 → 정리는 `docker exec ... rm` 로.

### 2026-06-04: Windows 로컬 캡처 지원 (앱 자동설치·실행)

**요구**: Windows 도 앱 경로 고정(`C:\Program Files (x86)\Kyobobook\eLibrary\KyoboBook.Ebook.ELibrary.exe`)이라 로컬 캡처 가능. 없으면 설치파일(`https://contents.kyobobook.co.kr/digital/download/elibrary/b2c/KyoboeBook_Setup.exe`) 받아 설치하고, 분석 시 앱 실행.

**추가/수정**
- `book-capture/bookcapture/win_app.py` (신규) — `is_installed()`/`download_installer()`/`ensure_installed()`(미설치 시 설치파일 다운 + `/S` 무인설치 시도 + exe 출현 폴링) + `KyoboWinCapture` 클래스(macOS `KyoboAppScreenshot` 와 동일 인터페이스). 캡처는 Pillow `ImageGrab` + `ctypes` SendInput 페이지 넘김(추가 의존성 0). 직전 해시 동일 시 책 끝으로 보고 중단.
- `book-capture/bookcapture/cli.py` — `cmd_capture_auto` 를 `platform.system()` 으로 분기: Windows → `KyoboWinCapture`(설치확인→실행→deep link→캡처, region/next_key 설정 반영), macOS → 기존 `KyoboAppScreenshot`.
- `index.html` — 캡처방식 UI 를 macOS **및 Windows** 둘 다 로컬 매크로 활성(`canMacro = isMac || isWin`). Windows 라벨 "앱 자동 설치·실행 후 캡처". 그 외 OS 만 업로드 전용.

**남은 검증·요구 (실 Windows 필요)**
- KyoboWinCapture 는 Mac 에서 작성·미검증 — 실제 Windows 에서 (1) 설치파일 `/S` 무인설치 동작 여부, (2) deep link `kyoboebook://` 등록 여부, (3) 캡처 region·페이지넘김 키 튜닝 확인 필요.
- Windows 로컬 캡처가 돌려면 **Windows 에 bookcapture 워커 실행** 필요 (Python + Pillow + 이 패키지). mode=auto 전체 파이프라인은 OCR 에 **Windows tesseract** 도 필요 → 또는 캡처만 하고 업로드→백엔드 처리(#67) 하이브리드가 더 단순.

### 2026-06-04: Windows 하이브리드 (B) — 원격 캡처 → 업로드 → 백엔드 처리

**배경**: Windows PC 가 **원격(외부망)**. full-local 은 (1) 산출물이 원격 PC 에 갇혀 NAS 발행 불가, (2) AI 키 LAN 전용, (3) claim LAN 전용 문제. → 캡처만 Windows, 나머지는 NAS 백엔드(#67)가 처리하는 하이브리드 채택.

**연결성 확인**: `_is_lan` 은 `request.client.host`(peer)만 검사. 9443 리버스 프록시 → localhost → docker 라 peer=게이트웨이(172.x, private) → 원격이라도 claim/patch/secrets 통과.

**구현**
- `cli.py` `cmd_upload` (신규) — 책 폴더 PNG 를 `/api/books/<slug>/upload` 로 multipart 업로드(urllib, stdlib만). 백엔드가 upload-process job 생성·처리.
- `worker.py` capture-only = `[capture-auto, upload]` — 캡처 후 업로드. (워커·자식 모두 `KYOBO_BRIDGE_URL` env 로 9443 사용)
- `index.html` — Windows 로컬 매크로 radio value=`capture-only`(Mac 은 `auto` 유지). 라벨 "앱 자동 실행·캡처 → 서버 처리".
- `scripts/install-worker-windows.ps1` — `-BridgeUrl` 파라미터(기본 LAN, env 우선) + `KYOBO_BRIDGE_URL` User env 설정 + tesseract kor/eng traineddata 자동 다운로드 보강.
- 검증: `bookcapture upload` 로 실 PNG 2장 업로드 → job #58 → 백엔드 done. (Windows 캡처 KyoboWinCapture 는 실기 미검증)

**원격 Windows 설치 (사용자)**
```powershell
$env:KYOBO_BRIDGE_URL="https://redcodeme.synology.me:9443"
cd <OneDrive>\Claude\NAS\KyoboLibrary\book-capture\scripts
powershell -ExecutionPolicy Bypass -File .\install-worker-windows.ps1 -BridgeUrl "https://redcodeme.synology.me:9443"
```
이후 웹(외부 URL)에서 책 → 🖥 로컬 매크로(capture-only) → 분석 시작 → Windows 워커가 앱 실행·캡처·업로드 → 백엔드 처리 → 서빙.

**무입력(더블클릭) 설치** — 명령어 타이핑 없이:
- `install/install-worker.cmd` (신규) — 더블클릭하면 `install-worker.ps1` 을 ExecutionPolicy Bypass 로 실행 (Mac `.command` 대응).
- `install/install-worker.ps1` — 백엔드 주소 **자동 감지**(LAN `:9000/health` 닿으면 LAN, 아니면 외부 `:9443`) 후 `KYOBO_BRIDGE_URL` 설정 → 메인 설치 스크립트 호출. winget Tesseract 설치 시 UAC [예] 한 번만 필요.
- 사용자: OneDrive 의 `KyoboLibrary\install\install-worker.cmd` 더블클릭 → 끝.
- 메모(MSI/서명): 진짜 MSI/.exe 인스톨러는 Windows 빌드도구(Inno/WiX) + **Windows 코드서명 인증서**(Apple Developer ID 와 별개) 필요 → Mac 에서 못 만듦. 폴리시드 .exe 원하면 Inno Setup 스크립트 스캐폴딩은 가능(빌드·서명은 Windows 에서).

### 2026-06-05: 앱/책 열림 실제 검증 (안내가 아니라 확인)
- 요구: 분석 시작 시 교보 앱 실행+해당 책 열림을 실제로 확인(Windows는 창 제목으로 가능).
- `win_app.get_app_window_title()` — ctypes EnumWindows 로 교보 창 제목 읽음(예 "교보eBook - HTTP 완벽 가이드"). win32 의존성 없음.
- `cli.cmd_capture_auto` (Win): 캡처 전 fail-fast — 앱 미실행/창 없음/책 제목 불일치(정규화 substring)면 명확한 메시지로 중단(잘못된 화면 캡처 방지).
- `worker.ping` 에 동적 `app_title` 첨부. `main.py` WorkerPing.app_title + `_last_app_title` + status 반환.
- `index.html showCapturePrep` — 워커 status 의 app_title 로 라이브 검증 배너: ✅감지 / ⚠️다른 책 / ⚠️앱 미감지 + [🔄 다시 확인] 루프.

### 2026-06-05: 워커가 자꾸 죽는 버그 — 자동업데이트 os._exit(0) 가 범인
- 증상: 워커가 잠깐 떴다 죽고 "워커 다시 시작" 패널이 계속 뜸(마지막 ping 36분 전).
- 원인: 자동업데이트가 `os._exit(0)` 로 재시작 시도 → **Windows 작업 스케줄러는 정상종료(코드 0)면 재시작 안 함**(실패=비0 일 때만) → 워커가 업데이트마다 죽고 안 살아남. (개발 중 버전 잦은 배포로 매번 발생)
- 수정 `worker.py _maybe_self_update`: **os._exit 제거** → zip 만 풀고 워커는 계속 실행. capture-auto/ocr/upload 는 매 subprocess 라 새 코드 즉시 사용. worker.py 자체 변경만 다음 재시작 때 반영.
- 보강 `install-worker-windows.ps1`: AtLogon 트리거에 **5분 반복**(RepetitionInterval) + `MultipleInstances IgnoreNew` → 워커가 어떤 이유로 죽어도 5분 내 자동 부활(반복 트리거는 전체 install 로 작업 재등록 시 적용).

### 2026-06-05: 캡처 준비 팝업(사용자 싱크) — 준비 안내 → 준비 완료 → 앱 전환 카운트다운
- 문제: 분석 시작 누르면 준비도 안 됐는데 바로 캡처 → 사용자와 싱크 안 맞음.
- `index.html` `showCapturePrep()` — 분석 시작(캡처 모드) 시 **준비 체크리스트 팝업**(OS별: 앱 실행→책 열기→시작페이지 이동→최대화→다른 창 치우기). [준비 완료] 눌러야 진행.
- Windows: 준비 완료 후 **5초 카운트다운**("교보 앱으로 전환 Alt+Tab") → 그동안 사용자가 앱으로 전환 → job 등록 → 워커가 포커스된 앱 캡처. (`_countdown` confirm 모달 재사용)
- bb-analyze onclick async 화: upload 는 기존, 캡처는 showCapturePrep 통과해야 showAnalyzeCmd. 프론트만 — 새로고침 즉시 적용.

### 2026-06-05: Windows 앱 크롬 크롭(OCR 깨끗) + 시작페이지=도서 페이지번호 명확화
- 교보 Windows 앱: 최대화 시 상단(제목+툴바)·하단(음성/페이지 컨트롤바, 우하단 `21/757p`)이 책과 같이 찍힘 → OCR 오염.
- `win_app._WIN_CROP` (top80/bottom70/left0/right0) — region 미지정 시 전체화면에서 크롬 크롭 후 캡처. 캡처 영역 로그 출력. region(절대좌표) 설정 시 그쪽 우선. (해상도/DPI 다르면 값 조정 필요 — 책 본문은 가운데라 여유 크롭 OK)
- 시작 페이지 라벨 = "앱에 표시된 도서 페이지 번호". 사용자가 앱 우하단 번호(예 21) 읽어 입력 → 파일 page_021+ 로 번호 매겨 도서 페이지와 정렬.
- (향후) 우하단 페이지번호 영역만 따로 OCR 해 자동 라벨링 가능.

### 2026-06-05: 시작 페이지 지정 (처음부터/이어서) — 자동 이동 불가 대응
- 한계: 교보 Windows 앱은 특정 페이지로 보내는 API·딥링크 없음 → 워커가 앱을 자동 이동 불가. 캡처는 현재 화면만 찍음.
- 대응(수동 위치 + 웹에서 번호 지정): `index.html` 에 **시작 페이지** number input(`cap-start-page`, 기본 1). showAnalyzeCmd 가 N>1 이면 `payload.pages=N`.
- `worker.py` capture-only: `job.pages` 가 숫자면 `--start-page N` 전달.
- `win_app`: `start_page==1` → 처음부터(잔여 삭제), `>1` → 그 번호부터 이어서(기존 유지, 앱이 그 페이지에 있어야 함). 로그로 명시.
- 워크플로: 앱에서 원하는 페이지로 직접 이동 → 웹 시작 페이지에 그 번호 → 분석 시작.

### 2026-06-05: 캡처 시작 페이지 검증 + 잔여 페이지 정리
- 로그 확인: capture-auto 는 **항상 page_001 부터**(처음부터). continue_from_last 미사용.
- 버그: 처음부터 찍지만 **기존 page 이미지를 안 지워** 이전 실행 잔여가 섞임(예: 9장 캡처했는데 백엔드가 더 많이 OCR). 
- 수정 `win_app.take_multiple_screenshots`: 시작 전 체크 — continue 면 "▶ 이어서 캡처: page N 부터(기존 유지)", 아니면 "▶ 처음부터 캡처: page 001 부터(기존 N장 삭제)" 로그 + 잔여 page/thumbs 삭제.
- 수정 `main.py upload`: 새 업로드 전 book_dir 의 page 이미지·thumbs/·summary/ 제거(잔여 OCR 방지). 백엔드 즉시 적용(워커 무관).
- #73 에 보인 `UnicodeDecodeError 0xc0` 는 옛 워커(인코딩 수정 전) — update-worker 로 해소.

### 2026-06-05: 워커 버전 라이브 옵저버
- `worker.py _ping_meta` 에 `version`(=_local_version) 추가 → ping 마다 워커 버전 전송.
- `main.py` — `WorkerPing.version`, `_last_worker_version` 전역, `_read_server_version()`(컨테이너 `/mnt/library/install/worker-version.txt` ro 마운트에서 읽음). `/api/worker/status` 에 `worker_version`·`server_version`·`up_to_date` 추가.
- `index.html` refreshWorkerBox — worker-alive 박스에 `v{ver} ✓최신` / `v{old} → v{new} 업데이트 중…(최대 5분)` 배지. 분석 중 자동 표시.
- 검증: status `server_version=ceace83ca0e7` 정상, 옛 워커라 `worker_version=None`. update-worker 1회 후 보고 시작.

### 2026-06-05: 워커 자동 업데이트 (매번 수동 irm 불필요)
- `worker.py` — `_maybe_self_update()`: idle 일 때 5분마다 `install/worker-version.txt` 조회, 로컬 `bookcapture/_version.txt` 와 다르면 `bookcapture.zip` 받아 `extractall` 후 `os._exit(0)` → Task Scheduler/launchd KeepAlive 가 새 코드로 재시작.
- `scripts/build-zip.sh` (신규) — 버전 = `.py`+requirements md5(12자) → `bookcapture/_version.txt`(zip 내) + `install/worker-version.txt`(서버) 동시 생성 후 zip. 코드 바뀌면 버전 자동 변경. 앞으로 워커 배포는 이 스크립트로.
- 효과: `irm update-worker` 는 **이 자동업데이트 워커를 까는 마지막 1회만**. 이후 서버에 새 버전 올리면 워커가 5분 내 자동 반영.
- (옵션 후보) 워커가 ping 에 `_version` 실어 보내면 웹 옵저버가 "워커 vXXX · 최신/업데이트중" 라이브 표시 가능.

### 2026-06-05: MS Store 버그 수정 + 분석 절차 안내(옵저버)
- 버그: Windows capture-auto 가 `os.startfile("kyoboebook://book/<id>")` deep link 시도 → Windows 에 이 스킴 미등록이라 **"프로토콜 열 앱을 MS Store 에서 찾기"** 창이 뜨고 책도 안 열림. (캡처가 된 건 사용자가 이미 책을 펼쳐둬서)
- 수정: `win_app.open_book_by_id()` 의 deep link 제거 → Windows 는 책 자동열기 미지원, 안내 메시지만. (앱 exe 실행은 유지)
- 절차 안내(`index.html` capture-guide): 로컬 매크로 선택 시 OS별 단계 표시. Windows = ①앱 직접 실행 ②책 펼치고 1p·전체화면 ③화면 그대로 ④[분석 시작] ⑤자동 페이지 넘김 ⑥서버 처리. "캡처 중 화면 건드리지 말 것 / 일찍 멈추면 →키 포커스" 경고.
- ⚠️ 캡처가 17p 에서 중단(직전 동일 해시) — Windows 에서 페이지 넘김(→ keybd_event)이 책 뷰어 포커스 없으면 안 먹음. 전권 캡처하려면 책 뷰어 포커스 유지 필요(절차 안내에 반영). 향후: 워커가 is_app_running/포커스 상태를 ping 에 실어 웹 옵저버가 라이브 표시.
- 적용: zip 재생성(딥링크 제거 win_app) + 프론트 배포. 워커는 update-worker 재실행으로 갱신 필요.

### 2026-06-05: 🎉 Windows 하이브리드 전 구간 end-to-end 성공
- 원격 Windows(OneDrive 없음, host=yundeoksoo)에서 `update-worker.ps1` 로 워커 갱신·재시작 후:
  - #71 capture-only **done** — 교보 eLibrary 앱 자동 실행 + ImageGrab 32페이지 캡처 성공(인코딩 크래시 없음)
  - 9443 으로 업로드 → #72 upload-process: 백엔드 OCR(32p)→요약($0.45)→merge→build **done**
  - analyzed: HTTP_완벽_가이드 **32페이지**, index.html 200. 캡처 썸네일 검증 = 실제 책 본문(콘솔 아님).
- 즉 **무설치 한 줄(irm) → 워커 설치 → 앱 캡처 → 서버 처리 → 라이브러리 게시** 전 구간 작동.
- `install/update-worker.ps1` (신규) — 관리자 권한 없이 워커 코드만 갱신+재시작(Stop→zip 다운로드→Expand→Start ScheduledTask). 전체 재설치보다 가볍고 빠름.
- 알려진 소소한 점(후순위): 백엔드 upload_processor 가 요약 진행을 페이지별로 job.progress 에 안 올려서 UI 진행바가 요약 중 25% 로 멈춘 듯 보임(실제론 백엔드 stdout 에 N/32 진행). summarize_pages 에 progress 콜백 추가하면 개선.

**Windows 워커 실전 연결 성공 + 잔여 버그 수정 (2026-06-04~05)**
- ✅ Windows 워커 연결됨(host=yundeoksoo, 9443 경유 ping/claim 정상). 설치→연결→claim 전 구간 검증.
- 권한 버그: 비관리자라 (1)kor.traineddata Program Files 쓰기 실패, (2)Register-ScheduledTask Access denied → install-worker-windows.ps1 에 **self-elevation**(UAC RunAs 재실행) 추가.
- zip 캐시 버그: Web Station 이 zip 캐시 → 부트스트랩 zip URL 에 `?t=ticks` 캐시버스트.
- 인코딩 크래시: capture-auto 가 cp949 콘솔에서 `—`(em-dash) 출력 시 `UnicodeEncodeError` 로 즉사 → `__main__.py` 에서 stdout/stderr `reconfigure(encoding=utf-8)`, `worker.py` Popen `encoding=utf-8`, 설치 시 `PYTHONUTF8=1` env.
- 재설치 잠금: 부트스트랩이 다운로드 전 `Stop-ScheduledTask` 로 워커 정지 후 덮어쓰기.

**OneDrive 없는 PC (A~Z 일반 사용자) 대응 — 워커 zip 다운로드 설치**
- `install/bookcapture.zip` (신규, ~64KB) — bookcapture 패키지 + requirements + scripts. `deploy.sh` 가 서빙(LAN 8080 / 외부 /kyobo).
- 부트스트랩이 OneDrive 에서 book-capture 못 찾으면 → 서버 zip 다운로드 → `%LOCALAPPDATA%\KyoboLibrary\book-capture` 풀기 → 거기서 설치. OneDrive·repo 불필요, 어느 Windows 든 `irm|iex` 한 줄로 끝.
- 의존성 멈춤 버그: 설치가 `pip install pyautogui` 에서 수 분 멈춤(pytweening 등 sdist 빌드). **win_app 은 ctypes+PIL 만 써서 pyautogui 불필요** → 제거. `--quiet` 도 제거(진행 표시), `--no-input` 추가. zip 재생성.

**Windows 설치 자동화 보강 (Python 자동설치 + 자체완결 .cmd + irm|iex 부트스트랩)**
- `install-worker-windows.ps1` — Python 미설치 시 그냥 죽던 것을 **자동 설치**로: `winget install Python.Python.3.12 --scope user` → 실패/부재 시 **python.org 무인설치**(`/quiet PrependPath=1`, `Start-Process -Wait` 로 완료 대기) → `Refresh-Path`(Machine+User PATH 재로드) → 재확인. MS Store 가짜 python stub(`WindowsApps`) 제외. `Die` 를 `throw` 로(iex 창 안 닫힘).
- `install/install-worker.ps1` (부트스트랩) — **ASCII + BOM 제거**(irm|iex 안전) + `Set-ExecutionPolicy -Scope Process Bypass` + 백엔드 자동감지 + `$env:OneDrive` 로 book-capture 탐색. 외부 경로 `/kyobo/install/install-worker.ps1`.
- `install/install-worker.cmd` — **자체완결**: 옆 .ps1(`%~dp0`) 찾던 것(다운로드 단독이면 깨짐) → `powershell -Command "irm <ext>/install-worker.ps1 | iex"` 로 변경. .cmd 하나만 받아도 동작.
- 권장 실행: PowerShell 에 `irm https://redcodeme.synology.me/kyobo/install/install-worker.ps1 | iex` (다운로드·인증서 불필요). 다중 사용자 무경고 .exe 는 Windows 코드서명 인증서 필요(별도).

**Windows .cmd/.ps1 인코딩·줄바꿈 버그** — Mac 에서 만든 `install-worker.cmd` 가 **LF 줄바꿈**이라 cmd.exe 가 파싱 실패('r'/'tionPolicy' 등 조각을 명령으로 실행, 한글 주석 mojibake). 수정: `.cmd` 를 **CRLF + ASCII**(한글 메시지는 PS 가 담당)로 printf 재작성. `.ps1` 2개는 **UTF-8 BOM** 추가(PS 5.1 이 CP949 로 오독해 한글 경로 후보 `OneDrive - 개인` 깨지는 것 방지). 교훈: Windows 배치는 CRLF 필수, PS 스크립트는 BOM 권장.

**워커 안내 패널 OS 인식 버그 수정** — `buildWorkerInstallHint` 가 `known.platform`(이전에 본 워커=Mac)을 우선해서 Windows 에서도 .pkg 패널을 띄우던 문제. `usePlat` 을 **현재 브라우저 OS(`detectOS()`)** 기준으로 변경. Windows 패널을 `irm|iex` 한 줄 → **`install-worker.cmd` 더블클릭 다운로드(무입력)** 우선으로 교체(PowerShell 은 details 폴백). (docker NAT 로 Windows 브라우저·Mac 워커가 같은 게이트웨이 IP 라 `previously_seen`/`known` 이 엉뚱하게 매칭되는 부작용도 이 변경으로 표시상 무력화.)

**Mac 워커 정지(다른 OS 로 전환)** — `launchctl bootout`+`disable`+plist 를 LaunchAgents 밖(`~/kyobo-worker-disabled/`)으로 이동. 로그인/재부팅에도 자동로드 안 됨. 재가동하려면 plist 복귀 후 `launchctl bootstrap gui/$UID ...` 또는 `install/restart-worker.command`.

**Mac 절전 방지 (caffeinate, 슬립으로 인한 좀비 근본 차단)**
- `worker.py` — `_start_caffeinate()`/`_stop_caffeinate()` 추가. `run_worker` 가 **job 도는 동안만** `caffeinate -i -m -s -w <worker_pid>` 를 띄우고 `finally` 로 해제. 평소(유휴)엔 안 켜므로 전력 영향 없음.
- `-w <pid>` 로 워커가 죽으면 caffeinate 도 따라 종료(orphan 방지). macOS/caffeinate 없으면 조용히 skip (`shutil.which`).
- 검증: 라이브로 `pmset -g assertions` 에 `PreventUserIdleSystemSleep`+`PreventSystemSleep` 활성 확인, stop 후 해제 확인. 워커 재시작 후 idle 상태에선 caffeinate 자식 없음(정상).

**배포·검증**
- `./deploy.sh --backend` (buildx amd64 → load → compose up) 8080·9000 200.
- reaper 라이브 테스트 OK, done job 은 미회수 확인. 워커 새 코드로 재시작(launchctl kickstart -k, PID 83011, ping 정상).

### 2026-07-15: '밑바닥부터 만들면서 배우는 LLM' 재검토 — 워크북(별책) 분리 + 최신 표준화

**발견(핵심)**: 발행본 400p 는 실제로 **두 권**이었다. 캡처가 본책이 끝난 뒤 **별책 《…LLM 워크북》**까지 이어 찍음. p1–296=본책(7장+부록 A~E, p296=부록E 그림 E-5로 끝), **p297=워크북 표지**, p297–399=워크북, p400="마지막 페이지" 모달. 사용자가 말한 "오염"의 실체 = OCR 오염이 아니라 **워크북이 통째로 섞임**. (전수 스캔: 옛 요약은 LLM 책이라 영어·코드 많아 대체로 정확, 오염은 p400 모달뿐)

**결정(사용자)**: 워크북 **별책으로 분리**.

**본책(1–296) 최신 표준화**
- 워크북 페이지/ocr_text/batch 분리, `chapters.json`(7장 + 부록 A 파이토치 217–254 · B 참고문헌 255–258 · C 연습문제해답 259–271 · D 훈련부가 272–282 · E LoRA 283–296) 작성.
- merge→build→overview(Haiku 12장)→build(개요 포함 재생성)→finalize→발행. 📋 책 개요·CH1~CH12 트리·296 페이지 카드 라이브 검증. analyzed 296p.
- NAS 고아 이미지(297–400 page/thumb/ocr) sudo heredoc+glob 로 정리(컨테이너 root 소유라 SSH 유저 rm 불가 → `echo $P|sudo -S`).

**워크북(297–399 → 1–103) 새 책 발행**
- 페이지·ocr_text 재번호(297→001), 썸네일 재생성, batch 재번호. `chapters.json`(본책 장 미러 11섹션: 1~7장 + 부록 A·D·E + 해답/용어/참고문헌).
- merge→overview(Haiku 11장)→build→finalize→발행(이미지 tar + 요약 + ocr). 103p, CH1~CH11.
- books 테이블에 수동 추가(`/api/library/sync`, kyobo_id `E000012061590-WB`, 표지=자체 page_001) → 메인에 카드 노출(85권). slugify(title)=폴더 슬러그 일치.

**스크립트 수정**
- `publish_images.sh` — sudo 추출 전 `mkdir -p $DST` 추가(**새 책 발행 시 폴더 없어 tar -C 조용히 실패하던 버그** 수정). publish 순서상 이미지가 요약보다 먼저 와도 폴더 자동 생성.

**미완(Phase 3)**: 두 LLM 책의 **팝업 OCR 패널은 아직 옛 mojibake OCR** — Gemini 무료 쿼터 소진(429)이라 전사 보류. 쿼터 리셋 시 `ocr --vision`(resume)으로 교체 예정. 요약·챕터·개요는 이미 완성(전사 무관).

---

### 2026-06-09: Windows capture-browser end-to-end 검증 (→ Mac 인계 메모)

**환경**: Windows 원격(host=yundeoksoo, 외부망 — LAN 192.168.10.205 미접근, SSH 22 미개방). 백엔드 외부 노출 `:9443`만 사용.

**한 일**
- `irm .../update-worker.ps1 | iex` 로 워커 `cfc3ceb8533b → 851be57ce586` 갱신, `up_to_date=true` 확인.
- 책 "밑바닥부터 만들면서 배우는 LLM" (`kyobo_id=E000012061590`, 세바스찬 라시카) 분석: 사용자가 Chrome wviewer에 책 펼치고 웹 UI에서 분석 시작.
  - job #96 (`capture-browser`) → done, **400p 캡처+업로드 OK** (dxcam/ArrowRight 동작)
  - job #97 (`upload-process`) → OCR stage 1/4 끝(약 15분), summarize stage 2/4 진행 시작. 끝까지 가면 ~$4.4 예상.
- OpenCV 책("C#과 파이썬을 활용한 OpenCV 4 프로그래밍") Chrome에 펼쳐둠 — LLM 끝나고 진행 예정.

**캡처 PNG 검증 (위치: `%LOCALAPPDATA%\KyoboLibrary\book-capture\books\밑바닥부터_만들면서_배우는_LLM\`, 400장 avg 295KB)**
- ✓ page_001(표지), 050/200(코드+한글 본문): 정상
- △ page_036/129/259(빈+푸터 챕터명), 184/398/399(짧은 한 줄): 챕터 시작·끝 페이지로 정상 (푸터 챕터명 OCR 가능)
- 🚨 **page_400 = 빈 회색 화면(책 끝 모달도 사라진 상태)** → 명확 노이즈. 외부에서 백엔드 폴더 접근 불가라 OCR 시작 전 못 지움.
- ⚠️ **모든 400장 상단 ~100px에 Chrome UI(탭/주소창/북마크 바 "NAVER, Replit, GitHub, android, 기획, 서버, blazor, 개발, 교육, 자료, Component, cloud, 문서작성, ChatGPT, 모든 북마크")**가 박힘 — F11 전체화면 미적용. `is_contaminated_ocr` 패턴에 안 걸려 매 페이지 OCR/AI에 노이즈로 섞임.

**Mac에서 수정 후보 (우선순위)**
1. **dxcam 캡처 영역에 top crop 추가** (`book-capture/bookcapture/win_app.py` 또는 capture-browser 분기) — Chrome 상단 ~100-150px 크롭. 하단 푸터(챕터명)는 유지. `_WIN_CROP` 패턴 참고.
2. **`is_contaminated_ocr` 패턴 보강** (`bookcapture/summarize.py` + `kyobo-bridge/app/processing/summarize.py` 둘 다) — "NAVER  Replit  GitHub" 연속 북마크 시그너처, "wviewer.kyobobook.co.kr" URL 등. 책 본문엔 절대 안 나타나는 지문만. 콘솔 패턴(`/Users/deoksooyun` 등)과 같은 자리에 추가.
3. **"마지막 페이지입니다" 모달 자동 감지 → 캡처 중단 + 마지막 1장 폐기** — capture-browser 동일 해시 감지 외에 모달 시그너처(예: 특정 영역 회색 단색) 추가하면 page_400 자동 제외.
4. **(선택) capture-browser 시작 전 Chrome F11 자동 전송** — 워커가 Chrome 포커스 후 F11 SendInput. 단, 사용자가 이미 풀스크린이면 토글로 풀스크린 해제되는 부작용 — 라이브 토글 체크 필요.

**현재 진행 중 (Mac에서 결과 확인 필요)**
- `#97 upload-process` 백그라운드 진행. 끝나면 `books/밑바닥부터_만들면서_배우는_LLM/summary/index.html` 생성, `/api/books/analyzed` 등록.
- Mac에서 LAN/SSH로 직접 OCR txt(`<book>/summary/ocr_text/page_NNN.txt`) 확인 가능 — Windows에선 불가했음.
- 결과 보면 (a) Chrome UI 텍스트가 AI 요약에 얼마나 들어갔는지 (b) page_400 요약이 노이즈인지 판단.

**Windows 워커 상태**: alive, 851be57ce586, last_ping 정상. Mac에서 작업 중에도 Windows 워커는 계속 살아있어 `capture-only/capture-browser` 잡 가능. 멈추고 싶으면 `Stop-ScheduledTask -TaskName KyoboBookcaptureWorker`.

**미해결 후속**
- OpenCV 책 분석 — LLM 끝나고 동일 흐름(capture-browser, ~400p 예상)
- 위 4개 수정 후보 코드 작업
- (선택) `/api/books/<slug>/ocr/<page>` 같은 LAN-only debug endpoint — 외부망에서도 OCR 결과 확인 가능하게

### 2026-06-09 (Mac 응답): Windows 인계 메모 4개 + 마무리 2개 반영
- ✅ **#1 dxcam top crop** → `win_app._content_crop`(상단11% 크롬 + 가장자리 그림자 + 어두운 글자 bbox 트림). no_crop(브라우저) 경로에 적용. worker zip **7573b5a** 배포 → Windows 워커 자동 반영. Mac 스크립트(`scripts/mac_wviewer_capture.py`)도 동일.
- ⚠️ **#2 is_contaminated_ocr 북마크 패턴 → 안 함**. 북마크바가 **책 본문과 같은 페이지**라 패턴 매칭 시 그 페이지(본문 포함) 전체가 스킵돼 본문 손실. #1 크롭이 근본 해법이라 불필요/해로움.
- (#3 마지막페이지 모달 / #4 F11 자동 — 미적용. 크롭+동일해시중단으로 대부분 커버. page_400 같은 빈장은 크롭 후 OCR 빈텍스트로 약하게 걸러짐. 필요시 후속.)
- ✅ **(A) 분석본 자동 서빙**: `/volume1/web/kyobo/books` → `/volume1/docker/web-apps/kyobo-library/books` **심링크**. 새 책 수동복사 불필요(이전엔 docker에만 생겨 외부 404). HTTP·비디오코덱 200 확인. (CLI는 summary 비어 원래 404)
- ✅ **(B) heartbeat watchdog 수정**(대용량 책이 OCR/요약 >600s 라 reap_stale_jobs에 죽던 것): `db.touch_heartbeat` + `upload_processor` 60s keeper 스레드. 컨테이너 cp 적용·동작확인(#95,#97 생존). **이미지 영구 재빌드는 #97 끝난 뒤**(실행 중 compose recreate 방지).
- **검증**: Mac=비디오코덱(366p) capture-browser→OCR→요약 전권 성공($2.86). Windows=LLM(400p) 성공. 둘 다 dxcam/창ID + ArrowRight(확장키) + 천천히(anti-bot 회피).
- **다음**: #97(LLM) 끝나면 (a) 요약에 chrome 노이즈 정도 확인 (b) 이미지 재빌드 (c) OpenCV 책 capture-browser.

### 2026-06-09 (Mac 마무리 완료)
- ✅ **#97(LLM 400p) 완료** — summary 743KB, chrome 노이즈 **0**(AI가 북마크바 무시, 책 내용만 요약: 트랜스포머·어텐션·토큰·임베딩 정상). → #2 오염패턴 불필요 재확인.
- ✅ **비디오코덱(194장)·LLM(400장) 이미지 재크롭** — 컨테이너 내 `_content_crop`(상단11%+그림자+bbox) in-place 적용 + 썸네일 재생성 + summary HTML 이미지 URL `?v=2` 캐시버스트. 둘 다 크롬·여백 제거 확인. (Windows 캡처도 Mac 크롭 그대로 동작)
- ✅ **이미지 재빌드 완료** — `deploy.sh --backend`. heartbeat(touch_heartbeat)·ffmpeg 이미지에 baking 확인. health 200.
- **남은 것**: OpenCV 책 capture-browser(Windows, ~400p). 이젠 워커가 크롭(7573b5a) 자동 반영하니 깨끗하게 캡처됨.

### 2026-07-05: 이북 처리 파이프라인 규칙화·정규화 + "클로드 코드" 책 전권 완성

이북 캡처→발행 전 과정을 **단일 런북 + 재사용 스크립트**로 정규화. "클로드 코드로 시작하는 실전 에이전틱 코딩"(246p)을 이 표준으로 완성.

**새 기능·자산**
1. **표(表) 정리본** — 표 있는 페이지에 이미지 대신 재구성한 깔끔한 HTML 표를 카드에 삽입.
   - `scripts/add_page_extras.py` — `page_extras.json`(`{"37":"<div class=page-extra>…표…</div>"}`)을 페이지 카드에 주입. `.ptable`/`<kbd>`/다중표 CSS 포함. 그림(그림 N-N)은 표 아님 → 제외.
   - "클로드 코드" 책 **19개 표 페이지·24개 표** 작성·배포(`scripts/page_extras_클로드코드_예시.json`). 단축키표는 `<kbd>` 키캡, 명령어·경로는 `<code>`.
2. **챕터 트리 + 챕터 요약** — `scripts/add_chapter_tree.py` — `chapters.json`으로 사이드바 접기/펴기 트리 + 챕터별 "무엇/왜/어떻게/개념" 요약 카드. (`scripts/chapters_클로드코드_예시.json`, 10챕터 리치 요약)
3. **최종화 통합** — `scripts/finalize_book.py <summary_dir>` — 깨끗한 빌드 index.html에 챕터트리+표정리본을 **한 명령으로** 주입. 멱등 아니라 이미 주입 시 중단(중복 방지), `--force`로만 강제.
4. **개별 도서 발행** — `scripts/publish_book.sh <SLUG> <파일>…` — root 소유 웹파일 문제 해결: 홈 업로드→`sudo cp`→`chown root:root`→`chmod 644`→검증. 비번은 `NAS_PASS` 환경변수(하드코딩 금지).
5. **캡처·크롭 표준** — `bookcapture/page_crop.py`(콘텐츠 감지+여백 복원 크롭), `scripts/crop_book.py`(배치), `scripts/app_capture_raws.py`(Mac앱 raw), `bookcapture/capture_standard.py`(모니터 독립 해상도), `scripts/mac_capture_preflight.py`. 근거: `docs/CAPTURE_SHARPNESS.md`.
6. **단일 런북** — `docs/EBOOK_CAPTURE_STANDARD.md` §0 에 캡처→크롭→OCR→요약→빌드→최종화→발행→검증 10단계 순서표. 이 문서가 이북 처리 단일 진실원본.

**캡처 개선(6월 작업 반영)** — `win_app.py`/`linux_app.py`/`wviewer.py`/`mac_wviewer_capture.py`: dxcam 상단 크롬 크롭, 그림자/bbox 트림, 브라우저(no_crop) 경로 적용.

**NAS 배포 메모(확정)** — SSH password 폴백은 `-o PubkeyAuthentication=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1` 필수(빼면 keyboard-interactive로 timeout). scp는 Synology에서 자주 끊김 → `ssh "cat > 원격" < 로컬` 우회. zsh는 미따옴표 변수 단어분할 안 함 → 옵션 인라인 또는 bash 스크립트.

### 2026-07-05: GitHub 최초 발행 + 비밀번호 이력 스크럽 (보안)
- **원격 최초 생성**: 개인 `ckidsm` 계정에 **Private** 리포 `Ebookibrary` 생성, main 최초 push(`github-com-ckidsm` SSH alias). 122개 파일.
- **보안 사고·조치**: `_archive/deploy_to_nas.sh`(초기 커밋부터 방치된 옛 스크립트)와 `_quick_deploy.sh`(미추적 스크래치)에 **NAS 비밀번호가 하드코딩**돼 있었음. push 전 발견 → (1) 두 파일 삭제, (2) `git filter-branch`로 **전체 이력에서 `_archive/` 제거**(refs/original·reflog·gc까지 정리), (3) 전 리비전 스캔으로 비번 0 확인 후 push. 리모트엔 비번 흔적 없음.
- **재발 방지 규칙**: 스크립트에 비밀 하드코딩 금지. 배포는 `publish_book.sh`(`NAS_PASS` env). `.gitignore`에 `.env` 유지. **비번이 로컬 이력·OneDrive에 노출됐던 값이므로 NAS 비밀번호 교체 권장**(교체 시 `인증서/나스인증/`·메모리 [[reference-nas-ssh-deploy]]만 갱신).

### 2026-07-12: 이북 처리 최종 규칙 확정 — '한 번에' 오케스트레이션 + '이미지 처리 바이블' 완성

**⭐ 다음 책부터 한 명령** (`docs/EBOOK_CAPTURE_STANDARD.md` §0.0, 메모리 [[kyobo-ebook-oneshot-pipeline]]):
```
cd book-capture
NAS_PASS=... ./scripts/process_book.sh <SLUG> --chrome 20,20,20,20 --publish
```
crop→qc→trim→ocr→summarize→merge→build→**code**→**book_overview**→finalize→발행 전 과정. 유일한 사람 입력=`summary/chapters.json`(장 제목·경계). `--from`으로 부분 재실행.

**이번에 확정한 규칙(재실수 방지)**
1. **크롭**: 교보 **데스크탑 앱 raw 는 `--chrome 20,20,20,20`**. 큰 top(150 등)이 섹션 헤더('1.1 …')를 잘라먹음 → "뷰어 잘림" 신고의 진짜 원인은 **모달 아닌 크롭**. `crop_book.py --chrome`(하드코딩 제거). 진단: 모달 DOM 측정(`.modal-stage img` vs stage rect 일치=무클립)으로 모달 먼저 배제. 메모리 [[ebook-viewer-cut-check-crop-first]].
2. **뷰어 모달 규칙화**: `build_html.ViewerLayout` 클래스 = 레이아웃 단일 관리처(솔리드 배경 #0a0e14·사방여백 64/96·화살표 이미지 밖·원본 풀해상도 로드·캐시버스트). `modal_css()`가 `_CSS` 오버라이드.
3. **책 개요**: 첫 페이지 `📋 책 개요` = 전체 요약 1개 + **챕터별 상세 요약(각 ~1페이지, 8챕터=~8장)**. `scripts/gen_book_overview.py`가 Claude **tool_use**(구조화 출력 → JSON 이스케이프 문제 0)로 생성, `_build_overview`의 `chapter_digests` 렌더.
4. **발행**: `publish_book.sh`(요약파일 sudo cp) + `publish_images.sh`(page/thumbs tar 스트리밍, `--raws`로 원본 보관). rsync/scp Synology 불안정 회피.

**'이미지 처리 바이블'(277p) 완성**: 재크롭(헤더 복원)·재발행, 코드추출 85p·285블록($0.81), 책 개요 생성($0.37). 표정리는 대상 없음(코드·다이어그램 중심). 라이브 검증 완료. OCR은 이 책 폰트에서 mojibake라 요약·개요는 비전 경로 기반(OCR 무관).

**신규 자산**: `scripts/process_book.sh`·`publish_images.sh`·`gen_book_overview.py`, `build_html.py`(ViewerLayout·chapter_digests), `crop_book.py --chrome`. 커밋 다수(7c68e8a~56f2b79, YUNDEOKSOO).

### 2026-07-13~14: 웹 로컬매크로 자동화 + 교보 앱 캡처 근본 안정화 + 크롭 재설계

'혼자 공부하는 머신러닝+딥러닝'을 웹(로컬매크로)으로 캡처하며 여러 근본 버그를 잡고, 하드코딩을 상수 클래스로 정리, 크롭을 재설계했다.

**교보 앱(iPad앱 kr.co.kyobobook.iPadB2C) 캡처 근본 수정 (`bookcapture/kyobo_app.py`)**
- **NFD/NFC 유니코드 버그(핵심)**: Quartz `kCGWindowOwnerName`='교보eBook'이 **NFD(분해형 자모)**로 와서 리터럴 '교보'(NFC)와 substring 매칭 실패 → 창을 영영 못 찾아 캡처 실패·마지막페이지 무한반복. `unicodedata.normalize('NFC',...)` 후 비교로 해결.
- **창 비활성 대응**: 마우스·클릭으로 교보가 비활성되면 →키/캡처 실패 → `_ensure_frontmost`(활성+최전면 폴링)를 캡처·페이지넘김 직전마다.
- **마지막 페이지 감지**: OCR 페이지번호는 mojibake라 못 씀 → 직전 캡처와 **축소 grayscale MAD**(<임계=같은 페이지). 오탐(242p 조기종료) 방지 위해 '같은 페이지'면 **→키 3회 재전송 확인**(넘어가면 계속=일시적 미스, 계속 같으면 책 끝).
- **오염 = 캡처 방식 문제(WID 전용으로 근본 해결)**: `-R` 영역 폴백이 교보 비-최전면 시 터미널을 찍는 유일한 오염원. '내용으로 오염 판별'(비전)은 **프로그래밍 책 코드와 구분 불가**(엄격→진짜 오염 놓침, 느슨→코드 오삭제 — 실제 ML 책 코드 84장 오삭제 사고). → **WID(-l) 전용**(occlusion-safe=창 내용만=구조적 무오염)으로 고정, -R·비전검사 폐기. WID 실패 시 재시도 후 그 페이지만 스킵.
- 속도: capture-auto `--no-ocr`(페이지번호 OCR은 mojibake라 무의미) + interval 0.8.

**크롭 재설계 (`bookcapture/page_crop.py` content_crop)**
- 증상: '혼자 공부하는 머신러닝' p31 **우측 39% 잘림**(우측 페이지 코드블록 손실). 이미지바이블은 안 잘림.
- 규명(추측 금지, 실측): 옛 content_crop은 **내용(어두운 텍스트) 밀도**로 경계 → 가장자리에 **드문 코드블록**(회색박스+적은 글자)은 밀도 미달로 잘림. 이미지바이블은 내용이 빽빽(전폭)해 우연히 안 걸렸을 뿐 = 근본 불안정. ('코드책이라서'가 아님 — 클로드코드도 코드책인데 됐음).
- 해결: **'종이(흰 min≥245) 또는 내용(유채색/어두움)' 열/행을 유지, 앱 회색 여백(~235)만 제거**. 종이 위 내용은 밀도 무관하게 다 포함 → 절대 안 잘림. 베이지 표지도 '유채색=내용'으로 유지. 검증: p31 3200폭(코드 다 포함), 이미지바이블·베이지 정상.

**하드코딩 → 도메인 상수 클래스 (스파게티 방지, 사용자 요청)**
- `CaptureTuning`(kyobo_app): 키코드·최전면대기·MAD임계·SIG_SIZE·창필터 등.
- `AnthropicAPI`(anthropic_api.py 신규): API URL·버전·모델·가격·재시도·이미지폭·타임아웃. summarize·extract_code·book_overview·contamination·chapters_detect 6파일 중복(47곳) 제거. 이름은 '실제 대상(Anthropic API)'으로.
- `CropRules`(page_crop): 크롬·여백·SAT/DARK/PAPER 임계·썸네일.

**웹 자동 파이프라인 (`worker.py` mode=auto)**
- capture→ocr→summarize→code→merge→build→**chapters-auto(비전 장표지)**→**overview(전체+장별)**→finalize→publish. 인라인 오염검사·전수 오염검사 제거.
- ⚠️ **미해결 버그**: `chapters-auto`가 장 0개면 exit 1 → 워커가 잡 전체 실패시킴(챕터는 선택인데). '혼자 공부하는 머신러닝'은 챕터 표지가 단색이 아니라 비전 감지 0개 → 잡 실패 → 수동 발행함. **수정 필요**: chapters-auto 0개여도 exit 0, 워커가 챕터/개요/finalize 실패를 non-fatal로. 색표지 없는 책 챕터 감지 개선(목차 기반)도 후속.

**'혼자 공부하는 머신러닝+딥러닝'(291스프레드)**: WID 전용으로 오탐·오염 없이 전권 캡처, 코드추출 130p·395블록($1.4), 내용 페이지 요약 정확(예 p31 KNN). 크롭 재설계 후 재크롭·재발행. OCR은 이 책도 mojibake(코드는 읽힘, 한글 깨짐).

### 2026-07-15: 요약·OCR 텍스트 **비전 경로화** (mojibake 책 근본 해결) + '혼자 공부하는 머신러닝' 재발행

'혼자 공부하는 머신러닝+딥러닝' 발행본이 (1) 주제 요약이 일부 페이지에서 환각(리액트·OSI·베타테스트 등), (2) 챕터트리·책개요 없음 = 이미지 처리 바이블과 다름 — 신고. 전수 진단·근본 수정.

**근본 원인 (전수 검증)**: `summarize`·`ocr` 두 단계가 **tesseract OCR 텍스트를 입력**으로 쓰는데, 교보 이북은 폰트 때문에 **전 페이지 OCR 이 mojibake(한글 0%)**. 코드 있는 페이지는 OCR 에 코드(ASCII)가 살아 요약이 우연히 정확했지만, TOC·산문·간지 페이지는 앵커조차 없어 AI 가 환각. (이미지 처리 바이블도 OCR 은 100% mojibake였으나 ISBN·URL 등 앵커가 있어 티가 덜 났을 뿐 — 구조적 문제.)

**수정 — 비전 경로 신설(재사용, 향후 모든 mojibake 책 적용)**
- `bookcapture/summarize.py` — `summarize_page_vision()` + `summarize_pages(images=...)`: OCR 텍스트 대신 **페이지 이미지**를 Claude 비전에 보내 요약(코드추출·챕터감지와 동일 계층). 5장마다 증분 저장 + **resume**(기존 batch 재사용) 추가.
- `bookcapture/transcribe.py` (신규) — `ocr --vision`: tesseract 대신 **Claude 비전으로 본문 전사** → `ocr_text/page_NNN.txt` 덮어씀. 팝업 '📄 OCR 텍스트' 패널이 mojibake 대신 깨끗한 한글 본문·코드 표시. resume 는 `.vision_done.json` manifest(코드 페이지는 한글비율 낮아 한글 판별 불가 → 별도 추적).
- `bookcapture/cli.py` — `summarize --vision`, `ocr --vision [--pages]` 플래그.

**이 책 재작업 (end-to-end)**
- 291p **비전 재요약**($4.9) — 환각 8+장(p8 리액트→Ch01 로드맵, p246 OSI→순환신경망 등) 전부 교정. 도중 크레딧 소진 → 충전 후 resume 로 14p 마저 완료.
- `chapters.json` 수동 작성 — 재요약 결과에서 9장 경계 정밀 확인('확인 문제'로 장 끝 + 다음 장 간지 패턴). Ch1(14–33)~Ch9(244–277), 앞 1–13=front matter.
- merge→build→**overview**(전체+9장 상세, $0.4)→finalize(챕터트리)→발행. 📋 책 개요·CH1~CH9 트리·291 페이지 카드 라이브 검증.
- 291p **비전 전사**($7.3) — 팝업 OCR 패널 교체. 전사 후 한글정상 258장, 코드페이지 23장(자연히 낮음), p5 1장 콘텐츠필터 오탐→재시도 성공. `publish_ocr.sh` 로 발행.
- 발행 3종: `publish_book.sh`(index/overview/code) + `publish_ocr.sh`(ocr_text 291). NAS_PASS 는 `인증서/나스인증/`에서 런타임 주입(하드코딩 금지).

**미해결/후속**
- `worker.py mode=auto` 는 아직 OCR-요약 경로 — **mode=auto 에 `--vision` 요약·전사 기본 적용**할지 결정 필요(모든 책이 mojibake 는 아님 → 자동 판별 후 분기 검토).
- 이미지 처리 바이블도 OCR 100% mojibake → `ocr --vision` 재전사·재발행 대상(요청 시).
- (기존) chapters-auto 0개 exit 1 워커 실패 버그 — 이번엔 chapters.json 수동 작성으로 우회.

### 2026-07-15: OCR/본문전사 엔진 **Gemini 전환** (비용 ~18배 절감, Claude 안 쓰기)

사용자 방침: 이북 OCR/전사는 되도록 Claude API 안 쓰고 절약. Claude가 이미 전사한 '혼자 공부하는 머신러닝'을 기준으로 **같은 페이지를 Gemini에도 전사시켜 실측 비교**.

**비교(대표 5p: 산문 p3·목차 p8·코드 p31·혼합 p100·색인 p289)** — Gemini `gemini-2.5-flash`(thinking off) vs Claude `claude-sonnet-4-5`:
- p3 산문: Gemini 우세(문장 더 정확). p8 목차: Gemini 우세(페이지번호까지, 341→582자). p31 코드: Gemini 우세(Claude는 `"""두 첫번째"""`·`"""세번..."""` 오독). p100 혼합·p289 색인: 동등.
- **결론: Gemini 품질 동등~우세, 비용 ~18배 저렴**($7.3→~$0.4/권). → 전사 엔진 Gemini 채택.
- ⚠️ 무료 티어(express 키 `AQ.Ab8…`)는 **503 과부하·429 쿼터**로 전권 실행 불안정 → **billing 활성 Gemini 키 필요**(그래도 Claude보다 훨씬 쌈).

**구현(커밋 예정)**
- `bookcapture/gemini_api.py` (신규) — `GeminiAPI` 상수(모델·가격·재시도) + `generate()`(generateContent, thinking off, 429/503 재시도) + `img_b64()`(JPEG). anthropic_api 와 같은 계층.
- `bookcapture/transcribe.py` — 엔진 선택: **Gemini 키 있고 ocr_provider!=claude 면 Gemini, 아니면 Claude 폴백**. manifest resume·증분 저장 그대로. quota 소진 시 중단(resume 가능).
- `bookcapture/settings.py` — `AiCfg` 에 `ocr_provider`(기본 gemini)·`gemini_api_key`(env GEMINI_API_KEY/GOOGLE_API_KEY)·`gemini_model`(gemini-2.5-flash) 추가. `explain()` 에 전사 엔진 표시.
- 검증: `ocr --vision` → `engine=gemini` 라우팅·quota 소진 graceful 처리 확인. **이 책은 이미 Claude 전사·발행됨(재전사 불필요)** — Gemini는 앞으로의 책에 자동 적용.

**요약 비용 절감 — Haiku + 깨끗한 텍스트 (Claude 유지)**
- 통찰: Gemini 전사가 **깨끗한 본문 텍스트**를 주므로, 요약을 이미지(비전 Sonnet, $4.9/권)가 아니라 **그 텍스트로** 하면 된다. 텍스트요약은 싼 **Claude Haiku**로도 정확(mojibake 아니니까).
- `settings.AiCfg.summarize_model="claude-haiku-4-5"` 추가. `cmd_summarize`/`cmd_overview` 가 이 모델 사용(`--model` override 가능). 기본 요약은 **텍스트 모드**(--vision 은 전사 텍스트 없을 때만).
- `process_book.sh`: OCR 단계를 `ocr --vision`(Gemini 전사)로, 요약은 Haiku 텍스트 → **파이프라인 전체가 Gemini전사+Haiku요약** 체인.
- 실측(p31·100·214): Haiku 텍스트요약 품질 Sonnet 비전과 동등~우세(p100 오히려 나음), **$4.9→~$1.4/권(3.4배↓)**. (p31 '두/세번' 잔오류는 Claude 전사본 오독 → Gemini 전사면 해소.)
- **권당 총비용**: 기존 ~$7.1 → (전사 Gemini ~$0.4 + 요약 Haiku ~$1.4 + 코드/개요) ≈ **$2 안팎**. 코드추출(Sonnet 비전 $1.4)도 Gemini로 옮기면 추가 절감 가능(후속).
- **후속**: billing Gemini 키 세팅 후 신규 책부터 적용. `worker.py mode=auto` 반영, 코드추출 Gemini 전환은 추가 결정.

### 2026-07-15: '밑바닥부터 LLM' 이미지 전수 조사·보정 (교보 Mac 앱 직접 캡처) + 앱 캡처 함정 정리

발행본 이미지 문제 신고("12~16 오염, 19 과대확대, 36 빈페이지") → 296p **콘택트 시트(64장/시트)로 육안 전수 조사**.

**진단**
- **12~16**: 워커 **콘솔 터미널이 책 위에 겹쳐 찍힘**(job #96 capture-browser 로그가 이미지에 보임). 요약은 정상(추천사).
- **36·129**: **빈 캡처**(페이지 전환 순간 = 뷰어 푸터만). 각각 Section 2.2 토큰화 / 5.2 훈련하기 자리. 요약 "내용 없음".
- **19·28·184·222·250·251·259**: 내용 온전한 간지·이월문장·부록요약(좁아서 확대돼 보일 뿐, 손실 X).
- **원본 raw 없음**(6월 재크롭이 in-place 덮어씀) → 재크롭 불가 → 재캡처만.

**교보 Mac 앱(iPadB2C '교보eBook') 직접 캡처 — 함정과 해법**
- 앱은 **네이티브 DRM 앱** — 브라우저 도구로 못 잡음. 이 Mac에 앱이 떠 있으면 `screencapture -l<wid>`(WID, occlusion-safe)로 잡힘. 창 owner 명이 **NFC 정규화 필요**('교보eBook').
- ⚠️ **WID 선택 버그**: 교보 창이 3개(얇은 툴바 2 + 내용 1). 첫 매칭 창을 잡으면 **얇은 툴바(1800×43) → 검정 캡처**. **가장 큰 창(1800×1126, wid 내용창) 선택**해야 함.
- ⚠️ **DRM 블랭크 오해**: 백그라운드(`&`)로 돌리면 앱 최전면 유지 실패로 검정 → 실은 WID 버그였음. 전체화면 캡처는 정상이라 이걸로 진단.
- **→ 키 = 2페이지(펼침) 이동**. `osascript key code 124`(→)/123(←). 앱 최전면 유지(`set frontmost`)하며 포그라운드로 캡처. **딜레이 0.3s로 �足른 캡처**(로컬앱이라 지연 불필요), 140펼침 검정 0장.
- ⚠️ **앱 목차(☰) 클릭 불안정**: 네이티브 앱 좌표 클릭(Quartz 마우스이벤트)이 빗나감 → **순차 → 이동 + 콘택트시트 내용대조**가 신뢰성 높음.

**보정·발행**
- 표지부터 140펼침 재캡처. **앱 판본에 한국 추천사(우리 12~16)가 없음** 확인(cover→title→판권→지은이의말→감사의말→이책에대하여→목차) — 브라우저 판과 다른 판본.
- 12~16: 앱에 없어 **콘솔 좌측을 잘라 우측 추천사 열만** 유지(어두운 콘솔 우측경계 검출 크롭).
- 36←앱 c28('2.2 텍스트 토큰화하기'), 129←앱 c107('5.2 LLM 훈련하기'). `crop_page(chrome=(20,95,20,110))`로 앱 툴바 제거 → 교체. **비전 재요약**('내용 없음'→토큰화/훈련 정상).
- 썸네일 7장 재생성(로컬 thumbs 없어 폴더 신설), index merge→build→finalize, **타깃 발행**(index + 7 page/thumb만 tar 스트리밍, 전체 296장 재전송 회피). 원본은 `books/<slug>/_orig_backup/`.
- 남은 '내용 없음' 3건 = 원래 sparse 간지/각주(정상). 296p 유지·라이브 반영.

---

### 2026-07-18: '밑바닥부터 LLM' 마감 — 오염 교체·OCR 전권 비전전사(Gemini billing)·이미지 여백·팝업 뷰어 규칙 확정

발행본 후속 신고 4건을 한 세션에 처리. **팝업 뷰어(모달) 반복수정 함정**(문서 경고)을 이번엔 "먼저 진단→트레이드오프 설명→사용자 결정"으로 끊음.

**1) 오염 추천사 이미지 교체 (11·13·14·15·16)**
- 진단: 11~17이 같은 추천사 2스프레드 **중복 캡처**. 11=앱 미리보기창 겹침, 13=콘솔조각, 14·15·16=콘솔바(동일 파일). **11≡17**(전체 스프레드)·**12≡13~16**(오른쪽 칼럼) — 깨끗한 쌍둥이(12·17) 존재.
- 처리: 11←17, 13·14·15·16←12 로 풀해상도+썸네일 교체(원본 `_orig_backup/`). `index.html` 해당 5개 `?v=` 캐시버스트. `scripts/publish_llm_recos_fix.sh`(일회성, 커밋 안 함)로 타깃 발행.

**2) 팝업 OCR 텍스트 전권 비전 재전사 (mojibake 근본 해결)**
- 신고(page 29 OCR 깨짐)의 실체 = 이 책 팝업 OCR 패널이 **아직 tesseract mojibake**(요약·챕터·개요는 이미 비전이라 정상, 팝업 전사만 미실행이었음 — 로직 회귀 아님). **이미지 처리 바이블도 동일**(`.vision_done.json` 없음, 전 페이지 mojibake) 확인 — "이미 보정"은 이미지·요약 얘기였고 팝업 전사는 두 책 다 미완이었던 것.
- 조치: `ocr --vision`로 296p 재전사. **Gemini free 키(`AQ.Ab8…`)는 분당쿼터로 5~20장씩 끊김** → 사용자가 **같은 키에 billing 활성화**(키 문자열 동일) → 한 번에 완주. **신규 273 + 재사용 23, $0.62**. `publish_ocr.sh` 발행, 라이브 검증(깨끗한 한글·코드·URL). resume=`.vision_done.json`(페이지번호 리스트).

**3) 이미지 사방 여백 (좌우상하 너무 타이트)**
- 진단(모달 아님, 소스크롭): page_29 내부 흰여백 **사방 1.3%(16px)**뿐, 재크롭할 raw 없음(`source_raws` 없음). → 모달 CSS 아닌 **이미지에 흰 여백 덧대기**가 정답.
- 처리: 296장 **각 배경색으로 폭·높이의 9% 비례 패딩**(page_29≈121px, 사용자 승인). 크기 제각각(최대 3560px)이라 고정px 대신 비례 → 상대여백 균일. 원본 `_prepad_backup/`, 썸네일 재생성(>1800만 리사이즈), 캐시버스트 전체, `publish_images.sh`+`publish_book.sh` 발행.

**4) 팝업 이미지 뷰어 — "와이드" 왕복 끝에 규칙 확정 (`build_html.py` ViewerLayout)**
- 시도1 `width:100%`(fit-to-width) → 좁은 페이지(12~16=추천사 조각 ~810px)가 2배 뻥튀기·흐림("이거 뭐냐").
- 시도2 `width:auto;max-width:100%`(원본크기 캡) → 좁은건 해결됐지만 스프레드가 세로 넘쳐 **아래 잘림**("짤린다").
- **결론(기하학)**: 스프레드(가로세로비 ~1.2)를 넓은 화면(~1.8)에 넣으면 **'가로 꽉 채움'과 '안 잘림'은 양립 불가**. 사용자 선택 = **전체 보이기 + 여백 최소화**.
- 확정: `.modal-stage img`는 **fit-to-screen 원복**(`max-width/height:100%`, origin center). 세로여백 **상단 58 / 하단 16 비대칭**(툴바는 상단만 → 하단 축소로 이미지 최대·좌우 검은여백 축소). `ViewerLayout`에 `STAGE_MARGIN_B` 추가, `modal_css` inset 4값. **좌우(H=96)는 안 줄임**(height-fit에선 줄이면 검은여백 오히려 늘어남). ⚠ 이 트레이드오프를 ViewerLayout 주석에 못박음 — 다음에 같은 왕복 금지.

**발행 메모**: NAS_PASS는 `인증서/나스인증/NAS_RedCode_접속정보.md`에서 런타임 주입. sudo tar 추출 시 `~`가 root 홈으로 확장되는 함정 → **`/tmp` 절대경로** 사용.

---

### 2026-07-19: 신규 책 자동화 완성 — Gemini 키 영구화 + 챕터 감지 안정화·목차(TOC) 폴백 + SSH 키

"새 책 분석 시 깨끗한 OCR·챕터·개요가 자동으로 나오는가"를 검증하다 두 공백을 메우고, 챕터 감지를 결정적으로 재설계했다.

**① Gemini billing 키 백엔드 영구화 (자동 저비용 전사)**
- 문제: `worker.py`/`process_book.sh` 는 이미 전 분기 `ocr --vision`(Gemini→Claude 폴백)인데, **Gemini 키가 백엔드에 없어** 새 책이 Claude 폴백(~18배 비쌈)으로 감. (env 키는 세션 한정)
- 조치: billing 활성 Gemini 키를 `/api/settings` 에 저장 → `/api/secrets/ai` 가 반환 → 워커/CLI 가 자동 사용. `ocr_provider=gemini`, `gemini_model=gemini-2.5-flash` 확인.
- **⚠️ 사고·수정**: PUT `ai:{gemini_api_key}` 만 보냈더니 `set_setting('ai', ...)` 이 **ai dict 를 통째 교체 → Claude `api_key` 삭제**. DB·WAL·env 어디에도 복구 불가 → 사용자에게 재입력받아 복원. **`put_settings` 를 deep-merge 로 수정**(형제 키 보존, 부분 업데이트 안전) 후 **백엔드 정식 재빌드**(`deploy.sh --backend`). 교훈: 부분 설정 PUT 전 기존값 병합 필수.
- 배포된 백엔드가 소스보다 옛 이미지였음(gemini 지원 미반영) → 재빌드로 해소.

**② 챕터 감지 안정화 + 목차(TOC) 폴백 재설계 (`chapters_detect.py`)**
- 배경: 발행본 챕터는 대부분 **수동 보정본**. 재현 테스트로 **커버 기반 감지가 비결정적**(temperature 미설정=기본 1.0)임이 드러남 — 실행마다 가짜 장·경계 흔들림.
- **안정화 3종**: (a) `AnthropicAPI.DETECT_TEMPERATURE=0.0` 신설 → 표지·목차 판정 **결정적**(재현성). (b) `_drop_false_chapters` — 장번호 역행/중복(섹션 오검출·스프레드 경계 중복) 제거. (c) 위치순 **순차 재번호**(부록 '9장'→'8장' 교정).
- **TOC 폴백**(색표지 없는 책): `find_toc_pages` 를 **연속 블록** 방식으로 재설계 — 목차가 여러 페이지에 걸치고 페이지당 1~2장만 담을 때(스프레드당 Chapter 1개) '페이지당 장 ≥3' 요구가 첫/끝 장을 놓침 → '제목……페이지번호' 라인 밀집 페이지의 **연속 범위 전체**를 목차로. 산문/추천사는 페이지번호 라인 없어 여전히 제외. 비전으로 장 목록 추출(temp=0) → **깨끗한 전사 텍스트**에서 각 장 제목/번호로 위치 검색 → 경계. 제목 가드는 길이(>40)만(짧은 '~합니다' 제목 오제외 버그 수정). **contiguity 게이트**: 장번호 불연속/일부 위치 실패 시 스킵(수동본 보호).
- 검증(개별 실행, 실측): **이미지바이블**(컬러표지·cover 경로) run1==run2 결정적, 가짜장 제거·부록 교정. **혼자공부 ML**(무표지·TOC 폴백) run1==run2 결정적, **9/9 장, 1~8장 경계 정확**(9장만 end 가 back matter 포함 291 vs 정답 277). **LLM**(무TOC·무표지·무헤딩=최악) → 0장 안전 반환(수동 필요, 가비지 없음).
- ⚠️ **미해결**: (a) 마지막 장 end 가 책 끝으로 잡혀 back matter 포함(뒤 부분 감지 필요). (b) cover 경로 남은 경계 오차(비전이 특정 표지를 일관되게 다르게 판정 — 이젠 결정적이라 재현은 됨).

**③ SSH 키 인증(비대화형 배포 근본 해결)**
- NAS 는 비번 인증이라 `deploy.sh`(평범한 `ssh`)가 비대화형에서 막힘 → **passphrase 없는 배포 전용 키**(`~/.ssh/id_ed25519_kyobo_nas`) 발급, NAS `authorized_keys` 등록, `~/.ssh/config` 설정. 이후 ssh/scp/deploy/docker 가 비번 없이. 키 백업·문서화: `인증서/나스인증/`.

**검증 함정 기록**: 5권 배치 재검증 스크립트가 **rate-limit 로 chapters-auto 크래시 → chapters.json 미수정 → 정답 그대로 남아 '거짓 일치'**(LLM 12/12 같은 불가능한 결과). chapters-auto 자체 로그(후보/장) 0건으로 판별. **재현 테스트는 산출물이 실제로 갱신됐는지(자체 로그/타임스탬프) 확인해야 함**. 개별 실측(위 ②)은 유효.

**변경 소스 4개**: `kyobo-bridge/app/main.py`(put_settings deep-merge) · `bookcapture/anthropic_api.py`(DETECT_TEMPERATURE) · `bookcapture/chapters_detect.py`(TOC 블록·dedup·재번호·게이트·temp0) · `bookcapture/cli.py`(chapters-auto TOC 폴백 + --no-toc).
