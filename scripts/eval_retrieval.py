"""RAG End-to-End 평가 스크립트 — LLM-as-Judge 기반.

전체 RAG 파이프라인(build_graph().invoke())을 실행한 뒤
LLM Judge가 Correctness, Faithfulness, Relevance를 채점한다.
기존 retrieval 지표(Hit Rate, MRR)도 보조로 계산.

실행: uv run python scripts/eval_retrieval.py --label current --top_k 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.evaluation.llm_judge import judge_rag_response
from src.evaluation.metrics import (
    calculate_hit_position,
    calculate_hit_rate_at_k,
    calculate_mrr,
    calculate_recall_at_k,
)
from src.graph.workflow import build_graph
from src.utils.env import load_env


def load_eval_dataset(path: Path) -> list[dict]:
    """평가셋 YAML 파일을 로드한다."""
    if not path.exists():
        print(f"[ERROR] 평가셋 파일이 없습니다: {path}")
        print("       먼저 실행: uv run python scripts/generate_eval_set.py")
        return []

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, list):
        print("[ERROR] 평가셋 형식이 올바르지 않습니다 (list 필요)")
        return []

    return data


def run_rag_pipeline(question: str, metadata_filter: dict | None, top_k: int) -> dict:
    """전체 RAG 파이프라인을 실행하고 state를 반환한다."""
    graph = build_graph()

    input_state = {"query": question}
    if metadata_filter:
        input_state["metadata_filter"] = metadata_filter
    if top_k:
        input_state["retriever_top_k"] = top_k

    result = graph.invoke(input_state)
    return result


def evaluate_e2e(
    eval_items: list[dict],
    top_k: int = 5,
    judge_model: str | None = None,
) -> dict:
    """E2E 평가: RAG 파이프라인 실행 → LLM Judge 채점."""
    per_query_results: list[dict] = []
    correctness_scores: list[int] = []
    answer_recall_scores: list[int] = []
    faithfulness_scores: list[int] = []
    relevance_scores: list[int] = []
    recalls: list[float] = []
    hit_positions: list[int | None] = []

    total = len(eval_items)

    for i, item in enumerate(eval_items, start=1):
        question = item["question"]
        expected_answer = item.get("expected_answer", "")
        gt = item.get("ground_truth", {})
        gt_source = gt.get("source", "")
        metadata_filter = item.get("metadata_filter")

        print(f"\n[{i}/{total}] {question[:60]}...")

        # 1) RAG 파이프라인 실행
        try:
            state = run_rag_pipeline(question, metadata_filter, top_k)
        except Exception as e:
            print(f"  [ERROR] 파이프라인 실행 실패: {e}")
            per_query_results.append({
                "id": item.get("id", f"q_{i}"),
                "question": question,
                "error": str(e),
            })
            continue

        generated_answer = state.get("answer", "")
        evidence = state.get("evidence", "")
        retrieved_docs = state.get("retrieved_docs", [])

        # 2) Retrieval 지표 (보조)
        retrieved_for_metrics = [
            {
                "source": doc.get("source", "unknown"),
                "page": doc.get("page"),
                "score": doc.get("score", 0.0),
            }
            for doc in retrieved_docs
        ]

        recall = calculate_recall_at_k(retrieved_for_metrics, gt_source, k=top_k)
        hit_pos = calculate_hit_position(retrieved_for_metrics, gt_source)
        recalls.append(recall)
        hit_positions.append(hit_pos)

        # 3) LLM Judge 채점
        context_text = evidence if evidence else "\n\n".join(
            doc.get("content", "") for doc in retrieved_docs
        )

        print(f"  → Retrieval: {'Hit@' + str(hit_pos) if hit_pos else 'MISS'} | {len(retrieved_docs)}개 문서")
        print(f"  → LLM Judge 채점 중...")

        judge_result = judge_rag_response(
            question=question,
            expected_answer=expected_answer,
            generated_answer=generated_answer,
            context=context_text,
            model=judge_model,
        )

        c_score = judge_result["correctness"]["score"]
        ar_score = judge_result["answer_recall"]["score"]
        f_score = judge_result["faithfulness"]["score"]
        r_score = judge_result["relevance"]["score"]

        correctness_scores.append(c_score)
        answer_recall_scores.append(ar_score)
        faithfulness_scores.append(f_score)
        relevance_scores.append(r_score)

        print(f"  → C={c_score} | AR={ar_score} | F={f_score} | R={r_score}")

        per_query_results.append({
            "id": item.get("id", f"q_{i}"),
            "question": question,
            "query_type": item.get("query_type", "unknown"),
            "expected_answer": expected_answer,
            "generated_answer": generated_answer,
            "correctness": judge_result["correctness"],
            "answer_recall": judge_result["answer_recall"],
            "faithfulness": judge_result["faithfulness"],
            "relevance": judge_result["relevance"],
            "hit_position": hit_pos,
            "recall_at_k": recall,
            "num_retrieved": len(retrieved_docs),
            "ground_truth_source": gt_source,
        })

    # 집계
    n = len(correctness_scores)
    avg_correctness = sum(correctness_scores) / n if n else 0.0
    avg_answer_recall = sum(answer_recall_scores) / n if n else 0.0
    avg_faithfulness = sum(faithfulness_scores) / n if n else 0.0
    avg_relevance = sum(relevance_scores) / n if n else 0.0
    hit_rate = calculate_hit_rate_at_k(recalls)
    mrr = calculate_mrr(hit_positions)

    return {
        "summary": {
            "num_queries": total,
            "num_evaluated": n,
            "top_k": top_k,
            "avg_correctness": round(avg_correctness, 2),
            "avg_answer_recall": round(avg_answer_recall, 2),
            "avg_faithfulness": round(avg_faithfulness, 2),
            "avg_relevance": round(avg_relevance, 2),
            "hit_rate_at_k": round(hit_rate, 4),
            "mrr": round(mrr, 4),
        },
        "per_query": per_query_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG E2E 평가 (LLM-as-Judge)")
    parser.add_argument("--label", type=str, default="current", help="결과 라벨 (e.g., before, after)")
    parser.add_argument("--top_k", type=int, default=5, help="검색 top-K (기본: 5)")
    parser.add_argument("--dataset", type=str, default=None, help="평가셋 경로")
    parser.add_argument("--judge_model", type=str, default=None, help="Judge LLM 모델 (기본: config 모델)")
    args = parser.parse_args()

    load_env()

    dataset_path = Path(args.dataset) if args.dataset else project_root / "eval" / "eval_dataset.yaml"
    eval_items = load_eval_dataset(dataset_path)
    if not eval_items:
        return

    print("=" * 60)
    print(f"BiddingMate RAG E2E 평가 — LLM-as-Judge")
    print(f"  label={args.label}, top_k={args.top_k}")
    print(f"  평가셋: {len(eval_items)}개 질문")
    if args.judge_model:
        print(f"  Judge 모델: {args.judge_model}")
    print("=" * 60)

    start = time.time()
    results = evaluate_e2e(
        eval_items,
        top_k=args.top_k,
        judge_model=args.judge_model,
    )
    elapsed = time.time() - start

    results["meta"] = {
        "label": args.label,
        "dataset_path": str(dataset_path),
        "elapsed_seconds": round(elapsed, 1),
        "judge_model": args.judge_model,
    }

    # 콘솔 출력
    summary = results["summary"]
    print(f"\n{'=' * 60}")
    print(f"평가 결과 (label={args.label})")
    print(f"{'-' * 60}")
    print(f"  [LLM Judge 점수 (0~5)]")
    print(f"    Correctness:    {summary['avg_correctness']:.2f}")
    print(f"    Answer Recall:  {summary['avg_answer_recall']:.2f}")
    print(f"    Faithfulness:   {summary['avg_faithfulness']:.2f}")
    print(f"    Relevance:      {summary['avg_relevance']:.2f}")
    print(f"  [Retrieval 보조 지표]")
    print(f"    Hit Rate@{args.top_k}:   {summary['hit_rate_at_k']:.4f}")
    print(f"    MRR:            {summary['mrr']:.4f}")
    print(f"  평가 건수: {summary['num_evaluated']}/{summary['num_queries']}")
    print(f"  소요 시간: {elapsed:.1f}초")
    print(f"{'=' * 60}")

    # JSON 저장
    output_path = project_root / "eval" / f"eval_results_{args.label}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[저장] {output_path}")


if __name__ == "__main__":
    main()
