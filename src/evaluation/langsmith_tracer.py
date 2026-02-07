"""LangSmith 트레이싱 설정."""

from __future__ import annotations

import os

from src.utils.config import load_config
from src.utils.env import load_env


def setup_langsmith_tracing() -> bool:
    """LangSmith 트레이싱을 활성화한다.

    환경변수를 설정하여 LangChain/LangGraph 실행이 자동으로 트레이싱되도록 한다.

    Returns:
        True면 트레이싱 활성화 성공, False면 API 키 없음.
    """
    load_env()
    config = load_config()
    tracing_cfg = config.get("tracing", {})

    api_key = os.getenv("LANGSMITH_API_KEY", "")
    if not api_key:
        return False

    # .env의 LANGSMITH_PROJECT가 있으면 우선 사용, 없으면 config 값
    project_name = os.getenv("LANGSMITH_PROJECT") or tracing_cfg.get(
        "langsmith_project", "biddingmate"
    )

    endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

    # LangChain >=0.3은 LANGCHAIN_API_KEY를 사용한다
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = project_name
    os.environ["LANGCHAIN_ENDPOINT"] = endpoint

    print(f"[LangSmith] 트레이싱 활성화 (project={project_name})")
    return True
