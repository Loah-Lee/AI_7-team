#!/usr/bin/env python3
"""입찰메이트 v17 - RAG 시스템 평가 스크립트."""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

try:
    from langsmith import traceable
except ImportError:
    def traceable(*_args: Any, **_kwargs: Any):
        """langsmith 미설치 환경용 no-op 데코레이터."""

        def _decorator(func):
            return func

        return _decorator

# 경로 설정
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv()

from src.evaluation.langsmith_tracer import setup_langsmith_tracing
from src.evaluation.llm_judge import judge_rag_response
from src.evaluation.metrics import (
    calculate_hit_position,
    calculate_mrr,
    calculate_recall_at_k,
    calculate_recall_at_k_summary,
)
from src.utils.config import OPENAI_API_KEY

if TYPE_CHECKING:
    from src.graph.workflow import RAGChatbotV17


LOW8_IDS = {
    "eval_001",
    "eval_002",
    "eval_003",
    "eval_005",
    "eval_010",
    "eval_012",
    "eval_013",
    "eval_020",
}


def load_eval_dataset(dataset_path: str) -> list[dict[str, Any]]:
    """평가 데이터셋을 로드한다."""
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []

    if not isinstance(data, list):
        raise ValueError(f"평가 데이터셋 형식 오류: list가 아닙니다. path={dataset_path}")
    return data


def filter_dataset(dataset: list[dict[str, Any]], slice_name: str) -> list[dict[str, Any]]:
    """평가 데이터셋을 슬라이스합니다."""
    if slice_name == "all":
        return dataset
    if slice_name == "low8":
        return [item for item in dataset if str(item.get("id", "")) in LOW8_IDS]
    if slice_name == "first5":
        return dataset[:5]
    raise ValueError(f"지원하지 않는 slice: {slice_name}")


