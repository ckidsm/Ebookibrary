# Phase B 설계 제안서 — Kyobo Library 고도화

> 작성일: 2026-05-28
> 대상: 9000 포트 신규 서비스 + 교보문고 e-Library 연동
> 작성: Claude (사용자 의사 결정 보조용 — 결정은 사용자가)

---

## 0. 사용자 의도 정리

> "기존 파이썬 소스 분석 후 `https://elibrary.kyobobook.co.kr/dig/elb/elibrary` 정보를 얻어와야하고
> 메인 페이지는 교보문고 로그인 할 수 있게 해야된다 `https://ebook.kyobobook.co.kr/dig/pnd/welcome`
> 같은 도커 내에 포함되어야 한다. 9000번 포트로 서비스."

요약:
- **신규**: 메인 페이지에 교보 로그인 진입점 추가, 로그인 후 e-Library 정보 가져오기
- **포트**: 9000으로 새 서비스 (기존 8080은 그대로 유지하라는 뉘앙스)
- **컨테이너**: "같은 도커 내" — 해석 두 가지 가능 (아래 1.1 참조)

---

## 1. 사실 정리 (Phase A 검증 결과)

### 1.1 "같은 도커 내" 의 두 해석
- **(a)** 같은 컨테이너 안에 두 nginx server 블록 → 호스트가 8080·9000 둘 다 매핑.
  - 단점: 컨테이너 한 개가 두 책임(정적 도서 라이브러리 + 교보 연동) 짊어짐.
  - 한 쪽 장애로 다른 쪽도 같이 죽음.
  - nginx만으로는 백엔드(로그인·세션·API 프록시) 처리 불가 — 9000은 실질적으로 백엔드가 필요.
- **(b)** 같은 NAS Docker 데몬에서 도는 별도 컨테이너 (=`docker-compose` 한 파일에 두 service).
  - 8080: 기존 nginx (정적 라이브러리)
  - 9000: 새 백엔드 컨테이너 (Python/Node — 교보 연동)
  - 두 서비스 독립 라이프사이클, 한 쪽 재시작이 다른 쪽 안 건드림.

**추천**: **(b)** — 같은 NAS·같은 compose stack, **다른 컨테이너**.
이유: 9000은 단순 정적 사이트가 아니라 백엔드(세션·HTTP 프록시) 책임. nginx 1개로는 불가.

### 1.2 교보 사이트 응답 헤더 (curl HEAD 검증)
| 항목 | `ebook.kyobobook.co.kr/dig/pnd/welcome` | `elibrary.kyobobook.co.kr/dig/elb/elibrary` |
|---|---|---|
| HTTP | 200 | 302 → `mmbr.kyobobook.co.kr/login?continue=...` |
| Server | istio-envoy | istio-envoy |
| **x-frame-options** | **SAMEORIGIN** | **SAMEORIGIN** |
| Set-Cookie | JSESSIONID + 도메인 쿠키 | JSESSIONID + 도메인 쿠키 |
| 로그인 필요 | (welcome 페이지는 공개) | **필수** (인증 미보유 시 즉시 로그인 페이지로) |

**핵심 결론**:
1. **iframe 임베드 불가** — `SAMEORIGIN` 정책이 외부 출처에서의 frame을 차단.
   → "메인 페이지에 교보 로그인을 iframe으로" 라는 접근은 **물리적으로 불가**.
2. **세션 쿠키 인증** — 로그인 후 JSESSIONID 등 쿠키로 API 호출 가능. 백엔드 프록시 방식이 기술적으로는 가능.
3. **공개 API 부재** — 정식 OpenAPI/공개 API 없음. e-Library 도서 목록은 비공개 내부 엔드포인트.

### 1.3 robots.txt
- `kyobobook.co.kr` 의 robots.txt: 일반 크롤러 허용 (`Allow: /`), 특정 봇만 차단(AhrefsBot 등).
- **단, 로그인 후 마이페이지·내 도서함은 robots.txt 와 무관한 사적 영역** — 인증된 본인 데이터만 접근.

