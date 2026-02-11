"""
Phase 2 RAG Pipeline
=====================
6-node LangGraph pipeline with Chain-of-Thought multi-step retrieval.

Architecture:
  START -> [expand] -> [build_cot] -> [prepare_step] -> [search_and_rerank] -> [step_router]
                                           ^                                       |
                                           +------ continue (next step) -----------+
                                                                                   |
                                                             done ---> [infer_answer] -> END

Bug Fixes (vs original implementation):
  #1: RRF reranking iterates explicit channel lists, NOT state.items()
  #2: Output docs include final_score, source_channels, rank fields
  #3: sparse_search uses l1 parameter for filtering, NOT h_id prefix hack
"""

import sys
import os
import json
import time
import dotenv
from typing import List, Dict, Literal, Optional
from typing_extensions import TypedDict
from threading import Lock
from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

dotenv.load_dotenv()

# ---------------------------------------------------------------------------
# Local imports
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from phase2_state import Phase2State, merge_context_dedup
from prompt import (
    PROMPT_CLARIFIER,
    PROMPT_LOGIC_REVIEWER,
    PROMPT_KEY_EXTRACTOR,
    PROMPT_KEY_VALIDATOR,
    COT_BUILDER_PROMPT,
    ANSWER_INFERENCE_PROMPT,
)
from SQLite_Retriever import vector_search, sparse_search, make_query_bigrams

# ===========================================================================
# Rate Limiter
# ===========================================================================
RATE_LIMIT_DELAY = 1.0
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_BACKOFF = 2.0


class RateLimiter:
    def __init__(self, min_interval: float = RATE_LIMIT_DELAY):
        self._min_interval = min_interval
        self._last_call = 0.0
        self._lock = Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()


rate_limiter = RateLimiter()


def call_with_rate_limit(chain, inputs, retries: int = RATE_LIMIT_MAX_RETRIES):
    """Invoke *chain* with automatic rate-limit back-off."""
    for attempt in range(retries):
        rate_limiter.wait()
        try:
            return chain.invoke(inputs)
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e).lower():
                wait = RATE_LIMIT_BACKOFF ** (attempt + 1)
                print(
                    f"  [Rate Limit] {wait:.1f}초 대기 후 재시도 "
                    f"({attempt + 1}/{retries})"
                )
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Rate limit 재시도 {retries}회 초과")


# ===========================================================================
# LLM Setup
# ===========================================================================
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
MAX_RETRIES = 2

# ===========================================================================
# Pydantic Models (structured output schemas)
# ===========================================================================


class Verdict(BaseModel):
    result: Literal["PASS", "FAIL"]
    feedback: str = Field(description="반려 사유 또는 수정 지침")


class Extraction(BaseModel):
    dense_query: str
    sparse_query: str


class CotPlan(BaseModel):
    steps: List[str]


# ===========================================================================
# Node 1: expand_node  (Stage 1 query expansion subgraph)
# ===========================================================================

# Internal state for the expansion subgraph --------------------------------

class _ExpandQueryState(TypedDict):
    original_query: str
    dense_query: str
    sparse_query: str
    expansion_feedback: str
    keyword_feedback: str
    retry_count_exp: int
    retry_count_key: int
    is_exp_verified: bool
    is_key_verified: bool


# Sub-agent node functions --------------------------------------------------

def _node_refine_query(state: _ExpandQueryState) -> dict:
    """Group A -- query refinement (Clarifier)."""
    chain = ChatPromptTemplate.from_template(PROMPT_CLARIFIER) | llm
    res = call_with_rate_limit(
        chain,
        {
            "original_query": state["original_query"],
            "expansion_feedback": state.get("expansion_feedback", ""),
        },
    )
    return {"dense_query": res.content.strip()}


