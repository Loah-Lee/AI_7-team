from typing import List, Dict, Any, Literal, Callable
from typing_extensions import TypedDict, Annotated
import operator


def merge_docs(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reducer function to merge document lists during parallel execution."""
    if not left:
        return right
    if not right:
        return left
    return left + right


def keep_last(left: str, right: str) -> str:
    """Reducer function that keeps the last value (for simple string fields)."""
    return right if right else left


class GraphState(TypedDict):
    """
    Advanced RAG Pipeline State
    
    Uses Annotated fields with reducer functions to handle parallel node execution.
    Each node specifies which fields it updates to avoid concurrent modification conflicts.
    """
    
    # =============== Router Output ===============
    question: str
    intent: Literal["metadata", "context", "hybrid"]
    
    # =============== Metadata Analyst Track ===============
    # These fields are ONLY updated by analyst and metadata_qa nodes
    analyst_reasoning: str
    dynamic_view: str
    qa_status: str
    qa_feedback: str
    retry_count: int
    
    # =============== Retrieval Track ===============
    # Annotated with merge_docs to handle parallel writes from retrieval node
    documents: Annotated[List[Dict[str, Any]], merge_docs]
    
    # =============== Final Output ===============
    final_answer: str


__all__ = ["GraphState", "merge_docs", "keep_last"]
