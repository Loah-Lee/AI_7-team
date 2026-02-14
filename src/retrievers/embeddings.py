#!/usr/bin/env python3
"""
임베딩 모듈

텍스트 임베딩을 생성합니다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.utils.config import OPENAI_API_KEY, embedding_config

if TYPE_CHECKING:
    pass


class EmbeddingGenerator:
    """텍스트 임베딩을 생성하는 클래스."""

    def __init__(self, api_key: str | None = None):
        """임베딩 생성기를 초기화합니다.

        Args:
            api_key: OpenAI API 키
        """
        self.api_key = api_key or OPENAI_API_KEY
        self.use_openai = self.api_key is not None

        if not self.use_openai:
            self._init_local_model()

    def _init_local_model(self) -> None:
        """로컬 모델을 초기화합니다."""
        try:
            from sentence_transformers import SentenceTransformer
            self.local_model = SentenceTransformer(embedding_config.fallback_model)
        except ImportError:
            self.local_model = None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """텍스트 리스트를 임베딩합니다.

        Args:
            texts: 임베딩할 텍스트 리스트

        Returns:
            임베딩 벡터 리스트
        """
        if self.use_openai:
            return self._embed_with_openai(texts)
        elif self.local_model is not None:
            return self._embed_with_local(texts)
        else:
            raise RuntimeError("임베딩 모델을 사용할 수 없습니다.")

    def embed_query(self, query: str) -> list[float]:
        """쿼리를 임베딩합니다.

        Args:
            query: 임베딩할 쿼리

        Returns:
            쿼리 임베딩 벡터
        """
        embeddings = self.embed_texts([query])
        return embeddings[0] if embeddings else []

    def _embed_with_openai(self, texts: list[str]) -> list[list[float]]:
        """OpenAI로 텍스트를 임베딩합니다.

        Args:
            texts: 임베딩할 텍스트 리스트

        Returns:
            임베딩 벡터 리스트
        """
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        # OpenAI embedding API의 request당 토큰 상한을 피하기 위해 배치 처리
        vectors: list[list[float]] = []
        batch_size = 64
        for idx in range(0, len(texts), batch_size):
            batch = texts[idx: idx + batch_size]
            embeddings = client.embeddings.create(
                model=embedding_config.model,
                input=batch,
            )
            vectors.extend([e.embedding for e in embeddings.data])
        return vectors

    def _embed_with_local(self, texts: list[str]) -> list[list[float]]:
        """로컬 모델로 텍스트를 임베딩합니다.

        Args:
            texts: 임베딩할 텍스트 리스트

        Returns:
            임베딩 벡터 리스트
        """
        if self.local_model is None:
            raise RuntimeError("로컬 임베딩 모델이 초기화되지 않았습니다.")

        embeddings = self.local_model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    @property
    def dimension(self) -> int | None:
        """임베딩 차원을 반환합니다.

        Returns:
            임베딩 차원 또는 None
        """
        if self.use_openai:
            # OpenAI text-embedding-3-small: 1536
            return 1536
        elif self.local_model is not None:
            return self.local_model.get_sentence_embedding_dimension()
        return None
