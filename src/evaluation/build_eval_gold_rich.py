from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from ..retrievers.rich_tfidf_search import (
    ChunkRecord,
    _build_tfidf,
    load_chunks_rich,
    tfidf_scores,
)
from .gold_rules import gold_bonus


def _iter_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _build_gold_for_query(
    query: str,
    chunks: List[ChunkRecord],
    vectors: List[Dict[str, float]],
    idf: Dict[str, float],
    *,
    top_k: int,
) -> List[Dict[str, object]]:
    base_scores = tfidf_scores(query, chunks, vectors, idf)

    ranked: List[Tuple[float, int]] = []
    for i, chunk in enumerate(chunks):
        score = float(base_scores[i])
        bonus, ok = gold_bonus(
            query=query,
            source_path=chunk.source_path,
            text=chunk.text,
            metadata=chunk.metadata if isinstance(chunk.metadata, dict) else None,
        )
        if not ok:
            continue
        score += bonus
        ranked.append((score, i))

    ranked.sort(key=lambda x: x[0], reverse=True)
    selected: List[Dict[str, object]] = []
    seen: set[Tuple[str, int]] = set()
    for score, i in ranked:
        chunk = chunks[i]
        key = (chunk.source_path, chunk.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        selected.append(
            {
                "source_path": chunk.source_path,
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "reason": f"auto_refresh_score={score:.4f}",
            }
        )
        if len(selected) >= top_k:
            break
    return selected


def build_eval_gold(
    *,
    input_queries_path: Path,
    chunks_dir: Path,
    output_path: Path,
    top_k: int = 3,
) -> None:
    queries = list(_iter_jsonl(input_queries_path))
    chunks = load_chunks_rich(chunks_dir)
    vectors, idf = _build_tfidf(chunks) if chunks else ([], {})

    refreshed_rows: List[Dict[str, object]] = []
    for row in queries:
        query = str(row.get("query", "")).strip()
        if not query:
            continue
        gold = _build_gold_for_query(query, chunks, vectors, idf, top_k=top_k)
        refreshed_rows.append(
            {
                "query_id": str(row.get("query_id", "")),
                "query": query,
                "gold": gold,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in refreshed_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        f"INGEST OK | build_eval_gold_rich | {input_queries_path} -> {output_path} | "
        f"queries={len(refreshed_rows)} | chunks={len(chunks)} | top_k={top_k}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(Path("configs") / "eval_queries_v2_rich.jsonl"),
    )
    parser.add_argument(
        "--chunks-dir",
        default=str(Path("notebooks") / "data_chunks_rich"),
    )
    parser.add_argument(
        "--output",
        default=str(Path("configs") / "eval_queries_v2_rich.jsonl"),
    )
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    build_eval_gold(
        input_queries_path=Path(args.input),
        chunks_dir=Path(args.chunks_dir),
        output_path=Path(args.output),
        top_k=args.top_k,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