def _node_logic_review(state: _ExpandQueryState) -> dict:
    """Group B -- logic verification (Logic-Reviewer)."""
    chain = ChatPromptTemplate.from_template(PROMPT_LOGIC_REVIEWER) | llm
    res = call_with_rate_limit(
        chain,
        {
            "original_query": state["original_query"],
            "dense_query": state["dense_query"],
        },
    )
    text = res.content.strip().upper()
    if "FAIL" in text:
        # Extract feedback after ISSUE: (if present)
        feedback = res.content.strip()
        for marker in ["ISSUE:", "ISSUES:"]:
            if marker in feedback.upper():
                idx = feedback.upper().index(marker)
                feedback = feedback[idx + len(marker):].strip()
                break
        return {
            "is_exp_verified": False,
            "expansion_feedback": feedback,
            "retry_count_exp": state.get("retry_count_exp", 0) + 1,
        }
    return {"is_exp_verified": True, "expansion_feedback": ""}


def _node_extract_keys(state: _ExpandQueryState) -> dict:
    """Group C -- keyword extraction (Key-Extractor)."""
    chain = ChatPromptTemplate.from_template(PROMPT_KEY_EXTRACTOR) | llm.with_structured_output(Extraction)
    res = call_with_rate_limit(
        chain,
        {
            "dense_query": state["dense_query"],
            "keyword_feedback": state.get("keyword_feedback", ""),
        },
    )
    return {"sparse_query": res.sparse_query}


def _node_technical_validate(state: _ExpandQueryState) -> dict:
    """Group D -- technical validation (Key-Validator)."""
    chain = ChatPromptTemplate.from_template(PROMPT_KEY_VALIDATOR) | llm
    res = call_with_rate_limit(
        chain,
        {
            "sparse_query": state["sparse_query"],
            "dense_query": state["dense_query"],
        },
    )
    text = res.content.strip().upper()
    if "FAIL" in text:
        feedback = res.content.strip()
        for marker in ["ISSUES:", "ISSUE:"]:
            if marker in feedback.upper():
                idx = feedback.upper().index(marker)
                feedback = feedback[idx + len(marker):].strip()
                break
        return {
            "is_key_verified": False,
            "keyword_feedback": feedback,
            "retry_count_key": state.get("retry_count_key", 0) + 1,
        }
    return {"is_key_verified": True, "keyword_feedback": ""}


# Routing helpers -----------------------------------------------------------

def _route_refinement(state: _ExpandQueryState) -> str:
    if state.get("is_exp_verified") or state.get("retry_count_exp", 0) >= MAX_RETRIES:
        return "proceed"
    return "retry"


def _route_validation(state: _ExpandQueryState) -> str:
    if state.get("is_key_verified") or state.get("retry_count_key", 0) >= MAX_RETRIES:
        return "end"
    return "retry"


# Build the compiled Stage-1 subgraph --------------------------------------

def _build_step1_graph():
    sg = StateGraph(_ExpandQueryState)

    sg.add_node("refine", _node_refine_query)
    sg.add_node("logic_review", _node_logic_review)
    sg.add_node("extract_keys", _node_extract_keys)
    sg.add_node("tech_validate", _node_technical_validate)

    sg.set_entry_point("refine")
    sg.add_edge("refine", "logic_review")
    sg.add_conditional_edges(
        "logic_review",
        _route_refinement,
        {"proceed": "extract_keys", "retry": "refine"},
    )
    sg.add_edge("extract_keys", "tech_validate")
    sg.add_conditional_edges(
        "tech_validate",
        _route_validation,
        {"end": END, "retry": "extract_keys"},
    )

    return sg.compile()


_step1_graph = _build_step1_graph()


def expand_node(state: Phase2State) -> dict:
    """Node 1 -- run the Stage 1 query-expansion subgraph."""
    res = _step1_graph.invoke(
        {
            "original_query": state["original_query"],
            "retry_count_exp": 0,
            "retry_count_key": 0,
        }
    )
    return {
        "dense_query": res["dense_query"],
        "sparse_query": res["sparse_query"],
    }


# ===========================================================================
# Node 2: build_cot_node
# ===========================================================================

