"""LangSmith 트레이싱 설정."""

from __future__ import annotations

import os

from dotenv import load_dotenv


def setup_langsmith_tracing() -> bool:
    """LangSmith 트레이싱을 활성화한다.

    환경변수를 설정하여 LangChain/LangGraph 실행이 자동으로 트레이싱되도록 한다.

    Returns:
        True면 트레이싱 활성화 성공, False면 API 키 없음.
    """
    load_dotenv()

    tracing_enabled = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
    if not tracing_enabled:
        return False

    api_key = os.getenv("LANGSMITH_API_KEY", "")
    if not api_key:
        return False

    project_name = os.getenv("LANGSMITH_PROJECT", "biddingmate_ai7")
    endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com/")

    # LangChain >=0.3은 LANGCHAIN_API_KEY를 사용한다
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = project_name
    os.environ["LANGCHAIN_ENDPOINT"] = endpoint

    print(f"[LangSmith] 트레이싱 활성화 (project={project_name})")
    return True
