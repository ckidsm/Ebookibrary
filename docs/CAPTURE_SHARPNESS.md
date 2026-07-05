# 캡처 이미지 선명도 — 원인·재캡처 체크리스트

> 계기: 2026-07-05 "클로드 코드로 시작하는 실전 에이전틱 코딩" #page-15 캡처가 흐림.

## 진단 결과

| 페이지 | 해상도 | 형태 |
|---|---|---|
| page_001 (표지) | 646×850 | 세로 단면 ✅ 정상 |
| page_002 ~ 246 (전권) | ~1000×700 (가로) | ❌ **양면 펼침(2p)을 한 장에 통째 캡처** |

- page_015 = 목차 xxvii·xxviii **두 페이지가 나란히** 1008×687 한 장에 들어감 → 실질 **페이지당 폭 ~500px** → 확대 시 글자 뭉개짐.
- thumbs(131KB) ≈ 원본(133KB): 썸네일이 키운 게 아니라 **소스 캡처 자체가 저해상**이라 리사이즈 여지 없음.

### 근본 원인
1. 교보 웹뷰어가 데스크톱에서 **"두 페이지 펼침(스프레드)" 보기** 상태로 캡처됨 → 페이지당 픽셀 절반.
2. 뷰어/창이 작게 렌더 → 전체 픽셀 자체도 부족.

> ⚠️ 이미 저장된 저해상 PNG는 **화질 복구 불가**(없는 픽셀은 못 만듦). **재캡처만이 해법.**

## 재캡처 체크리스트 (선명하게 다시 찍기)

1. **웹뷰어를 "한 페이지 보기(single page)"로 전환** ← 최우선. 한 페이지가 화면 폭을 꽉 채워야 함.
2. **Chrome 전체화면 최대화** + 뷰어 줌 "페이지 맞춤/확대"로 본문이 창을 꽉 채우게.
3. **내장 Retina 디스플레이에서** 캡처(외장 비-Retina 모니터면 실픽셀 절반).

## 경로별 코드 개선 지점 (재캡처 확정 시)

- **Playwright 경로** (`book-capture/bookcapture/wviewer.py`):
  - `browser.new_context(...)` / `_new_context()`에 `device_scale_factor=2`(또는 3) 추가 → 같은 렌더를 2배 픽셀로 스크린샷(현재 미설정=1배). `capture_book`·`capture_via_library` 둘 다.
  - 뷰어 진입 후 단면 레이아웃 토글 클릭 자동화 검토.
- **Mac 화면캡처 경로** (`book-capture/scripts/mac_wviewer_capture.py`):
  - `screencapture -l<wid>`는 **화면 실픽셀 의존** → 코드보다 뷰어 설정(단면+최대화+Retina)이 관건.
- **Windows 워커** (`book-capture/bookcapture/win_app.py`):
  - dxcam 캡처 영역/해상도 + `_content_crop` 확인. 마찬가지로 뷰어 단면 설정이 선행.

## 검증 방법
재캡처 후 `page_015.png` 같은 본문 페이지가 **세로 단면 + 폭 ≥ 1000px**(이상적으로 Retina 2배)면 정상.
```bash
python3 -c "from PIL import Image; im=Image.open('page_015.png'); print(im.size)"
# (W, H) 에서 H > W (세로) 이고 W 가 충분히 크면 OK
```

---

# 통일 캡처 파이프라인 (하이브리드) — 기기·OS·모니터 무관 균일·선명

> 목표: 어느 PC/OS/모니터에서 찍어도 **깨지지 않고·선명하고·균일한** 이미지. (2026-07-05 채택: 하이브리드)

## 엔진: Playwright 기본 + 물리 캡처 폴백
| 순위 | 엔진 | 특성 |
|---|---|---|
| **기본** | Playwright `page.screenshot()` (`wviewer.py`) | 오프스크린 렌더 → **모니터 무관 고정 픽셀**. 표준 viewport+DSF 내장 |
| **폴백** | 물리 캡처 (mac `screencapture`·win `dxcam`·linux `scrot`) | 내 로그인 세션 그대로(anti-bot 안전). preflight 게이트로 미달 거부 |

