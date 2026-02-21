#!/usr/bin/env python3
"""입찰메이트 RAG 챗봇 - Streamlit 웹 인터페이스."""

from __future__ import annotations

import os
import re
import sys
import time
import uuid

import streamlit as st
from dotenv import load_dotenv

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

load_dotenv()

st.set_page_config(
    page_title="입찰메이트 RAG 챗봇",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

STYLES = """
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: bold;
        text-align: center;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    .version-badge {
        display: inline-block;
        background: #1f77b4;
        color: white;
        padding: 0.3rem 0.8rem;
        border-radius: 1rem;
        font-size: 0.85rem;
        margin-left: 0.5rem;
    }
    .feature-tag {
        display: inline-block;
        background: #2563eb;
        color: white;
        padding: 0.2rem 0.6rem;
        border-radius: 0.3rem;
        font-size: 0.75rem;
        margin: 0.2rem;
    }
    .metric-card {
        background: #f8fafc;
        padding: 1rem;
        border-radius: 0.7rem;
        text-align: center;
        border: 1px solid #e5e7eb;
    }
    .metric-value {
        font-size: 1.4rem;
        font-weight: bold;
    }
    .metric-label {
        font-size: 0.85rem;
        color: #6b7280;
        margin-top: 0.4rem;
    }
</style>
"""
st.markdown(STYLES, unsafe_allow_html=True)


@st.cache_resource
def get_chatbot():
    """RAG 챗봇 로드."""
    from src.graph.workflow import RAGChatbot

    return RAGChatbot(
        retriever="hybrid",
        rerank="none",
        top_k=50,
        context_k=20,
    )


@st.cache_resource
def get_langfuse_tracer():
    from src.evaluation.langfuse_tracer import get_langfuse_tracer as _get

    return _get()


def render_metric_card(value: int | str, label: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-value">{value}</div>
            <div class="metric-label">{label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown(
        '<div class="main-header">🤖 입찰메이트 RAG 챗봇 <span class="version-badge">hybrid</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem;">
            <span class="feature-tag">Hybrid Retrieval</span>
            <span class="feature-tag">TopK 50</span>
            <span class="feature-tag">Context 20</span>
            <span class="feature-tag">Citations</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metrics(chatbot) -> None:
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_metric_card(chatbot.retriever_kind, "Retriever")
    with col2:
        render_metric_card(chatbot.rerank, "Rerank")
    with col3:
        render_metric_card(chatbot.top_k, "Top-K")
    with col4:
        render_metric_card(f"{len(chatbot.chunks):,}", "Chunks")


RAG_QUESTION_DEFAULTS = [
    "한국농어촌공사 입찰 보증금 비율은 얼마인가?",
    "한국농어촌공사 제안서 제출 마감일은 언제인가?",
    "고려대학교 평가 기준 중 기술평가 비중은?",
    "국립중앙의료원 사업예산은 얼마인가?",
]


def render_sidebar(chatbot) -> None:
    with st.sidebar:
        current_org = st.session_state.get("session_org", "")
        if current_org:
            st.caption(f"현재 기관 컨텍스트: `{current_org}`")
            if st.button("기관 컨텍스트 초기화", use_container_width=True):
                st.session_state.session_org = ""
                st.session_state.pending_org_query = ""
                st.rerun()

        st.header("빠른 질문")
        for q in RAG_QUESTION_DEFAULTS:
            if st.button(q, key=f"q_{hash(q)}", use_container_width=True):
                st.session_state.user_input = q

        st.divider()
        if st.button("챗봇 캐시 초기화", use_container_width=True):
            st.cache_resource.clear()
            st.session_state.messages = []
            st.session_state.user_input = ""
            st.rerun()

        st.caption(f"app: `{__file__}`")
        st.caption(f"retriever: `{chatbot.retriever_kind}`")
        st.caption(f"rerank: `{chatbot.rerank}`")
        st.caption(f"top_k/context_k: `{chatbot.top_k}/{chatbot.context_k}`")


def _extract_org_name(query: str) -> str:
    from src.graph.nodes import parse_org

    org = parse_org(query)
    if org.matched and org.org_name:
        return org.org_name.strip()
    return ""


def _looks_like_org_name(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if len(t) > 40:
        return False
    if re.search(r"[?？!！]", t):
        return False
    return bool(
        re.search(r"(공사|공단|재단|대학교|대학|병원|정보원|진흥원|연구원|협회|위원회|공항)$", t)
        or t.startswith("한국")
    )


def _append_assistant_message(text: str) -> None:
    with st.chat_message("assistant"):
        st.markdown(text)
    st.session_state.messages.append({"role": "assistant", "content": text})


def process_user_query(chatbot, query: str) -> None:
    tracer = get_langfuse_tracer()
    trace_name = "streamlit_user_query"
    trace_base_payload = {
        "query": query,
        "session_id": st.session_state.get("langfuse_session_id"),
        "tags": ["streamlit", "rag", f"retriever:{chatbot.retriever_kind}"],
        "version": "app.main.v1",
    }

    with st.chat_message("user"):
        st.markdown(f"**{query}**")
    st.session_state.messages.append({"role": "user", "content": query})

    pending_org_query = st.session_state.get("pending_org_query", "")
    session_org = st.session_state.get("session_org", "")
    detected_org = _extract_org_name(query)
    effective_query = query

    if pending_org_query:
        org_candidate = detected_org or query.strip()
        if not _looks_like_org_name(org_candidate):
            _append_assistant_message(
                "기관명을 먼저 확인해야 정확한 답변이 가능합니다. 예: `한국농어촌공사`, `고려대학교`"
            )
            st.session_state.user_input = ""
            st.rerun()
            return

        st.session_state.session_org = org_candidate
        st.session_state.pending_org_query = ""
        _append_assistant_message(
            f"기관 컨텍스트를 `{org_candidate}`로 설정했습니다. 이어서 답변합니다."
        )
        effective_query = f"{org_candidate} {pending_org_query}".strip()
    elif detected_org:
        st.session_state.session_org = detected_org
    elif session_org:
        effective_query = f"{session_org} {query}".strip()
    else:
        st.session_state.pending_org_query = query
        _append_assistant_message(
            "어느 기관 문서를 기준으로 찾을까요? 기관명을 먼저 입력해주세요. 예: `한국농어촌공사`"
        )
        st.session_state.user_input = ""
        st.rerun()
        return

    span = None
    with st.chat_message("assistant"):
        with st.spinner("검색/생성 중..."):
            start_span_fn = getattr(tracer, "start_span", None)
            if callable(start_span_fn):
                span = start_span_fn(trace_name, trace_base_payload)
            start_time = time.time()
            result = chatbot.answer(effective_query)
            response_time = time.time() - start_time

        st.markdown(result.get("answer", "답변 생성 실패"))
        st.caption(f"status: {result.get('status', 'unknown')}")
        if effective_query != query:
            st.caption(f"effective_query: {effective_query}")
        top1 = result.get("top1", {}) or {}
        if top1.get("source_path"):
            st.caption(
                f"top1: {top1.get('source_path')} (chunk {top1.get('chunk_index')})"
            )
        citations = result.get("citations", []) or []
        if citations:
            st.markdown("**citations**")
            for c in citations:
                st.write(f"- {c}")
        st.caption(f"응답 시간: {response_time:.2f}초")

    try:
        trace_payload = {
            **trace_base_payload,
            "effective_query": effective_query,
            "status": result.get("status", "unknown"),
            "answer": result.get("answer", ""),
            "top1": result.get("top1", {}),
            "citations": result.get("citations", []),
            "response_time_sec": round(response_time, 4),
        }
        if span is not None:
            end_span_fn = getattr(tracer, "end_span", None)
            if callable(end_span_fn):
                end_span_fn(span, trace_name, trace_payload)
            else:
                tracer.trace(name=trace_name, payload=trace_payload)
        else:
            tracer.trace(name=trace_name, payload=trace_payload)
    except Exception:
        pass

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result.get("answer", ""),
        }
    )

    st.session_state.user_input = ""
    st.rerun()


def main() -> None:
    chatbot = get_chatbot()
    if not chatbot:
        st.error("챗봇 로드 실패")
        return

    render_header()
    render_metrics(chatbot)
    st.divider()
    render_sidebar(chatbot)

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "user_input" not in st.session_state:
        st.session_state.user_input = ""
    if "session_org" not in st.session_state:
        st.session_state.session_org = ""
    if "pending_org_query" not in st.session_state:
        st.session_state.pending_org_query = ""
    if "langfuse_session_id" not in st.session_state:
        st.session_state.langfuse_session_id = str(uuid.uuid4())

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.markdown(f"**{message['content']}**")
            else:
                st.markdown(message["content"])

    if prompt := st.chat_input("질문을 입력하세요"):
        process_user_query(chatbot, prompt)

    if st.session_state.user_input and (
        not st.session_state.messages
        or st.session_state.messages[-1]["role"] == "assistant"
        or st.session_state.messages[-1]["content"] != st.session_state.user_input
    ):
        process_user_query(chatbot, st.session_state.user_input)


if __name__ == "__main__":
    main()
