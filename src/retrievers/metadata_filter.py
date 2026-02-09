"""메타데이터 필터링 + MMR 검색."""

from __future__ import annotations

import re

import numpy as np
from langchain_community.vectorstores.utils import maximal_marginal_relevance
from langchain_core.documents import Document

from src.graph.state import MetadataFilter
from src.retrievers.vectorstore import get_vectorstore
from src.utils.config import load_config

# --- TOC/표지 런타임 탐지 (re-ingest 없이 즉시 필터링) ---
_TOC_DOT_RE = re.compile(r"[·…]{3,}|\.{5,}")
_TOC_KW_RE = re.compile(r"목\s*차|차\s*례|Table\s+of\s+Contents", re.IGNORECASE)


def _is_toc_text(text: str, page: int | None = None) -> bool:
    """텍스트가 목차/표지인지 판별한다."""
    stripped = text.strip()
    # 짧은 표지 페이지 (page 1이고 300자 미만)
    if page == 1 and len(stripped) < 300:
        return True
    # 목차 키워드가 앞부분에 등장 (공백 무관하게 매칭)
    if _TOC_KW_RE.search(stripped[:200]):
        return True
    # 점선(···) 패턴이 3회 이상 → 목차 특유의 항목···페이지번호 형태
    if len(_TOC_DOT_RE.findall(stripped)) >= 3:
        return True
    return False


def _build_where_filter(metadata_filter: MetadataFilter) -> dict | None:
    """Chroma where 필터를 구성한다.

    institution/year만 $eq(정확매칭)으로 적용한다.
    project_name은 Chroma $contains 미지원이므로 query enrichment로 처리한다.
    """
    conditions = []

    if "institution" in metadata_filter:
        conditions.append({"institution": {"$eq": str(metadata_filter["institution"])}})
    if "year" in metadata_filter:
        conditions.append({"year": {"$eq": str(metadata_filter["year"])}})

    if len(conditions) == 1:
        return conditions[0]
    elif len(conditions) > 1:
        return {"$and": conditions}
    return None


_MAX_ENRICHMENT_KEYWORDS = 3


def _deduplicate_keywords(query: str, keywords: list[str]) -> list[str]:
    """쿼리와 중복되는 키워드를 제거하고, 키워드 간 부분문자열 중복도 제거한다."""
    query_normalized = query.replace(" ", "").lower()

    # 1단계: 쿼리에 이미 포함된 키워드 제거
    filtered = []
    for kw in keywords:
        kw_normalized = kw.replace(" ", "").lower()
        if kw_normalized in query_normalized:
            continue
        filtered.append(kw)

    # 2단계: 키워드 간 부분문자열 중복 제거 (짧은 것이 긴 것에 포함되면 짧은 것 제거)
    result = []
    for i, kw in enumerate(filtered):
        kw_norm = kw.replace(" ", "").lower()
        is_substring = False
        for j, other in enumerate(filtered):
            if i == j:
                continue
            other_norm = other.replace(" ", "").lower()
            if kw_norm in other_norm and len(kw_norm) < len(other_norm):
                is_substring = True
                break
        if not is_substring:
            result.append(kw)

    return result


def _enrich_query(query: str, metadata_filter: MetadataFilter | None) -> str:
    """institution, project_name, keywords를 query에 포함시켜 시맨틱 검색을 보강한다.

    institution은 $eq where 필터로도 사용되지만, 임베딩 유사도에도 반영하기 위해 쿼리에 추가.
    project_name은 Chroma $contains 미지원으로 where 필터가 아닌 query enrichment로 처리.
    keywords는 중복제거 후 최대 _MAX_ENRICHMENT_KEYWORDS개까지만 사용하여 쿼리 희석을 방지한다.
    """
    if not metadata_filter:
        return query
    parts: list[str] = []
    # institution도 쿼리에 포함 (임베딩 유사도에 기관명 반영)
    if "institution" in metadata_filter:
        inst = str(metadata_filter["institution"])
        if inst.replace(" ", "").lower() not in query.replace(" ", "").lower():
            parts.append(inst)
    if "project_name" in metadata_filter:
        parts.append(str(metadata_filter["project_name"]))
    keywords = metadata_filter.get("keywords", [])
    if keywords:
        deduped = _deduplicate_keywords(query, [str(k) for k in keywords])
        parts.extend(deduped[:_MAX_ENRICHMENT_KEYWORDS])
    if parts:
        return f"{query} {' '.join(parts)}"
    return query


