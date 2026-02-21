from __future__ import annotations

from pathlib import Path
from typing import Dict, List

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
    ) -> None:
        self.retriever_kind = retriever
        self.rerank = rerank
        self.top_k = top_k
        self.context_k = context_k
        self.chunks = _load_chunks_b(Path("notebooks") / "data_chunks_rich_joined.jsonl")
        self.retriever = _build_retriever(
            retriever_kind=self.retriever_kind,
            chunks_b=self.chunks,
            dense_index_b=Path("data_index") / "dense_B",
            hybrid_alpha=0.8,
            table_multiplier=1.0,
            chroma_persist_dir=Path("data_index") / "chroma_B",
            chroma_collection="rfp_b_auto",
            chroma_model="auto",
            chroma_org_filter=False,
        )

    def answer(self, query: str, model: str = "gpt-5-nano") -> Dict[str, object]:
        intent = parse_query(query)
        org = parse_org(query)
        state = ChatState(intent=intent, org=org)

        raw: List[ChunkRecord] = self.retriever.retrieve(query, self.chunks, k=self.top_k)
        expanded = _expand_candidates_with_neighbors(
            raw,
            self.chunks,
            target_k=max(self.top_k, min(self.top_k + 30, self.top_k * 2)),
            neighbor_window=1,
        )
        reranked, _ = _rerank(query, expanded, rerank_mode=self.rerank, llm_model=model)
        contexts = _expand_contexts_with_neighbors(
            reranked, self.chunks, context_k=self.context_k, neighbor_window=1
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
        }
