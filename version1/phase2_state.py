"""
Phase 2 RAG Pipeline State Definition

Defines the shared state (TypedDict) used across all Phase 2 LangGraph nodes.
Includes custom reducer for deduplicating accumulated context chunks.
"""

from typing import TypedDict, List, Dict, Optional, Annotated


def merge_context_dedup(existing: List[Dict], new: List[Dict]) -> List[Dict]:
    """
    Custom reducer for accumulated_context field.

    Merges two context lists while deduplicating by chunk_id.
    When duplicate chunk_id is found, keeps the entry with higher final_score.

    Args:
        existing: Previously accumulated context chunks
        new: New context chunks from current step

    Returns:
        Merged and deduplicated context list
    """
    if not existing:
        return new if new else []
    if not new:
        return existing

    # Build lookup map: chunk_id -> chunk dict
    merged_map = {}

    # Add existing chunks to map
    for chunk in existing:
        chunk_id = chunk.get("chunk_id")
        if chunk_id:
            merged_map[chunk_id] = chunk

    # Merge new chunks, keeping higher scored duplicates
    for chunk in new:
        chunk_id = chunk.get("chunk_id")
        if not chunk_id:
            continue

        if chunk_id in merged_map:
            # Keep chunk with higher final_score
            existing_score = merged_map[chunk_id].get("final_score", 0.0)
            new_score = chunk.get("final_score", 0.0)
            if new_score > existing_score:
                merged_map[chunk_id] = chunk
        else:
            # New unique chunk
            merged_map[chunk_id] = chunk

    return list(merged_map.values())


class Phase2State(TypedDict):
    """
    Shared state for Phase 2 RAG pipeline.

    Flow:
    1. Stage 1 produces original_query, dense_query, sparse_query
    2. build_cot generates cot_steps list
    3. For each step:
       - prepare_step creates step_dense_query, step_sparse_query
       - search_and_rerank retrieves chunks, updates accumulated_context
    4. synthesize produces final_answer
    """

    # === Stage 1 Output ===
    original_query: str          # User's original question
    dense_query: str             # Refined query for vector search
    sparse_query: str            # Keywords for BM25/sparse search

    # === Chain-of-Thought ===
    cot_steps: List[str]         # List of reasoning sub-steps (1-3 steps)
    current_step_index: int      # Current step being processed (0-based)

    # === Per-step Search Queries ===
    step_dense_query: str        # Vector query for current step
    step_sparse_query: str       # Sparse query for current step
    hierarchy_id: Optional[str]  # Matched hierarchy section ID

    # === Accumulated Context (with deduplication reducer) ===
    accumulated_context: Annotated[List[Dict], merge_context_dedup]

    # === Final Output ===
    final_answer: str
