from __future__ import annotations

import os
from pathlib import Path


# OpenAI
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL: str | None = os.getenv("OPENAI_BASE_URL")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gpt-5-nano")

# LangSmith
LANGSMITH_API_KEY: str | None = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_TRACING: bool = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_ENDPOINT: str = os.getenv(
    "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com/"
)
LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT", "ai_7_team")

# Langfuse
LANGFUSE_PUBLIC_KEY: str | None = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY: str | None = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_BASE_URL: str = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

# Embedding fallback and org aliases
FALLBACK_EMBEDDING_MODEL: str = "BM-K/KoSimCSE-roberta-multitask"
ORG_ALIASES: dict[str, str] = {
    "서울시": "서울특별시",
    "고려대": "고려대학교",
    "서울시립대": "서울시립대학교",
    "농어촌공사": "한국농어촌공사",
    "krc": "한국농어촌공사",
}


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_data_dir() -> Path:
    return get_project_root() / "data"


def get_default_db_path() -> str:
    return str(get_project_root() / "chroma_db")
