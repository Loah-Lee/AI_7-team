"""KPI 계산 함수.

KPI.md에 정의된 메트릭을 계산한다:
- Answer-in-Context Rate (AICR)
- Hallucination Rate
- Top-k Hit Position
- Empty Retrieval Rate
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable


def calculate_aicr(answer: str, context: str) -> float:
    """Answer-in-Context Rate를 계산한다.

    답변의 각 문장이 context에 근거가 있는지 비율을 반환한다.

    Args:
        answer: 생성된 답변.
        context: 검색된 문맥.

    Returns:
        0.0 ~ 1.0 사이의 비율.
    """
    # TODO: LLM 기반 정밀 판정으로 개선 예정
    sentences = [s.strip() for s in answer.split(".") if s.strip()]
    if not sentences:
        return 1.0

    in_context_count = sum(
        1 for s in sentences if s.lower() in context.lower()
    )
    return in_context_count / len(sentences)


def calculate_hallucination_rate(answer: str, context: str) -> float:
    """Hallucination Rate를 계산한다.

    context에 없는 정보가 답변에 포함된 비율.

    Args:
        answer: 생성된 답변.
        context: 검색된 문맥.

    Returns:
        0.0 ~ 1.0 사이의 비율.
    """
    return 1.0 - calculate_aicr(answer, context)


def _normalize_source_name(source: str) -> tuple[str, str]:
    """소스 문자열을 정규화해 (파일명, 확장자 제거 stem) 쌍으로 반환한다."""
    raw = unicodedata.normalize("NFKC", str(source or "")).strip().lower()
    raw = raw.replace("\\", "/")
    base = Path(raw).name
    stem = Path(base).stem

    # data_list (1).csv 와 data_list.csv 를 동일 계열로 간주
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = re.sub(r"[^0-9a-z가-힣]+", "", stem)

    base_key = re.sub(r"\s+", " ", base).strip()
    base_key = re.sub(r"[^0-9a-z가-힣.]+", "", base_key)
    return base_key, stem


def _iter_ground_truth_sources(ground_truth_source: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(ground_truth_source, str):
        return [ground_truth_source]
    if isinstance(ground_truth_source, Iterable):
        return [str(item) for item in ground_truth_source if str(item).strip()]
    return []


def _source_matches(retrieved_source: str, ground_truth_source: str | list[str] | tuple[str, ...]) -> bool:
    gt_sources = _iter_ground_truth_sources(ground_truth_source)
    if not gt_sources:
        return False

    ret_base, ret_stem = _normalize_source_name(retrieved_source)
    for gt in gt_sources:
        gt_base, gt_stem = _normalize_source_name(gt)
        if ret_base and gt_base and ret_base == gt_base:
            return True
        if ret_stem and gt_stem and ret_stem == gt_stem:
            return True
    return False


def calculate_hit_position(
    retrieved_docs: list[dict],
    ground_truth_source: str | list[str] | tuple[str, ...],
    ground_truth_page: int | None = None,
) -> int | None:
    """정답 문서가 검색 결과에서 몇 번째에 위치하는지 반환한다.

    Args:
        retrieved_docs: 검색된 문서 리스트 (RetrievedDoc 딕셔너리).
        ground_truth_source: 정답 문서의 source 값.
        ground_truth_page: 정답 페이지. 지정 시 source + page 모두 일치해야 hit.

    Returns:
        1-based 위치. 없으면 None.
    """
    for idx, doc in enumerate(retrieved_docs, start=1):
        if not _source_matches(doc.get("source", ""), ground_truth_source):
            continue
        if ground_truth_page is not None and doc.get("page") != ground_truth_page:
            continue
        return idx
    return None


def calculate_empty_retrieval_rate(
    query_results: list[list[dict]],
) -> float:
    """전체 질의 중 검색 결과가 비어있는 비율.

    Args:
        query_results: 각 질의별 검색 결과 리스트의 리스트.

    Returns:
        0.0 ~ 1.0 사이의 비율.
    """
    if not query_results:
        return 0.0

    empty_count = sum(1 for results in query_results if not results)
    return empty_count / len(query_results)


def calculate_recall_at_k(
    retrieved_docs: list[dict],
    ground_truth_source: str | list[str] | tuple[str, ...],
    ground_truth_page: int | None = None,
    k: int = 5,
) -> float:
    """Recall@K — 정답 source가 top-K 내에 존재하면 1.0, 아니면 0.0.

    page가 지정되면 source + page 모두 일치해야 정답으로 판정한다.
    """
    for doc in retrieved_docs[:k]:
        if not _source_matches(doc.get("source", ""), ground_truth_source):
            continue
        if ground_truth_page is not None and doc.get("page") != ground_truth_page:
            continue
        return 1.0
    return 0.0


def calculate_recall_at_k_summary(
    query_recalls: list[float],
) -> float:
    """Recall@K (summary) — per-query Recall@K의 평균 (= Hit Rate@K)."""
    if not query_recalls:
        return 0.0
    return sum(1 for r in query_recalls if r > 0) / len(query_recalls)


def calculate_mrr(
    hit_positions: list[int | None],
) -> float:
    """Mean Reciprocal Rank — 첫 정답 순위의 역수 평균.

    Args:
        hit_positions: 각 쿼리별 정답의 1-based 위치. None이면 정답 없음.
    """
    if not hit_positions:
        return 0.0
    reciprocals = [1.0 / pos if pos is not None else 0.0 for pos in hit_positions]
    return sum(reciprocals) / len(reciprocals)


def calculate_avg_score(
    retrieved_docs: list[dict],
    ground_truth_source: str | list[str] | tuple[str, ...],
    ground_truth_page: int | None = None,
) -> float | None:
    """정답 청크의 평균 유사도 점수를 반환한다. 정답이 없으면 None."""
    scores = []
    for doc in retrieved_docs:
        if not _source_matches(doc.get("source", ""), ground_truth_source):
            continue
        if ground_truth_page is not None and doc.get("page") != ground_truth_page:
            continue
        scores.append(doc.get("score", 0.0))
    return sum(scores) / len(scores) if scores else None
