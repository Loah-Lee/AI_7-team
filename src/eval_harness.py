from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from .langfuse_logger import get_langfuse_logger
from .rerank_openai import rerank_openai
from .rerank_rule import rerank_rule
from .rich_tfidf_search import ChunkRecord as RichChunkRecord
from .rich_tfidf_search import load_chunks_rich, search_tfidf, _build_tfidf


@dataclass(frozen=True)
class ChunkRecord:
    source_path: str
    chunk_index: int
    chunk_id: str
    text: str


@dataclass(frozen=True)
class QueryRecord:
    query_id: str
    query: str
    gold: List[Tuple[str, int]]


def _log_start(input_path: Path, output_path: Path) -> None:
    print(f"INGEST START | input={input_path} | output={output_path}")


def _log_ok(stage: str, input_path: Path, output_path: Path) -> None:
    print(f"INGEST OK | {stage} | {input_path} -> {output_path}")


def _log_fail(stage: str, input_path: Path, exc: Exception) -> None:
    print(f"INGEST FAIL | {stage} | {input_path} | {type(exc).__name__}: {exc}")


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[0-9A-Za-z가-힣]+", text.lower())


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _chunk_id(text: str) -> str:
    normalized = _normalize_text(text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _extract_sections(text: str) -> List[str]:
    sections = []
    section_map = {
        "보증금": ["보증금", "입찰보증", "보증"],
        "제출": ["제출", "마감", "접수"],
        "기간": ["기간", "개월", "착수", "종료", "일정"],
        "문의처": ["문의", "연락처", "전화", "이메일", "담당자"],
        "과업범위": ["과업", "범위", "주요 업무", "수행 내용"],
    }
    for key, toks in section_map.items():
        for tok in toks:
            if tok in text:
                sections.append(key)
                break
    return sections


def _qual_score_top1(query: str, snippet: str) -> Tuple[int, str]:
    q = query.strip()
    s = snippet.strip()
    if not q or not s:
        return 0, "unrelated"

    q_lower = q.lower()
    s_lower = s.lower()

    keyword_match = any(tok in s_lower for tok in _tokenize(q_lower))
    has_value = bool(
        re.search(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", s)
        or re.search(r"\d{1,2}\s*월\s*\d{1,2}\s*일", s)
        or re.search(r"\d+%|\d+\s*퍼센트", s)
        or re.search(r"\d[\d,]*\s*(원|만원|천원|억원)", s)
        or re.search(r"\d", s)
    )

    q_sections = _extract_sections(q)
    s_sections = _extract_sections(s)
    section_match = bool(set(q_sections) & set(s_sections)) if q_sections else False

    if keyword_match and has_value and section_match:
        return 2, "keyword+value+section"
    if keyword_match:
        if not has_value:
            return 1, "value_missing"
        if not section_match:
            return 1, "section_ambiguous"
        return 1, "keyword_partial"
    return 0, "unrelated"


def _score(query: str, chunk: ChunkRecord) -> float:
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return 0.0
    c_tokens = set(_tokenize(chunk.text))
    overlap = len(q_tokens & c_tokens)
    return overlap / max(len(q_tokens), 1)


def _iter_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_queries(path: Path) -> List[QueryRecord]:
    records: List[QueryRecord] = []
    for row in _iter_jsonl(path):
        gold_list = row.get("gold", [])
        gold_pairs: List[Tuple[str, int]] = []
        for item in gold_list:
            if not isinstance(item, dict):
                continue
            source_path = str(item.get("source_path", ""))
            try:
                chunk_index = int(item.get("chunk_index", -1))
            except Exception:
                chunk_index = -1
            if source_path and chunk_index >= 0:
                gold_pairs.append((source_path, chunk_index))

        records.append(
            QueryRecord(
                query_id=str(row.get("query_id", "")),
                query=str(row.get("query", "")),
                gold=gold_pairs,
            )
        )
    return records


def load_chunks(chunks_dir: Path) -> List[ChunkRecord]:
    records: List[ChunkRecord] = []
    if not chunks_dir.exists():
        return records

    for path in sorted(chunks_dir.rglob("*.jsonl")):
        for row in _iter_jsonl(path):
            source_path = str(row.get("source_path", ""))
            try:
                chunk_index = int(row.get("chunk_index", -1))
            except Exception:
                chunk_index = -1
            chunk_id = str(row.get("chunk_id", "")).strip()
            text = str(row.get("text", ""))
            if source_path and chunk_index >= 0:
                records.append(
                    ChunkRecord(
                        source_path=source_path,
                        chunk_index=chunk_index,
                        chunk_id=chunk_id or _chunk_id(text),
                        text=text,
                    )
                )
    return records


class RetrieverBase:
    name = "base"

    def retrieve(self, query: str, chunks: Sequence[ChunkRecord], k: int) -> List[ChunkRecord]:
        raise NotImplementedError


class RetrieverA(RetrieverBase):
    name = "A"

    def retrieve(self, query: str, chunks: Sequence[ChunkRecord], k: int) -> List[ChunkRecord]:
        scored = [(chunk, _score(query, chunk)) for chunk in chunks]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [chunk for chunk, _ in scored[:k]]


class RetrieverB(RetrieverBase):
    name = "B"

    def __init__(self, chunks: Sequence[RichChunkRecord]) -> None:
        self._chunks = list(chunks)
        self._vectors, self._idf = _build_tfidf(self._chunks) if self._chunks else ([], {})

    def retrieve(self, query: str, chunks: Sequence[ChunkRecord], k: int) -> List[ChunkRecord]:
        if not self._chunks:
            return []
        rich_results = search_tfidf(query, self._chunks, self._vectors, self._idf, k=k)
        return [
            ChunkRecord(
                source_path=item.source_path,
                chunk_index=item.chunk_index,
                chunk_id=_chunk_id(item.text),
                text=item.text,
            )
            for item in rich_results
        ]


def evaluate_query(
    query: QueryRecord,
    retrieved: Sequence[ChunkRecord],
) -> Dict[str, float]:
    gold_set = set(query.gold)
    rank: int | None = None
    for idx, item in enumerate(retrieved, start=1):
        key = (item.source_path, item.chunk_index)
        if key in gold_set:
            rank = idx
            break

    hit_at_5 = 1.0 if rank is not None and rank <= 5 else 0.0
    hit_at_10 = 1.0 if rank is not None and rank <= 10 else 0.0
    mrr = 1.0 / rank if rank is not None and rank > 0 else 0.0

    return {
        "hit@5": hit_at_5,
        "hit@10": hit_at_10,
        "mrr": mrr,
    }


def run_eval(
    input_path: Path = Path("configs/eval_queries.jsonl"),
    chunks_dir: Path = Path("data_chunks"),
    output_root: Path = Path("notebooks") / "runs",
    *,
    k: int = 10,
    rerank_mode: str = "none",
    llm_model: str = "gpt-5-nano",
    variant: str = "AB",
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / timestamp
    output_path = output_dir / "results.csv"

    _log_start(input_path, output_path)

    try:
        queries = load_queries(input_path)
        chunks = load_chunks(chunks_dir)
        rich_chunks = load_chunks_rich(Path("notebooks") / "data_chunks_rich")
        output_dir.mkdir(parents=True, exist_ok=True)

        retrievers: List[RetrieverBase] = []
        variant = variant.upper()
        if variant in {"A", "AB"}:
            retrievers.append(RetrieverA())
        if variant in {"B", "AB"}:
            retrievers.append(RetrieverB(rich_chunks))
        logger = get_langfuse_logger()

        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "query_id",
                    "query",
                    "variant",
                    "hit@5",
                    "hit@10",
                    "mrr",
                    "latency_ms",
                    "cost_usd",
                    "rerank_mode",
                    "top1_source_path",
                    "top1_chunk_index",
                    "top1_chunk_id",
                    "qual_score_top1",
                    "qual_reason_top1",
                ],
            )
            writer.writeheader()

            qual_scores: Dict[str, List[int]] = {}

            for query in queries:
                for retriever in retrievers:
                    start = time.perf_counter()
                    results = retriever.retrieve(query.query, chunks, k=k)
                    latency_ms = (time.perf_counter() - start) * 1000.0

                    cost_usd = 0.0
                    if rerank_mode != "none" and retriever.name == "B":
                        candidates = [
                            {
                                "text": item.text,
                                "source_path": item.source_path,
                                "chunk_id": item.chunk_id,
                            }
                            for item in results
                        ]
                        if rerank_mode == "rule":
                            reranked = rerank_rule(query.query, candidates)
                        else:
                            reranked, cost_usd = rerank_openai(
                                query.query, candidates, model=llm_model
                            )
                        id_map = {item.chunk_id: item for item in results}
                        results = [
                            id_map[item.get("chunk_id", "")]
                            for item in reranked
                            if item.get("chunk_id", "") in id_map
                        ]

                    metrics = evaluate_query(query, results)
                    top1 = results[0] if results else None
                    qual_score, qual_reason = _qual_score_top1(
                        query.query, top1.text if top1 else ""
                    )

                    row = {
                        "query_id": query.query_id,
                        "query": query.query,
                        "variant": retriever.name,
                        "hit@5": metrics["hit@5"],
                        "hit@10": metrics["hit@10"],
                        "mrr": metrics["mrr"],
                        "latency_ms": round(latency_ms, 3),
                        "cost_usd": cost_usd,
                        "rerank_mode": rerank_mode,
                        "top1_source_path": top1.source_path if top1 else "",
                        "top1_chunk_index": top1.chunk_index if top1 else "",
                        "top1_chunk_id": top1.chunk_id if top1 else "",
                        "qual_score_top1": qual_score,
                        "qual_reason_top1": qual_reason,
                    }

                    writer.writerow(row)
                    logger.log_trace(
                        name="eval_query",
                        payload={
                            "query_id": query.query_id,
                            "variant": retriever.name,
                            "latency_ms": row["latency_ms"],
                            "metrics": metrics,
                            "rerank_mode": rerank_mode,
                            "top1": {
                                "source_path": row["top1_source_path"],
                                "chunk_index": row["top1_chunk_index"],
                                "chunk_id": row["top1_chunk_id"],
                            },
                            "qual_score_top1": row["qual_score_top1"],
                            "qual_reason_top1": row["qual_reason_top1"],
                        },
                    )
                    key = f"{retriever.name}:{rerank_mode}"
                    qual_scores.setdefault(key, []).append(int(qual_score))

        if qual_scores:
            print("QUAL SUMMARY | variant:rerank | qual_score_top1_avg")
            for key, scores in qual_scores.items():
                avg = sum(scores) / max(len(scores), 1)
                print(f"{key} | {avg:.3f}")

        _log_ok("eval", input_path, output_path)
        return output_path
    except Exception as exc:
        _log_fail("eval", input_path, exc)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerank", choices=["none", "rule", "llm"], default="none")
    parser.add_argument("--llm-model", default="gpt-5-nano")
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument("--variant", choices=["A", "B", "AB"], default="AB")
    args = parser.parse_args()

    run_eval(
        k=args.topk,
        rerank_mode=args.rerank,
        llm_model=args.llm_model,
        variant=args.variant,
    )
