"""환경변수 로딩 유틸리티."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_loaded = False


def load_env() -> None:
    """프로젝트 루트의 .env 파일을 로드한다. 중복 호출 시 무시."""
    global _loaded
    if _loaded:
        return

    project_root = Path(__file__).resolve().parents[2]
    dotenv_path = project_root / ".env"
    load_dotenv(dotenv_path, override=False)
    _loaded = True


def get_openai_api_key() -> str:
    load_env()
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
    return key


def get_langsmith_api_key() -> str | None:
    load_env()
    return os.getenv("LANGSMITH_API_KEY")


def get_langfuse_keys() -> dict[str, str | None]:
    load_env()
    return {
        "public_key": os.getenv("LANGFUSE_PUBLIC_KEY"),
        "secret_key": os.getenv("LANGFUSE_SECRET_KEY"),
        "host": os.getenv("LANGFUSE_BASE_URL", os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")),
    }
