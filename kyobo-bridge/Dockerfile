# syntax=docker/dockerfile:1.6
# ─────────────────────────────────────────────────────────────
# Kyobo Bridge · FastAPI 백엔드
# 대상 아키텍처: linux/amd64 (Synology RS923+ Intel)
# ─────────────────────────────────────────────────────────────

FROM python:3.12-slim

WORKDIR /app

# 시스템 패키지: curl(헬스체크) + tesseract(업로드 OCR) + ffmpeg(화면녹화 영상→프레임)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl ca-certificates \
      tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng \
      ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 (캐시)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스
COPY app/ ./app/

# SQLite 데이터 디렉토리 (compose 볼륨으로 마운트되지만 default도 만들어둠)
RUN mkdir -p /data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    KYOBO_BRIDGE_DB=/data/library.db

EXPOSE 8000

# 헬스체크 (compose도 가능하지만 이미지 자체에도 명시)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
