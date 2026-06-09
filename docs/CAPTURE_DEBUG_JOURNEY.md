# 교보 캡처 디버깅 여정 — Mac에서 검증, Windows 이어가기

> 2026-06-09 · 아 **맥에서 이어서 윈도우로 왔구나** 하라고 남기는 기록.
> 한 겹씩 벗긴 문제와 해법, 그리고 Windows CLI로 같은 디버깅을 이어가는 법.

---

## 0. 한 줄 결론
교보 책은 **데스크탑 앱이 아니라 [바로보기] 웹뷰어(wviewer)** 를, **GDI가 아닌 최신 캡처(Mac=창ID / Win=dxcam)** 로, **사람처럼 천천히(랜덤 5~9초 + 휴식)** 찍으면 **전권 캡처된다.** 2026-06-09 Mac에서 366p 책 전권 캡처→업로드 성공.

---

## 1. 문제를 벗긴 순서 (각 층이 다음 층을 드러냄)

| # | 막힌 것 | 원인 | 해법 |
|---|---|---|---|
| 1 | iPad 자동 캡처 불가 | iOS 샌드박스(앱 자동제어·캡처 불가) | 화면녹화 영상 업로드 모드 추가(`video_frames.py`, `/upload-video`) |
| 2 | **Windows 데스크탑 교보 앱** 캡처=파란화면 | 앱이 화면캡처를 DRM 차단 ("정보 유출 방지…화면 캡처 기능을 사용할 수 없습니다") | 데스크탑 앱 포기 → **웹뷰어(wviewer) 사용** |
| 3 | 웹뷰어도 워커 캡처=파란화면 | **PIL ImageGrab = GDI BitBlt** 만 교보가 오염. Snipping Tool(WGC)은 통과 | **캡처 방식 교체**: Win=**dxcam(DXGI)**, Mac=**screencapture -l<창ID>** |
| 4 | →키로 페이지 안 넘어감(Win) | 화살표=**확장키**인데 `KEYEVENTF_EXTENDEDKEY`+scancode 없이 보냄 → 브라우저가 ArrowRight로 못 받음 | `win_app._press_key` 에 확장키 플래그+scancode 추가 |
| 5 | 36장에서 "정상적인 접근이 아니므로 이용을 중단합니다" | **교보 서버측 anti-bot** — 너무 빨리 넘김(1.7초/페이지) + 빠른 rewind | **사람처럼 천천히**: 랜덤 5~9초/페이지 + 12~18장마다 25~50초 휴식, rewind 제거 |

→ 5번 적용 후 **366p 책 전권(194장) 차단 없이 캡처 완료.**

## 2. 핵심 사실 (까먹지 말 것)
- 웹뷰어 = 브라우저 웹페이지라 **데스크탑 앱식 DRM 불가**. 단 교보가 **① GDI BitBlt 캡처 오염 ② 빠른 접근 anti-bot** 두 겹을 검.
- **GDI(ImageGrab)는 오염, 최신 캡처(WGC/DXGI/창ID)는 통과.**
- Mac `screencapture -l<windowID>` 는 **frontmost·Space 무관**하게 그 창만 찍어 제일 깔끔(전환 불필요).
- anti-bot은 **속도/규칙성**에 반응 → 느리고 불규칙하게 + 중간 휴식.

## 3. Mac 재현법 (검증됨)
스크립트: `book-capture/scripts/mac_wviewer_capture.py` (`/tmp/qz` venv = pyobjc-Quartz + Pillow)
1. Chrome에 교보 **[바로보기]** 열고 **1페이지**.
2. 창ID 찾기: `Quartz.CGWindowListCopyWindowInfo` 에서 owner='Google Chrome' 중 가장 큰 창.
3. 캡처: `screencapture -l<id> -x out.png` → 상단 7.5% 크롬 크롭.
4. 넘김: `osascript -e 'tell application "System Events" to key code 124'` (→ / 123=←).
5. 직전과 해시 동일 2회 = 끝. 랜덤 5~9초 + 휴식.
업로드: `POST https://redcodeme.synology.me:9443/api/books/<urlenc-slug>/upload` (multipart files[]) → upload-process job → OCR/요약/HTML.

## 4. Windows 이어가기 (CLI 디버깅)
**현 상태(배포됨, 버전 851be57+):**
- `capture-auto --no-app` = 데스크탑 앱 검증 스킵, 포그라운드(브라우저) 캡처.
- 캡처 백엔드 = **dxcam(DXGI)** 우선→ImageGrab 폴백 (`win_app._grab_frame`). dxcam은 `pip`(requirements) 필요 → **부트스트랩 재설치**로 설치.
- →키 = 확장키 수정 적용. `--next-key right` 기본.
- `no_crop`(브라우저 전체화면) 적용.

**CLI로 직접 디버깅:**
```powershell
# 1) 교보 [바로보기] 를 Edge/Chrome 전체화면(F11) 1페이지 + 책 클릭(포커스)
# 2) (책 폴더에서) 직접 실행해 로그 보기
cd "$env:LOCALAPPDATA\KyoboLibrary\book-capture"
python -m bookcapture capture-auto --slug "테스트슬러그" --no-app --next-key right --count 50 --interval 6
#   → dxcam 백엔드 뜨는지, 파란화면 아닌지, → 넘어가는지 확인
python -m bookcapture upload --slug "테스트슬러그"   # 캡처본 서버 업로드
```

**⚠️ 아직 안 한 것(Windows anti-bot 대응) — 다음 할 일:**
- `worker.py` 의 `capture-browser` 가 `--interval 2` **고정** → **anti-bot 위험**. Mac처럼 **느리게+랜덤+휴식** 필요.
  - `cli.cmd_capture_auto`/`win_app.take_multiple_screenshots` 에 **랜덤 interval + N장마다 휴식** 넣기 (Mac `mac_wviewer_capture.py` 의 페이싱 이식).
- Windows `--no-app` 캡처 영역: 브라우저를 **창ID로** 잡는 게 이상적(현재는 전체화면 dxcam). Win도 특정 창만 캡처하려면 WGC/창 핸들 방식 검토.
- Windows에서 dxcam이 실제로 파란화면을 뚫는지 **최종 확인 필요**(Mac은 확인됨, Win은 미확인 — 옛 ImageGrab 테스트만 파란화면 확인).

## 5. 관련 파일
- `book-capture/bookcapture/win_app.py` — `_grab_frame`(dxcam), `_press_key`(확장키), `take_multiple_screenshots`(no_crop)
- `book-capture/bookcapture/cli.py` — `--no-app`, `--next-key`
- `book-capture/bookcapture/worker.py` — `mode=capture-browser`
- `book-capture/scripts/mac_wviewer_capture.py` — **검증된 Mac 캡처(페이싱 포함)**
- `index.html` — "🌐 브라우저 웹뷰어 캡처" 라디오 + `showBrowserPrep`
- `kyobo-bridge/app/video_frames.py` — iPad 영상 모드
- 메모리: `reference_kyobo_drm_capture.md`