def _mmr_search(
    vectorstore,
    query: str,
    top_k: int,
    fetch_k: int,
    lambda_mult: float,
    where_filter: dict | None,
) -> list[Document]:
    """MMR 검색을 수행하고 유사도 점수를 메타데이터에 포함시켜 반환한다."""
    embedding = vectorstore._embedding_function.embed_query(query)

    # Chroma 컬렉션에서 fetch_k개 후보를 임베딩과 거리까지 함께 조회
    query_kwargs: dict = {
        "query_embeddings": [embedding],
        "n_results": fetch_k,
        "include": ["documents", "metadatas", "distances", "embeddings"],
    }
    if where_filter:
        query_kwargs["where"] = where_filter

    try:
        results = vectorstore._collection.query(**query_kwargs)
    except Exception:
        # 필터 실패 시 빈 결과 반환 (상위 graduated fallback이 처리)
        return []

    ids = results.get("ids", [[]])[0]
    if not ids:
        return []

    documents_raw = results["documents"][0]
    metadatas_raw = results["metadatas"][0]
    distances_raw = results["distances"][0]
    embeddings_raw = results["embeddings"][0]

    # TOC/표지 후보를 MMR 전에 제거
    valid_indices = []
    for i in range(len(ids)):
        meta = metadatas_raw[i] or {}
        # DB에 is_toc 태그가 있으면 사용, 없으면 런타임 탐지
        if meta.get("is_toc"):
            continue
        if _is_toc_text(documents_raw[i], meta.get("page")):
            continue
        valid_indices.append(i)

    if not valid_indices:
        return []

    # 유효한 후보만으로 MMR re-ranking
    valid_embeddings = [embeddings_raw[i] for i in valid_indices]
    mmr_indices = maximal_marginal_relevance(
        np.array(embedding, dtype=np.float32),
        valid_embeddings,
        k=min(top_k, len(valid_indices)),
        lambda_mult=lambda_mult,
    )

    docs: list[Document] = []
    for mmr_idx in mmr_indices:
        orig_idx = valid_indices[mmr_idx]
        meta = dict(metadatas_raw[orig_idx]) if metadatas_raw[orig_idx] else {}
        # Chroma L2 거리 → 유사도 점수 변환 (0~1 범위)
        distance = distances_raw[orig_idx]
        meta["score"] = round(1.0 / (1.0 + distance), 4)
        docs.append(
            Document(page_content=documents_raw[orig_idx], metadata=meta)
        )

    return docs


def _similarity_search(
    vectorstore,
    query: str,
    top_k: int,
    where_filter: dict | None,
) -> list[Document]:
    """기본 유사도 검색 (폴백용)."""
    # TOC 필터링을 감안하여 더 많이 가져온 뒤 필터링
    kwargs: dict = {"k": top_k + 10}
    if where_filter:
        kwargs["filter"] = where_filter

    results = vectorstore.similarity_search_with_relevance_scores(query, **kwargs)

    docs: list[Document] = []
    for doc, score in results:
        if doc.metadata.get("is_toc"):
            continue
        if _is_toc_text(doc.page_content, doc.metadata.get("page")):
            continue
        doc.metadata["score"] = round(score, 4)
        docs.append(doc)
        if len(docs) >= top_k:
            break
    return docs


def search_with_metadata(
    query: str,
    metadata_filter: MetadataFilter | None = None,
    top_k: int | None = None,
    search_type: str | None = None,
) -> list[Document]:
    """메타데이터 필터를 적용한 벡터 검색.

    전략:
    1. institution/year는 $eq로 Chroma where 필터 적용
    2. project_name과 keywords는 query에 포함시켜 시맨틱 검색으로 처리
    3. search_type에 따라 MMR 또는 similarity 검색 수행
    4. 단계적 폴백: 전체 필터 → 필터 없음
    """
    config = load_config()
    retriever_cfg = config.get("retriever", {})

    if top_k is None:
        top_k = retriever_cfg.get("top_k", 8)
    fetch_k = retriever_cfg.get("fetch_k", 50)
    lambda_mult = retriever_cfg.get("lambda_mult", 0.7)
    if search_type is None:
        search_type = retriever_cfg.get("search_type", "mmr")

    vectorstore = get_vectorstore()
    enriched_query = _enrich_query(query, metadata_filter)

    # 단계적 폴백: where 필터 → 필터 없음
    where_filter = _build_where_filter(metadata_filter) if metadata_filter else None
    filter_stages: list[dict | None] = []
    if where_filter:
        filter_stages.append(where_filter)
    filter_stages.append(None)  # 최종 폴백: 필터 없음

    def _search(where_filter: dict | None) -> list[Document]:
        if search_type == "mmr":
            return _mmr_search(
                vectorstore, enriched_query, top_k, fetch_k, lambda_mult, where_filter
            )
        return _similarity_search(vectorstore, enriched_query, top_k, where_filter)

    for where_filter in filter_stages:
        results = _search(where_filter)
        if results:
            return results

    return []
