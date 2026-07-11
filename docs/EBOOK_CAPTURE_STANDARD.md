# 이북 캡처·크롭·OCR 표준 (다른 책에도 적용)

> 2026-07-05 "클로드 코드로 시작하는 실전 에이전틱 코딩" 246장 전권으로 확정. 다른 이북도 이 절차로.
> 이 문서가 **단일 진실원본(런북)**. 세부 근거: 선명도=`CAPTURE_SHARPNESS.md`, 외부노출=`EXTERNAL_ACCESS.md`.

## 0. 표준 파이프라인 (순서대로 — 이것만 따라 하면 됨)

| # | 단계 | 명령/도구 | 산출물 |
|---|---|---|---|
| 1 | Raw 캡처 | `scripts/app_capture_raws.py`(Mac앱) 또는 `scripts/mac_wviewer_capture.py`(웹뷰어) | `raws/raw_NNN.png` |
| 2 | 크롭+썸네일 | `scripts/crop_book.py <raws> <out> --thumb 1800` | `page_NNN.png` + `thumbs/` |
| 3 | OCR | `python -m bookcapture ocr --book-dir <책>` | `summary/ocr_text/page_NNN.txt` |
| 4 | AI 요약 | `python -m bookcapture summarize --book-dir <책>` | `summary/batch_*.json` |
| 4.5 | **소스코드 추출** | `python -m bookcapture code --book-dir <책>` | `summary/code_blocks.json` |
| 5 | merge+빌드 | `python -m bookcapture merge && ... build` | 깨끗한 `summary/index.html`(리치 뷰어+코드 패널 포함) |
| 6 | 챕터·표 정의 | 사람이 작성: `summary/chapters.json`, `summary/page_extras.json` | 정의 JSON |
| 7 | **최종화(주입)** | `python scripts/finalize_book.py summary/` | 챕터트리+표정리본 든 `index.html` |
| 8 | **NAS 발행** | `NAS_PASS=... scripts/publish_book.sh <SLUG> summary/index.html summary/page_extras.json summary/chapters.json summary/code_blocks.json` | 라이브 반영 |
| 9 | 원본 보관 | raw 전량 → 책 폴더 `source_raws/` (sudo cp) | 재크롭 대비 |
| 10 | 검증 | 라이브 `grep -o 'class="ptable"'` 개수 + Playwright 렌더(팝업 뷰어·코드 패널) 육안 | — |

