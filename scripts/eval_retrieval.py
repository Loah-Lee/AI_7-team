#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv

from src.evaluation.llm_judge import judge_rag_response
from src.graph.workflow import RAGChatbot


def _to_int(value: Any) -> int | None:
    try:
        num = int(value)
    except Exception:
        return None
    return num if num > 0 else None


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").strip()


def _norm_source(source: str) -> str:
    return _nfc(Path(source or "").name)


def _ctx_source(ctx: Dict[str, Any]) -> str:
    metadata = ctx.get("metadata") if isinstance(ctx.get("metadata"), dict) else {}
    meta = metadata.get("meta") if isinstance(metadata.get("meta"), dict) else {}
    file_name = meta.get("파일명")
    if isinstance(file_name, str) and file_name.strip():
        return _norm_source(file_name)
    return _norm_source(str(ctx.get("source_path", "")))


def _ctx_page(ctx: Dict[str, Any]) -> int | None:
    metadata = ctx.get("metadata") if isinstance(ctx.get("metadata"), dict) else {}
    refs = metadata.get("page_refs")
    if not isinstance(refs, list):
        return None
    for ref in refs:
        try:
            page = int(ref)
        except Exception:
            continue
        if page > 0:
            return page
    return None


def _build_context_text(retrieved: List[Dict[str, Any]], limit: int) -> str:
    if not retrieved:
        return "(검색 결과 없음)"
    lines: List[str] = []
    for idx, ctx in enumerate(retrieved[:limit], start=1):
        source = _ctx_source(ctx)
        page = _ctx_page(ctx)
        text = " ".join(str(ctx.get("text", "")).split())
        if len(text) > 1200:
            text = text[:1200] + "..."
        page_text = f"p.{page}" if page is not None else "p.-"
        lines.append(f"[{idx}] {source} ({page_text})\n{text}")
    return "\n\n".join(lines)


