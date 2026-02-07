"""임베딩 모델 설정."""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from src.utils.config import load_config
from src.utils.env import get_openai_api_key


def get_embeddings(model: str | None = None) -> OpenAIEmbeddings:
    """OpenAI 임베딩 모델 인스턴스를 반환한다.

    Args:
        model: 임베딩 모델명. None이면 설정 파일 값 사용.

    Returns:
        OpenAIEmbeddings 인스턴스.
    """
    config = load_config()
    embedding_cfg = config.get("embedding", {})

    if model is None:
        model = embedding_cfg.get("model", "text-embedding-3-small")

    return OpenAIEmbeddings(
        model=model,
        api_key=get_openai_api_key(),
    )
