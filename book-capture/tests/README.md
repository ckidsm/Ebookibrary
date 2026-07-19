# bookcapture 테스트 스위트

이미 캡처·분석·발행된 도서를 기준으로 파이프라인 함수·발행본을 자동 검증한다.
**재캡처·API 호출·발행본 수정 없음(읽기전용).**

## 실행

```bash
cd book-capture
.venv/bin/pytest tests/ -v            # 전체(네트워크 포함)
.venv/bin/pytest tests/test_merge.py  # 개별
KYOBO_SKIP_NET=1 .venv/bin/pytest tests/   # 오프라인(발행 검증 스킵)
```

## 파일

| 파일 | 대상 | 성격 |
|---|---|---|
| `conftest.py` | 공용 상수(4권 슬러그·발행 URL)·`fetch` 픽스처 | — |
| `test_merge.py` | `merge.py` — chapter_id·챕터트리·batch 머지(정렬/중복) | 순수·tmp |
| `test_chapters_detect.py` | `chapters_detect.py` — 정규화·목차판정·가짜장제거·목차탐지 | 순수·tmp |
| `test_build_html.py` | `build_html.py` — 페이지카드·사이드바·개요 + **실제 3권 라운드트립** | 순수·tmp |
| `test_published.py` | 발행 4권 — HTTP 200·뷰어 마커·개요·자원·완전성 | 네트워크 |
| `test_postcapture.py`·`test_capture_standard.py` | 캡처 QC·해상도(기존) | 합성 |

`test_build_html` 의 라운드트립은 실제 `pages_data.json`+`book_overview.json` 을 **tmp 로만** 재빌드해
페이지 카드 수·개요 주입을 검증한다(발행본 index.html 무손상).

## 검증이 잡은 발행 불일치 (2026-07-19)

`test_published` 가 잡은 재발행 대상 2건:

- ✅ **밑바닥 LLM** — 코드모달 UI 는 있으나 `code_blocks.json` 미발행(404, 코드패널 로드 실패)였음.
  → **2026-07-19 `bookcapture code`(118p·307블록·$1.21) + `publish_book.sh` 재발행으로 해소.**
  strict 검증(`test_published_code_blocks_consistency`)으로 승격됨.
- ⏳ **클로드코드** — 레거시 발행본. 📋책개요는 있으나 **챕터별 상세요약·코드모달 없음**.
  로컬 산출물이 없어(재캡처/복원 필요) 미해소 → `xfail` 로 문서화(`_LEGACY_NO_DIGESTS`).

미해소 건이 재발행되면 `test_published.py` 상단 `_LEGACY_NO_DIGESTS` 집합에서 슬러그를 빼
strict 검증으로 승격한다.
