from __future__ import annotations

import argparse
import csv
import json
import os
import re
import unicodedata
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
    load_chunks_rich,
)


_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")
_FRACTION_OF_100_RE = re.compile(r"(?:100|백)\s*분의\s*(\d+(?:\.\d+)?)")
_MONEY_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:원|만원|천원|억원)\b")
_DATE_RE = re.compile(r"\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b|\b\d{1,2}\s*월\s*\d{1,2}\s*일\b")
_PERIOD_RE = re.compile(r"\b\d+\s*(?:개월|개월간|일|일간|년)\b")


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
    ) -> None:
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._model = model
        self._org_hard_filter = bool(org_hard_filter)

    def retrieve(self, query: str, chunks: Sequence[ChunkRecord], k: int) -> List[ChunkRecord]:
        q = unicodedata.normalize("NFC", query or "").strip()
        org = _extract_org_hint(q)

        # 2-pass 검색:
        # 1) 기관 후보가 있으면 기관 필터 결과를 우선
        # 2) 부족하면 전체 검색으로 보완
        results = []
        if org:
            filtered = search_chroma(
                query=q,
                persist_dir=self._persist_dir,
                collection_name=self._collection_name,
                model=self._model,
                top_k=k,
                fetch_k=max(k * 50, 500),
                org=org,
            )
            if self._org_hard_filter:
                results = filtered
            else:
                unfiltered = search_chroma(
                    query=q,
                    persist_dir=self._persist_dir,
                    collection_name=self._collection_name,
                    model=self._model,
                    top_k=k,
                    fetch_k=max(k * 30, 200),
                    org=None,
                )
                results = filtered + unfiltered
        else:
            results = search_chroma(
                query=q,
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

        # same-source keyword rerank:
        # 소스 내에서 값/키워드 근거가 풍부한 청크를 우선하도록 조정
        def _keyword_bonus(qtext: str, text: str, source_path: str, org_hint: str | None) -> float:
            bonus = 0.0
            kind = _question_kind(qtext)
            if kind == "percent":
                if _PERCENT_RE.search(text) or _FRACTION_OF_100_RE.search(text):
                    bonus += 1.2
                else:
                    bonus -= 0.2
            elif kind == "money":
                if _MONEY_RE.search(text):
                    bonus += 1.2
                else:
                    bonus -= 0.2
            elif kind == "date":
                if _DATE_RE.search(text):
                    bonus += 1.0
                else:
                    bonus -= 0.1
            elif kind == "period":
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
            kb = _keyword_bonus(q, c.text, c.source_path, org)
            sb = source_best.get(c.source_path, 0.0)
            final = s + (0.26 * kb) + (0.12 * sb) - (0.0001 * pos)
            reranked.append((c, final))
        reranked.sort(key=lambda x: x[1], reverse=True)

        out: List[ChunkRecord] = []
        for c, _ in reranked:
            out.append(c)
            if len(out) >= k:
                break
        return out[:k]


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


def _extract_org_hint(query: str) -> str | None:
    tokens = query.strip().split()
    if not tokens:
        return None
    cand = tokens[0].strip()
    if re.search(r"(공사|공단|재단|대학교|대학|병원|정보원|원)$", cand) or cand.startswith("한국"):
        return cand
    return None


def _pick_matches(text: str, kind: str) -> List[str]:
    if kind == "percent":
        matches: List[str] = []
        for m in _FRACTION_OF_100_RE.findall(text):
            matches.append(f"{m}%")
        matches.extend(_PERCENT_RE.findall(text))
        return matches
    if kind == "money":
        return _MONEY_RE.findall(text)
    if kind == "date":
        return _DATE_RE.findall(text)
    if kind == "period":
        return _PERIOD_RE.findall(text)

    matches: List[str] = []
    for pattern in (_PERCENT_RE, _MONEY_RE, _DATE_RE, _PERIOD_RE):
        matches.extend(pattern.findall(text))
    return matches


def _rule_based_answer(query: str, contexts: Sequence[ChunkRecord]) -> Dict[str, object]:
    if not contexts:
        return {
            "status": "not_found",
            "answer": "문서에 해당 정보가 없습니다.",
            "citations": [],
        }

    kind = _question_kind(query)
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
    parser.add_argument("--hybrid-alpha", type=float, default=0.8)
    parser.add_argument("--table-multiplier", type=float, default=1.0)
    parser.add_argument("--dense-index-b", default=str(Path("data_index") / "dense_B"))
    parser.add_argument("--chroma-persist-dir", default=str(Path("data_index") / "chroma_B"))
    parser.add_argument("--chroma-collection", default="rfp_b")
    parser.add_argument("--chroma-model", default="auto")
    parser.add_argument("--chroma-org-filter", action="store_true")
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
