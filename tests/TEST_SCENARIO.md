# Kyobo Library — 테스트 시나리오

> 자동 테스트는 `tests/e2e_test.sh`, 수동(실기) 절차는 아래 체크리스트.

## A. 자동 테스트 (Mac/LAN 에서)

```bash
bash tests/e2e_test.sh          # 빠른 체크 (무료)
bash tests/e2e_test.sh --full   # 업로드→OCR→요약→빌드 e2e 포함 (AI ~$0.02)
```

검증 항목:
1. 엔드포인트 — 정적 8080, 백엔드 9000/health
2. 설치 자산 서빙 + 인코딩 — `install-worker.ps1`(BOM 없음), `install-worker.cmd`(CRLF), `update-worker.ps1`, `bookcapture.zip`, `worker-version.txt`
3. 워커 버전 일치 — 서버 `worker-version.txt` == zip 내 `_version.txt` (자동업데이트 정합성)
4. 워커 status 스키마 — alive/worker_version/server_version/up_to_date/app_title
5. nginx 캐시 헤더 — 책 HTML `no-cache`
6. reaper — 2h-stale running job → 자동 failed (좀비 회수)
7. (--full) 업로드 → 백엔드 OCR/요약/빌드 → 서빙 → analyzed → 정리

기대: `PASS=N  FAIL=0`.

## B. 수동(실기) 시나리오 — Windows 워커 (자동화 불가 영역)

### B-1. 워커 설치 (무설치 PC)
1. Windows PowerShell: `irm https://redcodeme.synology.me/kyobo/install/install-worker.ps1 | iex`
2. UAC [예]. 기대 로그: `[OK] worker downloaded` → Python/venv/Tesseract(한·영) → `worker restarted`
3. 검증: 웹 새로고침 → 책 모달 → 워커 박스 `✓ worker 살아있음 · v… ✓최신`

### B-2. 워커 keep-alive
1. 작업관리자에서 `python.exe`(worker) 강제 종료
2. 기대: 5분 내 작업 스케줄러가 자동 부활 → status alive=True 복귀
3. (서버에 새 버전 배포 시) 워커가 5분 내 코드 자동 갱신, **죽지 않음**

### B-3. 앱/책 검증 + 캡처
1. 교보 eLibrary 앱 실행 + 「HTTP 완벽 가이드」 펼침 + 최대화
2. 웹 책 모달 → 시작 페이지 입력 → [분석 시작]
3. 기대: 준비 팝업에 `✅ 「HTTP 완벽 가이드」 감지됨` (다른 책이면 ⚠️ 경고)
4. [준비 완료] → 5초 카운트다운 동안 Alt+Tab 으로 교보 앱 전환
5. 기대: 캡처 진행(상·하단 크롬 크롭) → 업로드 → 백엔드 처리 → 라이브러리 게시
6. 실패 검증: 앱 안 켜고 시작 → `교보 앱이 실행 중이 아닙니다` fail-fast / 다른 책 → `다른 책이 열려 있습니다` fail-fast

### B-4. 시작 페이지(이어서)
1. 앱에서 N페이지로 이동(우하단 `N / 757p` 확인) → 웹 시작 페이지 N 입력 → 분석 시작
2. 기대 로그: `▶ 이어서 캡처: page 0NN 부터` / 1 입력 시 `▶ 처음부터 캡처 (기존 N장 삭제)`

## C. 회귀 체크 (배포 후 매번)
- `bash tests/e2e_test.sh` PASS=전체
- 책 모달 OS 인식(Windows=로컬매크로 활성), 캐시 새로고침 자동 갱신
- 좀비 job 자동 failed (≤10분), 워커 죽어도 자동 부활(≤5분)
