"""RAG End-to-End 평가 스크립트 — dev(v17) 기준.

- RAGChatbotV17.answer()를 직접 호출
- LLM Judge: Correctness / Answer Coverage / Faithfulness / Context Relevance
- Retrieval 보조 지표: Recall@K, MRR (source+optional page strict match)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.evaluation.llm_judge import judge_rag_response
from src.evaluation.metrics import (
    calculate_hit_position,
    calculate_mrr,
    calculate_recall_at_k,
    calculate_recall_at_k_summary,
)
from src.graph.workflow import RAGChatbotV17


def _get_eval_dir() -> Path:
    """평가 결과 디렉토리 경로를 반환한다. 환경변수 우선, 없으면 eval_resources (fallback: eval)."""
    if custom_dir := os.getenv("EVAL_DIR"):
        return project_root / custom_dir

    eval_resources = project_root / "eval_resources"
    eval_legacy = project_root / "eval"

    if eval_resources.exists():
        return eval_resources
    if eval_legacy.exists():
        print("[WARNING] 'eval/' 폴더가 감지되었습니다. 'eval_resources/' 사용을 권장합니다.")
        return eval_legacy
    return eval_resources


def load_eval_dataset(path: Path) -> list[dict[str, Any]]:
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

    return [item for item in data if isinstance(item, dict)]


def _extract_ground_truth(item: dict[str, Any]) -> tuple[str, int | None]:
    gt = item.get("ground_truth") if isinstance(item.get("ground_truth"), dict) else {}

    source = ""
    page: int | None = None

    sources = gt.get("sources")
    if isinstance(sources, list) and sources:
        first = sources[0]
        if isinstance(first, dict):
            source = str(first.get("source", "")).strip()
            try:
                page = int(first.get("page")) if first.get("page") is not None else None
            except Exception:
                page = None
        else:
            source = str(first).strip()

    if not source:
        source = str(gt.get("source", "")).strip()
        try:
            page = int(gt.get("page")) if gt.get("page") is not None else None
        except Exception:
            page = None

    return source, page


def _build_context_text(retrieved_docs: list[dict[str, Any]], limit: int = 20) -> str:
    if not retrieved_docs:
        return "(검색 결과 없음)"

    lines: list[str] = []
    for idx, doc in enumerate(retrieved_docs[:limit], start=1):
        source = str(doc.get("source", "unknown"))
        page = doc.get("page")
        page_text = f"p.{page}" if page is not None else "p.-"
        content = " ".join(str(doc.get("content", "")).split())
        if len(content) > 1200:
            content = content[:1200] + "..."
        lines.append(f"[{idx}] {source} ({page_text})\n{content}")
    return "\n\n".join(lines)


def run_rag_pipeline(
    chatbot: RAGChatbotV17,
    question: str,
    metadata_filter: dict[str, Any] | None,
    *,
    top_k: int,
    retriever: str,
    hybrid_alpha: float,
    dynamic_hard_threshold: int,
) -> dict[str, Any]:
    """RAG 파이프라인을 실행하고 상태를 반환한다."""
    result = chatbot.answer(
        question,
        retriever_mode=retriever,
        top_k=top_k,
        hybrid_alpha=hybrid_alpha,
        dynamic_hard_threshold=dynamic_hard_threshold,
    )

    # 기관 힌트가 있으면 1회 재시도
    if not result.get("found", False) and isinstance(metadata_filter, dict):
        institution = str(metadata_filter.get("institution", "")).strip()
        if institution and institution not in question:
            hinted_q = f"{institution} {question}"
            result = chatbot.answer(
                hinted_q,
                retriever_mode=retriever,
                top_k=top_k,
                hybrid_alpha=hybrid_alpha,
                dynamic_hard_threshold=dynamic_hard_threshold,
            )

    return result


def evaluate_e2e(
    eval_items: list[dict[str, Any]],
    *,
    top_k: int = 5,
    judge_model: str | None = None,
    retriever: str = "dynamic",
    hybrid_alpha: float = 0.6,
    dynamic_hard_threshold: int = 2,
) -> dict[str, Any]:
    """E2E 평가: RAG 파이프라인 실행 → LLM Judge 채점."""
    chatbot = RAGChatbotV17()

    per_query_results: list[dict[str, Any]] = []
    correctness_scores: list[int] = []
    answer_coverage_scores: list[int] = []
    faithfulness_scores: list[int] = []
    context_relevance_scores: list[int] = []
    recalls: list[float] = []
    hit_positions: list[int | None] = []

    total = len(eval_items)

    for i, item in enumerate(eval_items, start=1):
        question = str(item.get("question", "")).strip()
        if not question:
            continue

        expected_answer = str(item.get("expected_answer", "")).strip()
        metadata_filter = item.get("metadata_filter") if isinstance(item.get("metadata_filter"), dict) else None
        gt_source, gt_page = _extract_ground_truth(item)

        print(f"\n[{i}/{total}] {question[:60]}...")

        try:
            state = run_rag_pipeline(
                chatbot,
                question,
                metadata_filter,
                top_k=top_k,
                retriever=retriever,
                hybrid_alpha=hybrid_alpha,
                dynamic_hard_threshold=dynamic_hard_threshold,
            )
        except Exception as e:
            print(f"  [ERROR] 파이프라인 실행 실패: {e}")
            per_query_results.append(
                {
                    "id": item.get("id", f"q_{i}"),
                    "question": question,
                    "error": str(e),
                }
            )
            continue

        generated_answer = str(state.get("answer", ""))
        retrieved_docs = state.get("retrieved_docs") if isinstance(state.get("retrieved_docs"), list) else []

        retrieved_for_metrics = [
            {
                "source": str(doc.get("source", "unknown")),
                "page": doc.get("page"),
                "score": float(doc.get("score", 0.0)),
            }
            for doc in retrieved_docs
        ]
        retrieved_sources = list(dict.fromkeys(doc.get("source", "unknown") for doc in retrieved_for_metrics))

        recall = calculate_recall_at_k(
            retrieved_for_metrics,
            ground_truth_source=gt_source,
            ground_truth_page=gt_page,
            k=top_k,
        )
        hit_pos = calculate_hit_position(
            retrieved_for_metrics,
            ground_truth_source=gt_source,
            ground_truth_page=gt_page,
        )
        recalls.append(recall)
        hit_positions.append(hit_pos)

        context_text = str(state.get("evidence", "")).strip() or _build_context_text(retrieved_docs, limit=20)

        print(
            f"  → Retrieval[{state.get('retrieval_mode', 'unknown')}]: "
            f"{'Hit@' + str(hit_pos) if hit_pos else 'MISS'} | {len(retrieved_docs)}개 문서"
        )
        print("  → LLM Judge 채점 중...")

        judge_result = judge_rag_response(
            question=question,
            expected_answer=expected_answer,
            generated_answer=generated_answer,
            context=context_text,
            model=judge_model,
        )

        c_score = int(judge_result["correctness"]["score"])
        ac_score = int(judge_result["answer_coverage"]["score"])
        f_score = int(judge_result["faithfulness"]["score"])
        cr_score = int(judge_result["context_relevance"]["score"])

        correctness_scores.append(c_score)
        answer_coverage_scores.append(ac_score)
        faithfulness_scores.append(f_score)
        context_relevance_scores.append(cr_score)

        print(f"  → C={c_score} | AC={ac_score} | F={f_score} | CR={cr_score}")

        per_query_results.append(
            {
                "id": item.get("id", f"q_{i}"),
                "question": question,
                "query_type": item.get("query_type", "unknown"),
                "expected_answer": expected_answer,
                "generated_answer": generated_answer,
                "correctness": judge_result["correctness"],
                "answer_coverage": judge_result["answer_coverage"],
                "faithfulness": judge_result["faithfulness"],
                "context_relevance": judge_result["context_relevance"],
                "hit_position": hit_pos,
                "recall_at_k": recall,
                "num_retrieved": len(retrieved_docs),
                "ground_truth_source": gt_source,
                "ground_truth_page": gt_page,
                "retrieved_sources": retrieved_sources,
                "retrieval_mode": state.get("retrieval_mode", "unknown"),
                "status": state.get("status", "unknown"),
            }
        )

    n = len(correctness_scores)
    avg_correctness = sum(correctness_scores) / n if n else 0.0
    avg_answer_coverage = sum(answer_coverage_scores) / n if n else 0.0
    avg_faithfulness = sum(faithfulness_scores) / n if n else 0.0
    avg_context_relevance = sum(context_relevance_scores) / n if n else 0.0
    recall_at_k_source = calculate_recall_at_k_summary(recalls)
    mrr = calculate_mrr(hit_positions)

    return {
        "summary": {
            "num_queries": total,
            "num_evaluated": n,
            "top_k": top_k,
            "avg_correctness": round(avg_correctness, 2),
            "avg_answer_coverage": round(avg_answer_coverage, 2),
            "avg_faithfulness": round(avg_faithfulness, 2),
            "avg_context_relevance": round(avg_context_relevance, 2),
            "recall_at_k_source": round(recall_at_k_source, 4),
            "mrr_source": round(mrr, 4),
        },
        "per_query": per_query_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG E2E 평가 (LLM-as-Judge, dev 기준)")
    parser.add_argument("--label", type=str, default="current", help="결과 라벨 (e.g., before, after)")
    parser.add_argument("--top_k", type=int, default=5, help="검색 top-K (기본: 5)")
    parser.add_argument("--dataset", type=str, default=None, help="평가셋 경로")
    parser.add_argument("--judge_model", type=str, default=None, help="Judge LLM 모델")
    parser.add_argument(
        "--retriever",
        type=str,
        default="dynamic",
        choices=["chroma", "hybrid", "dynamic"],
        help="리트리버 모드",
    )
    parser.add_argument("--hybrid-alpha", type=float, default=0.6, help="hybrid 결합 가중치")
    parser.add_argument(
        "--dynamic-hard-threshold",
        type=int,
        default=2,
        help="dynamic hard 판정 임계값",
    )
    args = parser.parse_args()

    load_dotenv(".env")

    dataset_path = Path(args.dataset) if args.dataset else _get_eval_dir() / "eval_dataset.yaml"
    eval_items = load_eval_dataset(dataset_path)
    if not eval_items:
        return

    print("=" * 60)
    print("BiddingMate RAG E2E 평가 — LLM-as-Judge (dev 기준)")
    print(f"  label={args.label}, top_k={args.top_k}, retriever={args.retriever}")
    print(f"  hybrid_alpha={args.hybrid_alpha}, dynamic_hard_threshold={args.dynamic_hard_threshold}")
    print(f"  평가셋: {len(eval_items)}개 질문")
    if args.judge_model:
        print(f"  Judge 모델: {args.judge_model}")
    print("=" * 60)

    start = time.time()
    results = evaluate_e2e(
        eval_items,
        top_k=args.top_k,
        judge_model=args.judge_model,
        retriever=args.retriever,
        hybrid_alpha=float(args.hybrid_alpha),
        dynamic_hard_threshold=int(args.dynamic_hard_threshold),
    )
    elapsed = time.time() - start

    results["meta"] = {
        "label": args.label,
        "dataset_path": str(dataset_path),
        "elapsed_seconds": round(elapsed, 1),
        "judge_model": args.judge_model,
        "retriever": args.retriever,
        "hybrid_alpha": float(args.hybrid_alpha),
        "dynamic_hard_threshold": int(args.dynamic_hard_threshold),
    }

    summary = results["summary"]
    print(f"\n{'=' * 60}")
    print(f"평가 결과 (label={args.label})")
    print(f"{'-' * 60}")
    print("  [LLM Judge 점수 (0~5)]")
    print(f"    Correctness:       {summary['avg_correctness']:.2f}")
    print(f"    Answer Coverage:   {summary['avg_answer_coverage']:.2f}")
    print(f"    Faithfulness:      {summary['avg_faithfulness']:.2f}")
    print(f"    Context Relevance: {summary['avg_context_relevance']:.2f}")
    print("  [Retrieval 보조 지표 — Source Level (Strict Match)]")
    print(f"    Recall@{args.top_k}:       {summary['recall_at_k_source']:.4f}")
    print(f"    MRR:               {summary['mrr_source']:.4f}")
    print(f"  평가 건수: {summary['num_evaluated']}/{summary['num_queries']}")
    print(f"  소요 시간: {elapsed:.1f}초")
    print(f"{'=' * 60}")

    output_path = _get_eval_dir() / f"eval_results_{args.label}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[저장] {output_path}")


if __name__ == "__main__":
    main()