def build_cot_node(state: Phase2State) -> dict:
    """Generate Chain-of-Thought search steps."""
    chain = (
        ChatPromptTemplate.from_template(COT_BUILDER_PROMPT)
        | llm.with_structured_output(CotPlan)
    )
    res = call_with_rate_limit(
        chain,
        {
            "original_query": state["original_query"],
            "dense_query": state["dense_query"],
        },
    )
    return {"cot_steps": res.steps, "current_step_index": 0}


# ===========================================================================
# Node 3: prepare_step_node
# ===========================================================================

def prepare_step_node(state: Phase2State) -> dict:
    """Lightweight per-step query refinement (Group A + C, no validation loops)."""
    step_text = state["cot_steps"][state["current_step_index"]]

    # Group A: refine step text
    chain_a = ChatPromptTemplate.from_template(PROMPT_CLARIFIER) | llm
    res_a = call_with_rate_limit(
        chain_a,
        {"original_query": step_text, "expansion_feedback": ""},
    )
    step_dense = res_a.content.strip()

    # Group C: extract keywords
    chain_c = (
        ChatPromptTemplate.from_template(PROMPT_KEY_EXTRACTOR)
        | llm.with_structured_output(Extraction)
    )
    res_c = call_with_rate_limit(
        chain_c,
        {"dense_query": step_dense, "keyword_feedback": ""},
    )
    return {
        "step_dense_query": step_dense,
        "step_sparse_query": res_c.sparse_query,
    }


# ===========================================================================
# Node 4: search_and_rerank_node
# ===========================================================================

def _doc_to_dict(doc, channel: str) -> Dict:
    """Normalize retrieval results to a standard dict format.

    Handles LangChain Document objects, plain dicts, and
    sparse_search tuple rows ``(section_level1, metadata_json, score)``.
    """
    # --- LangChain Document objects ---
    if hasattr(doc, "page_content"):
        metadata = getattr(doc, "metadata", {}) or {}
        return {
            "chunk_id": metadata.get("chunk_id", metadata.get("rowid", "unknown")),
            "text": doc.page_content or "",
            "metadata": metadata,
            "score": metadata.get("score", 0.0),
            "source_channel": channel,
        }

    # --- Plain dicts ---
    if isinstance(doc, dict):
        meta = doc.get("metadata", {}) or {}
        return {
            "chunk_id": meta.get("chunk_id", meta.get("rowid", "unknown")),
            "text": doc.get("text") or doc.get("page_content") or "",
            "metadata": meta,
            "score": doc.get("score", meta.get("score", 0.0)),
            "source_channel": channel,
        }

    # --- Tuples from sparse_search: (section_level1, metadata_json, score) ---
    if isinstance(doc, (list, tuple)) and len(doc) >= 3:
        try:
            meta = json.loads(doc[1]) if isinstance(doc[1], str) else (doc[1] or {})
            return {
                "chunk_id": meta.get("chunk_id", meta.get("rowid", "unknown")),
                "text": meta.get("text") or meta.get("content") or "",
                "metadata": meta,
                "score": doc[2],
                "source_channel": channel,
            }
        except Exception:
            pass

    # --- Fallback ---
    return {
        "chunk_id": "unknown",
        "text": "",
        "metadata": {},
        "score": 0.0,
        "source_channel": channel,
    }


