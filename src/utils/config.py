#!/usr/bin/env python3
"""입찰메이트 v17 - 환경 설정 및 상수."""

from __future__ import annotations

import os
from pathlib import Path

# ============================================================================
# 환경 변수
# ============================================================================

# OpenAI
OPENAI_API_KEY: str | None = os.environ.get("OPENAI_API_KEY")
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
DEFAULT_MODEL: str = os.environ.get("DEFAULT_MODEL", "gpt-4o-mini")
REASONING_MODEL: str = os.environ.get("REASONING_MODEL", "gpt-5-mini")

# LangSmith (트레이싱 및 모니터링)
LANGSMITH_API_KEY: str | None = os.environ.get("LANGSMITH_API_KEY")
LANGSMITH_TRACING: bool = os.environ.get("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_ENDPOINT: str = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com/")
LANGSMITH_PROJECT: str = os.environ.get("LANGSMITH_PROJECT", "biddingmate_jh")

# Langfuse (대안 트레이싱)
LANGFUSE_PUBLIC_KEY: str | None = os.environ.get("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY: str | None = os.environ.get("LANGFUSE_SECRET_KEY")
LANGFUSE_BASE_URL: str = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

# HuggingFace
HF_TOKEN: str | None = os.environ.get("HF_TOKEN")

# ============================================================================
# 매직 넘버
# ============================================================================

MAX_TEXT_LENGTH: int = 5000
MIN_SECTION_LENGTH: int = 50
MAX_PAGES: int = 20
DEFAULT_TOP_K: int = 10
DEFAULT_TOP_N: int = 5
CHUNK_HASH_MOD: int = 1_000_000
AMOUNT_UNITS: dict[str, int] = {"억": 100_000_000, "만": 10_000}

# ============================================================================
# 한국어 설정
# ============================================================================

JOSA_LIST: list[str] = ['의', '은', '는', '이', '가', '께서', '에서', '에게']

# ============================================================================
# 기관명 설정
# ============================================================================

ORG_ALIASES: dict[str, str] = {
    "서울시": "서울특별시",
    "고려대": "고려대학교",
    "서울시립대": "서울시립대학교",
}

# ============================================================================
# 질문 유형별 키워드
# ============================================================================

RANKING_KEYWORDS: list[str] = ["가장", "최고", "최소", "최대", "제일", "top", "ranking", "순위"]
MAX_RANKING_KEYWORDS: list[str] = ["많은", "높은", "큰"]
MIN_RANKING_KEYWORDS: list[str] = ["적은", "낮은", "작은"]

# ============================================================================
# 경로 설정
# ============================================================================

def get_data_dir() -> Path:
    """데이터 디렉토리 경로를 반환합니다."""
    script_dir = Path(__file__).parent.parent.parent.resolve()
    return (script_dir / "data").resolve()

def get_default_db_path() -> str:
    """기본 DB 경로를 반환합니다."""
    return str(get_data_dir() / "chroma_db_v17")
