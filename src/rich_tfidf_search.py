from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class ChunkRecord:
    source_path: str
    chunk_index: int
    text: str
    metadata: Dict[str, object] | None = None


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[0-9A-Za-z가-힣]+", text.lower())


def _iter_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_chunks_rich(chunks_dir: Path) -> List[ChunkRecord]:
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
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else None
            if source_path and chunk_index >= 0:
                records.append(
                    ChunkRecord(
                        source_path=source_path,
                        chunk_index=chunk_index,
                        text=text,
                        metadata=metadata,
                    )
                )
    return records


def _build_tfidf(chunks: Sequence[ChunkRecord]) -> Tuple[List[Dict[str, float]], Dict[str, float]]:
    df: Dict[str, int] = {}
    docs_tokens: List[List[str]] = []
    for chunk in chunks:
        tokens = _tokenize(chunk.text)
        docs_tokens.append(tokens)
        unique = set(tokens)
        for tok in unique:
            df[tok] = df.get(tok, 0) + 1

    n_docs = max(len(chunks), 1)
    idf = {tok: math.log((n_docs + 1) / (count + 1)) + 1.0 for tok, count in df.items()}

    vectors: List[Dict[str, float]] = []
    for tokens in docs_tokens:
        tf: Dict[str, int] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1
        if not tf:
            vectors.append({})
            continue
        max_tf = max(tf.values())
        vec = {tok: (cnt / max_tf) * idf.get(tok, 0.0) for tok, cnt in tf.items()}
        vectors.append(vec)

    return vectors, idf


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    for k, v in a.items():
        dot += v * b.get(k, 0.0)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_tfidf(
    query: str,
    chunks: Sequence[ChunkRecord],
    vectors: Sequence[Dict[str, float]],
    idf: Dict[str, float],
    *,
    k: int = 10,
) -> List[ChunkRecord]:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []

    q_tf: Dict[str, int] = {}
    for tok in q_tokens:
        q_tf[tok] = q_tf.get(tok, 0) + 1
    max_tf = max(q_tf.values())
    q_vec = {tok: (cnt / max_tf) * idf.get(tok, 0.0) for tok, cnt in q_tf.items()}

    scored = []
    for chunk, vec in zip(chunks, vectors, strict=False):
        scored.append((chunk, _cosine(q_vec, vec)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [chunk for chunk, _ in scored[:k]]
