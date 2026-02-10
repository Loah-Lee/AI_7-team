"""Retrieval 품질 평가 스크립트.

eval/eval_dataset.yaml의 Q&A 쌍을 사용하여
Recall@K, Hit Rate@K, MRR, Avg Score를 측정한다.

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

from src.evaluation.metrics import (
    calculate_avg_score,
    calculate_hit_position,
    calculate_hit_rate_at_k,
    calculate_mrr,
    calculate_recall_at_k,
)
from src.retrievers.metadata_filter import search_with_metadata
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


def evaluate_retrieval(
    eval_items: list[dict],
    top_k: int = 5,
) -> dict:
    """평가셋의 각 질문으로 검색을 수행하고 지표를 계산한다."""
    recalls: list[float] = []
    hit_positions: list[int | None] = []
    avg_scores: list[float] = []
    per_query_results: list[dict] = []

    total = len(eval_items)
    for i, item in enumerate(eval_items, start=1):
        question = item["question"]
        gt = item.get("ground_truth", {})
        gt_source = gt.get("source", "")
        gt_page = gt.get("page")
        metadata_filter = item.get("metadata_filter")

        print(f"  [{i}/{total}] {question[:60]}...")

        # 검색 수행
        docs = search_with_metadata(
            question,
            metadata_filter=metadata_filter,
            top_k=top_k,
        )

        # RetrievedDoc 형식으로 변환
        retrieved = [
            {
                "content": doc.page_content,
                "source": doc.metadata.get("source", "unknown"),
                "page": doc.metadata.get("page"),
                "score": doc.metadata.get("score", 0.0),
            }
            for doc in docs
        ]

        # 지표 계산 (source 레벨 매칭 — 청크 분할 후 page가 달라질 수 있으므로)
        recall = calculate_recall_at_k(retrieved, gt_source, k=top_k)
        hit_pos = calculate_hit_position(retrieved, gt_source)
        avg_score = calculate_avg_score(retrieved, gt_source)

        recalls.append(recall)
        hit_positions.append(hit_pos)
        if avg_score is not None:
            avg_scores.append(avg_score)

        status = f"Hit@{hit_pos}" if hit_pos else "MISS"
        score_str = f"{avg_score:.4f}" if avg_score is not None else "N/A"
        print(f"           → {status} | Recall={recall:.0f} | AvgScore={score_str}")

        per_query_results.append({
            "id": item.get("id", f"q_{i}"),
            "question": question,
            "query_type": item.get("query_type", "unknown"),
            "ground_truth_source": gt_source,
            "ground_truth_page": gt_page,
            "hit_position": hit_pos,
            "recall_at_k": recall,
            "avg_score": avg_score,
            "num_retrieved": len(retrieved),
            "top_sources": [d["source"] for d in retrieved[:3]],
        })

    # 집계
    hit_rate = calculate_hit_rate_at_k(recalls)
    mrr = calculate_mrr(hit_positions)
    overall_avg_score = sum(avg_scores) / len(avg_scores) if avg_scores else 0.0

    return {
        "summary": {
            "num_queries": total,
            "top_k": top_k,
            "recall_at_k": round(sum(recalls) / len(recalls), 4) if recalls else 0.0,
            "hit_rate_at_k": round(hit_rate, 4),
            "mrr": round(mrr, 4),
            "avg_score": round(overall_avg_score, 4),
            "empty_retrieval_count": sum(1 for r in per_query_results if r["num_retrieved"] == 0),
        },
        "per_query": per_query_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval 품질 평가")
    parser.add_argument("--label", type=str, default="current", help="결과 라벨 (e.g., before, after)")
    parser.add_argument("--top_k", type=int, default=5, help="평가할 top-K (기본: 5)")
    parser.add_argument("--dataset", type=str, default=None, help="평가셋 경로")
    args = parser.parse_args()

    load_env()

    dataset_path = Path(args.dataset) if args.dataset else project_root / "eval" / "eval_dataset.yaml"
    eval_items = load_eval_dataset(dataset_path)
    if not eval_items:
        return

    print("=" * 60)
    print(f"BiddingMate Retrieval 평가 — label={args.label}, top_k={args.top_k}")
    print(f"평가셋: {len(eval_items)}개 질문")
    print("=" * 60)

    start = time.time()
    results = evaluate_retrieval(eval_items, top_k=args.top_k)
    elapsed = time.time() - start

    results["meta"] = {
        "label": args.label,
        "dataset_path": str(dataset_path),
        "elapsed_seconds": round(elapsed, 1),
    }

    # 콘솔 출력
    summary = results["summary"]
    print(f"\n{'=' * 60}")
    print(f"평가 결과 (label={args.label})")
    print(f"{'-' * 60}")
    print(f"  Recall@{args.top_k}:    {summary['recall_at_k']:.4f}")
    print(f"  Hit Rate@{args.top_k}:  {summary['hit_rate_at_k']:.4f}")
    print(f"  MRR:            {summary['mrr']:.4f}")
    print(f"  Avg Score:      {summary['avg_score']:.4f}")
    print(f"  Empty Retrieval: {summary['empty_retrieval_count']}/{summary['num_queries']}")
    print(f"  소요 시간:       {elapsed:.1f}초")
    print(f"{'=' * 60}")

    # JSON 저장
    output_path = project_root / "eval" / f"eval_results_{args.label}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[저장] {output_path}")


if __name__ == "__main__":
    main()
