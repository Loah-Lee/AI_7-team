from __future__ import annotations

from src.retrievers.vectorstore import VectorStore


def _sample_result(source: str, score: float) -> dict:
    return {
        "text": f"doc:{source}",
        "metadata": {"source": source, "org": "테스트기관", "type": "pdf", "page": 1, "section": "본문"},
        "score": score,
    }


def _make_store() -> VectorStore:
    store = VectorStore.__new__(VectorStore)
    store.last_hybrid_stats = {}
    store.last_search_results = []
    return store


def test_hybrid_lexical_prefilter_then_vector_rerank_order() -> None:
    store = _make_store()
    store.search_keyword = lambda *args, **kwargs: [
        {
            "id": "A",
            "text": "alpha",
            "metadata": {"source": "a.pdf", "org": "테스트기관", "type": "pdf", "page": 1, "section": "본문"},
            "score": 3.0,
            "lexical_score": 1.0,
        },
        {
            "id": "B",
            "text": "beta",
            "metadata": {"source": "b.pdf", "org": "테스트기관", "type": "pdf", "page": 2, "section": "본문"},
            "score": 2.0,
            "lexical_score": 0.8,
        },
    ]
    store._create_query_embedding = lambda query: [1.0, 0.0]
    store._fetch_candidates_by_ids = lambda ids: {
        "A": {
            "text": "alpha",
            "metadata": {"source": "a.pdf", "org": "테스트기관", "type": "pdf", "page": 1, "section": "본문"},
            "embedding": [0.0, 1.0],
        },
        "B": {
            "text": "beta",
            "metadata": {"source": "b.pdf", "org": "테스트기관", "type": "pdf", "page": 2, "section": "본문"},
            "embedding": [1.0, 0.0],
        },
    }

    def _semantic_unexpected(*args, **kwargs):
        raise AssertionError("렉시컬 후보가 충분한 경우 semantic fallback이 호출되면 안 됩니다.")

    store.search = _semantic_unexpected

    results = store.search_hybrid("웹페이지 용량 기준", top_k=2)

    assert len(results) == 2
    assert results[0]["metadata"]["source"] == "b.pdf"
    assert store.last_hybrid_stats.get("fallback_used") is False


def test_hybrid_semantic_fallback_when_lexical_candidates_are_insufficient() -> None:
    store = _make_store()
    store.search_keyword = lambda *args, **kwargs: []
    semantic_results = [_sample_result("semantic1.pdf", 0.81), _sample_result("semantic2.pdf", 0.76)]
    store.search = lambda *args, **kwargs: semantic_results
    store._create_query_embedding = lambda query: [1.0, 0.0]
    store._fetch_candidates_by_ids = lambda ids: {}

    results = store.search_hybrid("복구 기준 알려줘", top_k=2)

    assert [item["metadata"]["source"] for item in results] == ["semantic1.pdf", "semantic2.pdf"]
    assert store.last_hybrid_stats.get("fallback_used") is True
    assert store.last_hybrid_stats.get("keyword_reason") == "lexical_empty"


def test_hybrid_precision_query_boosts_lexical_weight() -> None:
    store = _make_store()
    lexical_candidates = [
        {
            "id": "L1",
            "text": "code-exact",
            "metadata": {"source": "lexical_high.pdf", "org": "테스트기관", "type": "pdf", "page": 1, "section": "본문"},
            "score": 4.0,
            "lexical_score": 1.0,
        },
        {
            "id": "L2",
            "text": "semantic-close",
            "metadata": {"source": "semantic_high.pdf", "org": "테스트기관", "type": "pdf", "page": 2, "section": "본문"},
            "score": 1.0,
            "lexical_score": 0.1,
        },
    ]
    store.search_keyword = lambda *args, **kwargs: lexical_candidates
    store._create_query_embedding = lambda query: [1.0, 0.0]
    store._fetch_candidates_by_ids = lambda ids: {
        "L1": {
            "text": "code-exact",
            "metadata": {"source": "lexical_high.pdf", "org": "테스트기관", "type": "pdf", "page": 1, "section": "본문"},
            "embedding": [0.0, 1.0],
        },
        "L2": {
            "text": "semantic-close",
            "metadata": {"source": "semantic_high.pdf", "org": "테스트기관", "type": "pdf", "page": 2, "section": "본문"},
            "embedding": [1.0, 0.0],
        },
    }
    store.search = lambda *args, **kwargs: []

    precision_results = store.search_hybrid("QUR-02 요구사항은?", top_k=2)
    normal_results = store.search_hybrid("요구사항은?", top_k=2)

    assert precision_results[0]["metadata"]["source"] == "lexical_high.pdf"
    assert normal_results[0]["metadata"]["source"] == "semantic_high.pdf"
