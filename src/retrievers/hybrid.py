"""BM25 + Dense 하이브리드 검색."""

from __future__ import annotations

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from kiwipiepy import Kiwi

from src.retrievers.vectorstore import get_vectorstore
from src.utils.config import load_config

_kiwi = Kiwi()

_CONTENT_TAGS = {"NNG", "NNP", "NNB", "VV", "VA", "MAG", "SL", "SN"}


def _tokenize(text: str) -> list[str]:
    """kiwipiepy 형태소 분석 기반 토큰화."""
    tokens = _kiwi.tokenize(text)
    return [t.form for t in tokens if t.tag in _CONTENT_TAGS]


class HybridRetriever:
    """BM25 + Dense 벡터 검색을 결합한 하이브리드 리트리버."""

    def __init__(
        self,
        documents: list[Document] | None = None,
        top_k: int | None = None,
        bm25_weight: float = 0.3,
    ):
        config = load_config()
        retriever_cfg = config.get("retriever", {})

        if top_k is None:
            self.top_k = retriever_cfg.get("top_k", 5)
        else:
            self.top_k = top_k

        self.bm25_weight = bm25_weight
        self.vectorstore = get_vectorstore()

        if documents:
            corpus = [_tokenize(doc.page_content) for doc in documents]
            self.bm25 = BM25Okapi(corpus)
            self.documents = documents
        else:
            self.bm25 = None
            self.documents = []

    def retrieve(self, query: str) -> list[Document]:
        """하이브리드 검색을 수행한다.

        Args:
            query: 검색 질의.

        Returns:
            검색된 Document 리스트 (top_k개).
        """
        # Dense 검색
        dense_results = self.vectorstore.similarity_search_with_score(
            query, k=self.top_k
        )

        if self.bm25 is None or not self.documents:
            return [doc for doc, _ in dense_results]

        # BM25 검색
        tokenized_query = _tokenize(query)
        bm25_scores = self.bm25.get_scores(tokenized_query)

        # 점수 정규화 및 결합
        score_map: dict[str, float] = {}
        doc_map: dict[str, Document] = {}

        for doc, dense_score in dense_results:
            key = doc.page_content[:100]
            score_map[key] = (1 - self.bm25_weight) * (1 / (1 + dense_score))
            doc_map[key] = doc

        for idx, bm25_score in enumerate(bm25_scores):
            if idx < len(self.documents):
                key = self.documents[idx].page_content[:100]
                existing = score_map.get(key, 0.0)
                score_map[key] = existing + self.bm25_weight * bm25_score
                if key not in doc_map:
                    doc_map[key] = self.documents[idx]

        sorted_keys = sorted(score_map, key=score_map.get, reverse=True)  # type: ignore[arg-type]
        return [doc_map[k] for k in sorted_keys[: self.top_k]]
