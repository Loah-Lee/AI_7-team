from __future__ import annotations

import argparse
import csv
import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .evaluation.eval_harness import (
    ChunkRecord,
    DenseRetriever,
    HybridRetriever,
    QueryRecord,
    TfidfRetriever,
    evaluate_query,
    load_joined_metadata,
    load_queries,
)
from .evaluation.rerank_openai import rerank_openai
from .evaluation.rerank_rule import rerank_rule
from .retrievers.dense_openai import DenseEmbedder, DenseIndex
from .retrievers.chroma_store import search_chroma
from .retrievers.rich_tfidf_search import (
    ChunkRecord as LexicalChunkRecord,
    _build_tfidf,
    load_chunks_rich,
    tfidf_scores,
)


_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")
_FRACTION_OF_100_RE = re.compile(r"(?:100|백)\s*분의\s*(\d+(?:\.\d+)?)")
_MONEY_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:원|만원|천원|억원)\b")
_MONEY_LOOSE_RE = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b")
_BUDGET_KEYWORD_RE = re.compile(r"(사업예산|사업비|총사업비|예정가격|기초금액|금액|예산)")
_DATE_RE = re.compile(r"\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b|\b\d{1,2}\s*월\s*\d{1,2}\s*일\b")
_PERIOD_RE = re.compile(r"\b\d+\s*(?:개월|개월간|일|일간|년)\b")
_CONTACT_RE = re.compile(r"(?:\d{2,3}-\d{3,4}-\d{4}|@|담당자|문의처|연락처|전화)")
_MONEY_VALUE_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(원|만원|천원|억원)")


def _get_client():
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        pass

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
    from openai import OpenAI  # type: ignore

    return OpenAI(api_key=api_key)


def _load_chunks_b(joined_chunks_path: Path) -> List[ChunkRecord]:
    rich_chunks = load_chunks_rich(Path("notebooks") / "data_chunks_rich")
    joined_meta = load_joined_metadata(joined_chunks_path)
    return [
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
        for item in rich_chunks
    ]


def _build_retriever(
    *,
    retriever_kind: str,
    chunks_b: Sequence[ChunkRecord],
    dense_index_b: Path,
    hybrid_alpha: float,
    table_multiplier: float,
    chroma_persist_dir: Path,
    chroma_collection: str,
    chroma_model: str,
    chroma_org_filter: bool,
    chroma_org_filter_mode: str,
    chroma_score_weight: float,
    lexical_score_weight: float,
    chroma_noise_mode: str,
    chroma_mmr: bool,
    chroma_mmr_lambda: float,
    chroma_query_rewrite: bool,
):
    kind = retriever_kind.lower()
    if kind == "tfidf":
        return TfidfRetriever("B", chunks_b)
    if kind == "chroma":
        return ChromaRetriever(
            chunks=chunks_b,
            persist_dir=chroma_persist_dir,
            collection_name=chroma_collection,
            model=chroma_model,
            org_hard_filter=chroma_org_filter,
            org_filter_mode=chroma_org_filter_mode,
            chroma_score_weight=chroma_score_weight,
            lexical_score_weight=lexical_score_weight,
            noise_mode=chroma_noise_mode,
            use_mmr=chroma_mmr,
            mmr_lambda=chroma_mmr_lambda,
            query_rewrite=chroma_query_rewrite,
        )

    if kind in {"dense", "hybrid"}:
        embedder = DenseEmbedder()
        dense_b = DenseIndex.load(dense_index_b / "index.npz", dense_index_b / "meta.json")
        if kind == "dense":
            return DenseRetriever("B", dense_b, embedder, table_multiplier, chunks_b)
        return HybridRetriever(
            "B",
            chunks_b,
            dense_b,
            embedder,
            hybrid_alpha,
            table_multiplier,
            org_hard_filter=True,
        )

    raise RuntimeError(f"지원하지 않는 retriever: {retriever_kind}")


