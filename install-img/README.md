# install-img · 설치 가이드 캡처 자리

이 폴더에 5장의 PNG 캡처를 넣으면 `install.html` 의 placeholder 자리에 자동으로 표시된다.

## 필요한 캡처 (파일명 정확히)

| 파일명 | 화면 | 표시할 번호 박스 |
|---|---|---|
| `01-tampermonkey-net.png` | tampermonkey.net 홈에서 본인 브라우저 아이콘(Chrome 등) 위에 화살표 | 본인이 누를 곳 위에 ① |
| `02-dev-mode.png` | `chrome://extensions/` 우상단 [개발자 모드] 토글 부근 | 토글 위에 ① |
| `03-userscript-install.png` | Tampermonkey 자동 인식 → 좌상단 [설치] 버튼 보이는 화면 | [설치] 버튼 위에 ① |
| `04-permission-ask.png` | `chrome-extension://...ask.html?aid=...` 권한 요청 화면 | [허용]/[항상 허용] 위에 ① |
| `05-sync-panel.png` | 교보 e-Library 페이지 우측 하단 다크 동기화 패널 | 패널 안 [동기화] 버튼 위에 ① |

## 캡처 팁
- macOS: `⌘⇧4` → 영역 선택 → 자동으로 Desktop에 저장
- 번호 박스는 미리보기(Preview) 앱의 마크업 도구로 직접 그려 넣거나, 그대로 보내도 됨
- 가능한 한 해상도 1200~1600px 사이 권장 (너무 크면 파일 무거움, 너무 작으면 흐림)

## 추가
캡처가 도착하면 `install.html` 의 `.shot-placeholder` 자리에 `<img src="install-img/0X-...png">` 로 교체.
