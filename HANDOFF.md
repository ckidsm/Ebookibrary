# 교보 라이브러리 — 인계 / 이어가기 문서

> 마지막 갱신: **2026-06-11**. 다른 PC/Mac에서 이 repo(OneDrive·git)를 받아 이어갈 때 **이 문서부터** 읽으세요.

---

## 1. 한눈에 — 현재 동작 중인 것
- **포털**: https://redcodeme.synology.me/kyobo/ (NAS nginx + `/volume1/web/kyobo/`, docker 사본 `/volume1/docker/web-apps/kyobo-library/`)
- **백엔드**: `kyobo-bridge` 컨테이너 (FastAPI, 9000/외부 9443). 이미지 빌드 완료(최신 코드 영구).
- **OCR 코퍼스 DB**: `/data/ocr_corpus/ocr_corpus.db` (마운트, 백업 backups/). 2권·786페이지.
- **워커**: Windows(yundeoksoo), Mac, **Ubuntu 노트북(192.168.0.66, ckidsm)** 모두 동작. systemd/launchd/task로 자동시작.
- **분석 완료 책**: 밑바닥부터…LLM(400p), 비디오 코덱…(2020)(386p 단일페이지·Haiku).

## 2. 이번 세션(2026-06) 완료 항목
- **OCR 코퍼스 DB**: book_master(종류·분야·출판일·개정일·소개 = AI 추출) + book_pages, save시 타임스탬프 백업.
- **분석 모달 강화**: 이미지 확대/축소·드래그·OCR텍스트 보기+복사·페이지별 메모(localStorage).
- **AI 교정 전문(full_text)**: 요약 시 OCR 오타 교정본도 ocr_text에 저장(tesseract 오타 해결).
- **진행 현행화**: 요약 페이지별 잡 진행 갱신(웹 진행바 실시간) + 카드/모달에 "현재 p.N·남은 M장".
- **다시분석 UX**: [분석페이지] 버튼 우선, 다시분석 경고 + 라디오(재처리=기존이미지 재요약 / 재캡처). `/api/books/{slug}/reprocess`.
- **분석 히스토리**: `summary/analysis_meta.json`(날짜·비용·토큰·모델) → 모달 표시.
- **워커 자동재시작**: 무한루프 래퍼(Win `run-worker-loop.ps1`) — 죽어도 5초 내 부활 + 로그.
- **원클릭 부트스트랩**: `setup-windows.ps1`·`setup-mac.sh`·`setup-linux.sh` (서버에서 최신 `book-capture.zip` 받아 설치). 트러블슈팅 페이지 탭(Win/Mac/Ubuntu).
- **Linux/Ubuntu 워커**: `linux_app.py`(scrot+xdotool, X11), cli capture-auto Linux 분기. 포털도 Linux 브라우저캡처 활성.
- **교보 뷰어/로그인 감지**: 캡처 전 교보창 감지, 준비팝업 로그인 링크+로그인 ✓체크(유저스크립트 v0.8.0 보고).

## 3. ⚠️ 인프라 핵심 (이어갈 때 반드시 알 것)
1. **배포 방법**:
   - 프론트(`index.html`·`troubleshoot.html`·`userscript`·`setup-*.sh`·`book-capture.zip`): `scp` → `/volume1/web/kyobo/` + `/volume1/docker/web-apps/kyobo-library/`. 재시작 불필요.
   - 백엔드(`kyobo-bridge/app/*`): 변경 시 **docker 이미지 재빌드** 필요(영구). 빠른 반영은 `docker cp` + `docker restart` 지만 컨테이너 재생성 시 사라짐. 재빌드 절차는 메모리 [[reference_kyobo_bridge_rebuild]] 참고 (tar→NAS→`docker build`→`docker-compose`(v1)).
2. **워커 코드 갱신**: 워커는 각 PC의 로컬 복사본(예: Windows=`LOCALAPPDATA\KyoboLibrary\book-capture`)에서 돈다 — OneDrive 동기화로 안 닿음! **`book-capture.zip`을 서버에 재배포**한 뒤 각 PC에서 부트스트랩 재실행해야 워커가 최신이 됨. (worker가 capture-auto를 매번 새 subprocess로 실행하므로, zip만 갱신되면 재설치 시 반영)
   - zip 재생성: repo 루트에서 `zip -rq /tmp/book-capture.zip book-capture -x 'book-capture/.venv/*' -x 'book-capture/books/*' ...` → `scp` to `/volume1/web/kyobo/`.
3. **SSH**: NAS = `RedCode@192.168.10.205`(키인증). Ubuntu 노트북 = `ckidsm@192.168.0.66`(pw REDACTED-see-cert-file, sshpass).
4. **여러 워커 주의**: 잡은 first-come claim. 캡처할 PC만 워커 켜고 나머지는 끌 것.

## 4. 남은 고도화 (PENDING — 차후)
- [ ] **재처리 "더 자세히" 옵션**: 현재 재처리는 동일 프롬프트 재요약. "보강/상세" 프롬프트 변형 추가 여지.
- [ ] **워커 타겟팅**: 특정 워커(예: Ubuntu)만 잡을 잡게 (현재 first-come).
- [ ] **진행바 단계 가중치**: OCR/요약/빌드 단계 % 비중 정교화(현재 4단계 균등).
- [ ] **다른 책 분석**: 이미지 처리 바이블 등.
- [ ] (선택) Blazor/MAUI 재구축 — [[project_myweb_git_blazor]] 참고(차후).

## 5. 다른 PC/Mac 에서 이어가기
1. 이 repo(`OneDrive/Claude/NAS/KyoboLibrary`)를 그 기기에서 받기(OneDrive 동기화 or `git clone Redocde/redcodeme-nas-portal`… 실제 origin 확인).
2. **이 HANDOFF.md + `CLAUDE.md` + `docs/CAPTURE_DEBUG_JOURNEY.md`** 읽기.
3. NAS SSH 키가 없으면 등록(메모리 [[reference_nas_ssh_deploy]]).
4. 워커 쓰려면 그 기기에 부트스트랩 실행(트러블슈팅 페이지 OS탭).
> 주의: Claude 메모리(`~/.claude/.../memory/`)는 **기기 로컬**이라 안 따라옴. repo 안의 이 문서들이 인계의 핵심.