def search_and_rerank_node(state: Phase2State) -> dict:
    """4-channel hybrid search + RRF reranking.

    Bug Fix #1: iterate explicit channel lists, NOT state.items()
    Bug Fix #2: output docs include final_score, source_channels, rank
    Bug Fix #3: sparse_search uses l1 parameter for filtering
    """
    d_query = state["step_dense_query"]
    s_query = state["step_sparse_query"]

    # 2-1: Hierarchy lookup
    h_results = vector_search(d_query, table="hierarchy", k=1)
    h_id = None
    if h_results:
        hr = h_results[0]
        if hasattr(hr, "page_content"):
            h_id = hr.page_content
        elif isinstance(hr, dict):
            h_id = hr.get("text") or hr.get("content")

    # 2-2 ~ 2-5: 4-channel search  (BUG FIX #1: explicit channel lists)
    ch1: List[Dict] = []  # filtered dense
    ch2: List[Dict] = []  # filtered sparse
    if h_id:
        raw = vector_search(
            d_query, table="chunks", filter={"section_level1": h_id}, k=5
        )
        ch1 = [_doc_to_dict(d, "filtered_dense") for d in raw]

        # BUG FIX #3: use l1 parameter with LIKE pattern
        raw = sparse_search(s_query, l1=f"%{h_id}%", l2="%", k=5)
        ch2 = [_doc_to_dict(d, "filtered_sparse") for d in raw]

    # Global dense (no filter)
    raw = vector_search(d_query, table="chunks", k=5)
    ch3 = [_doc_to_dict(d, "global_dense") for d in raw]

    # Global sparse (no filter -- pass '%' for l1/l2 to match everything via LIKE)
    raw = sparse_search(s_query, l1="%", l2="%", k=5)
    ch4 = [_doc_to_dict(d, "global_sparse") for d in raw]

    # --- RRF Reranking (BUG FIX #1: iterate explicit channels) ---
    k_rrf = 60
    numeric_tokens = [t for t in s_query.split() if "_" in t]

    rrf_scores: Dict[str, dict] = {}
    for channel_name, docs in [
        ("filtered_dense", ch1),
        ("filtered_sparse", ch2),
        ("global_dense", ch3),
        ("global_sparse", ch4),
    ]:
        for rank, doc in enumerate(docs, start=1):
            c_id = doc["chunk_id"]
            if c_id not in rrf_scores:
                has_numeric = (
                    any(token in doc["text"] for token in numeric_tokens)
                    if numeric_tokens
                    else False
                )
                rrf_scores[c_id] = {
                    "rrf_score": 0.0,
                    "doc": doc,
                    "channels": [],
                    "num_match": has_numeric,
                }
            rrf_scores[c_id]["rrf_score"] += 1.0 / (k_rrf + rank)
            rrf_scores[c_id]["channels"].append(channel_name)

    sorted_items = sorted(
        rrf_scores.values(),
        key=lambda x: (
            -x["rrf_score"],
            -x["num_match"],
            -any("filtered" in c for c in x["channels"]),
            -x["doc"].get("score", 0),
            x["doc"]["chunk_id"],
        ),
    )

    # BUG FIX #2: include final_score, source_channels, rank in output
    top5: List[Dict] = []
    for rank_idx, item in enumerate(sorted_items[:5], start=1):
        doc = item["doc"]
        doc["final_score"] = item["rrf_score"]
        doc["source_channels"] = item["channels"]
        doc["rank"] = rank_idx
        # Replace the single source_channel with the aggregated source_channels
        doc.pop("source_channel", None)
        top5.append(doc)

    return {"accumulated_context": top5, "hierarchy_id": h_id}


# ===========================================================================
# Node 5: step_router_node + route_step_loop
# ===========================================================================

def step_router_node(state: Phase2State) -> dict:
    """Advance the step index."""
    return {"current_step_index": state["current_step_index"] + 1}


def route_step_loop(state: Phase2State) -> str:
    """Conditional edge: continue to next step or proceed to inference."""
    if state["current_step_index"] < len(state["cot_steps"]):
        return "continue"
    return "done"


# ===========================================================================
# Node 6: infer_answer_node
# ===========================================================================