class ChromaRetriever:
    name = "B"
    kind = "chroma"

    def __init__(
        self,
        *,
        chunks: Sequence[ChunkRecord],
        persist_dir: Path,
        collection_name: str,
        model: str,
        org_hard_filter: bool = False,
        org_filter_mode: str = "hard",
        chroma_score_weight: float = 0.7,
        lexical_score_weight: float = 0.3,
        noise_mode: str = "soft",
        use_mmr: bool = False,
        mmr_lambda: float = 0.85,
        query_rewrite: bool = False,
    ) -> None:
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._model = model
        self._org_hard_filter = bool(org_hard_filter)
        mode = str(org_filter_mode or "").strip().lower()
        if mode not in {"hard", "soft", "adaptive"}:
            mode = "hard" if self._org_hard_filter else "soft"
        self._org_filter_mode = mode
        cw = max(0.0, float(chroma_score_weight))
        lw = max(0.0, float(lexical_score_weight))
        if cw + lw <= 0:
            cw, lw = 0.7, 0.3
        denom = cw + lw
        self._chroma_weight = cw / denom
        self._lexical_weight = lw / denom
        self._noise_mode = str(noise_mode or "soft").lower()
        if self._noise_mode not in {"off", "soft", "hard"}:
            self._noise_mode = "soft"
        self._use_mmr = bool(use_mmr)
        self._mmr_lambda = max(0.0, min(1.0, float(mmr_lambda)))
        self._query_rewrite = bool(query_rewrite)

        self._lexical_chunks: List[LexicalChunkRecord] = [
            LexicalChunkRecord(
                source_path=c.source_path,
                chunk_index=c.chunk_index,
                chunk_id=c.chunk_id,
                text=c.text,
                metadata=c.metadata if isinstance(c.metadata, dict) else None,
            )
            for c in chunks
        ]
        self._lexical_vectors, self._lexical_idf = (
            _build_tfidf(self._lexical_chunks) if self._lexical_chunks else ([], {})
        )
        self._lexical_idx_map: Dict[Tuple[str, int], int] = {
            (c.source_path, c.chunk_index): i for i, c in enumerate(self._lexical_chunks)
        }
        self._lexical_chunk_map: Dict[Tuple[str, int], LexicalChunkRecord] = {
            (c.source_path, c.chunk_index): c for c in self._lexical_chunks
        }
        source_to_indices: Dict[str, set[int]] = defaultdict(set)
        for c in self._lexical_chunks:
            source_to_indices[c.source_path].add(c.chunk_index)
        self._source_index_set: Dict[str, set[int]] = {
            source: idxs for source, idxs in source_to_indices.items()
        }

    def retrieve(self, query: str, chunks: Sequence[ChunkRecord], k: int) -> List[ChunkRecord]:
        q = unicodedata.normalize("NFC", query or "").strip()
        q_search = _rewrite_query_for_retrieval(q) if self._query_rewrite else q
        org = _extract_org_hint(q)
        kind = _question_kind(q)

        # 2-pass 검색:
        # 1) 기관 후보가 있으면 기관 필터 결과를 우선
        # 2) 부족하면 전체 검색으로 보완
        results = []
        if org:
            filtered = search_chroma(
                query=q_search,
                persist_dir=self._persist_dir,
                collection_name=self._collection_name,
                model=self._model,
                top_k=k,
                fetch_k=max(k * 50, 500),
                org=org,
            )
            mode = self._org_filter_mode
            if mode == "hard":
                results = filtered
            else:
                unfiltered = search_chroma(
                    query=q_search,
                    persist_dir=self._persist_dir,
                    collection_name=self._collection_name,
                    model=self._model,
                    top_k=k,
                    fetch_k=max(k * 30, 200),
                    org=None,
                )
                if mode == "soft":
                    results = filtered + unfiltered
                else:
                    # adaptive:
                    # 기관 힌트 신뢰도가 높거나 기관 필터 결과가 충분하면 hard처럼 동작.
                    conf = _org_confidence(q, org)
                    enough = len(filtered) >= max(5, k // 4)
                    if conf >= 0.9 or enough:
                        results = filtered
                    else:
                        results = filtered + unfiltered
        else:
            if self._org_hard_filter:
                # 기관 필수 모드에서는 무기관 질의에 대해 검색을 수행하지 않는다.
                results = []
            else:
                results = search_chroma(
                    query=q_search,
                    persist_dir=self._persist_dir,
                    collection_name=self._collection_name,
                    model=self._model,
                    top_k=k,
                    fetch_k=max(k * 30, 200),
                    org=None,
                )

        scored: List[tuple[ChunkRecord, float, int]] = []
        seen: set[tuple[str, int]] = set()
        for pos, item in enumerate(results):
            try:
                chunk_index = int(item.get("chunk_index", -1))
            except Exception:
                chunk_index = -1
            source_path = str(item.get("source_path", ""))
            key = (source_path, chunk_index)
            if key in seen:
                continue
            seen.add(key)
            score = float(item.get("score", 0.0))
            chunk = ChunkRecord(
                source_path=source_path,
                chunk_index=chunk_index,
                chunk_id=str(item.get("chunk_id", "")),
                text=str(item.get("text", "")),
                metadata={
                    "org": item.get("org", ""),
                    "type": item.get("type", ""),
                    "source": item.get("source", source_path),
                },
            )
            scored.append((chunk, score, pos))

        if kind == "money" and scored:
            scored = self._expand_money_neighbor_candidates(scored)

        # 질의 내 영문/숫자 고신호 토큰(IP-NAVI 등)을 별도로 추적해
        # 해당 토큰이 실제 source/text에 나타나는 청크를 우선한다.
        signal_terms = _extract_signal_terms(q)
        signal_match_count: Dict[Tuple[str, int], int] = {}
        signal_any_match = False
        for c, _, _ in scored:
            key = (c.source_path, c.chunk_index)
            hay = f"{c.source_path}\n{c.text}".lower()
            cnt = sum(1 for t in signal_terms if t and t in hay)
            signal_match_count[key] = cnt
            if cnt > 0:
                signal_any_match = True

        # 캡션/테이블 JSON 잔재처럼 값 추출에 방해가 되는 노이즈 청크를 감점한다.
        # hard 모드에서는 강한 노이즈 청크를 사전에 제거한다.
        if self._noise_mode == "hard":
            hard_filtered: List[tuple[ChunkRecord, float, int]] = []
            for c, s, pos in scored:
                hits = _noise_hits(c.text)
                threshold = 1 if kind == "money" else 2
                if hits >= threshold and not _has_value_hint(c.text, kind):
                    continue
                hard_filtered.append((c, s, pos))
            if hard_filtered:
                scored = hard_filtered

        noise_penalty_map: Dict[Tuple[str, int], float] = {}
        for c, _, _ in scored:
            key = (c.source_path, c.chunk_index)
            hits = _noise_hits(c.text)
            if self._noise_mode == "off":
                noise_penalty_map[key] = 0.0
            elif self._noise_mode == "hard":
                unit_pen = 0.16 if kind == "money" else 0.10
                noise_penalty_map[key] = -unit_pen * hits
            else:
                unit_pen = 0.22 if kind == "money" else 0.18
                noise_penalty_map[key] = -unit_pen * hits

        lexical_score_map: Dict[Tuple[str, int], float] = {}
        if scored and self._lexical_chunks:
            all_lexical_scores = tfidf_scores(
                q,
                self._lexical_chunks,
                self._lexical_vectors,
                self._lexical_idf,
            )
            for c, _, _ in scored:
                key = (c.source_path, c.chunk_index)
                idx = self._lexical_idx_map.get(key)
                if idx is None:
                    lexical_score_map[key] = 0.0
                else:
                    lexical_score_map[key] = float(all_lexical_scores[idx])

            max_lex = max(lexical_score_map.values()) if lexical_score_map else 0.0
            if max_lex > 0:
                for key in list(lexical_score_map.keys()):
                    lexical_score_map[key] = lexical_score_map[key] / max_lex

        # same-source keyword rerank:
        # 소스 내에서 값/키워드 근거가 풍부한 청크를 우선하도록 조정
        def _keyword_bonus(qtext: str, text: str, source_path: str, org_hint: str | None) -> float:
            bonus = 0.0
            q_kind = _question_kind(qtext)
            if q_kind == "percent":
                if _PERCENT_RE.search(text) or _FRACTION_OF_100_RE.search(text):
                    bonus += 1.2
                else:
                    bonus -= 0.2
            elif q_kind == "money":
                if _MONEY_RE.search(text):
                    bonus += 1.2
                elif _BUDGET_KEYWORD_RE.search(text) and _MONEY_LOOSE_RE.search(text):
                    bonus += 0.8
                elif _BUDGET_KEYWORD_RE.search(text):
                    bonus += 0.2
                else:
                    bonus -= 0.2
            elif q_kind == "date":
                if _DATE_RE.search(text):
                    bonus += 1.0
                else:
                    bonus -= 0.1
            elif q_kind == "period":
                if _PERIOD_RE.search(text):
                    bonus += 1.0
                else:
                    bonus -= 0.1

            q_tokens = [t for t in re.findall(r"[0-9A-Za-z가-힣]+", qtext.lower()) if len(t) >= 2][:8]
            if q_tokens:
                overlap = sum(1 for t in q_tokens if t in text.lower())
                bonus += min(overlap * 0.1, 0.5)
            if org_hint:
                sp = source_path.lower().replace(" ", "")
                hint = org_hint.lower().replace(" ", "")
                if hint in sp:
                    bonus += 0.6
            return bonus

        source_best: Dict[str, float] = {}
        for c, _, _ in scored:
            b = _keyword_bonus(q, c.text, c.source_path, org)
            prev = source_best.get(c.source_path, -1.0)
            if b > prev:
                source_best[c.source_path] = b

        reranked = []
        for c, s, pos in scored:
            key = (c.source_path, c.chunk_index)
            lex = lexical_score_map.get((c.source_path, c.chunk_index), 0.0)
            kb = _keyword_bonus(q, c.text, c.source_path, org)
            sb = source_best.get(c.source_path, 0.0)
            signal_bonus = 0.0
            if signal_terms and signal_any_match:
                cnt = signal_match_count.get(key, 0)
                signal_bonus = min(0.25 * cnt, 0.75) if cnt > 0 else -0.30
            noise_pen = noise_penalty_map.get(key, 0.0)
            base = (self._chroma_weight * s) + (self._lexical_weight * lex)
            final = base + (0.26 * kb) + (0.12 * sb) + signal_bonus + noise_pen - (0.0001 * pos)
            reranked.append((c, final))
        reranked.sort(key=lambda x: x[1], reverse=True)

        if self._use_mmr and len(reranked) > 1:
            reranked = _apply_mmr_sparse(
                reranked,
                k=max(k, 1),
                lambda_mult=self._mmr_lambda,
                idx_map=self._lexical_idx_map,
                vectors=self._lexical_vectors,
            )

        out: List[ChunkRecord] = []
        for c, _ in reranked:
            out.append(c)
            if len(out) >= k:
                break
        return out[:k]

    def _expand_money_neighbor_candidates(
        self, scored: List[tuple[ChunkRecord, float, int]]
    ) -> List[tuple[ChunkRecord, float, int]]:
        expanded = list(scored)
        seen = {(c.source_path, c.chunk_index) for c, _, _ in expanded}
        top_seed = min(len(scored), 12)
        offsets = (-2, -1, 1, 2, 3)
        next_pos = len(expanded)

        for i in range(top_seed):
            c, s, _ = scored[i]
            src = c.source_path
            base_idx = c.chunk_index
            idx_set = self._source_index_set.get(src)
            if idx_set is None:
                continue
            for d in offsets:
                cand_idx = base_idx + d
                key = (src, cand_idx)
                if cand_idx < 0 or cand_idx not in idx_set or key in seen:
                    continue
                rec = self._lexical_chunk_map.get(key)
                if rec is None:
                    continue
                text = rec.text or ""
                if not (_BUDGET_KEYWORD_RE.search(text) or _MONEY_RE.search(text) or _MONEY_LOOSE_RE.search(text)):
                    continue
                neighbor = ChunkRecord(
                    source_path=rec.source_path,
                    chunk_index=rec.chunk_index,
                    chunk_id=rec.chunk_id,
                    text=rec.text,
                    metadata=rec.metadata if isinstance(rec.metadata, dict) else None,
                )
                # 인접 청크는 의미 보강용 후보이므로 소폭 낮은 초기점수를 부여한다.
                adj_score = s - (0.06 * abs(d))
                expanded.append((neighbor, adj_score, next_pos))
                next_pos += 1
                seen.add(key)

        return expanded


def _rerank(
    query: str,
    results: List[ChunkRecord],
    *,
    rerank_mode: str,
    llm_model: str,
) -> Tuple[List[ChunkRecord], float]:
    mode = rerank_mode.lower()
    if mode == "none" or not results:
        return results, 0.0

    if mode == "rule":
        candidates = [
            {
                "text": item.text,
                "source_path": item.source_path,
                "chunk_id": item.chunk_id,
                "metadata": item.metadata if isinstance(item.metadata, dict) else None,
            }
            for item in results
        ]
        ranked = rerank_rule(query, candidates)
        id_map = {item.chunk_id: item for item in results}
        return [id_map[item.get("chunk_id", "")] for item in ranked if item.get("chunk_id", "") in id_map], 0.0

    candidates = [
        {
            "text": item.text,
            "source_path": item.source_path,
            "chunk_id": item.chunk_id,
        }
        for item in results
    ]
    ranked, cost_usd = rerank_openai(query, candidates, model=llm_model)
    id_map = {item.chunk_id: item for item in results}
    reranked = [id_map[item.get("chunk_id", "")] for item in ranked if item.get("chunk_id", "") in id_map]
    return reranked, cost_usd


def _extract_output_text(response) -> str:
    text = getattr(response, "output_text", None) or ""
    if text:
        return text.strip()

    parts: List[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") != "message":
            continue
        for content in getattr(item, "content", []) or []:
            ctype = getattr(content, "type", "")
            if ctype in {"output_text", "text"}:
                parts.append(str(getattr(content, "text", "")))
    return "\n".join(parts).strip()


def _parse_json_object(text: str) -> Dict[str, object]:
    text = text.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _question_kind(query: str) -> str:
    q = query.strip()
    if re.search(r"개요|요약|설명|무엇|어떤", q):
        return "overview"
    if re.search(r"비율|퍼센트|%", q):
        return "percent"
    if re.search(r"예산|금액|비용|얼마", q):
        return "money"
    if re.search(r"마감|일자|언제|날짜", q):
        return "date"
    if re.search(r"기간|며칠|몇\s*개월", q):
        return "period"
    if re.search(r"문의|연락처|전화|이메일|담당자", q):
        return "contact"
    return "generic"


def _extract_signal_terms(query: str) -> List[str]:
    return [
        t.lower().strip("-_/")
        for t in re.findall(r"[0-9A-Za-z][0-9A-Za-z\\-_/]{2,}", query or "")
        if len(t.strip("-_/")) >= 3
    ][:6]


def _noise_hits(text: str) -> int:
    t = (text or "").lower()
    hits = 0
    if '"summary"' in t and "]]" in t:
        hits += 1
    if "../data_assets/" in t:
        hits += 1
    if '"type": "table"' in t or '"type":"table"' in t:
        hits += 1
    if t.lstrip().startswith("!["):
        hits += 1
    return hits


def _has_value_hint(text: str, kind: str) -> bool:
    t = text or ""
    if kind == "percent":
        return bool(_PERCENT_RE.search(t) or _FRACTION_OF_100_RE.search(t))
    if kind == "money":
        if _MONEY_RE.search(t):
            return True
        return bool(_BUDGET_KEYWORD_RE.search(t) and _MONEY_LOOSE_RE.search(t))
    if kind == "date":
        return bool(_DATE_RE.search(t))
    if kind == "period":
        return bool(_PERIOD_RE.search(t))
    if kind == "contact":
        return bool(_CONTACT_RE.search(t))
    if kind == "overview":
        return bool(re.search(r"(사업개요|과업\s*개요|추진\s*배경|사업\s*목적|주요\s*업무)", t))
    return bool(re.search(r"(예산|금액|기간|마감|문의|담당|연락처|입찰|평가)", t))


def _rewrite_query_for_retrieval(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return q

    kind = _question_kind(q)
    additions: List[str] = []
    if kind == "money":
        additions += ["사업예산", "사업비", "총사업비", "예정가격", "기초금액", "금액"]
    elif kind == "date":
        additions += ["제안서 제출 마감일", "접수마감", "공고일", "제출일"]
    elif kind == "period":
        additions += ["사업기간", "수행기간", "계약기간", "개월", "일"]
    elif kind == "percent":
        additions += ["입찰보증금 비율", "평가비율", "기술평가 비중", "가격평가 비중"]
    elif kind == "contact":
        additions += ["문의처", "담당자", "연락처", "전화", "이메일"]

    for t in _extract_signal_terms(q):
        additions.append(t)

    seen = set()
    deduped: List[str] = []
    for tok in additions:
        s = tok.strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)
    if not deduped:
        return q
    return f"{q} {' '.join(deduped)}"


def _sparse_cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    for k, v in a.items():
        dot += v * b.get(k, 0.0)
    if dot == 0.0:
        return 0.0
    norm_a = sum(v * v for v in a.values()) ** 0.5
    norm_b = sum(v * v for v in b.values()) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _apply_mmr_sparse(
    ranked: List[Tuple[ChunkRecord, float]],
    *,
    k: int,
    lambda_mult: float,
    idx_map: Dict[Tuple[str, int], int],
    vectors: Sequence[Dict[str, float]],
) -> List[Tuple[ChunkRecord, float]]:
    if not ranked:
        return []
    if len(ranked) <= 1 or k <= 1:
        return ranked[:k]

    rels = [s for _, s in ranked]
    min_rel, max_rel = min(rels), max(rels)
    denom = (max_rel - min_rel) if max_rel > min_rel else 1.0
    rel_norm = [(s - min_rel) / denom for _, s in ranked]

    selected: List[int] = [0]
    remaining = set(range(1, len(ranked)))

    while remaining and len(selected) < k:
        best_i = None
        best_score = -1e9
        for i in list(remaining):
            c_i, _ = ranked[i]
            idx_i = idx_map.get((c_i.source_path, c_i.chunk_index), -1)
            vec_i = vectors[idx_i] if 0 <= idx_i < len(vectors) else {}

            max_sim = 0.0
            for j in selected:
                c_j, _ = ranked[j]
                idx_j = idx_map.get((c_j.source_path, c_j.chunk_index), -1)
                vec_j = vectors[idx_j] if 0 <= idx_j < len(vectors) else {}
                sim = _sparse_cosine(vec_i, vec_j)
                if sim > max_sim:
                    max_sim = sim
            mmr_score = lambda_mult * rel_norm[i] - (1.0 - lambda_mult) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_i = i
        if best_i is None:
            break
        selected.append(best_i)
        remaining.discard(best_i)

    return [ranked[i] for i in selected][:k]


def _extract_org_hint(query: str) -> str | None:
    tokens = query.strip().split()
    if not tokens:
        return None
    cand = tokens[0].strip()
    if re.search(r"(공사|공단|재단|대학교|대학|병원|정보원|원)$", cand) or cand.startswith("한국"):
        return cand
    return None


def _org_confidence(query: str, org: str | None) -> float:
    if not org:
        return 0.0
    q = (query or "").strip()
    o = (org or "").strip()
    if not q or not o:
        return 0.0
    if q.startswith(o + " ") and re.search(r"(공사|공단|재단|대학교|대학|병원|정보원|연구원|협회|위원회)$", o):
        return 1.0
    if q.startswith(o + " ") and len(o) >= 3:
        return 0.9
    if o in q and len(o) >= 3:
        return 0.7
    return 0.4


def _pick_matches(text: str, kind: str) -> List[str]:
    if kind == "percent":
        matches: List[str] = []
        for m in _FRACTION_OF_100_RE.findall(text):
            matches.append(f"{m}%")
        matches.extend(_PERCENT_RE.findall(text))
        return matches
    if kind == "money":
        strict = _MONEY_RE.findall(text)
        if strict:
            return strict
        if _BUDGET_KEYWORD_RE.search(text):
            loose = _MONEY_LOOSE_RE.findall(text)
            if loose:
                return loose
        return []
    if kind == "date":
        return _DATE_RE.findall(text)
    if kind == "period":
        return _PERIOD_RE.findall(text)

    matches: List[str] = []
    for pattern in (_PERCENT_RE, _MONEY_RE, _DATE_RE, _PERIOD_RE):
        matches.extend(pattern.findall(text))
    return matches


def _parse_top_n_for_rank_query(query: str, default: int = 3) -> int:
    q = query or ""
    m = re.search(r"\btop\s*(\d+)\b", q, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d+)\s*(?:곳|기관|개|건)", q)
    if not m:
        return default
    try:
        n = int(m.group(1))
    except Exception:
        return default
    return max(1, min(n, 10))


def _extract_org_from_source(source_path: str) -> str:
    name = Path(source_path or "").name.strip()
    if not name:
        return ""
    base = re.sub(r"\.(?:pdf|hwp|docx?|txt)$", "", name, flags=re.IGNORECASE)
    if "_" in base:
        org = base.split("_", 1)[0].strip()
        if org:
            return org
    return base.strip()


def _extract_org_name(chunk: ChunkRecord) -> str:
    metadata = chunk.metadata if isinstance(chunk.metadata, dict) else {}
    for key in ("org", "institution", "기관"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = metadata.get("meta")
    if isinstance(nested, dict):
        for key in ("발주 기관", "기관", "institution"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return _extract_org_from_source(chunk.source_path)


def _parse_money_values(text: str) -> List[Tuple[float, str, int, int]]:
    out: List[Tuple[float, str, int, int]] = []
    if not text:
        return out
    for m in _MONEY_VALUE_RE.finditer(text):
        raw_num = m.group(1).replace(",", "")
        unit = m.group(2)
        try:
            num = float(raw_num)
        except Exception:
            continue
        multiplier = 1.0
        if unit == "억원":
            multiplier = 100_000_000.0
        elif unit == "만원":
            multiplier = 10_000.0
        elif unit == "천원":
            multiplier = 1_000.0
        value_won = num * multiplier
        out.append((value_won, m.group(0), m.start(), m.end()))
    return out


def _filter_budget_values(text: str, values: List[Tuple[float, str, int, int]]) -> List[Tuple[float, str, int, int]]:
    if not values:
        return []
    if _BUDGET_KEYWORD_RE.search(text):
        return values

    filtered: List[Tuple[float, str, int, int]] = []
    for item in values:
        _, _, s, e = item
        win = text[max(0, s - 28) : min(len(text), e + 28)]
        if _BUDGET_KEYWORD_RE.search(win):
            filtered.append(item)
    return filtered


def generate_money_rank_answer(
    query: str,
    contexts: Sequence[ChunkRecord],
) -> Dict[str, object]:
    if not contexts:
        return {
            "status": "not_found",
            "answer": "문서에 해당 정보가 없습니다.",
            "citations": [],
        }

    top_n = _parse_top_n_for_rank_query(query, default=3)
    best_by_org: Dict[str, Tuple[float, str, int]] = {}

    for idx, c in enumerate(contexts, start=1):
        text = c.text or ""
        values = _parse_money_values(text)
        if not values:
            continue
        values = _filter_budget_values(text, values)
        if not values:
            continue
        best = max(values, key=lambda x: x[0])
        org = _extract_org_name(c).strip()
        if not org:
            continue
        prev = best_by_org.get(org)
        if prev is None or best[0] > prev[0]:
            best_by_org[org] = (best[0], best[1], idx)

    if not best_by_org:
        return {
            "status": "not_found",
            "answer": "사업비 근거를 찾지 못했습니다.",
            "citations": [],
        }

    ranked = sorted(best_by_org.items(), key=lambda x: (-x[1][0], x[0]))[:top_n]
    lines = [f"{i}. {org} - {amount}" for i, (org, (_, amount, _)) in enumerate(ranked, start=1)]
    citations = sorted({ref_idx for _, (_, _, ref_idx) in ranked})

    status = "ok" if len(ranked) >= top_n else "partial"
    return {
        "status": status,
        "answer": "\n".join(lines),
        "citations": citations,
    }


def _rule_based_answer(query: str, contexts: Sequence[ChunkRecord]) -> Dict[str, object]:
    if not contexts:
        return {
            "status": "not_found",
            "answer": "문서에 해당 정보가 없습니다.",
            "citations": [],
        }

    kind = _question_kind(query)
    # 개요/설명형 질의는 규칙 기반 값 추출을 건너뛰고 LLM 생성으로 넘긴다.
    if kind in {"overview", "generic"}:
        preview = re.sub(r"\s+", " ", contexts[0].text).strip()[:160]
        if preview:
            return {
                "status": "partial",
                "answer": f"요약 생성을 위해 관련 문맥을 확보했습니다: {preview}",
                "citations": [1],
            }
        return {
            "status": "partial",
            "answer": "요약 생성을 위해 관련 문맥을 확보했습니다.",
            "citations": [1],
        }

    percent_keywords = ["입찰보증금", "입찰 보증금", "입찰금액", "입찰 금액", "보증금"]
    percent_exclude = ["기술능력", "평가", "배점", "협상적격"]
    percent_candidates: List[Tuple[int, str]] = []

    for i, c in enumerate(contexts, start=1):
        matches = _pick_matches(c.text, kind)
        if not matches:
            continue

        if kind == "percent":
            text = c.text
            if any(k in text for k in percent_exclude) and not any(k in text for k in percent_keywords):
                continue
            if any(k in text for k in percent_keywords):
                percent_candidates.append((i, matches[0]))
                continue

        return {
            "status": "ok",
            "answer": f"근거 문구에서 확인된 값은 `{matches[0]}` 입니다.",
            "citations": [i],
        }

    if kind == "percent" and percent_candidates:
        idx, val = percent_candidates[0]
        return {
            "status": "ok",
            "answer": f"근거 문구에서 확인된 값은 `{val}` 입니다.",
            "citations": [idx],
        }

    # 수치 추출은 실패했어도 컨텍스트가 있으면 partial로 처리한다.
    preview = re.sub(r"\s+", " ", contexts[0].text).strip()[:160]
    if preview:
        return {
            "status": "partial",
            "answer": f"정확한 값 추출에는 실패했습니다. 관련 근거: {preview}",
            "citations": [1],
        }

    return {
        "status": "partial",
        "answer": "정확한 값 추출에는 실패했습니다. 관련 문맥은 확인되었습니다.",
        "citations": [1],
    }


def generate_answer(
    query: str,
    contexts: Sequence[ChunkRecord],
    *,
    answer_model: str,
) -> Dict[str, object]:
    rule_ans = _rule_based_answer(query, contexts)
    if rule_ans["status"] == "ok":
        return rule_ans

    client = _get_client()
    payload = {
        "query": query,
        "contexts": [
            {
                "idx": i + 1,
                "source_path": c.source_path,
                "chunk_index": c.chunk_index,
                "text": c.text[:1800],
            }
            for i, c in enumerate(contexts)
        ],
        "instruction": (
            "반드시 JSON으로만 답하세요. "
            "키는 status, answer, citations를 사용하세요. "
            "status는 'ok', 'partial', 'not_found' 중 하나만 사용하세요. "
            "정확한 값은 없지만 관련 문맥이 있으면 partial로 답하세요. "
            "근거가 전혀 없으면 answer를 '문서에 해당 정보가 없습니다.'로 반환하세요."
        ),
    }

    response = client.responses.create(
        model=answer_model,
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)}],
            }
        ],
    )
    text = _extract_output_text(response)
    data = _parse_json_object(text)

    status = str(data.get("status", "")).strip().lower()
    answer = str(data.get("answer", "")).strip()
    raw_citations = data.get("citations", [])

    citations: List[int] = []
    if isinstance(raw_citations, list):
        for item in raw_citations:
            try:
                idx = int(item)
            except Exception:
                continue
            if 1 <= idx <= len(contexts):
                citations.append(idx)

    if status not in {"ok", "partial", "not_found"}:
        status = "partial" if answer else "not_found"
    if not answer:
        if rule_ans["status"] in {"ok", "partial"}:
            return rule_ans
        answer = "문서에 해당 정보가 없습니다." if status == "not_found" else ""

    if "문서에 해당 정보가 없습니다" in answer:
        if rule_ans["status"] in {"ok", "partial"}:
            return rule_ans
        status = "not_found"
    elif status == "not_found" and rule_ans["status"] in {"ok", "partial"}:
        return rule_ans

    if not citations and rule_ans["citations"]:
        citations = list(rule_ans["citations"])

    return {
        "status": status,
        "answer": answer,
        "citations": citations,
    }


