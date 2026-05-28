# Kyobo Bridge

NAS 9000 포트에서 도는 FastAPI 백엔드. 교보문고 e-Library 연동·동기화·검색 담당.

> 상위 프로젝트: `../CLAUDE.md` (Kyobo Library 전체 컨벤션).
> 같은 NAS의 자매: `../../NasVideoTrimmer/` (Blazor 영상 편집기).

## 1. 책임 (Phase B-1)
- `/health` — 헬스체크
- `/api/library/books` — 동기화된 도서 카탈로그 조회 (SQLite)
- `/api/auth/kyobo/login` — **501** (Phase B-2에서 구현 — 교보 로그인 프록시)
- `/api/library/sync` — **501** (Phase B-2 — 교보 e-Library 도서 메타 가져와 SQLite 저장)

## 2. 폴더
```
kyobo-bridge/
├── Dockerfile           multistage 없이 단일 stage (FastAPI는 base가 가벼움)
├── requirements.txt     fastapi, uvicorn[standard], httpx
└── app/
    ├── __init__.py      __version__
    ├── main.py          FastAPI app, lifespan, CORS, 라우트
    └── db.py            SQLite 연결·스키마 (books 테이블)
```

## 3. 데이터
- `/data/library.db` (SQLite, WAL 모드)
- 컨테이너 외부 마운트: `/volume1/docker/web-apps/kyobo-bridge/data` → `/data`

## 4. 로컬 실행 (Mac)
```bash
cd kyobo-bridge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
KYOBO_BRIDGE_DB=./local.db uvicorn app.main:app --reload --port 9000
# http://localhost:9000/health
```

## 5. NAS 배포
상위 `../deploy.sh` 가 일괄 처리:
1. 정적 라이브러리 rsync (8080)
2. 이 이미지 buildx amd64 + save + scp + load
3. compose up (8080·9000 둘 다)
