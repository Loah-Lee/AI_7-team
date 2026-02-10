"""Langfuse 메트릭 수집."""

from __future__ import annotations

from langfuse import Langfuse

from src.utils.env import get_langfuse_keys, load_env


def get_langfuse_client() -> Langfuse | None:
    """Langfuse 클라이언트를 초기화한다.

    환경변수에 키가 없으면 None을 반환한다.

    Returns:
        Langfuse 인스턴스 또는 None.
    """
    load_env()
    keys = get_langfuse_keys()

    if not keys["public_key"] or not keys["secret_key"]:
        return None

    return Langfuse(
        public_key=keys["public_key"],
        secret_key=keys["secret_key"],
        host=keys["host"],
    )


def log_score(
    trace_id: str,
    name: str,
    value: float,
    comment: str | None = None,
) -> None:
    """Langfuse에 평가 점수를 기록한다.

    Args:
        trace_id: 트레이스 ID.
        name: 메트릭 이름 (e.g., "aicr", "hallucination_rate").
        value: 점수 값.
        comment: 부가 설명.
    """
    client = get_langfuse_client()
    if client is None:
        return

    client.score(
        trace_id=trace_id,
        name=name,
        value=value,
        comment=comment,
    )


def log_retrieval_metrics(
    trace_id: str,
    retrieved_docs: list[dict],
) -> None:
    """검색 결과의 요약 지표를 Langfuse에 기록한다.

    기록 항목:
    - retrieval_count: 검색된 청크 수
    - retrieval_avg_score: 평균 유사도 점수
    - retrieval_max_score: 최고 유사도 점수

    Args:
        trace_id: 트레이스 ID.
        retrieved_docs: RetrievedDoc 딕셔너리 리스트.
    """
    if not trace_id:
        return

    count = len(retrieved_docs)
    log_score(trace_id, "retrieval_count", float(count))

    scores = [doc.get("score", 0.0) for doc in retrieved_docs if doc.get("score")]
    if scores:
        log_score(trace_id, "retrieval_avg_score", round(sum(scores) / len(scores), 4))
        log_score(trace_id, "retrieval_max_score", round(max(scores), 4))