def _expand_candidates_with_neighbors(
    ranked: Sequence[ChunkRecord],
    all_chunks: Sequence[ChunkRecord],
    *,
    target_k: int,
    neighbor_window: int = 1,
) -> List[ChunkRecord]:
    base = list(ranked)
    if not base or target_k <= 0 or neighbor_window <= 0:
        return base[:target_k]

    by_key: Dict[Tuple[str, int], ChunkRecord] = {
        (c.source_path, c.chunk_index): c for c in all_chunks
    }

    out: List[ChunkRecord] = []
    seen: set[Tuple[str, int]] = set()
    for c in base:
        key = (c.source_path, c.chunk_index)
        if key not in seen:
            out.append(c)
            seen.add(key)
        if len(out) >= target_k:
            break
        for delta in range(1, neighbor_window + 1):
            for ni in (c.chunk_index - delta, c.chunk_index + delta):
                nkey = (c.source_path, ni)
                n = by_key.get(nkey)
                if not n or nkey in seen:
                    continue
                out.append(n)
                seen.add(nkey)
                if len(out) >= target_k:
                    break
            if len(out) >= target_k:
                break
    return out[:target_k]


def _run_single_query(
    query: str,
    *,
    retriever,
    chunks_b: Sequence[ChunkRecord],
    top_k: int,
    context_k: int,
    rerank_mode: str,
    llm_model: str,
    answer_model: str,
    generate: bool,
) -> int:
    raw_results = retriever.retrieve(query, chunks_b, k=top_k)
    expanded_raw = _expand_candidates_with_neighbors(
        raw_results,
        chunks_b,
        target_k=max(top_k, min(top_k + 30, top_k * 2)),
        neighbor_window=1,
    )
    reranked, _ = _rerank(query, expanded_raw, rerank_mode=rerank_mode, llm_model=llm_model)
    contexts = _expand_contexts_with_neighbors(reranked, chunks_b, context_k=context_k, neighbor_window=1)
    print(f"query: {query}")
    if generate:
        ans = generate_answer(query, contexts, answer_model=answer_model)
        print(f"status: {ans['status']}")
        print(f"answer: {ans['answer']}")
        print("citations:")
        for idx in ans["citations"]:
            c = contexts[idx - 1]
            print(f"- [{idx}] {c.source_path} (chunk {c.chunk_index})")

        if not ans["citations"] and contexts:
            print("retrieved contexts:")
            for i, c in enumerate(contexts, start=1):
                preview = re.sub(r"\s+", " ", c.text).strip()[:180]
                print(f"- [{i}] {c.source_path} (chunk {c.chunk_index}) :: {preview}...")
    else:
        print("retrieved contexts:")
        for i, c in enumerate(contexts, start=1):
            preview = re.sub(r"\s+", " ", c.text).strip()[:180]
            print(f"- [{i}] {c.source_path} (chunk {c.chunk_index}) :: {preview}...")

    return 0


