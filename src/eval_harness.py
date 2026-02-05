from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from .langfuse_logger import get_langfuse_logger
from .rich_tfidf_search import ChunkRecord as RichChunkRecord
from .rich_tfidf_search import load_chunks_rich, search_tfidf, _build_tfidf


@dataclass(frozen=True)
class ChunkRecord:
    source_path: str
    chunk_index: int
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
            text = str(row.get("text", ""))
            if source_path and chunk_index >= 0:
                records.append(
                    ChunkRecord(
                        source_path=source_path,
                        chunk_index=chunk_index,
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

        retrievers: List[RetrieverBase] = [RetrieverA(), RetrieverB(rich_chunks)]
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
                    "top1_source_path",
                    "top1_chunk_index",
                ],
            )
            writer.writeheader()

            for query in queries:
                for retriever in retrievers:
                    start = time.perf_counter()
                    results = retriever.retrieve(query.query, chunks, k=k)
                    latency_ms = (time.perf_counter() - start) * 1000.0

                    metrics = evaluate_query(query, results)
                    top1 = results[0] if results else None

                    row = {
                        "query_id": query.query_id,
                        "query": query.query,
                        "variant": retriever.name,
                        "hit@5": metrics["hit@5"],
                        "hit@10": metrics["hit@10"],
                        "mrr": metrics["mrr"],
                        "latency_ms": round(latency_ms, 3),
                        "cost_usd": 0.0,
                        "top1_source_path": top1.source_path if top1 else "",
                        "top1_chunk_index": top1.chunk_index if top1 else "",
                    }

                    writer.writerow(row)
                    logger.log_trace(
                        name="eval_query",
                        payload={
                            "query_id": query.query_id,
                            "variant": retriever.name,
                            "latency_ms": row["latency_ms"],
                            "metrics": metrics,
                            "top1": {
                                "source_path": row["top1_source_path"],
                                "chunk_index": row["top1_chunk_index"],
                            },
                        },
                    )

        _log_ok("eval", input_path, output_path)
        return output_path
    except Exception as exc:
        _log_fail("eval", input_path, exc)
        raise


if __name__ == "__main__":
    run_eval()
