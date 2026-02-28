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
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask")
CHROMA_COLLECTION: str = os.environ.get("CHROMA_COLLECTION", "chunks")
DEFAULT_MODEL: str = os.environ.get("DEFAULT_MODEL", "gpt-5-mini")
REASONING_MODEL: str = os.environ.get("REASONING_MODEL", "gpt-5-mini")
QUERY_INTENT_MODEL: str = os.environ.get("QUERY_INTENT_MODEL", "gpt-5-nano")

# 임베딩 설정
class EmbeddingConfig:
    """임베딩 설정."""
    model: str = EMBEDDING_MODEL
    dimension: int = 1536 if EMBEDDING_MODEL.startswith("text-embedding-") else 768
    fallback_model: str = "distiluse-base-multilingual-cased-v2"

embedding_config = EmbeddingConfig()

# LangSmith (트레이싱 및 모니터링)
LANGSMITH_API_KEY: str | None = os.environ.get("LANGSMITH_API_KEY")
LANGSMITH_TRACING: bool = os.environ.get("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_ENDPOINT: str = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com/")
LANGSMITH_PROJECT: str = os.environ.get("LANGSMITH_PROJECT", "biddingmate_ai7")

# Langfuse (대안 트레이싱)
LANGFUSE_PUBLIC_KEY: str | None = os.environ.get("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY: str | None = os.environ.get("LANGFUSE_SECRET_KEY")
LANGFUSE_BASE_URL: str = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

# HuggingFace
HF_TOKEN: str | None = os.environ.get("HF_TOKEN")


def _get_env_int(name: str, default: int, *, min_value: int = 1) -> int:
    """정수 환경 변수를 안전하게 파싱합니다."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, value)


def _get_env_float(name: str, default: float, *, min_value: float = 0.1) -> float:
    """실수 환경 변수를 안전하게 파싱합니다."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(min_value, value)


OPENAI_TIMEOUT_SEC: int = _get_env_int("OPENAI_TIMEOUT_SEC", 25, min_value=5)
OPENAI_MAX_RETRIES: int = _get_env_int("OPENAI_MAX_RETRIES", 1, min_value=0)

# ============================================================================
# 매직 넘버
# ============================================================================

MAX_TEXT_LENGTH: int = 20000
MIN_SECTION_LENGTH: int = 50
# 0 이하로 설정하면 문서 전체 페이지를 추출합니다.
MAX_PAGES: int = int(os.environ.get("MAX_PAGES", "120"))
DEFAULT_TOP_K: int = 10
DEFAULT_TOP_N: int = 5
CHUNK_HASH_MOD: int = 1_000_000
AMOUNT_UNITS: dict[str, int] = {"억": 100_000_000, "만": 10_000}

# 검색/컨텍스트 성능 튜닝
RETRIEVAL_EXPANSION_CAP: int = _get_env_int("RETRIEVAL_EXPANSION_CAP", 3, min_value=1)
RETRIEVAL_SEARCH_PASSES: int = _get_env_int("RETRIEVAL_SEARCH_PASSES", 1, min_value=1)
RETRIEVAL_HIGH_RECALL_K_MULTIPLIER: float = _get_env_float(
    "RETRIEVAL_HIGH_RECALL_K_MULTIPLIER", 0.8, min_value=0.5
)
CONTEXT_TOP_RESULTS: int = _get_env_int("CONTEXT_TOP_RESULTS", 6, min_value=1)
CONTEXT_MAX_CHARS: int = _get_env_int("CONTEXT_MAX_CHARS", 700, min_value=200)
RETRIEVAL_MAX_HYBRID_CALLS: int = _get_env_int("RETRIEVAL_MAX_HYBRID_CALLS", 6, min_value=1)
KEYWORD_SCAN_LIMIT: int = _get_env_int("KEYWORD_SCAN_LIMIT", 1200, min_value=100)
INTENT_REGEX_FIRST: bool = os.environ.get("INTENT_REGEX_FIRST", "true").lower() == "true"
DEBUG_RETRIEVAL_TIMING: bool = os.environ.get("DEBUG_RETRIEVAL_TIMING", "false").lower() == "true"
ANSWER_QUALITY_MODE: str = os.environ.get("ANSWER_QUALITY_MODE", "balanced").strip().lower()
CSV_SHORTCIRCUIT_ENABLED: bool = os.environ.get("CSV_SHORTCIRCUIT_ENABLED", "true").lower() == "true"
HYBRID_LEXICAL_PREFILTER_K: int = _get_env_int("HYBRID_LEXICAL_PREFILTER_K", 120, min_value=10)
HYBRID_LEXICAL_MIN_HITS: int = _get_env_int("HYBRID_LEXICAL_MIN_HITS", 1, min_value=1)
HYBRID_RERANK_TOP_MULTIPLIER: int = _get_env_int("HYBRID_RERANK_TOP_MULTIPLIER", 4, min_value=1)

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

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
CHROMA_PATH = PROJECT_ROOT / "data_index" / "chroma_B"
OUTPUT_PATH = PROJECT_ROOT / "output"
DATA_PATH = PROJECT_ROOT / "data"
CHUNK_DIR = PROJECT_ROOT / "output" / "chunks"

def get_data_dir() -> Path:
    """데이터 디렉토리 경로를 반환합니다."""
    default_path = DATA_PATH.resolve()
    if default_path.exists():
        return default_path
    # workspace_collab는 data_index/files 구조를 주로 사용한다.
    fallback_path = (PROJECT_ROOT / "data_index").resolve()
    return fallback_path

def get_default_db_path() -> str:
    """기본 DB 경로를 반환합니다."""
    return str(CHROMA_PATH.resolve())