### 1.4 기존 파이썬 코드와의 관계
- `verify_ocr.py` / `merge_batches.py` / `generate_html.py` 는 **오프라인 OCR/HTML 빌드** 도구.
- 교보 e-Library API/로그인과는 **무관** — 사용자가 "기존 파이썬 소스 분석"이라고 한 건 이 코드가 아니라 **혹시 별도로 가지고 계신 교보 크롤링 파이썬**일 가능성. 확인 필요.
- 만약 별도 파이썬 없다면 Phase B의 백엔드는 0부터 새로 만들어야 함.

---

## 2. 교보 e-Library 연동 — 4가지 접근 방식 비교

### 옵션 A. 외부 링크 모음 (최단)
- 메인에 큰 카드 두 개: `[교보 로그인]` `[내 e-Library]` — 클릭 시 새 탭으로 교보 사이트 열기.
- **장점**: 0 백엔드, 0 인증 처리, 0 ToS 리스크. 1시간이면 끝.
- **단점**: "정보를 얻어와야 한다"는 사용자 요구를 충족 못 함 — 단지 링크 노출일 뿐.
- **권장 시점**: Phase B-0 즉시 — 최소 보증값.

### 옵션 B. 사용자 브라우저 + Userscript / 확장
- Tampermonkey/Violentmonkey 같은 Userscript Manager에 스크립트 설치
- 사용자가 직접 교보 사이트 방문 (브라우저 안에서 로그인) → 스크립트가 내 도서 목록 DOM에서 메타 추출 → 우리 9000 서비스 `POST /sync` 로 전송 → 내 카탈로그에 동기화
- **장점**:
  - 인증을 우리 서버가 들고 있지 않음 (가장 안전)
  - 교보의 ToS 위반 소지 최소 (사용자 본인의 브라우저 세션)
  - iframe 정책·X-Frame-Options 우회 불필요
- **단점**: 사용자가 직접 브라우저 확장 설치·동기화 액션 필요
- **권장 시점**: Phase B-2 (B-1 백엔드 완성 후 옵션 추가)

### 옵션 C. 백엔드 프록시 (사용자 자격증명 보관)
- 9000 서비스 안에 `POST /login` 폼 → 백엔드가 교보 로그인 페이지로 POST 대행 → JSESSIONID 받아 우리 서버 세션에 저장 → 이후 `/elibrary/books` 요청 시 백엔드가 그 쿠키로 교보 API 호출 → 결과 JSON을 우리 UI에 표시
- **장점**: 사용자가 한 번 로그인하면 우리 사이트 안에서 전부 처리
- **단점**:
  - 교보 비밀번호를 우리 서버가 잠시라도 들고 있음 (보안 책임 큼)
  - CAPTCHA·OTP·기기 인증 도입되면 즉시 깨짐
  - 비공개 내부 엔드포인트 의존 → 교보가 구조 바꾸면 매번 수리
  - 교보 ToS 회색지대 (자동화 로그인을 명시적으로 금지하는 사이트 多)
- **권장 시점**: 신중. 본인 단일 사용자라 위험은 낮지만 유지보수 비용 큼.

### 옵션 D. 헤드리스 브라우저 (Playwright/Selenium)
- 9000 백엔드가 Playwright로 교보 사이트를 직접 띄워 로그인 자동화·스크롤·DOM 추출
- **장점**: 브라우저 동작과 똑같이 → JS 렌더링·CAPTCHA 일부 대응
- **단점**: 컨테이너 무거움 (chrome+ffmpeg+...) · 메모리 폭증 · 봇 탐지 우회 어려움 · 가장 ToS 위험
- **권장 시점**: 마지막 수단. 추천 안 함.

### 비교 한 줄
| 옵션 | 즉시 가치 | 구현 비용 | 보안·ToS 위험 | 유지보수 비용 |
|---|---|---|---|---|
| A 링크 모음 | ★ | 매우 작음 | 없음 | 없음 |
| **B Userscript** | ★★★ | 중간 | 낮음 | 작음 |
| C 백엔드 프록시 | ★★★★ | 큼 | 중~높음 | 매우 큼 |
| D Headless | ★★★★ | 매우 큼 | 매우 높음 | 매우 큼 |

---

## 3. 추천 단계 (Phase B-0 → B-1 → B-2)

