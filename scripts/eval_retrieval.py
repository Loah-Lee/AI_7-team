"""RAG End-to-End 평가 스크립트 — LLM-as-Judge 기반.

전체 RAG 파이프라인(build_graph().invoke())을 실행한 뒤
LLM Judge가 Correctness, Answer Coverage, Faithfulness, Context Relevance를 채점한다.
Retrieval 보조 지표(Recall@K, MRR — Source 단위)도 병행 계산.

실행: uv run python scripts/eval_retrieval.py --label current --top_k 5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv as _load_dotenv

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))


def _get_eval_dir() -> Path:
    """평가 결과 디렉토리 경로를 반환한다. 환경변수 우선, 없으면 eval_resources (fallback: eval)."""
    if custom_dir := os.getenv("EVAL_DIR"):
        return project_root / custom_dir

    eval_resources = project_root / "eval_resources"
    eval_legacy = project_root / "eval"

    if eval_resources.exists():
        return eval_resources
    elif eval_legacy.exists():
        print(f"[WARNING] 'eval/' 폴더가 감지되었습니다. 'eval_resources/'로 이름을 변경하는 것을 권장합니다.")
        return eval_legacy
    else:
        return eval_resources

from src.evaluation.llm_judge import judge_rag_response
from src.evaluation.metrics import (
    calculate_hit_position,
    calculate_mrr,
    calculate_recall_at_k,
    calculate_recall_at_k_summary,
)

try:
    from src.graph.workflow import build_graph
    _WORKFLOW_MODE = "graph"
    _chatbot_cls = None
except ImportError:
    from src.graph.workflow import RAGChatbotV17

    build_graph = None
    _chatbot_cls = RAGChatbotV17
    _WORKFLOW_MODE = "chatbot"

try:
    from src.utils.env import load_env
except ImportError:
    def load_env() -> None:
        _load_dotenv(project_root.parent / ".env")
        _load_dotenv(project_root / ".env")
        _load_dotenv()


_CHATBOT_SINGLETON = None


def _normalize_source_label(source: str | None) -> str:
    """source 문자열을 소문자/확장자 제거 형태로 정규화한다."""
    if not source:
        return ""
    label = str(source).strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
    if "." in label:
        label = label.rsplit(".", 1)[0]
    return label


def _has_csv_ground_truth(gt_sources: list[str]) -> bool:
    """GT source 목록에 data_list.csv 계열이 포함되어 있는지 판정한다."""
    for source in gt_sources:
        normalized = _normalize_source_label(source)
        if normalized == "data_list" or normalized.startswith("data_list_"):
            return True
    return False


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
    if build_graph:
        graph = build_graph()

        input_state = {"query": question}
        if metadata_filter:
            input_state["metadata_filter"] = metadata_filter
        if top_k:
            input_state["retriever_top_k"] = top_k

        result = graph.invoke(input_state)
        if not isinstance(result, dict):
            return {}

        graph_retrieved = result.get("retrieved_docs", [])
        retrieved_docs: list[dict] = []
        if isinstance(graph_retrieved, list):
            for doc in graph_retrieved:
                if not isinstance(doc, dict):
                    continue
                source = str(doc.get("source", "unknown") or "unknown")
                page = doc.get("page")
                try:
                    score = float(doc.get("score", 0.0) or 0.0)
                except (TypeError, ValueError):
                    score = 0.0
                content = str(doc.get("content") or doc.get("text") or "")
                retrieved_docs.append(
                    {
                        "source": source,
                        "page": page,
                        "score": score,
                        "content": content,
                    }
                )

        evidence_items = result.get("evidence", [])
        if isinstance(evidence_items, list):
            evidence_text = "\n\n".join(
                str(item.get("text", "")).strip()
                for item in evidence_items
                if isinstance(item, dict) and str(item.get("text", "")).strip()
            )
        else:
            evidence_text = str(evidence_items or "")

        return {
            "answer": result.get("answer", ""),
            "evidence": evidence_text,
            "evidence_items": evidence_items if isinstance(evidence_items, list) else [],
            "retrieved_docs": retrieved_docs,
            "csv_short_circuit": bool(result.get("csv_short_circuit", False)),
            "source_type": str(result.get("source_type", "") or "").lower(),
            "latencies": result.get("latencies", {}),
        }

    global _CHATBOT_SINGLETON
    if _CHATBOT_SINGLETON is None:
        _CHATBOT_SINGLETON = _chatbot_cls()

    query_text = question
    if metadata_filter:
        institution = str(
            metadata_filter.get("institution")
            or metadata_filter.get("org")
            or metadata_filter.get("org_name")
            or ""
        ).strip()
        if institution and institution not in query_text:
            query_text = f"{institution} {query_text}"

    response = _CHATBOT_SINGLETON.answer(query_text, top_k=top_k or 5)
    response_retrieved = response.get("retrieved_docs", [])
    retrieved_docs = []
    if isinstance(response_retrieved, list) and response_retrieved:
        for doc in response_retrieved:
            if not isinstance(doc, dict):
                continue
            source = str(doc.get("source", "unknown") or "unknown")
            page = doc.get("page")
            try:
                score = float(doc.get("score", 0.0) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            retrieved_docs.append(
                {
                    "source": source,
                    "page": page,
                    "score": score,
                    "content": str(doc.get("content") or doc.get("text") or ""),
                }
            )
    else:
        raw_retrieved = getattr(_CHATBOT_SINGLETON.vector_store, "last_search_results", []) or []
        for doc in raw_retrieved:
            if not isinstance(doc, dict):
                continue
            meta = doc.get("metadata", {}) or {}
            source = str(
                doc.get("source")
                or meta.get("source")
                or meta.get("source_file")
                or meta.get("filename")
                or "unknown"
            )
            try:
                score = float(doc.get("score", 0.0) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            retrieved_docs.append(
                {
                    "source": source,
                    "page": doc.get("page") if doc.get("page") is not None else meta.get("page"),
                    "score": score,
                    "content": str(doc.get("content") or doc.get("text") or ""),
                }
            )

    evidence_items = response.get("evidence", [])
    if isinstance(evidence_items, list):
        evidence_text = "\n\n".join(
            str(item.get("text", "")).strip()
            for item in evidence_items
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        )
    else:
        evidence_text = str(evidence_items or "")

    return {
        "answer": response.get("answer", ""),
        "evidence": evidence_text,
        "evidence_items": evidence_items if isinstance(evidence_items, list) else [],
        "retrieved_docs": retrieved_docs,
        "csv_short_circuit": bool(response.get("csv_short_circuit", False)),
        "source_type": str(response.get("source_type", "") or "").lower(),
        "latencies": response.get("latencies", {}),
    }


def evaluate_e2e(
    eval_items: list[dict],
    top_k: int = 5,
    judge_model: str | None = None,
) -> dict:
    """E2E 평가: RAG 파이프라인 실행 → LLM Judge 채점."""
    per_query_results: list[dict] = []
    correctness_scores: list[int] = []
    answer_coverage_scores: list[int] = []
    faithfulness_scores: list[int] = []
    context_relevance_scores: list[int] = []
    recalls: list[float] = []
    hit_positions: list[int | None] = []

    total = len(eval_items)

    for i, item in enumerate(eval_items, start=1):
        question = item["question"]
        expected_answer = item.get("expected_answer", "")
        gt = item.get("ground_truth", {})
        gt_sources: list[str] = gt.get("sources", [])
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
        source_type = str(state.get("source_type", "") or "").lower()
        csv_short_circuit = bool(state.get("csv_short_circuit", False))

        # 2) Retrieval 지표 (보조 — Source 단위)
        retrieved_for_metrics = [
            {
                "source": doc.get("source", "unknown"),
                "page": doc.get("page"),
                "score": doc.get("score", 0.0),
            }
            for doc in retrieved_docs
        ]

        # CSV short-circuit 질의는 vector retrieval을 거치지 않으므로
        # data_list.csv를 pseudo source로 주입해 source-level 지표를 평가한다.
        if _has_csv_ground_truth(gt_sources) and (csv_short_circuit or source_type == "csv"):
            already_has_data_list = any(
                _normalize_source_label(doc.get("source")) == "data_list"
                for doc in retrieved_for_metrics
            )
            if not already_has_data_list:
                retrieved_for_metrics = [
                    {
                        "source": "data_list.csv",
                        "page": None,
                        "score": 1.0,
                    },
                    *retrieved_for_metrics,
                ]

        retrieved_sources = list(dict.fromkeys(
            doc.get("source", "unknown") for doc in retrieved_for_metrics
        ))

        recall = calculate_recall_at_k(retrieved_for_metrics, gt_sources, k=top_k)
        hit_pos = calculate_hit_position(retrieved_for_metrics, gt_sources)
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
        ac_score = judge_result["answer_coverage"]["score"]
        f_score = judge_result["faithfulness"]["score"]
        cr_score = judge_result["context_relevance"]["score"]

        correctness_scores.append(c_score)
        answer_coverage_scores.append(ac_score)
        faithfulness_scores.append(f_score)
        context_relevance_scores.append(cr_score)

        print(f"  → C={c_score} | AC={ac_score} | F={f_score} | CR={cr_score}")

        per_query_results.append({
            "id": item.get("id", f"q_{i}"),
            "question": question,
            "query_type": item.get("query_type", "unknown"),
            "memo": item.get("memo", ""),
            "expected_answer": expected_answer,
            "generated_answer": generated_answer,
            "correctness": judge_result["correctness"],
            "answer_coverage": judge_result["answer_coverage"],
            "faithfulness": judge_result["faithfulness"],
            "context_relevance": judge_result["context_relevance"],
            "hit_position": hit_pos,
            "recall_at_k": recall,
            "num_retrieved": len(retrieved_docs),
            "csv_short_circuit": csv_short_circuit,
            "source_type": source_type,
            "ground_truth_sources": gt_sources,
            "retrieved_sources": retrieved_sources,
            "latencies": state.get("latencies", {}),
        })

    # 집계
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
    parser = argparse.ArgumentParser(description="RAG E2E 평가 (LLM-as-Judge)")
    parser.add_argument("--label", type=str, default="current", help="결과 라벨 (e.g., before, after)")
    parser.add_argument("--top_k", type=int, default=5, help="검색 top-K (기본: 5)")
    parser.add_argument("--dataset", type=str, default=None, help="평가셋 경로")
    parser.add_argument("--judge_model", type=str, default=None, help="Judge LLM 모델 (기본: config 모델)")
    args = parser.parse_args()

    load_env()

    dataset_path = Path(args.dataset) if args.dataset else _get_eval_dir() / "eval_dataset.yaml"
    eval_items = load_eval_dataset(dataset_path)
    if not eval_items:
        return

    print("=" * 60)
    print(f"BiddingMate RAG E2E 평가 — LLM-as-Judge")
    print(f"  label={args.label}, top_k={args.top_k}")
    print(f"  pipeline={_WORKFLOW_MODE}")
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
    print(f"    Correctness:       {summary['avg_correctness']:.2f}")
    print(f"    Answer Coverage:   {summary['avg_answer_coverage']:.2f}")
    print(f"    Faithfulness:      {summary['avg_faithfulness']:.2f}")
    print(f"    Context Relevance: {summary['avg_context_relevance']:.2f}")
    print(f"  [Retrieval 보조 지표 — Source Level (Strict Match)]")
    print(f"    Recall@{args.top_k}:       {summary['recall_at_k_source']:.4f}")
    print(f"    MRR:               {summary['mrr_source']:.4f}")
    print(f"  평가 건수: {summary['num_evaluated']}/{summary['num_queries']}")
    print(f"  소요 시간: {elapsed:.1f}초")
    print(f"{'=' * 60}")

    # JSON 저장
    output_path = _get_eval_dir() / f"eval_results_{args.label}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[저장] {output_path}")


if __name__ == "__main__":
    main()
