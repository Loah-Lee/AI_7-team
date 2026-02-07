"""LangGraph 노드 함수.

파이프라인 흐름: analyze_query → retrieve → extract_evidence → generate
"""

from __future__ import annotations

import json
import time

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.graph.state import RFPState, RetrievedDoc
from src.prompts.templates import (
    EVIDENCE_EXTRACTION_PROMPT,
    OUT_OF_SCOPE_PROMPT,
    QUERY_ANALYSIS_PROMPT,
    RAG_GENERATION_PROMPT,
)
from src.retrievers.metadata_filter import search_with_metadata
from src.utils.config import load_config
from src.utils.env import get_langfuse_keys, get_openai_api_key, load_env


def _get_langfuse_callback():
    """Langfuse LangChain 콜백 핸들러를 반환한다. 키가 없으면 None."""
    load_env()
    keys = get_langfuse_keys()
    if not keys["public_key"] or not keys["secret_key"]:
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler(
            public_key=keys["public_key"],
            secret_key=keys["secret_key"],
            host=keys["host"],
        )
    except Exception:
        return None


def _get_llm(
    model: str | None = None,
    temperature: float | None = None,
) -> ChatOpenAI:
    config = load_config()
    llm_cfg = config.get("llm", {})

    callbacks = []
    langfuse_cb = _get_langfuse_callback()
    if langfuse_cb:
        callbacks.append(langfuse_cb)

    return ChatOpenAI(
        model=model or llm_cfg.get("model", "gpt-5-mini"),
        temperature=temperature if temperature is not None else llm_cfg.get("temperature", 0.0),
        max_tokens=llm_cfg.get("max_tokens", 4096),
        api_key=get_openai_api_key(),
        callbacks=callbacks if callbacks else None,
    )


def analyze_query(state: RFPState) -> RFPState:
    """사용자 질의를 분석하여 query_type, metadata_filter를 추출한다."""
    start = time.time()
    llm = _get_llm(
        model=state.get("llm_model"),
        temperature=state.get("llm_temperature"),
    )
    query = state["query"]

    chain = QUERY_ANALYSIS_PROMPT | llm
    result = chain.invoke({"query": query})

    # LLM 응답에서 JSON 추출 (마크다운 코드블록 처리)
    content = result.content.strip()
    if content.startswith("```"):
        # ```json ... ``` 블록에서 JSON만 추출
        lines = content.split("\n")
        json_lines = []
        inside = False
        for line in lines:
            if line.strip().startswith("```") and not inside:
                inside = True
                continue
            elif line.strip().startswith("```") and inside:
                break
            elif inside:
                json_lines.append(line)
        content = "\n".join(json_lines)

    try:
        analysis = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        analysis = {"query_type": "single_doc", "keywords": []}

    query_type = analysis.get("query_type", "single_doc")
    is_out_of_scope = query_type == "out_of_scope"

    # 사이드바에서 전달된 기존 필터를 기반으로 시작
    existing_filter = state.get("metadata_filter") or {}
    metadata_filter = dict(existing_filter)

    # LLM이 분석한 값은 사용자 입력이 없는 필드만 보충
    if not metadata_filter.get("institution") and analysis.get("institution"):
        metadata_filter["institution"] = str(analysis["institution"])
    if not metadata_filter.get("project_name") and analysis.get("project_name"):
        metadata_filter["project_name"] = str(analysis["project_name"])
    if not metadata_filter.get("year") and analysis.get("year"):
        metadata_filter["year"] = str(analysis["year"])
    if analysis.get("keywords"):
        metadata_filter["keywords"] = [str(k) for k in analysis["keywords"]]

    elapsed = time.time() - start
    return {
        "query_type": query_type,
        "is_out_of_scope": is_out_of_scope,
        "metadata_filter": metadata_filter,
        "latencies": {"analyze_query": elapsed},
    }