→ Playwright가 anti-bot/duplicateUse로 막힐 때만 물리 캡처로 폴백. 둘 다 **아래 공통 tail**로 수렴.

## 공통 tail (모든 경로 저장 직전)
```
raw → content_crop(물리경로만) → validate/preflight(미달 거부) → safe_normalize(폭 1600px) → save
```
- `safe_normalize()`는 어떤 예외에도 원본 반환 → **캡처 파이프라인 절대 안 깨짐**.
- 결과: 2x·1x·세로 어디서 왔든 **최종 저장물은 폭 1600px 동일**(균일). 미달분은 게이트에서 탈락(선명 보장).

## 라이브 증명 (2026-07-05, 이 Mac)
```
Playwright 표준 컨텍스트 {viewport 960×1440, device_scale_factor 2}
 → 원시 스크린샷 1920×2880  (모니터 종류와 무관, 오프스크린)
 → safe_normalize → 1600×2400 (폭 1600 고정)
```
→ **노트북/외장 QHD/4K 어느 모니터에서 실행해도 1920×2880 동일.** 물리 화면을 안 거치므로 scale(1x/2x) 편차가 원천 소멸.

## 배선된 파일
- `wviewer.py` — 두 컨텍스트에 `playwright_context_kwargs()` + 스크린샷마다 `_finalize_shot()`(정규화)
- `win_app.py`·`linux_app.py` — 저장 직전 `_std_normalize()` (⚠️ Windows/Ubuntu 실기 미검증, 문법만 확인)
- `scripts/mac_wviewer_capture.py` — preflight 게이트 + 저장 직전 `safe_normalize`

---

# 표준 해상도 규격 — KyoboCaptureStandard v1 (OS·모니터 무관 정량화)

> 기기(Mac/Win/Ubuntu)·모니터(4K/FHD/Retina)가 제각각이어도 **동일 픽셀**을 보장하기 위한 규칙.
> 코드 정의: `book-capture/bookcapture/capture_standard.py` (상수 + `validate_page()` + `normalize_page()`).

## 모니터 편차를 없애는 원리
| 캡처 방식 | 출력 해상도 결정 요인 | 모니터 영향 |
|---|---|---|
| `screencapture -l`(Mac)·dxcam(Win)·scrot(Ubuntu) | **물리 화면 픽셀** | ❌ 모니터·DPI·창크기마다 다름 |
| **Playwright `page.screenshot()`** | **viewport CSS × device_scale_factor** | ✅ **없음** (오프스크린 렌더) |

→ **규칙 0: 해상도가 중요한 캡처는 물리 화면 캡처를 버리고 `page.screenshot()`로 통일.**
그러면 어느 OS·어느 모니터든 출력 픽셀이 동일. 모니터는 "워커가 도는 위치"만 결정, 결과엔 무관.

## 정량 스펙
| 항목 | 값 | 근거 |
|---|---|---|
| 레이아웃 | **단면(1페이지)** | 스프레드는 페이지당 픽셀 절반 → 금지 |
| 방향 | 세로 (H > W) | 책 본문 |
| 캡처 API | Playwright `page.screenshot()` | 모니터 무관 |
| viewport (CSS) | **960 × 1440** (2:3) | 단면 세로 |
| device_scale_factor | **2** | 픽셀 2배 |
| 원시 스크린샷 | **1920 × 2880 px** | 960×2, 1440×2 |
| 정규 목표 본문 폭 | **1600 px** (±10%) | 국판 152mm ≈ **268 DPI** (OCR 300DPI 근접) |
| 최소 허용 폭(게이트) | **1400 px** | 미만이면 저해상 → 재캡처 |
| 포맷 | PNG / RGB | 무손실 |

**DPI 계산**: 국판 책 폭 152mm=5.98in. 1600px/5.98in ≈ **268 DPI**, 2000px ≈ 334 DPI. tesseract 권장 300 DPI 부근이라 OCR·열람 모두 양호.