def _normalize_page(value: Any) -> int | None:
    """페이지 값을 int로 정규화한다."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_retrieved_docs(retrieved_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """검색 결과를 evaluation.metrics 입력 형식으로 정규화한다."""
    normalized: list[dict[str, Any]] = []
    for doc in retrieved_docs:
        metadata = doc.get("metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}

        source = str(metadata.get("source", "")).strip()
        page = _normalize_page(metadata.get("page"))

        score_raw = doc.get("score", metadata.get("score"))
        try:
            score = float(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None

        normalized.append(
            {
                "source": source,
                "page": page,
                "score": score,
                "text": str(doc.get("text", "")),
                "metadata": metadata,
            }
        )
    return normalized


def _build_retrieved_context(retrieved_docs: list[dict[str, Any]], max_docs: int = 3) -> str:
    """Judge 입력용 검색 context를 구성한다."""
    blocks = []
    for doc in retrieved_docs[:max_docs]:
        metadata = doc.get("metadata", {}) or {}
        source = metadata.get("source", "Unknown")
        text = str(doc.get("text", ""))[:500]
        blocks.append(f"[{source}]\n{text}")
    return "\n\n".join(blocks)


def calculate_retrieval_metrics(
    results: list[dict[str, Any]],
    top_k: int = 10,
) -> dict[str, Any]:
    """검색 메트릭(Recall@K, MRR)을 계산한다."""
    query_recalls_source: list[float] = []
    query_recalls_page: list[float] = []
    hit_positions_source: list[int | None] = []
    hit_positions_page: list[int | None] = []

    for result in results:
        ground_truth = result.get("ground_truth", {}) or {}
        expected_source = str(ground_truth.get("source", "")).strip()
        expected_page = _normalize_page(ground_truth.get("page"))
        retrieved_docs = result.get("retrieved_docs", []) or []

        if not expected_source:
            query_recalls_source.append(0.0)
            query_recalls_page.append(0.0)
            hit_positions_source.append(None)
            hit_positions_page.append(None)
            continue

        query_recalls_source.append(
            calculate_recall_at_k(retrieved_docs, expected_source, k=top_k)
        )
        query_recalls_page.append(
            calculate_recall_at_k(
                retrieved_docs, expected_source, ground_truth_page=expected_page, k=top_k
            )
        )
        hit_positions_source.append(calculate_hit_position(retrieved_docs, expected_source))
        hit_positions_page.append(
            calculate_hit_position(
                retrieved_docs,
                expected_source,
                ground_truth_page=expected_page,
            )
        )

    return {
        "recall_at_k_source": calculate_recall_at_k_summary(query_recalls_source),
        "recall_at_k_page": calculate_recall_at_k_summary(query_recalls_page),
        "mrr_source": calculate_mrr(hit_positions_source),
        "mrr_page": calculate_mrr(hit_positions_page),
    }


def _percentile(values: list[float], p: float) -> float:
    """선형 보간 기반 분위수를 계산합니다."""
    if not values:
        return 0.0
    if p <= 0:
        return min(values)
    if p >= 1:
        return max(values)
    sorted_vals = sorted(values)
    idx = (len(sorted_vals) - 1) * p
    low = int(idx)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = idx - low
    return sorted_vals[low] * (1.0 - frac) + sorted_vals[high] * frac


@traceable(name="eval_llm_judge", run_type="llm")
def evaluate_with_llm_judge(
    question: str,
    expected_answer: str,
    generated_answer: str,
    retrieved_context: str,
    model: str | None = None,
) -> dict[str, Any]:
    """LLM Judge로 답변을 평가한다."""
    result = judge_rag_response(
        question=question,
        expected_answer=expected_answer,
        generated_answer=generated_answer,
        context=retrieved_context[:2000],
        model=model,
    )

    correctness = int(result.get("correctness", {}).get("score", 0))
    coverage = int(result.get("answer_coverage", {}).get("score", 0))
    faithfulness = int(result.get("faithfulness", {}).get("score", 0))
    context_relevance = int(result.get("context_relevance", {}).get("score", 0))

    reasons = []
    for label, key in (
        ("C", "correctness"),
        ("Cv", "answer_coverage"),
        ("F", "faithfulness"),
        ("CR", "context_relevance"),
    ):
        reason = str(result.get(key, {}).get("reason", "")).strip()
        if reason:
            reasons.append(f"{label}: {reason}")

    return {
        "correctness": correctness,
        "coverage": coverage,
        "faithfulness": faithfulness,
        "context_relevance": context_relevance,
        "reasoning": " | ".join(reasons),
    }


@traceable(name="eval_retrieval_run", run_type="chain")
def run_evaluation(
    chatbot: "RAGChatbotV17",
    dataset: list[dict[str, Any]],
    label: str = "current",
    top_k: int = 10,
    use_judge: bool = True,
    judge_model: str | None = None,
) -> dict[str, Any]:
    """평가를 실행한다."""
    results: list[dict[str, Any]] = []

    print(f"\n{'=' * 60}")
    print(f"평가 시작: {len(dataset)}개 질문")
    print(f"{'=' * 60}\n")

    for i, item in enumerate(dataset, 1):
        question_id = item.get("id", f"q_{i:03d}")
        question = item.get("question", "")
        expected_answer = item.get("expected_answer", "")
        ground_truth = item.get("ground_truth", {}) or {}
        query_type = item.get("query_type", "single_doc")

        print(f"[{i}/{len(dataset)}] {question_id}: {question[:50]}...")

        start_time = time.time()
        answer_result = chatbot.answer(question, top_k=top_k)
        generated_answer = answer_result.get("answer", "")
        response_time = time.time() - start_time
        answer_mode = str(answer_result.get("answer_mode", "generative"))
        try:
            slot_fill_rate = float(answer_result.get("slot_fill_rate", 0.0) or 0.0)
        except (TypeError, ValueError):
            slot_fill_rate = 0.0
        try:
            evidence_count = int(answer_result.get("evidence_count", 0) or 0)
        except (TypeError, ValueError):
            evidence_count = 0
        try:
            confidence = float(answer_result.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        evidence = answer_result.get("evidence", []) or []

        retrieved_docs_raw: list[dict[str, Any]] = []
        if hasattr(chatbot.vector_store, "last_search_results"):
            retrieved_docs_raw = chatbot.vector_store.last_search_results or []
        retrieved_docs = _normalize_retrieved_docs(retrieved_docs_raw)
        retrieved_context = _build_retrieved_context(retrieved_docs_raw)

        judge_scores: dict[str, Any] = {}
        if use_judge:
            judge_scores = evaluate_with_llm_judge(
                question=question,
                expected_answer=expected_answer,
                generated_answer=generated_answer,
                retrieved_context=retrieved_context,
                model=judge_model,
            )

        result_item = {
            "id": question_id,
            "question": question,
            "expected_answer": expected_answer,
            "generated_answer": generated_answer,
            "ground_truth": ground_truth,
            "query_type": query_type,
            "response_time": response_time,
            "retrieved_docs": retrieved_docs,
            "retrieved_context": retrieved_context,
            "answer_mode": answer_mode,
            "slot_fill_rate": slot_fill_rate,
            "evidence_count": evidence_count,
            "confidence": confidence,
            "evidence": evidence,
            **judge_scores,
        }
        results.append(result_item)

        print(f"  응답 시간: {response_time:.2f}초")
        if judge_scores:
            print(
                f"  점수: C={judge_scores.get('correctness', 0)}/5, "
                f"Cv={judge_scores.get('coverage', 0)}/5, "
                f"F={judge_scores.get('faithfulness', 0)}/5, "
                f"CR={judge_scores.get('context_relevance', 0)}/5"
            )
        print()

    retrieval_metrics = calculate_retrieval_metrics(results, top_k=top_k)

    llm_metrics: dict[str, float] = {}
    if results and all("correctness" in r for r in results):
        n = len(results)
        llm_metrics = {
            "avg_correctness": sum(r.get("correctness", 0) for r in results) / n,
            "avg_coverage": sum(r.get("coverage", 0) for r in results) / n,
            "avg_faithfulness": sum(r.get("faithfulness", 0) for r in results) / n,
            "avg_context_relevance": sum(r.get("context_relevance", 0) for r in results) / n,
        }

    avg_response_time = (
        sum(r.get("response_time", 0.0) for r in results) / len(results) if results else 0.0
    )
    response_times = [float(r.get("response_time", 0.0) or 0.0) for r in results]
    answer_mode_counter = Counter(str(r.get("answer_mode", "unknown")) for r in results)
    avg_slot_fill_rate = (
        sum(float(r.get("slot_fill_rate", 0.0) or 0.0) for r in results) / len(results) if results else 0.0
    )
    avg_confidence = (
        sum(float(r.get("confidence", 0.0) or 0.0) for r in results) / len(results) if results else 0.0
    )
    overall_metrics = {
        "total_questions": len(results),
        "avg_response_time": avg_response_time,
        "p50_response_time": _percentile(response_times, 0.5),
        "p90_response_time": _percentile(response_times, 0.9),
        "answer_mode_distribution": dict(answer_mode_counter),
        "avg_slot_fill_rate": avg_slot_fill_rate,
        "avg_confidence": avg_confidence,
        **retrieval_metrics,
        **llm_metrics,
    }

    return {"label": label, "metrics": overall_metrics, "results": results}


def main() -> None:
    """메인 진입점 함수."""
    import argparse

    parser = argparse.ArgumentParser(description="입찰메이트 RAG 평가")
    parser.add_argument("--label", default="current", help="평가 라벨")
    parser.add_argument(
        "--dataset",
        default="eval_resources/eval_dataset.yaml",
        help="평가 데이터셋 경로",
    )
    parser.add_argument(
        "--slice",
        default="all",
        choices=["all", "low8", "first5"],
        help="평가 슬라이스 선택 (all|low8|first5)",
    )
    parser.add_argument("--output", default="eval/eval_results.json", help="결과 저장 경로")
    parser.add_argument("--top_k", type=int, default=10, help="검색할 문서 수")
    parser.add_argument("--no-judge", action="store_true", help="LLM Judge 사용 안 함")
    parser.add_argument("--judge-model", default=None, help="LLM Judge 모델명 (기본: DEFAULT_MODEL)")
    args = parser.parse_args()

    if setup_langsmith_tracing():
        print("🔍 LangSmith 트레이싱 활성화")
    else:
        print("ℹ️ LangSmith 트레이싱 비활성화")

    print("챗봇 초기화 중...")
    try:
        from src.graph.workflow import RAGChatbotV17
    except ImportError as e:
        print(f"오류: 평가 실행에 필요한 의존성이 없습니다. ({e})")
        print("먼저 `pip install -r requirements.txt`를 실행해 주세요.")
        sys.exit(1)

    chatbot = RAGChatbotV17()

    print(f"데이터셋 로드: {args.dataset}")
    dataset = load_eval_dataset(args.dataset)
    dataset = filter_dataset(dataset, args.slice)
    print(f"평가 슬라이스: {args.slice} ({len(dataset)}문항)")

    judge_enabled = (not args.no_judge) and bool(OPENAI_API_KEY)
    print("LLM Judge 활성화" if judge_enabled else "LLM Judge 비활성화")

    eval_result = run_evaluation(
        chatbot=chatbot,
        dataset=dataset,
        label=args.label,
        top_k=args.top_k,
        use_judge=judge_enabled,
        judge_model=args.judge_model,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(eval_result, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print("평가 완료!")
    print(f"{'=' * 60}")
    print("\n전체 메트릭:")
    for key, value in eval_result["metrics"].items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")
    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    main()
