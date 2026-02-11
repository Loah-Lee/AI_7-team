#!/usr/bin/env python3
"""
입찰메이트 RFP 챗봇 v17 - Streamlit 웹 인터페이스
"""

import os
import sys
import time
from typing import TYPE_CHECKING

import streamlit as st
from dotenv import load_dotenv

# 경로 설정
sys.path.insert(0, 'src')

# 설정 로드
load_dotenv()

# LangSmith 트레이싱 활성화
from src.utils.config import (
    LANGSMITH_API_KEY,
    LANGSMITH_TRACING,
    LANGSMITH_ENDPOINT,
    LANGSMITH_PROJECT
)

if LANGSMITH_TRACING and LANGSMITH_API_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY
    os.environ["LANGCHAIN_ENDPOINT"] = LANGSMITH_ENDPOINT
    os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT

from src.utils.config import *

# Streamlit 페이지 설정
st.set_page_config(
    page_title="입찰메이트 RFP 챗봇 v17",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# CSS 스타일
# ============================================================================

STYLES = """
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        padding: 1rem;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 2rem;
    }
    .version-badge {
        display: inline-block;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 0.3rem 0.8rem;
        border-radius: 1rem;
        font-size: 0.9rem;
        font-weight: bold;
        margin-left: 0.5rem;
    }
    .feature-tag {
        display: inline-block;
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        color: white;
        padding: 0.2rem 0.6rem;
        border-radius: 0.3rem;
        font-size: 0.75rem;
        margin: 0.2rem;
        font-weight: bold;
    }
    .metric-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 1.5rem;
        border-radius: 1rem;
        text-align: center;
        border: 1px solid #e0e0e0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .metric-value {
        font-size: 2rem;
        font-weight: bold;
        color: #667eea;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #666;
        margin-top: 0.5rem;
    }
    .source-badge {
        display: inline-block;
        padding: 0.2rem 0.5rem;
        border-radius: 0.3rem;
        font-size: 0.75rem;
        font-weight: bold;
        margin-left: 0.5rem;
    }
    .source-csv { background: linear-gradient(135deg, #2196f3 0%, #1976d2 100%); color: white; }
    .source-pdf { background: linear-gradient(135deg, #ff9800 0%, #ff5722 100%); color: white; }
    .source-hwp { background: linear-gradient(135deg, #9c27b0 0%, #7b1fa2 100%); color: white; }
    .stButton>button { width: 100%; border-radius: 0.5rem; padding: 0.5rem 1rem; margin-bottom: 0.3rem; font-weight: 500; }
</style>
"""

st.markdown(STYLES, unsafe_allow_html=True)

# ============================================================================
# 챗봇 로드
# ============================================================================

@st.cache_resource
def get_chatbot():
    """챗봇을 로드합니다."""
    from src.graph.workflow import RAGChatbotV17
    
    data_dir = str(get_data_dir())
    return RAGChatbotV17(data_dir=data_dir)


# ============================================================================
# 답변 렌더링
# ============================================================================

SOURCE_BADGES = {
    "csv": '<span class="source-badge source-csv">📊 CSV</span>',
    "pdf": '<span class="source-badge source-pdf">📄 PDF</span>',
    "hwp": '<span class="source-badge source-hwp">📝 HWP</span>'
}


def render_answer(answer: str, source_type: str = "csv") -> None:
    """답변을 렌더링합니다."""
    badge = SOURCE_BADGES.get(source_type, "")
    st.markdown(answer + badge, unsafe_allow_html=True)


def render_metric_card(value: int | str, label: str) -> None:
    """메트릭 카드를 렌더링합니다."""
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{value}</div>
        <div class="metric-label">{label}</div>
    </div>
    """, unsafe_allow_html=True)


# ============================================================================
# 사이드바
# ============================================================================

ORG_QUESTION_DEFAULTS = [
    "고려대학교 사업비는 얼마인가요?",
    "서울특별시의 사업비는?",
    "서울시립대학교 정보 알려줘",
    "기초과학연구원 사업비",
    "한영대학 프로젝트 정보",
]

RANKING_QUESTION_DEFAULTS = [
    "사업비가 가장 많은 3곳은?",
    "사업비가 가장 적은 3곳은?",
    "TOP5 기관을 알려주세요",
]

SEARCH_QUESTION_DEFAULTS = [
    "IT 관련 사업은 어떤 것이 있나요?",
    "교육 분야 기관 찾아줘",
    "시스템 구축 관련 사업",
]


def render_sidebar(chatbot) -> None:
    """사이드바를 렌더링합니다."""
    with st.sidebar:
        st.header("📋 빠른 질문")

        st.subheader("🏢 기관별 조회")
        for q in ORG_QUESTION_DEFAULTS:
            if st.button(q, key=f"org_{hash(q)}", use_container_width=True):
                st.session_state.user_input = q

        st.subheader("📊 랭킹 조회")
        for q in RANKING_QUESTION_DEFAULTS:
            if st.button(q, key=f"rank_{hash(q)}", use_container_width=True):
                st.session_state.user_input = q

        st.subheader("🔍 전체 검색")
        for q in SEARCH_QUESTION_DEFAULTS:
            if st.button(q, key=f"search_{hash(q)}", use_container_width=True):
                st.session_state.user_input = q

        st.divider()

        st.subheader("📊 등록된 기관")

        if chatbot and chatbot.vector_store:
            total_orgs = len(chatbot.vector_store.org_registry)
            pdf_count = sum(1 for o in chatbot.vector_store.org_registry.values() if o.has_pdf)
            hwp_count = sum(1 for o in chatbot.vector_store.org_registry.values() if o.has_hwp)

            st.metric("총 기관", f"{total_orgs}개")
            st.metric("PDF", f"{pdf_count}개")
            st.metric("HWP", f"{hwp_count}개")

            st.markdown("**💰 사업비 TOP 5**")
            ranking = chatbot.vector_store.get_ranking("amount", 5)
            for i, org in enumerate(ranking, 1):
                if org.amount_numeric > 0:
                    st.text(f"{i}. {org.name}: {format_amount(org.amount_numeric)}")


# ============================================================================
# 메인 화면
# ============================================================================

FEATURE_TAGS = """
<div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1.5rem;">
    <span class="feature-tag">📊 CSV+HWP+PDF 통합</span>
    <span class="feature-tag">📝 마크다운 DB</span>
    <span class="feature-tag">⚡ 간결한 답변</span>
    <span class="feature-tag">🎯 RFP 핵심 추출</span>
</div>
"""


def render_header() -> None:
    """헤더를 렌더링합니다."""
    st.markdown(
        '<div class="main-header">🤖 입찰메이트 RFP 챗봇 <span class="version-badge">v17</span></div>',
        unsafe_allow_html=True
    )
    st.markdown(FEATURE_TAGS, unsafe_allow_html=True)


def render_metrics(chatbot) -> None:
    """메트릭 카드들을 렌더링합니다."""
    col1, col2, col3, col4 = st.columns(4)

    total_orgs = len(chatbot.vector_store.org_registry)
    pdf_count = sum(1 for o in chatbot.vector_store.org_registry.values() if o.has_pdf)
    hwp_count = sum(1 for o in chatbot.vector_store.org_registry.values() if o.has_hwp)
    total_chunks = chatbot.vector_store.count

    with col1:
        render_metric_card(total_orgs, "등록 기관")
    with col2:
        render_metric_card(pdf_count, "PDF 문서")
    with col3:
        render_metric_card(hwp_count, "HWP 문서")
    with col4:
        render_metric_card(f"{total_chunks:,}", "마크다운 청크")


def process_user_query(chatbot, query: str) -> None:
    """사용자 질문을 처리합니다."""
    with st.chat_message("user"):
        st.markdown(f"**{query}**")
    st.session_state.messages.append({"role": "user", "content": query})

    with st.chat_message("assistant"):
        with st.spinner("🔍 RFP 핵심 정보 추출 중..."):
            start_time = time.time()
            result = chatbot.answer(query)
            response_time = time.time() - start_time

        render_answer(result.get("answer", "죄송합니다. 답변을 생성할 수 없습니다."), result.get("source_type", "csv"))
        st.caption(f"⏱️ 응답 시간: {response_time:.2f}초")

    st.session_state.messages.append({
        "role": "assistant",
        "content": result.get("answer", ""),
        "source_type": result.get("source_type", "csv")
    })

    st.session_state.user_input = ""
    st.rerun()


# ============================================================================
# 메인 함수
# ============================================================================

def main() -> None:
    """메인 진입점 함수."""
    chatbot = get_chatbot()

    if not chatbot:
        st.error("❌ 챗봇을 로드할 수 없습니다.")
        st.info("데이터 디렉토리에 데이터가 있는지 확인하세요.")
        return

    render_header()
    render_metrics(chatbot)
    st.divider()
    render_sidebar(chatbot)

    chat_container = st.container()

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "user_input" not in st.session_state:
        st.session_state.user_input = ""

    with chat_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.markdown(f"**{message['content']}**")
                else:
                    render_answer(message["content"], message.get("source_type", "csv"))

    if prompt := st.chat_input("질문을 입력하세요... (기관명, 사업비, 랭킹 등)"):
        process_user_query(chatbot, prompt)

    if st.session_state.user_input and (
        len(st.session_state.messages) == 0 or
        st.session_state.messages[-1]["role"] == "assistant" or
        st.session_state.messages[-1]["content"] != st.session_state.user_input
    ):
        process_user_query(chatbot, st.session_state.user_input)


if __name__ == "__main__":
    main()