def _extract_ground_truth_sources(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    gt = item.get("ground_truth") if isinstance(item.get("ground_truth"), dict) else {}
    raw_sources = gt.get("sources")
    parsed: List[Dict[str, Any]] = []

    if isinstance(raw_sources, list):
        for entry in raw_sources:
            if isinstance(entry, dict):
                source = str(entry.get("source", "")).strip()
                page = _to_int(entry.get("page"))
            else:
                source = str(entry).strip()
                page = None
            if source:
                parsed.append({"source": source, "page": page})

    if not parsed:
        source = str(gt.get("source", "")).strip()
        page = _to_int(gt.get("page"))
        if source:
            parsed.append({"source": source, "page": page})

    dedup: List[Dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()
    for entry in parsed:
        key = (_norm_source(entry["source"]), entry.get("page"))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(entry)
    return dedup


def _hit_positions_multi(
    retrieved: List[Dict[str, Any]],
    *,
    gt_sources: List[Dict[str, Any]],
    top_k: int,
) -> Dict[str, Any]:
    source_hits: List[int | None] = []
    page_hits: List[int | None] = []
    retrieved_top = retrieved[:top_k]

    for gt in gt_sources:
        target_source = _norm_source(str(gt.get("source", "")))
        target_page = _to_int(gt.get("page"))
        hit_source: int | None = None
        hit_page: int | None = None

        for rank, ctx in enumerate(retrieved_top, start=1):
            source = _ctx_source(ctx)
            page = _ctx_page(ctx)
            if hit_source is None and source == target_source:
                hit_source = rank
            if (
                hit_page is None
                and target_page is not None
                and source == target_source
                and page == target_page
            ):
                hit_page = rank
            if hit_source is not None and (target_page is None or hit_page is not None):
                break

        source_hits.append(hit_source)
        page_hits.append(hit_page)

    source_targets = len(gt_sources)
    source_hit_count = sum(1 for hit in source_hits if hit is not None)
    source_recall = (source_hit_count / source_targets) if source_targets > 0 else 0.0
    source_mrr = (
        sum((1.0 / float(hit)) if hit is not None else 0.0 for hit in source_hits) / source_targets
        if source_targets > 0
        else 0.0
    )

    page_targets = sum(1 for gt in gt_sources if _to_int(gt.get("page")) is not None)
    page_hit_count = sum(1 for hit in page_hits if hit is not None)
    page_recall = (page_hit_count / page_targets) if page_targets > 0 else 0.0
    page_mrr = (
        sum((1.0 / float(hit)) if hit is not None else 0.0 for hit in page_hits) / page_targets
        if page_targets > 0
        else 0.0
    )

    first_source_hit = next((hit for hit in source_hits if hit is not None), None)
    first_page_hit = next((hit for hit in page_hits if hit is not None), None)

    return {
        "hit_position": first_source_hit,
        "hit_position_page": first_page_hit,
        "hit_positions_all": source_hits,
        "hit_positions_page_all": page_hits,
        "source_targets": source_targets,
        "source_hits": source_hit_count,
        "page_targets": page_targets,
        "page_hits": page_hit_count,
        "recall_at_k_source": source_recall,
        "recall_at_k_page": page_recall,
        "mrr_source_query": source_mrr,
        "mrr_page_query": page_mrr,
    }


def _avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _load_dataset(path: Path) -> List[Dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError(f"dataset 형식이 올바르지 않습니다: {path}")
    return [x for x in raw if isinstance(x, dict)]


def run_eval(args: argparse.Namespace) -> Path:
    load_dotenv(".env")

    dataset = _load_dataset(Path(args.dataset))
    chatbot = RAGChatbot(
        retriever=str(args.retriever),
        rerank=str(args.rerank),
        top_k=int(args.top_k),
        context_k=int(args.context_k),
        chroma_collection=str(args.chroma_collection),
        chroma_org_filter=True,
        chroma_org_filter_mode="hard",
        chroma_noise_mode="hard",
        chroma_mmr=True,
        chroma_query_rewrite=True,
    )

    started = time.time()
    per_query: List[Dict[str, Any]] = []

    for item in dataset:
        qid = str(item.get("id", "")).strip()
        question = str(item.get("question", "")).strip()
        expected = str(item.get("expected_answer", "")).strip()
        query_type = str(item.get("query_type", "generic")).strip() or "generic"
        gt_sources = _extract_ground_truth_sources(item)
        primary_gt = gt_sources[0] if gt_sources else {"source": "", "page": None}
        gt_source = str(primary_gt.get("source", "")).strip()
        gt_page = _to_int(primary_gt.get("page"))

        result = chatbot.answer(question, model=str(args.answer_model))
        if str(result.get("status", "")) == "need_org":
            metadata_filter = (
                item.get("metadata_filter") if isinstance(item.get("metadata_filter"), dict) else {}
            )
            institution = str(metadata_filter.get("institution", "")).strip()
            if institution:
                result = chatbot.answer(f"{institution} {question}", model=str(args.answer_model))

        generated_answer = str(result.get("answer", "")).strip()
        retrieved = result.get("retrieved_contexts")
        if not isinstance(retrieved, list):
            retrieved = []

        hit_stat = _hit_positions_multi(
            retrieved,
            gt_sources=gt_sources,
            top_k=int(args.top_k),
        )

        context_text = _build_context_text(retrieved, limit=int(args.context_k))
        judge = judge_rag_response(
            question=question,
            expected_answer=expected,
            generated_answer=generated_answer,
            context=context_text,
            model=str(args.judge_model),
        )

        per_query.append(
            {
                "id": qid,
                "question": question,
                "query_type": query_type,
                "expected_answer": expected,
                "generated_answer": generated_answer,
                "correctness": judge["correctness"],
                "answer_coverage": judge["answer_coverage"],
                "faithfulness": judge["faithfulness"],
                "context_relevance": judge["context_relevance"],
                "hit_position": hit_stat["hit_position"],
                "recall_at_k": hit_stat["recall_at_k_source"],
                "hit_position_page": hit_stat["hit_position_page"],
                "recall_at_k_page": hit_stat["recall_at_k_page"],
                "num_retrieved": min(len(retrieved), int(args.top_k)),
                "ground_truth_source": gt_source,
                "ground_truth_page": gt_page,
                "ground_truth_sources": gt_sources,
                "source_targets": hit_stat["source_targets"],
                "source_hits": hit_stat["source_hits"],
                "page_targets": hit_stat["page_targets"],
                "page_hits": hit_stat["page_hits"],
                "hit_positions_all": hit_stat["hit_positions_all"],
                "hit_positions_page_all": hit_stat["hit_positions_page_all"],
                "mrr_source_query": hit_stat["mrr_source_query"],
                "mrr_page_query": hit_stat["mrr_page_query"],
                "status": str(result.get("status", "unknown")),
            }
        )

    elapsed = time.time() - started
    summary = {
        "num_queries": len(dataset),
        "num_evaluated": len(per_query),
        "top_k": int(args.top_k),
        "avg_correctness": round(_avg([float(x["correctness"]["score"]) for x in per_query]), 4),
        "avg_answer_coverage": round(
            _avg([float(x["answer_coverage"]["score"]) for x in per_query]), 4
        ),
        "avg_faithfulness": round(_avg([float(x["faithfulness"]["score"]) for x in per_query]), 4),
        "avg_context_relevance": round(
            _avg([float(x["context_relevance"]["score"]) for x in per_query]), 4
        ),
        "recall_at_k_source": round(_avg([float(x["recall_at_k"]) for x in per_query]), 4),
        "mrr_source": round(_avg([float(x["mrr_source_query"]) for x in per_query]), 4),
        "recall_at_k_page": round(_avg([float(x["recall_at_k_page"]) for x in per_query]), 4),
        "mrr_page": round(_avg([float(x["mrr_page_query"]) for x in per_query]), 4),
    }
    meta = {
        "label": str(args.label),
        "judge_model": str(args.judge_model),
        "answer_model": str(args.answer_model),
        "elapsed_seconds": round(elapsed, 1),
        "generated_date": datetime.now().strftime("%Y-%m-%d"),
    }
    combined = {"summary": summary, "per_query": per_query, "meta": meta}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_root) / f"main_eval_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "per_query.json").write_text(
        json.dumps(per_query, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "eval_results_current.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    eval_resources_dir = Path("eval_resources")
    eval_resources_dir.mkdir(parents=True, exist_ok=True)
    (eval_resources_dir / "eval_results_current.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = out_dir / "eval_results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "query_type",
                "status",
                "correctness",
                "answer_coverage",
                "faithfulness",
                "context_relevance",
                "recall_at_k",
                "recall_at_k_page",
                "question",
                "generated_answer",
            ],
        )
        writer.writeheader()
        for row in per_query:
            writer.writerow(
                {
                    "id": row["id"],
                    "query_type": row["query_type"],
                    "status": row["status"],
                    "correctness": row["correctness"]["score"],
                    "answer_coverage": row["answer_coverage"]["score"],
                    "faithfulness": row["faithfulness"]["score"],
                    "context_relevance": row["context_relevance"]["score"],
                    "recall_at_k": row["recall_at_k"],
                    "recall_at_k_page": row["recall_at_k_page"],
                    "question": row["question"],
                    "generated_answer": row["generated_answer"],
                }
            )

    print(f"output_dir={out_dir}")
    print(f"summary={out_dir / 'summary.json'}")
    print(f"per_query={out_dir / 'per_query.json'}")
    print(f"eval_json={eval_resources_dir / 'eval_results_current.json'}")
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="eval_resources/eval_dataset.yaml")
    parser.add_argument("--output-root", default="results")
    parser.add_argument("--label", default="current")
    parser.add_argument("--retriever", choices=["chroma", "tfidf", "hybrid", "dense"], default="chroma")
    parser.add_argument("--rerank", choices=["none", "rule", "llm"], default="none")
    parser.add_argument("--top_k", type=int, default=5)
    parser.add_argument("--context_k", type=int, default=20)
    parser.add_argument("--answer-model", default="gpt-5-nano")
    parser.add_argument("--judge-model", default="gpt-5-mini")
    parser.add_argument("--chroma-collection", default="rfp_b_oai_clean_v1")
    args = parser.parse_args()

    run_eval(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
