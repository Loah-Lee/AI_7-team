"""KPI 계산 함수.

KPI.md에 정의된 메트릭을 계산한다:
- Answer-in-Context Rate (AICR)
- Hallucination Rate
- Top-k Hit Position
- Empty Retrieval Rate
"""

from __future__ import annotations

import unicodedata
from pathlib import Path


_CONVERTED_DOC_EXTS = {"hwp", "hwpx", "pdf"}


def _normalize_source_name(source: str | None) -> str:
    """source 문자열을 비교 가능한 형태로 정규화한다.

    - Unicode NFC 정규화
    - 앞뒤 공백 제거
    - 파일명 기준 비교를 위해 basename 추출
    - 기본은 확장자 포함 exact 매칭
    """
    if not source:
        return ""
    normalized = unicodedata.normalize("NFC", str(source)).strip()
    normalized = Path(normalized).name
    return normalized.lower()


def _split_source_parts(source: str | None) -> tuple[str, str, str]:
    """정규화된 source를 (name, stem, ext)로 분해한다."""
    normalized = _normalize_source_name(source)
    if not normalized:
        return "", "", ""
    parsed = Path(normalized)
    ext = parsed.suffix.lower().lstrip(".")
    return normalized, parsed.stem.lower(), ext


def _normalize_stem_for_equivalence(stem: str) -> str:
    """파일 stem 비교를 위한 추가 정규화(구두점/공백 차이 무시)."""
    if not stem:
        return ""
    normalized = unicodedata.normalize("NFKC", stem.lower())
    return "".join(ch for ch in normalized if ch.isalnum())


def _is_equivalent_source_name(a: str | None, b: str | None) -> bool:
    """두 source 문자열이 동일 문서를 가리키는지 판정한다.

    규칙:
    - exact filename 일치면 동일
    - stem이 같고 확장자가 hwp/hwpx/pdf 변환군 내이면 동일
    - 한쪽이 확장자 없는 stem이어도 stem이 같으면 동일로 본다.
    """
    a_name, a_stem, a_ext = _split_source_parts(a)
    b_name, b_stem, b_ext = _split_source_parts(b)
    if not a_name or not b_name:
        return False
    if a_name == b_name:
        return True

    def _stem_match() -> bool:
        return _normalize_stem_for_equivalence(a_stem) == _normalize_stem_for_equivalence(b_stem)

    if _stem_match():
        # DB source를 확장자 없이 저장하는 모드 지원
        if not a_ext or not b_ext:
            return True
        if a_ext in _CONVERTED_DOC_EXTS and b_ext in _CONVERTED_DOC_EXTS:
            return True

    return False


def _normalize_ground_truth_sources(
    ground_truth_source: str | list[str] | tuple[str, ...] | set[str],
) -> list[str]:
    """ground truth source 입력을 정규화된 리스트로 변환한다."""
    if isinstance(ground_truth_source, str):
        values = [ground_truth_source]
    else:
        values = list(ground_truth_source)

    return [
        _normalize_source_name(v)
        for v in values
        if _normalize_source_name(v)
    ]


def _is_source_match(
    retrieved_source: str | None,
    ground_truth_sources: list[str],
) -> bool:
    """retrieved source가 정답 source 집합과 일치하는지 판정한다."""
    for gt_source in ground_truth_sources:
        if _is_equivalent_source_name(retrieved_source, gt_source):
            return True
    return False


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


def calculate_hit_position(
    retrieved_docs: list[dict],
    ground_truth_source: str | list[str] | tuple[str, ...] | set[str],
    ground_truth_page: int | None = None,
) -> int | None:
    """정답 문서가 검색 결과에서 몇 번째에 위치하는지 반환한다.

    단일 source: 첫 번째 일치 위치를 반환한다.
    다중 source (strict): 모든 source가 발견된 경우, 마지막으로 발견된 source의
        위치를 반환한다 (= 모든 정답을 포함하기 위해 필요한 최소 rank).
        하나라도 누락이면 None.

    Args:
        retrieved_docs: 검색된 문서 리스트 (RetrievedDoc 딕셔너리).
        ground_truth_source: 정답 문서 source 값(단일 문자열 또는 리스트).
        ground_truth_page: 정답 페이지. 지정 시 source + page 모두 일치해야 hit.

    Returns:
        1-based 위치. 없으면 None.
    """
    gt_sources = _normalize_ground_truth_sources(ground_truth_source)
    if not gt_sources:
        return None

    if len(gt_sources) == 1:
        for idx, doc in enumerate(retrieved_docs, start=1):
            if not _is_source_match(doc.get("source"), gt_sources):
                continue
            if ground_truth_page is not None and doc.get("page") != ground_truth_page:
                continue
            return idx
        return None

    # Multi-source strict: 모든 GT source의 첫 출현 위치 수집 → max 반환
    # 하나라도 미발견이면 None
    gt_set = set(gt_sources)
    found_at: dict[str, int] = {}
    for idx, doc in enumerate(retrieved_docs, start=1):
        norm_src = _normalize_source_name(doc.get("source"))
        if norm_src in gt_set and norm_src not in found_at:
            found_at[norm_src] = idx
        if len(found_at) == len(gt_set):
            return max(found_at.values())
    return None  # 하나 이상 미발견


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
    ground_truth_source: str | list[str] | tuple[str, ...] | set[str],
    ground_truth_page: int | None = None,
    k: int = 5,
) -> float:
    """Recall@K — top-K 내에 정답 source가 있으면 1.0, 아니면 0.0.

    - 단일 source: top-K 내 포함 시 1.0
    - 다중 source: top-K 내에 모든 source가 포함되어야 1.0 (strict)
    - page가 지정되면 단일 source 케이스에서 source + page 모두 일치해야 정답으로 판정한다.
    - 단, source 확장자가 hwp/hwpx/pdf 변환군인 경우 stem 동일 시 동일 문서로 간주한다.
    """
    gt_sources = _normalize_ground_truth_sources(ground_truth_source)
    if not gt_sources:
        return 0.0

    top_k_docs = retrieved_docs[:k]

    # 단일 source는 페이지 조건을 지원한다.
    if len(gt_sources) == 1:
        target = gt_sources[0]
        for doc in top_k_docs:
            if not _is_equivalent_source_name(doc.get("source"), target):
                continue
            if ground_truth_page is not None and doc.get("page") != ground_truth_page:
                continue
            return 1.0
        return 0.0

    # 다중 source는 strict match: 모든 GT source가 top-K 내 매칭되어야 hit.
    for gt_source in gt_sources:
        matched = any(_is_equivalent_source_name(doc.get("source"), gt_source) for doc in top_k_docs)
        if not matched:
            return 0.0
    return 1.0


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
    ground_truth_source: str | list[str] | tuple[str, ...] | set[str],
    ground_truth_page: int | None = None,
) -> float | None:
    """정답 청크의 평균 유사도 점수를 반환한다. 정답이 없으면 None."""
    gt_sources = _normalize_ground_truth_sources(ground_truth_source)
    if not gt_sources:
        return None

    scores = []
    for doc in retrieved_docs:
        if not _is_source_match(doc.get("source"), gt_sources):
            continue
        if ground_truth_page is not None and doc.get("page") != ground_truth_page:
            continue
        scores.append(doc.get("score", 0.0))
    return sum(scores) / len(scores) if scores else None