def _run_batch(
    query_path: Path,
    *,
    retriever,
    chunks_b: Sequence[ChunkRecord],
    top_k: int,
    context_k: int,
    rerank_mode: str,
    llm_model: str,
    answer_model: str,
    generate: bool,
    output_csv: Path,
) -> int:
    queries: List[QueryRecord] = load_queries(query_path)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, object]] = []
    for q in queries:
        raw_results = retriever.retrieve(q.query, chunks_b, k=top_k)
        expanded_raw = _expand_candidates_with_neighbors(
            raw_results,
            chunks_b,
            target_k=max(top_k, min(top_k + 30, top_k * 2)),
            neighbor_window=1,
        )
        reranked, cost_usd = _rerank(
            q.query, expanded_raw, rerank_mode=rerank_mode, llm_model=llm_model
        )
        metrics_retrieve = evaluate_query(q, raw_results)
        metrics_rerank = evaluate_query(q, reranked)
        gold_sources = {src for src, _ in q.gold}
        retrieve_sources = [item.source_path for item in raw_results[:10]]
        rerank_sources = [item.source_path for item in reranked[:10]]
        retrieve_source_recall10 = (
            len(set(retrieve_sources) & gold_sources) / len(gold_sources) if gold_sources else 0.0
        )
        rerank_source_recall10 = (
            len(set(rerank_sources) & gold_sources) / len(gold_sources) if gold_sources else 0.0
        )

        answer_status = "skipped"
        answer = ""
        citations_json = "[]"
        if generate:
            contexts = _expand_contexts_with_neighbors(
                reranked, chunks_b, context_k=context_k, neighbor_window=1
            )
            ans = generate_answer(q.query, contexts, answer_model=answer_model)
            answer_status = str(ans["status"])
            answer = str(ans["answer"])
            citations_json = json.dumps(ans.get("citations", []), ensure_ascii=False)

        top1 = reranked[0] if reranked else None
        rows.append(
            {
                "query_id": q.query_id,
                "query": q.query,
                "retrieve_recall@10": metrics_retrieve["recall@10"],
                "rerank_recall@10": metrics_rerank["recall@10"],
                "retrieve_source_recall@10": retrieve_source_recall10,
                "rerank_source_recall@10": rerank_source_recall10,
                "retrieve_mrr": metrics_retrieve["mrr"],
                "rerank_mrr": metrics_rerank["mrr"],
                "answer_status": answer_status,
                "answer": answer,
                "citations": citations_json,
                "has_citation": int(citations_json != "[]"),
                "top1_source_path": top1.source_path if top1 else "",
                "top1_chunk_index": top1.chunk_index if top1 else "",
                "cost_usd": cost_usd,
            }
        )

    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "query_id",
                "query",
                "retrieve_recall@10",
                "rerank_recall@10",
                "retrieve_source_recall@10",
                "rerank_source_recall@10",
                "retrieve_mrr",
                "rerank_mrr",
                "answer_status",
                "answer",
                "citations",
                "has_citation",
                "top1_source_path",
                "top1_chunk_index",
                "cost_usd",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    n = max(len(rows), 1)
    avg_ret = sum(float(r["retrieve_recall@10"]) for r in rows) / n
    avg_rer = sum(float(r["rerank_recall@10"]) for r in rows) / n
    avg_ret_src = sum(float(r["retrieve_source_recall@10"]) for r in rows) / n
    avg_rer_src = sum(float(r["rerank_source_recall@10"]) for r in rows) / n
    avg_ret_mrr = sum(float(r["retrieve_mrr"]) for r in rows) / n
    avg_rer_mrr = sum(float(r["rerank_mrr"]) for r in rows) / n
    not_found = sum(1 for r in rows if r["answer_status"] == "not_found") if generate else 0

    print(f"NODE SUMMARY | queries={len(rows)}")
    print(f"retrieve_recall@10={avg_ret:.6f}")
    print(f"rerank_recall@10={avg_rer:.6f}")
    print(f"retrieve_source_recall@10={avg_ret_src:.6f}")
    print(f"rerank_source_recall@10={avg_rer_src:.6f}")
    print(f"retrieve_mrr={avg_ret_mrr:.6f}")
    print(f"rerank_mrr={avg_rer_mrr:.6f}")
    if generate:
        print(f"answer_not_found={not_found} / {len(rows)}")
    print(f"output={output_csv}")
    return 0


