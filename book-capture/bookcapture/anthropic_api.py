# -*- coding: utf-8 -*-
"""Anthropic(Claude) Messages API 상수·헬퍼 (단일 관리처).

summarize · extract_code · book_overview · contamination · chapters_detect 가 공유하던
API URL·버전·모델명·가격·재시도·이미지폭·타임아웃을 여기 한 곳에서만 관리한다.
값 조정(모델 교체·가격 변경·재시도 튜닝)은 이 파일만 고친다.
"""
from __future__ import annotations
import time
import urllib.request
import urllib.error


class AnthropicAPI:
    """Anthropic API 파라미터. 인스턴스 X — 클래스 상수로 참조. (2026-07-13 규칙화)"""
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    # ── 모델 ──
    DEFAULT_MODEL = "claude-sonnet-4-5"   # 요약·책개요 등 품질 필요 작업
    VISION_MODEL = "claude-haiku-4-5"     # 오염검사·챕터표지 감지 등 싼 시각 판정

    # ── 가격 ($/1M 토큰) = (input, output) ──
    PRICES = {
        "claude-sonnet-4-5":         (3.0, 15.0),
        "claude-sonnet-4-7":         (3.0, 15.0),
        "claude-haiku-4-5":          (1.0,  5.0),
        "claude-haiku-4-5-20251001": (1.0,  5.0),
        "claude-opus-4":             (15.0, 75.0),
        "claude-opus-4-7":           (15.0, 75.0),
    }
    DEFAULT_PRICE = (3.0, 15.0)           # 미등록 모델 폴백 단가

    # ── 재시도 (429/5xx exponential backoff) ──
    MAX_RETRIES = 4                       # 총 시도 횟수
    RETRY_STATUS = (429, 500, 502, 503, 504, 529)  # 504(게이트웨이)·529(과부하) 포함
    BACKOFF_BASE = 2                      # sleep = BACKOFF_BASE ** attempt (* factor)

    # ── 비전 입력 이미지 다운스케일 폭(px) ──
    VISION_MAX_W = 1100                   # 오염검사·챕터감지·개요(적당)
    CODE_MAX_W = 1500                     # 코드추출(작은 글자 정확도 위해 더 크게)

    # ── 타임아웃(초) ──
    TIMEOUT_TEXT = 180                    # 텍스트 생성(요약·개요)
    TIMEOUT_VISION = 90                   # 비전(코드·챕터)
    TIMEOUT_QUICK = 60                    # 짧은 비전(오염검사)

    HEADERS_CT = "application/json"

    @classmethod
    def price(cls, model):
        """모델 단가 (input,output) $/1M. 미등록이면 DEFAULT_PRICE."""
        return cls.PRICES.get(model, cls.DEFAULT_PRICE)

    @classmethod
    def headers(cls, api_key):
        return {"x-api-key": api_key, "anthropic-version": cls.API_VERSION,
                "content-type": cls.HEADERS_CT}

    @classmethod
    def is_retryable(cls, status_code):
        return status_code in cls.RETRY_STATUS
