from __future__ import annotations

from pathlib import Path
from typing import Dict, List

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
    ) -> None:
        self.retriever_kind = retriever
        self.rerank = rerank
        self.top_k = top_k
        self.context_k = context_k
        self.chunks = _load_chunks_b(Path("notebooks") / "data_chunks_rich_joined.jsonl")
        self.asset_chunks = self._load_asset_chunks(
            joined_chunks_path=Path("notebooks") / "data_chunks_rich_joined.jsonl",
            asset_chunks_dir=Path("notebooks") / "data_chunks_rich_asset_v1",
        )
        self.retriever = _build_retriever(
            retriever_kind=self.retriever_kind,
            chunks_b=self.chunks,
            dense_index_b=Path("data_index") / "dense_B",
            hybrid_alpha=1.0,
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

    def answer(self, query: str, model: str = "gpt-5-nano") -> Dict[str, object]:
        intent = parse_query(query)
        org = parse_org(query)
        state = ChatState(intent=intent, org=org)

        use_asset = intent.query_type == "asset" and self.asset_retriever is not None
        if self.retriever_kind == "chroma" and not org.matched:
            return {
                "status": "need_org",
                "answer": "정확한 검색을 위해 기관명을 먼저 입력해주세요. 예: `한국농어촌공사`, `고려대학교`",
                "citations": [],
                "top1": {"source_path": "", "chunk_index": -1},
                "retrieval_mode": "asset" if use_asset else "default",
            }
        active_retriever = self.asset_retriever if use_asset else self.retriever
        active_chunks = self.asset_chunks if use_asset else self.chunks

        raw: List[ChunkRecord] = active_retriever.retrieve(query, active_chunks, k=self.top_k)
        expanded = _expand_candidates_with_neighbors(
            raw,
            active_chunks,
            target_k=max(self.top_k, min(self.top_k + 30, self.top_k * 2)),
            neighbor_window=1,
        )
        reranked, _ = _rerank(query, expanded, rerank_mode=self.rerank, llm_model=model)
        contexts = _expand_contexts_with_neighbors(
            reranked, active_chunks, context_k=self.context_k, neighbor_window=1
        )
        state = generate_answer_node(
            state,
            [
                {
                    "source_path": c.source_path,
                    "chunk_index": c.chunk_index,
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "metadata": c.metadata if isinstance(c.metadata, dict) else None,
                }
                for c in contexts
            ],
            model=model,
        )
        return {
            "status": state.status or "not_found",
            "answer": state.answer or "문서에 해당 정보가 없습니다.",
            "citations": state.citations,
            "top1": {
                "source_path": contexts[0].source_path if contexts else "",
                "chunk_index": contexts[0].chunk_index if contexts else -1,
            },
            "retrieval_mode": "asset" if use_asset else "default",
        }