- **3~5는 `python -m bookcapture run` 한 번으로도** (capture→ocr→summarize→**code**→merge→build). 스킵: `--no-summarize`, `--no-code`.
- **페이지별 팝업 뷰어(표준)**: `build`가 리치 모달을 생성 — 좌상단 📄 텍스트 토글·줌(−/100%/+/원복), 우측 `📄 OCR 텍스트`(복사, `ocr_text/` fetch)·`💻 소스코드`(언어별 C#/Python 코드 패널, `code_blocks.json` fetch)·`📝 메모`(페이지별 localStorage 자동저장). **build_html.py는 로컬·벤더드(`kyobo-bridge/app/processing/`) 동일 버전 유지**(웹 분석도 같은 뷰어 생성).
- **소스코드 추출(4.5)**: OCR은 코드 품질 낮음(문자오류·들여쓰기 손실) → `bookcapture/extract_code.py`가 Claude 비전으로 페이지 이미지에서 언어별 코드를 정밀 추출. 코드 자동감지·resume·429재시도. 웹 파이프라인은 `upload_processor.py`가 summarize 뒤 자동 실행.
- **6→7 규칙**: `finalize_book.py` 는 *깨끗한 빌드 결과*에만 돌린다(멱등 아님, 이미 주입 시 중단). chapters.json/page_extras.json 은 **있으면** 자동 주입, 없으면 건너뜀.
- **8 규칙**: 웹 파일은 root 소유라 RedCode 가 직접 못 덮어씀 → `publish_book.sh` 가 홈 업로드→`sudo cp`→`chown root:root`→`chmod 644`→검증까지 처리. 비번은 `NAS_PASS` 환경변수(하드코딩 금지, 출처 `인증서/나스인증/`).
- 이미지만 바뀌면 8에서 이미지도 넘기고, HTML 썸네일 src `?v=N` 증가(캐시버스트).

---

## 1. 캡처 = 교보 eBook **Mac 앱** (웹뷰어 아님)
- **웹뷰어(wviewer)는 anti-bot 세션당 ~127페이지 제한** → 중간에 "정상적인 접근이 아니므로 이용을 중단합니다" 차단. 전권 불가.
- **Mac 앱(교보eBook.app, 번들 `kr.co.kyobobook.iPadB2C`)은 제한 없음** + DRM 화면캡처 차단 없음(Mac 한정). → 246장 한 번에 성공.
- 뷰어 레이아웃: **두 페이지 보기(오른쪽 시작)** = 표지 단독 + 이후 양면(배포 구조와 일치).

## 1.5 로컬 매크로 해상도 사전 게이트 (필수 규칙) — 저해상 캡처 원천 차단

**로컬 매크로(교보 데스크탑 앱 캡처 = 물리 화면 캡처)** 는 결과 해상도가 **모니터 해상도 × scale**에 종속된다(§CAPTURE_SHARPNESS 실측). 그래서 도서 라이브러리 웹 UI에서 **로컬 매크로 선택 후 [분석 시작] 시 캡처 대상 화면이 표준을 만족하는지 먼저 검증**하고, 미달이면 **차단 + 조치 안내**한다.

- **정량 기준**: `페이지당_픽셀 = 화면폭(pt) × devicePixelRatio ÷ 페이지수`. 양면(스프레드) 표준 = **페이지당 ≥ `MIN_SOURCE_WIDTH`(1400px)** → **백킹 폭 ≥ 2800px**. (단면이면 백킹 ≥1400px.) 상수·수식은 `book-capture/bookcapture/capture_standard.py`(`MIN_SOURCE_WIDTH`, `required_window_width_pt`, `capture_preflight`)가 단일 진실원본.
- **동작(미달 시 = 차단)**: 분석 시작을 막고, `그래도 진행(저해상 감수)`으로만 우회. 조치 안내를 권장 순으로 제시:
  1. **단면(1페이지) 보기로 전환** — 백킹 폭 전체를 한 페이지가 쓰므로 대개 즉시 충족(단, 레이아웃이 한 장에 1페이지로 달라짐).
  2. **해상도 올리기** — 시스템 설정 > 디스플레이 > `모든 해상도 보기`에서 **백킹 폭 ≥2800px** 되는 더 높은 HiDPI 해상도 선택.
  3. **내장 Retina 디스플레이에서 캡처** — 양면 표준을 여유 있게 충족.
- **외장 모니터는 강제 아님**: 멀티태스킹하며 외장으로 캡처하는 것은 정당한 선택. 그래서 규칙은 "내장을 써라"가 아니라 **"권장 해상도를 제시하고 사용자가 직접 맞추게"** 안내한다(코드가 시스템 해상도를 자동 변경하지 않음).
- **패널 한계 주의**: 외장 패널의 최대 백킹이 2800px 미만이면(예: **1920×1200 패널 → 최대 HiDPI 백킹 2560px**) 그 모니터에선 **양면 표준이 물리적으로 불가** → 조치는 ①단면 전환 또는 ③내장 Retina로 수렴.
- **2단 방어**: (a) **웹 UI 게이트**(`index.html` `ensureCaptureResolutionOK()`) = 브라우저가 있는 모니터 기준 1차 경고·차단. (b) **워커 게이트**(권장) = 캡처 직전 `capture_preflight()`로 실제 캡처 모니터를 재검증해 미달 시 job 실패(웹은 브라우저 모니터만 알아 다중 모니터에선 부정확할 수 있으므로 워커가 최종 판정).
- **적용 범위**: 물리 화면 캡처 모드(`auto`=Mac, `capture-only`=Win)만. **`capture-browser`(Playwright 오프스크린 렌더)는 모니터 무관이라 게이트 제외.**

## 2. Raw 캡처 (전체창, 크롭 안 함 → 견고)
`scratchpad/capture_raws.py` 패턴:
- `screencapture -l<wid>` 로 앱 창 전체를 raw로 저장(크롭 로직 없음 → 캡처가 안 깨짐).
- **키보드만**(오른쪽 화살표 `key code 124`), 마우스 이동 안 함(screencapture는 커서 미포함).
- **매 키 입력 전 앱 재활성화**(`osascript ... activate`) — 포커스 유실로 멈추는 것 방지(안 하면 8장쯤서 멈춤).
- 표지로 복귀: 왼쪽 화살표 반복(앱은 anti-bot 없어 빠르게 OK), 해시 안 변하면 표지 도착.
- 끝 감지: 연속 2장 동일 해시 → 종료. 결과 raw_NNN.png (배포 페이지수와 1:1).

## 3. 크롭 = `bookcapture/page_crop.py` `crop_page()`
- **핵심 규칙**(빡빡하게 잘리던 문제 해결):
  1. 콘텐츠 감지 = 채도>18 또는 어두움<155 (흰·회색 배경 제외).
  2. 열/행 밀도 + 연속블록(union), 낮은 임계 → **세로로 짧은 코드블록 등도 안 잘림**.
  3. **여백 유지**: 스프레드는 가로6%·세로5% 여백 추가(책 본문 여백 복원). portrait(표지)는 1%(회색 방지).
- 배치: raw 폴더 → `crop_page(Image.open(raw))` → page_NNN.png + thumbs(폭 1800).

## 4. OCR
- **크롭 결과(page_NNN.png)에 OCR** 돌리면 가장자리 잘림·브라우저 크롬 오염 없이 깨끗.
- 오염 필터(`summarize.is_contaminated_ocr`)는 앱 캡처엔 불필요(콘솔/URL 안 섞임).

## 5. 배포 (root 소유 → sudo)
- 웹 이미지는 도커가 만든 **root 소유** → RedCode로 직접 못 덮어씀.
- RedCode 홈에 rsync 업로드 → `sudo cp` 로 `/volume1/web/kyobo/books/<책>/` 반영 + `chown root:root`·`chmod 644`.
- 접속 정보: `인증서/나스인증/` (비밀번호), 메모리 [[reference_nas_ssh_deploy]].
- **원본 raw 보관**: 책 폴더 `source_raws/` 에 raw 전량 저장(재크롭 대비).

## 6. 미리보기(summary/index.html) 표시
- 메인 카드: 이미지 열 1.35fr + `width:100%` (크게, 스트레치). 패딩 10px.
- 팝업(모달): **원본 풀해상도**(`../page_NNN.png`) 로드 — `openModal`이 `src.replace('/thumbs/','/')`.
- **캐시버스트**: 이미지 교체 시 thumb src에 `?v=N` 증가(브라우저 캐시로 옛 이미지 방지). 안 하면 강력새로고침 필요.

## 7. 챕터 그룹화 + 챕터 요약 (사이드바 트리)
전 페이지 OCR·요약이 있으면 **챕터 단위로 묶어** 사이드바를 접기/펴기 트리로 만들고, 각 챕터에 요약 카드를 넣는다.
- **챕터 경계·제목 감지**: 목차(차례) 페이지에서 챕터 목록 확보 + 각 페이지 running header의 "CHAPTER N"/제목 + AI요약의 "N장." 도입 문구로 시작 페이지 확정. (OCR 헤더는 노이즈 있으니 목차+요약 교차검증)
- **챕터 요약**: 각 챕터 페이지들의 `topics`/`points`(batch json)를 모아 "이 챕터에서 무엇을 다루나" 작성(별도 AI 호출 없이 기존 추출 내용 활용).
- **정의 파일** `summary/chapters.json`: `[{num,title,start,end,summary,topics}]`. (예: `scripts/chapters_클로드코드_예시.json`)
- **주입**: `python scripts/add_chapter_tree.py summary/index.html summary/chapters.json` → 접기/펴기 트리(챕터→페이지, 📖챕터요약 링크) + 챕터 요약 카드 삽입 + CSS/JS. 재실행 가능(멱등 아님 주의 — 원본에 1회).
- 배포는 `index.html`만 교체(sudo). 이미지 캐시버스트와 별개.

## 8. 표(表) 정리본 — 표 있는 페이지에 깔끔한 HTML 표 추가
이미지 안의 표는 스트레치·크롭으로 읽기 불편 → 해당 페이지 카드에 **재구성한 HTML 표**를 넣는다.
- **대상 판별**: OCR/AI요약에 "표 N-N"이 있는 페이지. 단 **그림(그림 N-N)은 표가 아님** → 스킵(예: 클로드코드 책 p117·135·203 은 다이어그램). 한 페이지에 표 여러 개면 모두 이어붙인다(예: p95=표5-1·5-2·5-3, p162=표8-4·8-5).
- **재구성**: 표 이미지를 육안으로 읽어 `(제목, 헤더[], 행[][])` 로 옮긴다. 등폭 식별자(명령어·필드명·경로)는 `<code>`, 단축키는 `<kbd>` 로 감싼다. OCR 자동추출은 표 구조가 깨지므로 **사람이 이미지 보고 작성**.
- **정의 파일** `summary/page_extras.json`: `{ "38": "<div class=\"section page-extra\">...</div>", ... }`. 각 값은 `.page-summary` 끝(핵심 내용 아래)에 삽입. (예: `scripts/page_extras_클로드코드_예시.json` — 19개 표 페이지)
- **주입**: `python scripts/add_page_extras.py summary/index.html summary/page_extras.json` → 표 카드 + CSS(.ptable/kbd) 삽입. CSS는 1회만(멱등). **이미 주입된 페이지는 json에서 빼서 중복 삽입 방지**(재실행 시 카드가 두 번 들어감).
- 배포는 `index.html`만 교체(sudo cp → chown root:root → chmod 644). 챕터 트리·이미지 캐시버스트와 별개.

## 검증 체크
- 컨택트시트(전 페이지 축소 grid)로 잘림/여백/차단화면 일괄 육안 확인.
- 배포 후 Playwright로 라이브 페이지 렌더 → 여백·정렬 확인.
- 표 정리본: 라이브 HTML `grep -o 'class="ptable"' | wc -l` 로 표 개수 확인 + Playwright로 표 페이지 렌더 육안 확인.