def _expand_contexts_with_neighbors(
    ranked: Sequence[ChunkRecord],
    all_chunks: Sequence[ChunkRecord],
    *,
    context_k: int,
    neighbor_window: int = 1,
) -> List[ChunkRecord]:
    base = list(ranked[:context_k])
    if not base or context_k <= 0 or neighbor_window <= 0:
        return base

    by_key: Dict[Tuple[str, int], ChunkRecord] = {
        (c.source_path, c.chunk_index): c for c in all_chunks
    }
    out: List[ChunkRecord] = []
    seen: set[Tuple[str, int]] = set()

    for c in base:
        key = (c.source_path, c.chunk_index)
        if key not in seen:
            out.append(c)
            seen.add(key)
        if len(out) >= context_k:
            break

        for delta in range(1, neighbor_window + 1):
            for neighbor_idx in (c.chunk_index - delta, c.chunk_index + delta):
                nkey = (c.source_path, neighbor_idx)
                n = by_key.get(nkey)
                if not n or nkey in seen:
                    continue
                out.append(n)
                seen.add(nkey)
                if len(out) >= context_k:
                    break
            if len(out) >= context_k:
                break

    return out[:context_k]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--query-file", default="")
    parser.add_argument("--retriever", choices=["tfidf", "dense", "hybrid", "chroma"], default="hybrid")
    parser.add_argument("--rerank", choices=["none", "rule", "llm"], default="none")
    parser.add_argument("--llm-model", default="gpt-5-nano")
    parser.add_argument("--answer-model", default="gpt-5-nano")
    parser.add_argument("--topk", type=int, default=50)
    parser.add_argument("--context-k", type=int, default=20)
    parser.add_argument("--hybrid-alpha", type=float, default=1.0)
    parser.add_argument("--table-multiplier", type=float, default=1.0)
    parser.add_argument("--dense-index-b", default=str(Path("data_index") / "dense_B"))
    parser.add_argument("--chroma-persist-dir", default=str(Path("data_index") / "chroma_B"))
    parser.add_argument("--chroma-collection", default="rfp_b_oai")
    parser.add_argument("--chroma-model", default="text-embedding-3-small")
    parser.add_argument("--chroma-org-filter", action="store_true")
    parser.add_argument("--chroma-org-filter-mode", choices=["hard", "soft", "adaptive"], default="hard")
    parser.add_argument("--chroma-score-weight", type=float, default=0.7)
    parser.add_argument("--lexical-score-weight", type=float, default=0.3)
    parser.add_argument("--chroma-noise-mode", choices=["off", "soft", "hard"], default="soft")
    parser.add_argument("--chroma-mmr", action="store_true")
    parser.add_argument("--chroma-mmr-lambda", type=float, default=0.85)
    parser.add_argument("--chroma-query-rewrite", action="store_true")
    parser.add_argument(
        "--joined-chunks",
        default=str(Path("notebooks") / "data_chunks_rich_joined.jsonl"),
    )
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--output-csv", default="")
    args = parser.parse_args()

    if not args.query and not args.query_file:
        raise RuntimeError("--query 또는 --query-file 중 하나는 필요합니다.")

    chunks_b = _load_chunks_b(Path(args.joined_chunks))
    retriever = _build_retriever(
        retriever_kind=args.retriever,
        chunks_b=chunks_b,
        dense_index_b=Path(args.dense_index_b),
        hybrid_alpha=args.hybrid_alpha,
        table_multiplier=args.table_multiplier,
        chroma_persist_dir=Path(args.chroma_persist_dir),
        chroma_collection=args.chroma_collection,
        chroma_model=args.chroma_model,
        chroma_org_filter=bool(args.chroma_org_filter),
        chroma_org_filter_mode=str(args.chroma_org_filter_mode),
        chroma_score_weight=float(args.chroma_score_weight),
        lexical_score_weight=float(args.lexical_score_weight),
        chroma_noise_mode=str(args.chroma_noise_mode),
        chroma_mmr=bool(args.chroma_mmr),
        chroma_mmr_lambda=float(args.chroma_mmr_lambda),
        chroma_query_rewrite=bool(args.chroma_query_rewrite),
    )

    if args.query:
        return _run_single_query(
            args.query,
            retriever=retriever,
            chunks_b=chunks_b,
            top_k=args.topk,
            context_k=args.context_k,
            rerank_mode=args.rerank,
            llm_model=args.llm_model,
            answer_model=args.answer_model,
            generate=bool(args.generate),
        )

    output_csv = (
        Path(args.output_csv)
        if args.output_csv
        else Path("results") / f"node_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    return _run_batch(
        Path(args.query_file),
        retriever=retriever,
        chunks_b=chunks_b,
        top_k=args.topk,
        context_k=args.context_k,
        rerank_mode=args.rerank,
        llm_model=args.llm_model,
        answer_model=args.answer_model,
        generate=bool(args.generate),
        output_csv=output_csv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
