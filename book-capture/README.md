# book-capture · Phase C-2

교보 e-book 캡처 → OCR → (Phase C-3: AI 요약) → HTML 빌드 파이프라인.

> Mac 로컬에서만 동작 (macOS Accessibility 권한 필요). NAS 컨테이너 안에서는 못 돈다.

## 빠른 시작 (Mac)

```bash
cd KyoboLibrary/book-capture

# 1) venv 생성 (한 번만)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2) tesseract 설치 (한 번만)
brew install tesseract tesseract-lang

# 3) 현재 설정 확인 (백엔드 /api/settings 로드)
python -m bookcapture settings

# 4) AI 키는 환경변수로 (Phase C-3 부터 사용)
export ANTHROPIC_API_KEY="sk-ant-..."

# 5) 캡처 → OCR → 임시 HTML 인덱스 일괄
python -m bookcapture run --slug "그림으로 이해하는 알고리즘"
```

## 구조

```
book-capture/
├── README.md
├── requirements.txt        httpx, Pillow, pytesseract
└── bookcapture/
    ├── __init__.py
    ├── __main__.py         python -m bookcapture 진입
    ├── cli.py              argparse 통합 CLI (settings/capture/ocr/build/run)
    ├── settings.py         /api/settings 호출 + 환경변수 우선
    ├── kyobo_app.py        ★ 기존 KyoboAppScreenshot (817줄, 그대로 이식)
    ├── ocr.py              tesseract 호출 + 썸네일 생성
    └── build_html.py       Phase C-2 placeholder 인덱스 (C-3에서 본격)
```

## 서브커맨드

| 명령 | 동작 |
|---|---|
| `settings` | `/api/settings` 현재 값 출력 + AI 키 환경변수 점검 |
| `capture --mode 3` | `kyobo_app.py` 인터랙티브 캡처 (1=전체화면 / 2=윈도우 / 3=연속) |
| `ocr --slug X` | `<books_dir>/X/` 안 *.png → `summary/ocr_text/page_NNN.txt` |
| `build --slug X` | C-2 placeholder 인덱스 HTML |
| `run --slug X --mode 3` | capture → ocr → build 일괄 |

## 출력 폴더

`settings.output.books_dir` 기준 (기본 `./books`).
```
<books_dir>/<slug>/
├── <slug>_001.png           ← kyobo_app 캡처 결과
├── <slug>_002.png
├── ...
├── thumbs/                  ← 1800px 리사이즈본 (Claude 호환)
└── summary/
    ├── ocr_text/page_NNN.txt
    └── index.html           ← C-2 placeholder, C-3 에서 본격 빌드
```

## Phase C-2 → C-3 전환 예정

- `summarize.py` 추가 — Claude/OpenAI API 호출, OCR 텍스트 → `batch_NNN.json`
- `merge.py` 추가 — `merge_batches.py` 이식
- `build_html.py` 본격 — `generate_html.py` 패턴 (사이드바·챕터 카드·scroll spy)
- `worker.py` — 백엔드 `/api/jobs` 큐 polling

## macOS 권한 (한 번만)

시스템 설정 → 개인정보 보호 및 보안 →
- **화면 및 시스템 오디오 녹화**: 사용 중인 터미널 앱 (iTerm/Terminal) 허용
- **접근성**: 터미널 앱 허용 (AppleScript 키 입력용)
