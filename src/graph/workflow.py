from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Sequence

from ..evaluation.eval_harness import load_joined_metadata
from ..retrievers.rich_tfidf_search import load_chunks_rich

from ..evaluation.eval_harness import ChunkRecord
from ..rag_answer import (
    _build_retriever,
    _expand_candidates_with_neighbors,
    _expand_contexts_with_neighbors,
    _load_chunks_b,
    _rerank,
)
from .nodes import generate_answer_node, parse_org, parse_query
from .state import ChatState


_ORG_SUFFIX_RE = re.compile(
    r"(공사|공단|재단|재단법인|사단법인|법인|대학교|대학|병원|의료원|정보원|진흥원|연구원|협회|위원회|조직위원회|사무국|센터|서비스|은행|공항|학교)$"
)
_COMPLEX_QUERY_RE = re.compile(
    r"(비교|차이|각각|동시에|모두|종합|근거|영향|설명해|설명하시오|어떻게\s*다른|무엇이며|요구사항)"
)
_FACTOID_QUERY_RE = re.compile(
    r"(얼마|금액|예산|사업비|비율|퍼센트|마감|일자|날짜|언제|기간|개월|며칠|문의처|연락처|전화)"
)
_CLAUSE_CONNECTOR_RE = re.compile(r"(그리고|또한|및|또는|아울러|동시에)")