def infer_answer_node(state: Phase2State) -> dict:
    """Synthesize final answer from accumulated context."""
    # Sort by final_score descending
    docs = sorted(
        state["accumulated_context"],
        key=lambda x: x.get("final_score", 0),
        reverse=True,
    )

    # Build context block (500 chars per doc)
    context_parts: List[str] = []
    for i, doc in enumerate(docs, start=1):
        title = doc.get("metadata", {}).get("document_title", "N/A")
        section = doc.get("metadata", {}).get("section_level1", "")
        text = doc.get("text", "")[:500]
        context_parts.append(f"[문서 {i}] (출처: {title} > {section})\n{text}")

    context_block = "\n\n".join(context_parts)

    chain = ChatPromptTemplate.from_template(ANSWER_INFERENCE_PROMPT) | llm
    res = call_with_rate_limit(
        chain,
        {
            "original_query": state["original_query"],
            "doc_count": len(docs),
            "context_block": context_block,
        },
    )
    return {"final_answer": res.content.strip()}


# ===========================================================================
# Graph Assembly
# ===========================================================================

def build_phase2_graph():
    """Construct and compile the Phase 2 LangGraph pipeline."""
    graph = StateGraph(Phase2State)

    graph.add_node("expand", expand_node)
    graph.add_node("build_cot", build_cot_node)
    graph.add_node("prepare_step", prepare_step_node)
    graph.add_node("search_and_rerank", search_and_rerank_node)
    graph.add_node("step_router", step_router_node)
    graph.add_node("infer_answer", infer_answer_node)

    graph.set_entry_point("expand")
    graph.add_edge("expand", "build_cot")
    graph.add_edge("build_cot", "prepare_step")
    graph.add_edge("prepare_step", "search_and_rerank")
    graph.add_edge("search_and_rerank", "step_router")
    graph.add_conditional_edges(
        "step_router",
        route_step_loop,
        {"continue": "prepare_step", "done": "infer_answer"},
    )
    graph.add_edge("infer_answer", END)

    return graph.compile()


app = build_phase2_graph()


# ===========================================================================
# Entry Point
# ===========================================================================

def run_phase2(query: str) -> dict:
    """Run the full Phase 2 RAG pipeline for a single query.

    Args:
        query: The user's natural-language question.

    Returns:
        The final Phase2State dict with all intermediate and final results.
    """
    print(f"\n{'=' * 80}")
    print(" Phase 2 RAG Pipeline")
    print(f"{'=' * 80}")
    print(f"▶ Input: {query}\n")

    result = app.invoke({"original_query": query})

    # ----- Pretty-print results -----
    print(f"\n{'=' * 80}")
    print(" [RESULT]")
    print(f"{'=' * 80}")
    print(f"▶ Query      : {result['original_query']}")
    print(f"▶ Dense Query : {result['dense_query']}")
    print(f"▶ Sparse Query: {result['sparse_query']}")
    print(f"▶ CoT Steps   : {result['cot_steps']}")
    print(f"▶ Hierarchy   : {result.get('hierarchy_id', 'N/A')}")
    print(f"{'-' * 80}")

    sorted_docs = sorted(
        result["accumulated_context"],
        key=lambda x: x.get("final_score", 0),
        reverse=True,
    )
    for i, doc in enumerate(sorted_docs, start=1):
        print(
            f"[{i}위] Chunk ID: {doc['chunk_id']} | "
            f"Score: {doc['final_score']:.4f}"
        )
        print(f"    - 출처 채널: {', '.join(doc['source_channels'])}")
        title = doc.get("metadata", {}).get("document_title", "N/A")
        section = doc.get("metadata", {}).get("section_level1", "")
        print(f"    - 문서 경로: {title} > {section}")
        snippet = doc["text"].replace("\n", " ")[:250]
        if len(doc["text"]) > 250:
            snippet += "..."
        print(f"    - 본문: {snippet}")
        print(f"{'-' * 80}")

    print(f"\n▶ 최종 답변:\n{result['final_answer']}")
    print(f"{'=' * 80}")
    return result


if __name__ == "__main__":
    test_queries = [
        "철도 ISP 수립용역 마감 언제야?",
        "예산이 3억 5천만원 이상인 ISP 사업의 기술 요구사항은?",
    ]
    for q in test_queries:
        run_phase2(q)