### Phase B-0 (1~2시간)
**즉시 가치 보증**. 9000 서비스 0줄 코드 — 메인 index.html 만 수정.
- 메인에 두 카드 추가: `[교보문고 로그인]`, `[내 e-Library 열기]`
- 새 탭으로 교보 URL 열기. 끝.
- 이걸로 **사용자 요구의 "로그인 진입점"은 즉시 충족**.

### Phase B-1 (반나절)
**9000 서비스 인프라** — 옵션 B/C 모두의 토대.
- `docker-compose.yml` 에 새 서비스 추가:
  ```yaml
  kyobo-bridge:
    image: kyobo-bridge:latest          # 우리가 빌드
    ports: ["9000:8080"]
    restart: unless-stopped
  ```
- 기술 스택: **Python 3 + FastAPI** (가장 적은 코드로 백엔드·세션·HTTPX 프록시 지원)
- 엔드포인트:
  - `GET /health` — 헬스체크
  - `GET /api/library/books` — 내 도서 카탈로그 (Phase B-2에서 채움)
  - `POST /api/library/sync` — Userscript에서 받은 데이터 저장
- 데이터 저장: SQLite (`/data/library.db`, NAS 볼륨 마운트)
- 메인 페이지: `/kyobo/` 경로에 도서 검색·필터 UI (정적 HTML + fetch)

### Phase B-2 (옵션 B 적용, 1일)
**Userscript 작성** — 사용자가 교보 사이트에서 본인 도서 목록을 우리 서비스로 동기화.
- `userscript/sync-kyobo-library.user.js` 작성
- 사용자가 교보 e-Library 진입 시 자동 발동 → DOM 파싱 → `POST 9000/api/library/sync` 호출
- 인증·세션·CAPTCHA 모두 교보 측 자연스러운 흐름에 위임

### Phase B-3 (선택, 미정)
- 옵션 C 백엔드 프록시는 본인 단일 사용자 환경이라 추후 결정.
- 정적 라이브러리 To-Do (검색·다크모드·OCR 검색)는 8080 서비스에 직접 추가.

---

## 4. 권장 결정 매트릭스

| 결정 | 추천 |
|---|---|
| 컨테이너 분리 | **별도 컨테이너** (`docker-compose.yml`의 두 service) |
| Phase B-0 (즉시) | **외부 링크 모음** 적용 — 메인 index.html만 수정 |
| Phase B-1 백엔드 스택 | **Python 3 + FastAPI**, SQLite 저장 |
| Phase B-2 데이터 수집 | **Userscript (옵션 B)** — 백엔드 프록시(C) 추천 안 함 |
| 기존 파이썬 3개 | 그대로 유지 (오프라인 OCR/HTML 빌드용, Phase B와 무관) |

---

## 5. 사용자에게 확인이 필요한 것

1. **"같은 도커 내"의 해석** — 위 1.1의 (a)/(b) 중 어느 쪽인지?
2. **별도 교보 크롤링 파이썬 코드를 이미 가지고 있는지?** — 있다면 위치·내용 공유 부탁
3. **Phase B-2의 옵션 선택** — Userscript(B) vs 백엔드 프록시(C) vs 둘 다 미정 (B-0만 우선)
4. **Userscript 설치 의향** — Tampermonkey 등 확장 설치에 거부감 없는지

---

## 6. ToS·보안·법적 고려

- 교보문고 이용약관 검토 필요 (자동화·스크래핑 허용 여부 — 일반적으로 회색)
- 본인 계정 본인 데이터만 다루는 한 일반적 위험 작음, 그러나 비밀번호·세션 토큰을 서버가 보관하는 옵션(C)은 책임 큼
- 모든 데이터는 LAN 내부에만 — 외부 공개·재배포 금지

---

## 7. 다음 액션 제안

1. 사용자가 위 5번 확인 사항에 답
2. Claude는 답에 따라:
   - 무조건 — **Phase B-0** (메인 링크 추가) 즉시 작업
   - "B 권장" 답 시 — **Phase B-1** 인프라 + Phase B-2 Userscript
   - "C 권장" 답 시 — Phase B-1 인프라까지만 만들고 사용자와 더 상세한 보안 합의 후 진행
