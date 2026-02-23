"""Langfuse 메트릭 수집."""

from __future__ import annotations

import os
import warnings
from typing import Any

try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE = True
except ImportError:
    Langfuse = None  # type: ignore
    LANGFUSE_AVAILABLE = False

try:
    from src.utils.env import get_langfuse_keys, load_env
    UTILS_AVAILABLE = True
except ImportError:
    UTILS_AVAILABLE = False


def get_langfuse_client() -> Any | None:
    """Langfuse 클라이언트를 초기화한다.

    환경변수에 키가 없으면 None을 반환한다.

    Returns:
        Langfuse 인스턴스 또는 None.
    """
    if not LANGFUSE_AVAILABLE:
        warnings.warn(
            "Langfuse is not installed. Install it with: pip install langfuse",
            ImportWarning,
            stacklevel=2,
        )
        return None

    if UTILS_AVAILABLE:
        load_env()
        keys = get_langfuse_keys()
    else:
        # Fallback to direct env vars
        keys = {
            "public_key": os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            "secret_key": os.getenv("LANGFUSE_SECRET_KEY", ""),
            "host": os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        }

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


class _NoOpTracer:
    """main.py 호환용 no-op tracer."""

    def trace(self, *, name: str, payload: dict[str, Any]) -> None:
        return

    def start_span(self, name: str, payload: dict[str, Any]) -> Any:
        return None

    def end_span(self, span: Any, name: str, payload: dict[str, Any]) -> None:
        return


class _LoggerBackedTracer:
    """src.utils.langfuse_logger 기반 tracer 어댑터.

    app/main.py가 기대하는 trace/start_span/end_span 시그니처를 제공한다.
    """

    def __init__(self, logger: Any) -> None:
        self._logger = logger

    def trace(self, *, name: str, payload: dict[str, Any]) -> None:
        log_trace = getattr(self._logger, "log_trace", None)
        if callable(log_trace):
            log_trace(name, payload)
            return
        # 호환 fallback
        trace_fn = getattr(self._logger, "trace", None)
        if callable(trace_fn):
            trace_fn(name=name, payload=payload)

    def start_span(self, name: str, payload: dict[str, Any]) -> Any:
        start_span = getattr(self._logger, "start_span", None)
        if callable(start_span):
            return start_span(name, payload)
        return None

    def end_span(self, span: Any, name: str, payload: dict[str, Any]) -> None:
        end_span = getattr(self._logger, "end_span", None)
        if callable(end_span):
            end_span(span, name, payload)


def get_langfuse_tracer() -> Any:
    """app/main.py 호환 tracer를 반환한다.

    - src.utils.langfuse_logger가 있으면 해당 로거를 감싼 tracer를 반환
    - 없거나 초기화 실패 시 no-op tracer를 반환
    """
    try:
        from src.utils.langfuse_logger import get_langfuse_logger  # type: ignore

        logger = get_langfuse_logger()
        return _LoggerBackedTracer(logger)
    except Exception:
        return _NoOpTracer()