class RAGChatbot:
    def __init__(
        self,
        *,
        retriever: str = "hybrid",
        rerank: str = "none",
        top_k: int = 50,
        context_k: int = 20,
        chroma_persist_dir: Path = Path("data_index") / "chroma_B",
        chroma_collection: str = "rfp_b_oai_clean_v1",
        chroma_model: str = "text-embedding-3-small",
        chroma_org_filter: bool = True,
        chroma_org_filter_mode: str = "hard",
        chroma_score_weight: float = 0.7,
        lexical_score_weight: float = 0.3,
        chroma_noise_mode: str = "hard",
        chroma_mmr: bool = True,
        chroma_mmr_lambda: float = 0.85,
        chroma_query_rewrite: bool = True,
        asset_collection: str = "rfp_b_assets_oai_v1",
        hybrid_alpha: float = 0.6,
        dynamic_hard_threshold: int = 2,
    ) -> None:
        self.retriever_kind = retriever
        self.rerank = rerank
        self.top_k = top_k
        self.context_k = context_k
        self.hybrid_alpha = max(0.0, min(1.0, float(hybrid_alpha)))
        self.dynamic_hard_threshold = max(1, int(dynamic_hard_threshold))
        self.chunks = _load_chunks_b(Path("notebooks") / "data_chunks_rich_joined.jsonl")
        self.asset_chunks = self._load_asset_chunks(
            joined_chunks_path=Path("notebooks") / "data_chunks_rich_joined.jsonl",
            asset_chunks_dir=Path("notebooks") / "data_chunks_rich_asset_v1",
        )
        self.retriever = None
        if self.retriever_kind != "dynamic":
            self.retriever = _build_retriever(
                retriever_kind=self.retriever_kind,
                chunks_b=self.chunks,
                dense_index_b=Path("data_index") / "dense_B",
                hybrid_alpha=self.hybrid_alpha,
                table_multiplier=1.0,
                chroma_persist_dir=chroma_persist_dir,
                chroma_collection=chroma_collection,
                chroma_model=chroma_model,
                chroma_org_filter=chroma_org_filter,
                chroma_org_filter_mode=chroma_org_filter_mode,
                chroma_score_weight=chroma_score_weight,
                lexical_score_weight=lexical_score_weight,
                chroma_noise_mode=chroma_noise_mode,
                chroma_mmr=chroma_mmr,
                chroma_mmr_lambda=chroma_mmr_lambda,
                chroma_query_rewrite=chroma_query_rewrite,
            )
        self.dynamic_hybrid_retriever = None
        self.dynamic_chroma_retriever = None
        if self.retriever_kind == "dynamic":
            try:
                self.dynamic_hybrid_retriever = _build_retriever(
                    retriever_kind="hybrid",
                    chunks_b=self.chunks,
                    dense_index_b=Path("data_index") / "dense_B",
                    hybrid_alpha=self.hybrid_alpha,
                    table_multiplier=1.0,
                    chroma_persist_dir=chroma_persist_dir,
                    chroma_collection=chroma_collection,
                    chroma_model=chroma_model,
                    chroma_org_filter=False,
                    chroma_org_filter_mode="soft",
                    chroma_score_weight=1.0,
                    lexical_score_weight=0.0,
                    chroma_noise_mode=chroma_noise_mode,
                    chroma_mmr=chroma_mmr,
                    chroma_mmr_lambda=chroma_mmr_lambda,
                    chroma_query_rewrite=chroma_query_rewrite,
                )
            except Exception:
                self.dynamic_hybrid_retriever = None
            try:
                # hard query 경로: lexical 혼합 없이 순수 chroma 사용
                self.dynamic_chroma_retriever = _build_retriever(
                    retriever_kind="chroma",
                    chunks_b=self.chunks,
                    dense_index_b=Path("data_index") / "dense_B",
                    hybrid_alpha=self.hybrid_alpha,
                    table_multiplier=1.0,
                    chroma_persist_dir=chroma_persist_dir,
                    chroma_collection=chroma_collection,
                    chroma_model=chroma_model,
                    chroma_org_filter=chroma_org_filter,
                    chroma_org_filter_mode=chroma_org_filter_mode,
                    chroma_score_weight=1.0,
                    lexical_score_weight=0.0,
                    chroma_noise_mode=chroma_noise_mode,
                    chroma_mmr=chroma_mmr,
                    chroma_mmr_lambda=chroma_mmr_lambda,
                    chroma_query_rewrite=chroma_query_rewrite,
                )
            except Exception:
                self.dynamic_chroma_retriever = None
        self.money_rank_retriever = None
        try:
            self.money_rank_retriever = _build_retriever(
                retriever_kind="tfidf",
                chunks_b=self.chunks,
                dense_index_b=Path("data_index") / "dense_B",
                hybrid_alpha=self.hybrid_alpha,
                table_multiplier=1.0,
                chroma_persist_dir=chroma_persist_dir,
                chroma_collection=chroma_collection,
                chroma_model=chroma_model,
                chroma_org_filter=False,
                chroma_org_filter_mode="soft",
                chroma_score_weight=chroma_score_weight,
                lexical_score_weight=lexical_score_weight,
                chroma_noise_mode=chroma_noise_mode,
                chroma_mmr=chroma_mmr,
                chroma_mmr_lambda=chroma_mmr_lambda,
                chroma_query_rewrite=chroma_query_rewrite,
            )
        except Exception:
            self.money_rank_retriever = None
        self.global_retriever = None
        if self.retriever_kind in {"chroma", "dynamic"}:
            try:
                base_chroma_weight = 1.0 if self.retriever_kind == "dynamic" else chroma_score_weight
                base_lexical_weight = 0.0 if self.retriever_kind == "dynamic" else lexical_score_weight
                self.global_retriever = _build_retriever(
                    retriever_kind="chroma",
                    chunks_b=self.chunks,
                    dense_index_b=Path("data_index") / "dense_B",
                    hybrid_alpha=self.hybrid_alpha,
                    table_multiplier=1.0,
                    chroma_persist_dir=chroma_persist_dir,
                    chroma_collection=chroma_collection,
                    chroma_model=chroma_model,
                    chroma_org_filter=False,
                    chroma_org_filter_mode="soft",
                    chroma_score_weight=base_chroma_weight,
                    lexical_score_weight=base_lexical_weight,
                    chroma_noise_mode=chroma_noise_mode,
                    chroma_mmr=chroma_mmr,
                    chroma_mmr_lambda=chroma_mmr_lambda,
                    chroma_query_rewrite=chroma_query_rewrite,
                )
            except Exception:
                self.global_retriever = None
        self.asset_retriever = self._build_asset_retriever(
            chroma_persist_dir=chroma_persist_dir,
            chroma_model=chroma_model,
            asset_collection=asset_collection,
        )

    @staticmethod
    def _load_asset_chunks(*, joined_chunks_path: Path, asset_chunks_dir: Path) -> List[ChunkRecord]:
        if not asset_chunks_dir.exists():
            return []
        joined_meta = load_joined_metadata(joined_chunks_path)
        items = load_chunks_rich(asset_chunks_dir)
        out: List[ChunkRecord] = []
        for item in items:
            out.append(
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
            )
        return out

    def _build_asset_retriever(
        self,
        *,
        chroma_persist_dir: Path,
        chroma_model: str,
        asset_collection: str,
    ):
        if not self.asset_chunks:
            return None
        try:
            return _build_retriever(
                retriever_kind="chroma",
                chunks_b=self.asset_chunks,
                dense_index_b=Path("data_index") / "dense_B",
                hybrid_alpha=1.0,
                table_multiplier=1.0,
                chroma_persist_dir=chroma_persist_dir,
                chroma_collection=asset_collection,
                chroma_model=chroma_model,
                chroma_org_filter=False,
                chroma_org_filter_mode="soft",
                chroma_score_weight=0.8,
                lexical_score_weight=0.2,
                chroma_noise_mode="off",
                chroma_mmr=False,
                chroma_mmr_lambda=0.85,
                chroma_query_rewrite=True,
            )
        except Exception:
            return None

    @staticmethod
    def _status_score(status: str) -> int:
        s = (status or "").strip().lower()
        if s == "ok":
            return 2
        if s == "partial":
            return 1
        return 0

    @staticmethod
    def _has_substantive_answer(answer: str) -> bool:
        txt = (answer or "").strip()
        return bool(txt and "문서에 해당 정보가 없습니다" not in txt)

    @classmethod
    def _is_better_result(
        cls,
        candidate_state: ChatState,
        candidate_contexts: Sequence[ChunkRecord],
        current_state: ChatState,
        current_contexts: Sequence[ChunkRecord],
    ) -> bool:
        candidate_score = cls._status_score(candidate_state.status)
        current_score = cls._status_score(current_state.status)
        if candidate_score != current_score:
            return candidate_score > current_score

        candidate_has_answer = cls._has_substantive_answer(candidate_state.answer)
        current_has_answer = cls._has_substantive_answer(current_state.answer)
        if candidate_has_answer != current_has_answer:
            return candidate_has_answer

        if candidate_score == 0:
            return False
        return len(candidate_contexts) > len(current_contexts)

    @staticmethod
    def _sources_from_contexts(contexts: Sequence[ChunkRecord], limit: int = 8) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for c in contexts:
            src = (c.source_path or "").strip()
            if not src or src in seen:
                continue
            seen.add(src)
            out.append(src)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _to_context_payload(contexts: Sequence[ChunkRecord]) -> List[Dict[str, object]]:
        return [
            {
                "source_path": c.source_path,
                "chunk_index": c.chunk_index,
                "chunk_id": c.chunk_id,
                "text": c.text,
                "metadata": c.metadata if isinstance(c.metadata, dict) else None,
            }
            for c in contexts
        ]

    @staticmethod
    def _count_org_like_entities(query: str) -> int:
        q = (query or "").strip()
        if not q:
            return 0
        head = q.split("에서", 1)[0] if "에서" in q else q
        parts = re.split(r"\s+(?:과|와|및)\s+", head)
        cnt = 0
        for part in parts:
            token = re.sub(r"[\"'“”‘’\[\]{}()]", "", part).strip()
            if len(token) < 3:
                continue
            if _ORG_SUFFIX_RE.search(token) or token.startswith(
                ("한국", "국립", "국가", "재단법인", "사단법인", "(재)", "(사)")
            ):
                cnt += 1
        return cnt

    @classmethod
    def _estimate_query_hardness(cls, query: str) -> int:
        q = (query or "").strip()
        if not q:
            return 0
        score = 0
        token_count = len(re.findall(r"[0-9A-Za-z가-힣]+", q))
        if len(q) >= 80:
            score += 2
        elif len(q) >= 45:
            score += 1
        if token_count >= 16:
            score += 2
        elif token_count >= 10:
            score += 1
        if _COMPLEX_QUERY_RE.search(q):
            score += 2
        if len(_CLAUSE_CONNECTOR_RE.findall(q)) >= 2:
            score += 1
        if cls._count_org_like_entities(q) >= 2:
            score += 2
        if _FACTOID_QUERY_RE.search(q) and token_count <= 12 and not _COMPLEX_QUERY_RE.search(q):
            score -= 2
        return score

    def _select_dynamic_retriever_kind(self, query: str) -> str:
        score = self._estimate_query_hardness(query)
        if score >= self.dynamic_hard_threshold:
            return "chroma"
        return "hybrid"

    def _run_answer_pass(
        self,
        *,
        base_state: ChatState,
        query: str,
        model: str,
        retriever,
        chunks: Sequence[ChunkRecord],
        retrieval_query: str,
        retrieve_k: int,
        context_k: int,
        source_filter: set[str] | None = None,
    ) -> tuple[ChatState, List[ChunkRecord]]:
        raw: List[ChunkRecord] = []
        if retriever is not None:
            raw = retriever.retrieve(retrieval_query, chunks, k=retrieve_k)
        if source_filter:
            raw = [c for c in raw if c.source_path in source_filter]

        expanded = _expand_candidates_with_neighbors(
            raw,
            chunks,
            target_k=max(retrieve_k, min(retrieve_k + 80, retrieve_k * 2)),
            neighbor_window=1,
        )
        if source_filter:
            expanded = [c for c in expanded if c.source_path in source_filter]

        reranked, _ = _rerank(query, expanded, rerank_mode=self.rerank, llm_model=model)
        if source_filter:
            reranked = [c for c in reranked if c.source_path in source_filter]

        contexts = _expand_contexts_with_neighbors(
            reranked, chunks, context_k=context_k, neighbor_window=1
        )
        if source_filter:
            contexts = [c for c in contexts if c.source_path in source_filter]

        pass_state = ChatState(intent=base_state.intent, org=base_state.org)
        pass_state = generate_answer_node(
            pass_state,
            self._to_context_payload(contexts),
            model=model,
        )
        return pass_state, contexts

    def answer(self, query: str, model: str = "gpt-5-nano") -> Dict[str, object]:
        intent = parse_query(query)
        org = parse_org(query)
        state = ChatState(intent=intent, org=org)

        is_money_rank = intent.query_type == "money_rank"
        use_asset = intent.query_type == "asset" and self.asset_retriever is not None
        dynamic_kind = ""
        if self.retriever_kind == "dynamic" and not is_money_rank and not use_asset:
            dynamic_kind = self._select_dynamic_retriever_kind(query)

        if not is_money_rank and not use_asset:
            token_count = len(re.findall(r"[0-9A-Za-z가-힣]+", query or ""))
            need_org_for_chroma = (
                self.retriever_kind == "chroma"
                or (self.retriever_kind == "dynamic" and dynamic_kind == "chroma")
            )
            if need_org_for_chroma and not org.matched and token_count <= 8:
                mode = "dynamic_chroma" if self.retriever_kind == "dynamic" else "default"
                return {
                    "status": "need_org",
                    "answer": "정확한 검색을 위해 기관명을 먼저 입력해주세요. 예: `한국농어촌공사`, `고려대학교`",
                    "citations": [],
                    "top1": {"source_path": "", "chunk_index": -1},
                    "retrieval_mode": mode,
                    "retrieved_contexts": [],
                }
        active_retriever = self.asset_retriever if use_asset else self.retriever
        if self.retriever_kind == "dynamic" and not use_asset and not is_money_rank:
            if dynamic_kind == "chroma":
                active_retriever = self.dynamic_chroma_retriever or self.global_retriever
            else:
                active_retriever = self.dynamic_hybrid_retriever or self.dynamic_chroma_retriever
        if is_money_rank:
            if self.money_rank_retriever is not None:
                active_retriever = self.money_rank_retriever
            elif self.global_retriever is not None:
                active_retriever = self.global_retriever
        active_chunks = self.asset_chunks if use_asset else self.chunks

        retrieval_query = query
        retrieve_k = self.top_k
        context_k = self.context_k
        if is_money_rank:
            retrieval_query = f"{query} 사업예산 사업비 총사업비 예정가격 기초금액 금액 원 억원"
            retrieve_k = max(self.top_k, 240)
            context_k = max(self.context_k, 120)

        if use_asset:
            base_mode = "asset"
        elif is_money_rank:
            base_mode = "money_rank"
        elif self.retriever_kind == "dynamic":
            selected = dynamic_kind or "hybrid"
            base_mode = f"dynamic_{selected}"
        else:
            base_mode = "default"
        primary_state, primary_contexts = self._run_answer_pass(
            base_state=state,
            query=query,
            model=model,
            retriever=active_retriever,
            chunks=active_chunks,
            retrieval_query=retrieval_query,
            retrieve_k=retrieve_k,
            context_k=context_k,
        )

        final_state = primary_state
        final_contexts = primary_contexts
        retrieval_mode = base_mode

        should_try_asset_fallback = (
            not use_asset
            and self.asset_retriever is not None
            and (not primary_contexts or self._status_score(primary_state.status) == 0)
        )
        if should_try_asset_fallback:
            source_hints = self._sources_from_contexts(primary_contexts)
            if source_hints:
                # 2차는 같은 source에 한정한 asset 검색만 수행한다(레이턴시 최적화).
                fallback_state, fallback_contexts = self._run_answer_pass(
                    base_state=state,
                    query=query,
                    model=model,
                    retriever=self.asset_retriever,
                    chunks=self.asset_chunks,
                    retrieval_query=retrieval_query,
                    retrieve_k=retrieve_k,
                    context_k=context_k,
                    source_filter=set(source_hints),
                )
                if self._is_better_result(
                    fallback_state,
                    fallback_contexts,
                    final_state,
                    final_contexts,
                ):
                    final_state = fallback_state
                    final_contexts = fallback_contexts
                    retrieval_mode = "asset_fallback"

        return {
            "status": final_state.status or "not_found",
            "answer": final_state.answer or "문서에 해당 정보가 없습니다.",
            "citations": final_state.citations,
            "top1": {
                "source_path": final_contexts[0].source_path if final_contexts else "",
                "chunk_index": final_contexts[0].chunk_index if final_contexts else -1,
            },
            "retrieval_mode": retrieval_mode,
            "retrieved_contexts": [
                {
                    "source_path": c.source_path,
                    "chunk_index": c.chunk_index,
                    "text": c.text,
                    "metadata": c.metadata if isinstance(c.metadata, dict) else None,
                }
                for c in final_contexts
            ],
        }