## 강제(enforcement) 방법
1. **Playwright 경로**(`wviewer.py`): `browser.new_context(**capture_standard.playwright_context_kwargs())` 로 viewport+DSF 주입. → 모니터 무관 1920×2880 스크린샷.
2. **물리 화면 캡처 경로**(anti-bot 등으로 불가피할 때만): 창을 규격대로 강제한 뒤 반드시 `validate_page()` 게이트 통과. 미달이면 저해상 경고·재캡처.
3. **모든 경로 공통**: 크롭 후 `normalize_page()` 로 폭 1600px 리샘플 → 책·OS 무관 동일 폭. `validate_page()` 로 스프레드/저해상 자동 검출.

> ⚠️ `normalize_page()`의 업스케일은 없는 픽셀을 못 만든다 — **MIN_SOURCE_WIDTH 게이트를 먼저 통과**해야 실질 선명. 정규화는 "표시 일관성"만 보장.

---

## 실측 — 모니터 3종 캡처 테스트 (2026-07-05, Mac)

같은 Chrome wviewer 창(1728pt, "클로드 코드" 책)을 모니터만 바꿔 `screencapture -l` 실측:

| 모니터 | scale | 원시 캡처 | 크롭 본문 | 페이지당 폭(스프레드) | 판정 |
|---|---|---|---|---|---|
| 내장 Liquid Retina XDR | **2x** | 3592×2304 | 3530×2050 | **1765px** | ✅ 선명 |
| LG ULTRAGEAR (2560×1440) | **1x** | 1840×1196 | 1810×997 | **905px** | ❌ 저해상 |
| LG HDR 4K (2880×5120, 세로) | 2x | — | — | (계산) 1440px | ✅ |

→ **같은 창인데 1x 모니터에선 픽셀이 정확히 절반.** 물리 화면 캡처 픽셀 = `창_폭(pt) × 디스플레이_scale`.
기존 배포본 1008px(페이지당 ~500px)은 더 작은 창/1x 조합의 결과.

### 정량 공식 (물리 화면 캡처 경로)
```
페이지당_픽셀 = 창_폭(pt) × 디스플레이_scale ÷ 스프레드_페이지수
표준 충족 최소 창폭(pt) = ceil(1400 × 스프레드_페이지수 ÷ scale)
```
(코드: `capture_standard.expected_page_px()`, `required_window_width_pt()`)

### 모니터별 표준 충족 여부 (목표 페이지당 ≥1400px)
| 모니터 | 최대 창폭 | **스프레드** 페이지당 | **단면** 페이지당 |
|---|---|---|---|
| 내장 Retina 2x | 1728pt | 1728px ✅ | 3456px ✅ |
| LG ULTRAGEAR 1x | 2560pt | 1280px ❌ | 2560px ✅ |
| LG HDR 4K 2x(세로) | 1440pt | 1440px ✅ | 2880px ✅ |

→ **결론: 단면(single-page)으로 찍으면 3개 모니터 전부 표준 충족. 스프레드는 1x 모니터에서 실패.**
그래서 규칙: **① 단면 강제(스프레드 금지) ② 이 모니터 scale에서 `required_window_width_pt`만큼 창폭 확보 ③ Playwright 경로면 모니터 자체가 무관.**
세로 모니터(LG HDR 4K)는 뷰어가 자연히 단면 레이아웃이 되고 폭도 2880px라 **단면 캡처 최적**.

## 규칙 — 캡처 전 "최대화" 검증 게이트 (필수)

물리 화면 캡처 해상도는 **창 크기 × 모니터 scale**이라, 창을 **최대화하지 않으면 픽셀이 그만큼 손해**.
그래서 캡처 직전 **최대화 여부를 반드시 검증**한다. (코드: `capture_standard.is_maximized()` / `capture_preflight()`)