def retrieve(state: RFPState) -> RFPState:
    """메타데이터 필터를 적용하여 관련 문서를 검색한다."""
    start = time.time()

    if state.get("is_out_of_scope"):
        return {"retrieved_docs": [], "latencies": {"retrieve": 0.0}}

    query = state["query"]
    metadata_filter = state.get("metadata_filter")

    docs = search_with_metadata(
        query,
        metadata_filter=metadata_filter,
        top_k=state.get("retriever_top_k"),
        search_type=state.get("retriever_search_type"),
    )

    # --- Verbose logging ---
    print(f"\n{'='*70}")
    print(f"[RETRIEVE] query: {query}")
    if metadata_filter:
        print(f"[RETRIEVE] filters: {metadata_filter}")
    print(f"[RETRIEVE] {len(docs)}개 청크 검색됨")
    print(f"{'-'*70}")
    for i, doc in enumerate(docs, start=1):
        page = doc.metadata.get("page", "?")
        score = doc.metadata.get("score", 0.0)
        source = doc.metadata.get("source", "unknown")
        section = doc.metadata.get("section", "")
        snippet = doc.page_content[:50].replace("\n", " ")
        section_info = f" | Section: {section}" if section else ""
        print(f"  [Chunk {i}] Page {page} | Score: {score} | {source}{section_info}")
        print(f"            Content: {snippet}...")
    print(f"{'='*70}\n")
    # --- End logging ---

    retrieved_docs: list[RetrievedDoc] = [
        {
            "content": doc.page_content,
            "source": doc.metadata.get("source", "unknown"),
            "page": doc.metadata.get("page"),
            "score": doc.metadata.get("score", 0.0),
            "metadata": doc.metadata,
        }
        for doc in docs
    ]

    elapsed = time.time() - start
    return {
        "retrieved_docs": retrieved_docs,
        "latencies": {"retrieve": elapsed},
    }


def _filter_docs_by_score(
    docs: list[RetrievedDoc],
    score_threshold: float,
    max_docs: int = 5,
    fallback_top_n: int = 3,
) -> list[RetrievedDoc]:
    """점수 기반으로 저품질 청크를 사전 필터링한다."""
    filtered = [d for d in docs if d.get("score", 0.0) >= score_threshold]
    if not filtered:
        # 전부 필터링되면 점수 상위 N개 폴백
        sorted_docs = sorted(docs, key=lambda d: d.get("score", 0.0), reverse=True)
        return sorted_docs[:fallback_top_n]
    return filtered[:max_docs]


def extract_evidence(state: RFPState) -> RFPState:
    """검색된 문서에서 핵심 근거를 추출한다."""
    start = time.time()

    if state.get("is_out_of_scope") or not state.get("retrieved_docs"):
        return {"evidence": "", "latencies": {"extract_evidence": 0.0}}

    # 점수 기반 사전 필터링
    config = load_config()
    score_threshold = config.get("retriever", {}).get("score_threshold", 0.3)
    quality_docs = _filter_docs_by_score(state["retrieved_docs"], score_threshold)

    llm = _get_llm(
        model=state.get("llm_model"),
        temperature=state.get("llm_temperature"),
    )
    query = state["query"]

    docs_text = "\n\n---\n\n".join(
        f"[출처: {doc['source']}, 페이지: {doc.get('page', 'N/A')}]\n{doc['content']}"
        for doc in quality_docs
    )

    chain = EVIDENCE_EXTRACTION_PROMPT | llm
    try:
        result = chain.invoke({"query": query, "retrieved_docs": docs_text})
        evidence = result.content.strip()
    except Exception as e:
        print(f"[extract_evidence] LLM 호출 실패: {e}")
        evidence = ""

    # 빈 응답이면 원본 청크를 출처 포함하여 폴백
    if not evidence:
        evidence = docs_text

    elapsed = time.time() - start
    return {
        "evidence": evidence,
        "latencies": {"extract_evidence": elapsed},
    }


def generate(state: RFPState) -> RFPState:
    """최종 답변을 생성한다."""
    start = time.time()
    llm = _get_llm(
        model=state.get("llm_model"),
        temperature=state.get("llm_temperature"),
    )
    query = state["query"]

    if state.get("is_out_of_scope"):
        chain = OUT_OF_SCOPE_PROMPT | llm
        result = chain.invoke({"query": query})
    else:
        context = state.get("evidence", "")
        if not context:
            context = "\n\n---\n\n".join(
                doc["content"] for doc in state.get("retrieved_docs", [])
            )

        chat_history = state.get("messages", [])
        chain = RAG_GENERATION_PROMPT | llm
        result = chain.invoke({
            "query": query,
            "context": context,
            "chat_history": chat_history,
        })

    elapsed = time.time() - start
    return {
        "answer": result.content,
        "messages": [AIMessage(content=result.content)],
        "latencies": {"generate": elapsed},
    }
