#!/usr/bin/env python3
"""리트리버 오케스트레이션 서비스.

검색 모드 선택, 동적 fallback, 검색 결과 컨텍스트 구성 책임을 담당한다.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.retrievers.vectorstore import VectorStore


class RetrievalService:
    """검색 단계 오케스트레이션 서비스."""

    def __init__(self, vector_store: "VectorStore") -> None:
        self.vector_store = vector_store

    def resolve_org_name(self, query: str) -> str | None:
        """질문에서 기관명을 추정한다."""
        normalized_query = self.vector_store.normalize_org_name(query)
        for org_name in self.vector_store.org_registry.keys():
            if org_name in normalized_query or normalized_query in org_name:
                return org_name
        return None

    @staticmethod
    def _to_retrieved_docs(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        for item in results:
            metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
            source = item.get("source") or metadata.get("source") or metadata.get("source_file") or "unknown"
            docs.append(
                {
                    "source": str(source),
                    "page": item.get("page"),
                    "score": float(item.get("score", 0.0)),
                    "content": str(item.get("text", "")),
                    "metadata": metadata,
                }
            )
        return docs

    @staticmethod
    def _build_context(results: list[dict[str, Any]], limit: int = 20) -> str:
        context_parts: list[str] = []
        for r in results[:limit]:
            metadata = r.get("metadata", {}) if isinstance(r.get("metadata"), dict) else {}
            source = r.get("source") or metadata.get("source", "Unknown")
            org = metadata.get("org", "")
            text = r.get("text", "")
            context_parts.append(f"[{org} - {source}]\n{text[:8000]}")
        return "\n\n---\n\n".join(context_parts)

    def retrieve(
        self,
        query: str,
        *,
        retriever_mode: str = "dynamic",
        top_k: int = 30,
        hybrid_alpha: float = 0.6,
        dynamic_hard_threshold: int = 2,
    ) -> dict[str, Any]:
        """질의에 대해 검색을 수행하고 검색 결과 payload를 반환한다."""
        org_name = self.resolve_org_name(query)
        search_query = query
        if org_name and org_name in self.vector_store.org_registry:
            search_query = f"{org_name} {query}"

        retrieve_k = max(1, int(top_k))
        results = self.vector_store.search(
            search_query,
            top_k=retrieve_k,
            mode=retriever_mode,
            hybrid_alpha=hybrid_alpha,
            dynamic_hard_threshold=dynamic_hard_threshold,
        )
        retrieval_mode = self.vector_store.last_retrieval_mode

        # easy query에서 hybrid 경로가 빈약하면 chroma로 재시도
        if retriever_mode == "dynamic" and retrieval_mode == "hybrid":
            unique_sources = self.vector_store.count_unique_sources(results)
            weak_hybrid = (
                not results
                or (results and float(results[0].get("score", 0.0)) < 0.2)
                or (len(results) >= 2 and unique_sources < 2)
            )
            if weak_hybrid:
                fallback = self.vector_store.search(
                    search_query,
                    top_k=retrieve_k,
                    mode="chroma",
                    hybrid_alpha=hybrid_alpha,
                    dynamic_hard_threshold=dynamic_hard_threshold,
                )
                if fallback:
                    fallback_unique_sources = self.vector_store.count_unique_sources(fallback)
                    keep_fallback = (
                        not results
                        or float(fallback[0].get("score", 0.0)) > float(results[0].get("score", 0.0))
                        or fallback_unique_sources > unique_sources
                    )
                    if keep_fallback:
                        results = fallback
                        retrieval_mode = "dynamic_chroma_fallback"

        return {
            "search_query": search_query,
            "retrieval_mode": retrieval_mode,
            "found": bool(results),
            "results": results,
            "retrieved_docs": self._to_retrieved_docs(results),
            "evidence": self._build_context(results, limit=20) if results else "",
        }