- **최대화 판정**: 창이 디스플레이 point 크기의 **폭 ≥95% · 높이 ≥90%**를 덮으면 최대화로 간주.
- **게이트 규칙**: `capture_preflight().ok == (최대화 AND 예상 페이지당 ≥ 1400px)`.
  - 미충족이면 **캡처 중단** + 조치 안내. 강제하려면 `KYOBO_ALLOW_SUBSTANDARD=1`.
- **라이브 점검 도구**: `<venv>/bin/python scripts/mac_capture_preflight.py [창제목]`
  — 모니터·scale·최대화·스프레드·예상 해상도를 한눈에. (종료코드 0=OK, 1=미충족, 2=창없음)
- **캡처 경로 배선**: `scripts/mac_wviewer_capture.py`가 캡처 루프 진입 전 `_preflight_gate()`로 자동 검사.

### 실측 검증 (2026-07-05, LG ULTRAGEAR 1x에서 최대화 상태)
```
모니터: 외장 2560x1440pt scale=1x · 창 2560x1410pt
레이아웃: 스프레드(양면 2p) · 최대화 ✅ 예 (폭 100% · 높이 98%)
예상 페이지당: 1280px → 표준(≥1400px) ❌ 미충족
   • 스프레드 감지 — 단면 전환 권장(페이지당 픽셀 2배)
   • 1x·2p면 창폭 ≥2800pt 필요 → 이 모니터 폭으론 부족, 단면 전환 또는 2x 모니터
```
→ **최대화됐어도(폭 100%) 1x·스프레드면 1280px로 미달**. 게이트가 정확히 중단시키고 "단면 전환"을 지시함. 단면으로 바꾸면 같은 창에서 2560px ✅.

## 규칙 — 뷰어 줌(보기 비율)은 "페이지가 캡처 폭을 채우는가"로 판정

교보 뷰어 툴바의 줌%(예 **59%**)가 낮으면 페이지가 작게 렌더돼 캡처 픽셀 손해. 하지만 **줌% 자체가 지표가 아니다** — 중요한 건 *페이지가 캡처 영역 폭을 꽉 채우는가*.

- **줌효율 = 실측_페이지당_픽셀 ÷ 이론최대(창폭×scale÷페이지수)**. `< 85%`면 "줌/맞춤 낮음"으로 플래그.
- **판정은 창폭(이론)이 아니라 실측 크롭 폭으로** — 실측이 줌·여백을 자동 반영해 정확. (`capture_preflight(measured_page_px=...)`)
- **acceptance는 결국 하나**: `실측_페이지당_픽셀 ≥ 1400`. 최대화·단면·줌효율은 *어느 손잡이를 돌릴지* 알려주는 진단일 뿐.

### 라이브 (2026-07-05, 뷰어 줌 59%·스프레드·1x 최대화)
```
페이지당 픽셀: 실측 1294px / 이론최대 1280px (줌효율 101%) → 표준(≥1400px) ❌ 미충족
   • 스프레드 감지 — 단면 전환 권장
   • 1294px < 1400px. 1x·2p면 창폭 ≥2800pt 필요 → 단면 전환 또는 2x 모니터
```
→ **줌효율 101%**: 59%는 스프레드의 fit-width라 이미 폭을 채움(줌 더 올리면 페이지가 창보다 커져 잘림). **줌은 정상, 병목은 1x+스프레드.** 단면 전환 시 fit-width가 ~100%로 올라 한 페이지가 2560px를 채움.

## 세 변수 요약 — 실측 페이지당 픽셀이 이 전부를 통합
| 변수 | 손잡이 | 진단 지표 |
|---|---|---|
| 레이아웃 | 단면(1p) vs 스프레드(2p) | 크롭 종횡비(가로=2p) |
| 창 크기 | 최대화 | coverage 폭≥95%·높이≥90% |
| 뷰어 줌 | fit-width로 폭 채움 | 줌효율 ≥85% |
| (모니터 scale) | 2x 우선 | scale 1x/2x |
| **최종 판정** | — | **실측 페이지당 픽셀 ≥ 1400** |
