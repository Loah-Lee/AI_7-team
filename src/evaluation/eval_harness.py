from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from ..utils.langfuse_logger import get_langfuse_logger
from .rerank_openai import rerank_openai
from .rerank_rule import rerank_rule
from .gold_rules import extract_org_prefix, gold_bonus, metadata_text, org_match
from ..retrievers.dense_openai import DenseEmbedder, DenseIndex
from ..retrievers.rich_tfidf_search import ChunkRecord as RichChunkRecord
from ..retrievers.rich_tfidf_search import load_chunks_rich, search_tfidf, tfidf_scores, _build_tfidf


@dataclass(frozen=True)
class ChunkRecord:
    source_path: str
    chunk_index: int
    chunk_id: str
    text: str
    metadata: Dict[str, object] | None = None


@dataclass(frozen=True)
class QueryRecord:
    query_id: str
    query: str
    gold: List[Tuple[str, int]]
    gold_chunk_ids: List[str]


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


def _normalize_source_path(path: str) -> str:
    # HFS+/macOS 환경에서 NFD/NFC 혼용으로 키 매칭이 깨지는 문제를 방지
    return unicodedata.normalize("NFC", path).strip()


def _normalize_query_text(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").strip()


_PERCENT_RE = re.compile(r"\d+(\.\d+)?\s*%|\d+(\.\d+)?\s*퍼센트|(?:100|백)\s*분의\s*\d+(\.\d+)?")
_MONEY_RE = re.compile(r"\d[\d,]*(\.\d+)?\s*(원|만원|천원|억원)")
_DATE_RE = re.compile(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일")
_PERIOD_RE = re.compile(r"\d+\s*(일|개월|월|년)")
_CONTACT_RE = re.compile(
    r"(전화|연락처|담당자|이메일|e-mail)|\b\d{2,4}-\d{3,4}-\d{4}\b|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    re.IGNORECASE,
)


def _query_kind(query: str) -> str:
    q = query.strip()
    if re.search(r"비율|퍼센트|%", q):
        return "percent"
    if re.search(r"예산|금액|비용|사업비|얼마", q):
        return "money"
    if re.search(r"마감|일자|언제|날짜", q):
        return "date"
    if re.search(r"기간|며칠|몇\s*개월", q):
        return "period"
    if re.search(r"문의|연락처|전화|이메일|담당자", q):
        return "contact"
    return "generic"


def _has_kind_signal(text: str, kind: str) -> bool:
    if kind == "percent":
        return bool(_PERCENT_RE.search(text))
    if kind == "money":
        return bool(_MONEY_RE.search(text))
    if kind == "date":
        return bool(_DATE_RE.search(text))
    if kind == "period":
        return bool(_PERIOD_RE.search(text))
    if kind == "contact":
        return bool(_CONTACT_RE.search(text))
    return True


def _query_type_weight_bonus(
    *,
    query: str,
    source_path: str,
    text: str,
    metadata: Dict[str, object] | None,
) -> float:
    kind = _query_kind(query)
    merged = f"{source_path} {text} {metadata_text(metadata)}"
    bonus = 0.0

    # 기관명이 명시된 질의는 source/meta에 기관 흔적이 있는 청크를 우선
    if extract_org_prefix(query) and org_match(
        query=query,
        source_path=source_path,
        text=text,
        metadata=metadata,
        meta_only=False,
    ):
        bonus += 0.18

    if _has_kind_signal(merged, kind):
        if kind in {"percent", "money"}:
            bonus += 0.24
        elif kind in {"date", "period"}:
            bonus += 0.20
        elif kind == "contact":
            bonus += 0.16
    elif kind in {"percent", "money", "date", "period", "contact"}:
        # 숫자/기관 질의에서 시그널이 전혀 없는 청크는 약한 패널티
        bonus -= 0.08

    return bonus


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
    if q and not s:
        return 0, "문서에 해당 정보가 없습니다."
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
        gold_chunk_ids: List[str] = []
        for item in gold_list:
            if not isinstance(item, dict):
                continue
            source_path = _normalize_source_path(str(item.get("source_path", "")))
            try:
                chunk_index = int(item.get("chunk_index", -1))
            except Exception:
                chunk_index = -1
            if source_path and chunk_index >= 0:
                gold_pairs.append((source_path, chunk_index))
            chunk_id = str(item.get("chunk_id", "")).strip()
            if chunk_id:
                gold_chunk_ids.append(chunk_id)

        records.append(
            QueryRecord(
                query_id=str(row.get("query_id", "")),
                query=_normalize_query_text(str(row.get("query", ""))),
                gold=gold_pairs,
                gold_chunk_ids=gold_chunk_ids,
            )
        )
    return records


def load_chunks(chunks_dir: Path) -> List[ChunkRecord]:
    records: List[ChunkRecord] = []
    if not chunks_dir.exists():
        return records

    for path in sorted(chunks_dir.rglob("*.jsonl")):
        for row in _iter_jsonl(path):
            source_path = _normalize_source_path(str(row.get("source_path", "")))
            try:
                chunk_index = int(row.get("chunk_index", -1))
            except Exception:
                chunk_index = -1
            chunk_id = str(row.get("chunk_id", "")).strip()
            text = str(row.get("text", ""))
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else None
            if source_path and chunk_index >= 0:
                records.append(
                    ChunkRecord(
                        source_path=source_path,
                        chunk_index=chunk_index,
                        chunk_id=chunk_id or _chunk_id(text),
                        text=text,
                        metadata=metadata,
                    )
                )
    return records


def load_joined_metadata(path: Path) -> Dict[Tuple[str, int], Dict[str, object]]:
    result: Dict[Tuple[str, int], Dict[str, object]] = {}
    if not path.exists():
        return result

    for row in _iter_jsonl(path):
        source_path = _normalize_source_path(str(row.get("source_path", "")))
        try:
            chunk_index = int(row.get("chunk_index", -1))
        except Exception:
            chunk_index = -1
        metadata = row.get("metadata")
        if source_path and chunk_index >= 0 and isinstance(metadata, dict):
            result[(source_path, chunk_index)] = metadata
    return result


class RetrieverBase:
    name = "base"
    kind = "base"

    def retrieve(self, query: str, chunks: Sequence[ChunkRecord], k: int) -> List[ChunkRecord]:
        raise NotImplementedError


class TfidfRetriever(RetrieverBase):
    kind = "tfidf"

    def __init__(self, variant: str, chunks: Sequence[ChunkRecord]) -> None:
        self.name = variant
        self._chunks = [
            RichChunkRecord(
                source_path=chunk.source_path,
                chunk_index=chunk.chunk_index,
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                metadata=chunk.metadata if isinstance(chunk.metadata, dict) else None,
            )
            for chunk in chunks
        ]
        self._vectors, self._idf = _build_tfidf(self._chunks) if self._chunks else ([], {})

    def retrieve(self, query: str, chunks: Sequence[ChunkRecord], k: int) -> List[ChunkRecord]:
        if not self._chunks:
            return []
        rich_results = search_tfidf(query, self._chunks, self._vectors, self._idf, k=k)
        return [
            ChunkRecord(
                source_path=item.source_path,
                chunk_index=item.chunk_index,
                chunk_id=item.chunk_id,
                text=item.text,
                metadata=item.metadata if isinstance(item.metadata, dict) else None,
            )
            for item in rich_results
        ]


class DenseRetriever(RetrieverBase):
    kind = "dense"

    def __init__(
        self,
        variant: str,
        index: DenseIndex,
        embedder: DenseEmbedder,
        table_multiplier: float,
        chunks: Sequence[ChunkRecord] | None = None,
    ) -> None:
        self.name = variant
        self._index = index
        self._embedder = embedder
        # 자체 생성 코드: 표 캡션 가중치 적용을 위한 설정
        self._table_multiplier = max(0.0, float(table_multiplier))
        self._table_map = {meta.chunk_id: meta.is_table for meta in self._index.meta}
        self._metadata_map: Dict[str, Dict[str, object]] = {}
        if chunks:
            self._metadata_map = {
                c.chunk_id: c.metadata
                for c in chunks
                if isinstance(c.metadata, dict)
            }

    def retrieve(self, query: str, chunks: Sequence[ChunkRecord], k: int) -> List[ChunkRecord]:
        query_vec = self._embedder.embed_query(query)
        scores = self._index.score_all(query_vec)
        if scores.size == 0:
            return []
        scored: List[Tuple[int, float]] = []
        for idx, score in enumerate(scores.tolist()):
            if self._table_multiplier != 1.0 and self._table_map.get(
                self._index.meta[idx].chunk_id, False
            ):
                # 자체 생성 코드: 표 청크 점수 가중치
                score *= self._table_multiplier
            scored.append((idx, float(score)))
        if k <= 0:
            return []
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: min(int(k), len(scored))]
        return [
            ChunkRecord(
                source_path=self._index.meta[i].source_path,
                chunk_index=self._index.meta[i].chunk_index,
                chunk_id=self._index.meta[i].chunk_id,
                text=self._index.meta[i].text,
                metadata=self._metadata_map.get(self._index.meta[i].chunk_id),
            )
            for i, _ in top
        ]


class HybridRetriever(RetrieverBase):
    kind = "hybrid"

    def __init__(
        self,
        variant: str,
        chunks: Sequence[ChunkRecord],
        index: DenseIndex,
        embedder: DenseEmbedder,
        alpha: float,
        table_multiplier: float,
        org_hard_filter: bool = False,
    ) -> None:
        self.name = variant
        self._chunks = [
            RichChunkRecord(
                source_path=chunk.source_path,
                chunk_index=chunk.chunk_index,
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                metadata=chunk.metadata if isinstance(chunk.metadata, dict) else None,
            )
            for chunk in chunks
        ]
        self._vectors, self._idf = _build_tfidf(self._chunks) if self._chunks else ([], {})
        self._index = index
        self._embedder = embedder
        self._alpha = max(0.0, min(1.0, float(alpha)))
        self._org_hard_filter = bool(org_hard_filter)
        # 자체 생성 코드: 표 캡션 가중치 적용을 위한 설정
        self._table_multiplier = max(0.0, float(table_multiplier))
        self._table_map = {meta.chunk_id: meta.is_table for meta in self._index.meta}

    def retrieve(self, query: str, chunks: Sequence[ChunkRecord], k: int) -> List[ChunkRecord]:
        if not self._chunks:
            return []
        lexical_scores = tfidf_scores(query, self._chunks, self._vectors, self._idf)
        query_vec = self._embedder.embed_query(query)
        dense_scores = self._index.score_all(query_vec)
        dense_map = {
            meta.chunk_id: float(score)
            for meta, score in zip(self._index.meta, dense_scores, strict=False)
        }

        if self._org_hard_filter:
            candidate_indices = [
                idx
                for idx, chunk in enumerate(self._chunks)
                if org_match(
                    query=query,
                    source_path=chunk.source_path,
                    text=chunk.text,
                    metadata=chunk.metadata if isinstance(chunk.metadata, dict) else None,
                    meta_only=True,
                )
            ]
            if not candidate_indices:
                return []
        else:
            candidate_indices = list(range(len(self._chunks)))

        scored = []
        for idx in candidate_indices:
            chunk = self._chunks[idx]
            dense_score = dense_map.get(chunk.chunk_id, 0.0)
            score = self._alpha * lexical_scores[idx] + (1.0 - self._alpha) * dense_score
            bonus, ok = gold_bonus(
                query=query,
                source_path=chunk.source_path,
                text=chunk.text,
                metadata=chunk.metadata if isinstance(chunk.metadata, dict) else None,
            )
            if self._org_hard_filter and not ok:
                continue
            score += bonus
            score += _query_type_weight_bonus(
                query=query,
                source_path=chunk.source_path,
                text=chunk.text,
                metadata=chunk.metadata if isinstance(chunk.metadata, dict) else None,
            )
            if self._table_multiplier != 1.0 and self._table_map.get(chunk.chunk_id, False):
                # 자체 생성 코드: 표 청크 점수 가중치
                score *= self._table_multiplier
            scored.append((idx, score))

        if not scored:
            return []

        # source 내에서 가장 유망한 청크 주변(±1, ±2)에 소폭 가중치를 더해
        # 숫자/조건이 분리된 청크를 상단으로 끌어올린다.
        source_anchor: Dict[str, int] = {}
        for idx, score in sorted(scored, key=lambda x: x[1], reverse=True):
            src = self._chunks[idx].source_path
            if src not in source_anchor:
                source_anchor[src] = self._chunks[idx].chunk_index

        adjusted: List[Tuple[int, float]] = []
        for idx, score in scored:
            chunk = self._chunks[idx]
            anchor = source_anchor.get(chunk.source_path, -1)
            if anchor >= 0 and chunk.chunk_index >= 0:
                dist = abs(chunk.chunk_index - anchor)
                if dist == 1:
                    score += 0.10
                elif dist == 2:
                    score += 0.05
            adjusted.append((idx, score))

        adjusted.sort(key=lambda x: x[1], reverse=True)
        top = adjusted[:k]
        return [
            ChunkRecord(
                source_path=self._chunks[i].source_path,
                chunk_index=self._chunks[i].chunk_index,
                chunk_id=self._chunks[i].chunk_id,
                text=self._chunks[i].text,
                metadata=self._chunks[i].metadata if isinstance(self._chunks[i].metadata, dict) else None,
            )
            for i, _ in top
        ]


def evaluate_query(
    query: QueryRecord,
    retrieved: Sequence[ChunkRecord],
) -> Dict[str, float]:
    gold_set = {(_normalize_source_path(src), idx) for src, idx in query.gold}
    gold_chunk_id_set = {cid for cid in query.gold_chunk_ids if cid}
    rank: int | None = None
    retrieved_keys = [(_normalize_source_path(item.source_path), item.chunk_index) for item in retrieved]
    retrieved_chunk_ids = [item.chunk_id for item in retrieved]
    for idx, item in enumerate(retrieved, start=1):
        key = (_normalize_source_path(item.source_path), item.chunk_index)
        if key in gold_set or (item.chunk_id and item.chunk_id in gold_chunk_id_set):
            rank = idx
            break

    denom = 0
    if gold_chunk_id_set:
        denom = len(gold_chunk_id_set)
    elif gold_set:
        denom = len(gold_set)

    if denom > 0:
        found_top5 = 0
        found_top10 = 0
        if gold_chunk_id_set:
            found_top5 = len(set(retrieved_chunk_ids[:5]) & gold_chunk_id_set)
            found_top10 = len(set(retrieved_chunk_ids[:10]) & gold_chunk_id_set)
        else:
            found_top5 = len(set(retrieved_keys[:5]) & gold_set)
            found_top10 = len(set(retrieved_keys[:10]) & gold_set)
        recall_at_5 = found_top5 / denom
        recall_at_10 = found_top10 / denom
    else:
        recall_at_5 = 0.0
        recall_at_10 = 0.0
    mrr = 1.0 / rank if rank is not None and rank > 0 else 0.0

    return {
        "recall@5": recall_at_5,
        "recall@10": recall_at_10,
        "mrr": mrr,
    }


def _rerank_if_needed(
    query: QueryRecord,
    retriever: RetrieverBase,
    results: List[ChunkRecord],
    rerank_mode: str,
    llm_model: str,
) -> Tuple[List[ChunkRecord], float]:
    # 자체 생성 코드: 공통 재랭크 로직
    cost_usd = 0.0
    if rerank_mode != "none" and retriever.name == "B":
        if rerank_mode == "rule":
            candidates = [
                {
                    "text": item.text,
                    "source_path": item.source_path,
                    "chunk_id": item.chunk_id,
                    "metadata": item.metadata if isinstance(item.metadata, dict) else None,
                }
                for item in results
            ]
            reranked = rerank_rule(query.query, candidates)
        else:
            candidates = [
                {
                    "text": item.text,
                    "source_path": item.source_path,
                    "chunk_id": item.chunk_id,
                }
                for item in results
            ]
            reranked, cost_usd = rerank_openai(query.query, candidates, model=llm_model)
        id_map = {item.chunk_id: item for item in results}
        results = [
            id_map[item.get("chunk_id", "")]
            for item in reranked
            if item.get("chunk_id", "") in id_map
        ]
    return results, cost_usd


def _tune_hybrid_alpha(
    queries: Sequence[QueryRecord],
    *,
    variant: str,
    chunks_a: Sequence[ChunkRecord],
    chunks_b: Sequence[ChunkRecord],
    dense_a: DenseIndex | None,
    dense_b: DenseIndex | None,
    embedder: DenseEmbedder | None,
    k: int,
    rerank_mode: str,
    llm_model: str,
    table_multiplier: float,
) -> float:
    # 자체 생성 코드: 하이브리드 alpha 자동 튜닝
    candidates = [0.2, 0.4, 0.6, 0.8]
    best_alpha = candidates[0]
    best_score = (-1.0, -1.0, -1.0)

    for alpha in candidates:
        retrievers: List[RetrieverBase] = []
        if variant in {"A", "AB"}:
            if dense_a is None or embedder is None:
                raise RuntimeError("hybrid 인덱스(A)가 필요합니다.")
            retrievers.append(
                HybridRetriever("A", chunks_a, dense_a, embedder, alpha, table_multiplier)
            )
        if variant in {"B", "AB"}:
            if dense_b is None or embedder is None:
                raise RuntimeError("hybrid 인덱스(B)가 필요합니다.")
            retrievers.append(
                HybridRetriever("B", chunks_b, dense_b, embedder, alpha, table_multiplier)
            )

        total_hit5 = 0.0
        total_hit10 = 0.0
        total_mrr = 0.0
        count = 0
        for query in queries:
            for retriever in retrievers:
                chunks = chunks_a if retriever.name == "A" else chunks_b
                results = retriever.retrieve(query.query, chunks, k=k)
                results, _ = _rerank_if_needed(
                    query, retriever, results, rerank_mode=rerank_mode, llm_model=llm_model
                )
                metrics = evaluate_query(query, results)
                total_hit5 += metrics["recall@5"]
                total_hit10 += metrics["recall@10"]
                total_mrr += metrics["mrr"]
                count += 1

        denom = max(count, 1)
        avg_hit5 = total_hit5 / denom
        avg_hit10 = total_hit10 / denom
        avg_mrr = total_mrr / denom
        score = (avg_mrr, avg_hit10, avg_hit5)
        if score > best_score:
            best_score = score
            best_alpha = alpha

    print(
        "TUNE ALPHA | candidates="
        + ",".join(f"{c:.2f}" for c in candidates)
        + f" | best_alpha={best_alpha:.2f}"
    )
    return best_alpha


def run_eval(
    input_path: Path = Path("configs/eval_queries_v2_rich.jsonl"),
    chunks_dir: Path = Path("data_chunks"),
    output_root: Path = Path("notebooks") / "runs",
    *,
    k: int = 10,
    rerank_mode: str = "none",
    llm_model: str = "gpt-5-nano",
    variant: str = "B",
    retriever: str = "hybrid",
    hybrid_alpha: float = 0.8,
    tune_alpha: bool = False,
    table_multiplier: float = 1.2,
    dense_index_a: Path = Path("data_index") / "dense_A",
    dense_index_b: Path = Path("data_index") / "dense_B",
    joined_chunks_path: Path = Path("notebooks") / "data_chunks_rich_joined.jsonl",
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / timestamp
    output_path = output_dir / "results.csv"

    _log_start(input_path, output_path)

    try:
        queries = load_queries(input_path)
        chunks_a = load_chunks(chunks_dir)
        rich_chunks_b = load_chunks_rich(Path("notebooks") / "data_chunks_rich")
        joined_meta = load_joined_metadata(joined_chunks_path)
        chunks_b = [
            ChunkRecord(
                source_path=item.source_path,
                chunk_index=item.chunk_index,
                chunk_id=item.chunk_id,
                text=item.text,
                metadata=joined_meta.get(
                    (item.source_path, item.chunk_index),
                    item.metadata if isinstance(item.metadata, dict) else None,
                ),
            )
            for item in rich_chunks_b
        ]
        output_dir.mkdir(parents=True, exist_ok=True)

        retrievers: List[RetrieverBase] = []
        variant = variant.upper()
        retriever = retriever.lower()
        embedder: DenseEmbedder | None = None
        dense_a: DenseIndex | None = None
        dense_b: DenseIndex | None = None
        if retriever in {"dense", "hybrid"}:
            embedder = DenseEmbedder()
            if variant in {"A", "AB"}:
                dense_a = DenseIndex.load(dense_index_a / "index.npz", dense_index_a / "meta.json")
            if variant in {"B", "AB"}:
                dense_b = DenseIndex.load(dense_index_b / "index.npz", dense_index_b / "meta.json")

        best_alpha: float | None = None
        if tune_alpha and retriever == "hybrid":
            best_alpha = _tune_hybrid_alpha(
                queries,
                variant=variant,
                chunks_a=chunks_a,
                chunks_b=chunks_b,
                dense_a=dense_a,
                dense_b=dense_b,
                embedder=embedder,
                k=k,
                rerank_mode=rerank_mode,
                llm_model=llm_model,
                table_multiplier=table_multiplier,
            )
            hybrid_alpha = best_alpha
        elif tune_alpha:
            print("TUNE ALPHA | retriever가 hybrid가 아니어서 건너뜁니다.")

        if variant in {"A", "AB"}:
            if retriever == "tfidf":
                retrievers.append(TfidfRetriever("A", chunks_a))
            elif retriever == "dense":
                if dense_a is None or embedder is None:
                    raise RuntimeError("dense 인덱스(A)가 필요합니다.")
                retrievers.append(DenseRetriever("A", dense_a, embedder, table_multiplier, chunks_a))
            elif retriever == "hybrid":
                if dense_a is None or embedder is None:
                    raise RuntimeError("hybrid 인덱스(A)가 필요합니다.")
                retrievers.append(
                    HybridRetriever(
                        "A",
                        chunks_a,
                        dense_a,
                        embedder,
                        hybrid_alpha,
                        table_multiplier,
                        org_hard_filter=False,
                    )
                )
            else:
                raise RuntimeError(f"지원하지 않는 retriever: {retriever}")
        if variant in {"B", "AB"}:
            if retriever == "tfidf":
                retrievers.append(TfidfRetriever("B", chunks_b))
            elif retriever == "dense":
                if dense_b is None or embedder is None:
                    raise RuntimeError("dense 인덱스(B)가 필요합니다.")
                retrievers.append(DenseRetriever("B", dense_b, embedder, table_multiplier, chunks_b))
            elif retriever == "hybrid":
                if dense_b is None or embedder is None:
                    raise RuntimeError("hybrid 인덱스(B)가 필요합니다.")
                retrievers.append(
                    HybridRetriever(
                        "B",
                        chunks_b,
                        dense_b,
                        embedder,
                        hybrid_alpha,
                        table_multiplier,
                        org_hard_filter=True,
                    )
                )
            else:
                raise RuntimeError(f"지원하지 않는 retriever: {retriever}")
        logger = get_langfuse_logger()

        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "query_id",
                    "query",
                    "variant",
                    "retriever",
                    "recall@5",
                    "recall@10",
                    "mrr",
                    "latency_ms",
                    "cost_usd",
                    "rerank_mode",
                    "best_alpha",
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
                    if retriever.name == "A":
                        chunks = chunks_a
                    else:
                        chunks = chunks_b
                    start = time.perf_counter()
                    results = retriever.retrieve(query.query, chunks, k=k)
                    latency_ms = (time.perf_counter() - start) * 1000.0

                    results, cost_usd = _rerank_if_needed(
                        query, retriever, results, rerank_mode=rerank_mode, llm_model=llm_model
                    )

                    metrics = evaluate_query(query, results)
                    top1 = results[0] if results else None
                    qual_score, qual_reason = _qual_score_top1(
                        query.query, top1.text if top1 else ""
                    )

                    row = {
                        "query_id": query.query_id,
                        "query": query.query,
                        "variant": retriever.name,
                        "retriever": retriever.kind,
                        "recall@5": metrics["recall@5"],
                        "recall@10": metrics["recall@10"],
                        "mrr": metrics["mrr"],
                        "latency_ms": round(latency_ms, 3),
                        "cost_usd": cost_usd,
                        "rerank_mode": rerank_mode,
                        "best_alpha": f"{best_alpha:.2f}" if best_alpha is not None else "",
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
                            "query": query.query,
                            "query_id": query.query_id,
                            "status": "ok",
                            "variant": retriever.name,
                            "retriever": retriever.kind,
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
                            "tags": ["evaluation", f"variant:{retriever.name}", f"retriever:{retriever.kind}"],
                            "version": "eval_harness.v1",
                        },
                    )
                    key = f"{retriever.name}:{retriever.kind}:{rerank_mode}"
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
    parser.add_argument("--variant", choices=["A", "B", "AB"], default="B")
    parser.add_argument("--retriever", choices=["tfidf", "dense", "hybrid"], default="hybrid")
    parser.add_argument("--hybrid-alpha", type=float, default=0.8)
    parser.add_argument("--tune-alpha", action="store_true")
    parser.add_argument("--table-multiplier", type=float, default=1.2)
    parser.add_argument("--dense-index-a", default=str(Path("data_index") / "dense_A"))
    parser.add_argument("--dense-index-b", default=str(Path("data_index") / "dense_B"))
    args = parser.parse_args()

    run_eval(
        k=args.topk,
        rerank_mode=args.rerank,
        llm_model=args.llm_model,
        variant=args.variant,
        retriever=args.retriever,
        hybrid_alpha=args.hybrid_alpha,
        tune_alpha=args.tune_alpha,
        table_multiplier=args.table_multiplier,
        dense_index_a=Path(args.dense_index_a),
        dense_index_b=Path(args.dense_index_b),
    )
