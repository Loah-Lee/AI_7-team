"""BiddingMate Streamlit 앱.

RFP 문서 분석 RAG 시스템의 실험 UI.
실행: streamlit run app/main.py
"""

from __future__ import annotations

import streamlit as st
from langchain_core.messages import HumanMessage

from src.evaluation.langsmith_tracer import setup_langsmith_tracing
from src.graph.workflow import build_graph
from src.retrievers.vectorstore import get_unique_institutions
from src.utils.config import load_config

# --- 페이지 설정 ---
st.set_page_config(
    page_title="BiddingMate - RFP 분석",
    page_icon="📋",
    layout="wide",
)

# --- LangSmith 트레이싱 활성화 ---
setup_langsmith_tracing()

# --- 설정 로드 ---
config = load_config()


def _deduplicate_sources(sources: list[dict]) -> list[dict]:
    """참조 문서를 파일명 기준으로 중복 제거하고, 페이지를 합산한다."""
    seen: dict[str, dict] = {}
    for src in sources:
        name = src.get("source", "unknown")
        if name not in seen:
            seen[name] = {**src, "pages": set()}
        page = src.get("page")
        if page is not None:
            seen[name]["pages"].add(page)
    # pages set → 정렬된 리스트로 변환
    for item in seen.values():
        item["pages"] = sorted(item["pages"])
    return list(seen.values())


def _render_sources(sources: list[dict]) -> None:
    """참조 문서를 카드형 레이아웃으로 렌더링한다."""
    deduped = _deduplicate_sources(sources)
    for i, src in enumerate(deduped):
        name = src.get("source", "unknown")
        file_type = name.rsplit(".", 1)[-1].upper() if "." in name else "FILE"
        pages = src.get("pages", [])
        institution = src.get("metadata", {}).get("institution", "")
        project = src.get("metadata", {}).get("project_name", "")

        # 파일타입별 아이콘
        icon = "📝" if file_type == "HWP" else "📄"

        # 페이지 정보: HWP는 "구간", PDF는 "p."
        if pages:
            if file_type == "HWP":
                page_info = "구간 " + ", ".join(str(p) for p in pages)
            else:
                page_info = "p." + ", ".join(str(p) for p in pages)
        else:
            page_info = ""

        with st.container(border=True):
            st.markdown(f"{icon} **{name}**")
            details = []
            if institution:
                details.append(f"기관: {institution}")
            if project:
                details.append(f"사업: {project}")
            if page_info:
                details.append(page_info)
            if details:
                st.caption(" | ".join(details))


def _render_latencies(latencies: dict) -> None:
    """소요 시간을 렌더링한다."""
    for step, elapsed in latencies.items():
        st.caption(f"{step}: {elapsed:.2f}s")


# --- 사이드바 ---
with st.sidebar:
    st.title("BiddingMate")
    st.caption("B2G 입찰 RFP 분석 시스템")
    st.divider()

    st.subheader("검색 설정")
    retriever_type = st.selectbox(
        "검색 타입",
        ["mmr", "similarity"],
        index=0,
        help="MMR: 관련성+다양성 균형, similarity: 순수 유사도 검색",
    )
    top_k = st.slider("Top-K", min_value=1, max_value=20, value=8)

    st.subheader("LLM 설정")
    llm_model = st.selectbox(
        "모델",
        ["gpt-5-mini", "gpt-5", "gpt-5-nano"],
        index=0,
    )
    temperature = st.slider("Temperature", 0.0, 1.0, 0.0, 0.1)

    st.subheader("메타데이터 필터")

    # 기관명: DB에서 가져온 리스트 + 직접 입력 지원
    if "institution_list" not in st.session_state:
        st.session_state.institution_list = get_unique_institutions()

    institutions = st.session_state.institution_list
    institution_options = ["(전체)"] + institutions

    selected_institution = st.selectbox(
        "기관명 선택",
        institution_options,
        index=0,
        help="DB에 저장된 기관 목록에서 선택하거나, 아래에 직접 입력하세요.",
    )
    custom_institution = st.text_input(
        "기관명 직접 입력",
        placeholder="예: 국민연금공단",
        help="선택 목록에 없는 기관은 직접 입력하세요.",
    )

    # 직접 입력 우선, 없으면 선택값 사용
    if custom_institution:
        filter_institution = custom_institution
    elif selected_institution != "(전체)":
        filter_institution = selected_institution
    else:
        filter_institution = ""

    filter_project = st.text_input("사업명", placeholder="예: 이러닝시스템")
    filter_year = st.text_input("연도", placeholder="예: 2024")

    st.divider()
    if st.button("대화 초기화", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# --- 세션 상태 초기화 ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- 메인 영역 ---
st.title("RFP 문서 질의응답")

# 기존 대화 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander("참조 문서"):
                _render_sources(msg["sources"])
        if msg.get("latencies"):
            with st.expander("소요 시간"):
                _render_latencies(msg["latencies"])

# --- 사용자 입력 ---
if user_input := st.chat_input("RFP 문서에 대해 질문하세요..."):
    # 사용자 메시지 추가
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 메타데이터 필터 구성
    metadata_filter = {}
    if filter_institution:
        metadata_filter["institution"] = filter_institution
    if filter_project:
        metadata_filter["project_name"] = filter_project
    if filter_year:
        metadata_filter["year"] = filter_year

    # 그래프 실행
    with st.chat_message("assistant"):
        with st.spinner("분석 중..."):
            graph = build_graph()
            result = graph.invoke({
                "query": user_input,
                "messages": [HumanMessage(content=user_input)],
                "metadata_filter": metadata_filter if metadata_filter else {},
                "llm_model": llm_model,
                "llm_temperature": temperature,
                "retriever_top_k": top_k,
                "retriever_search_type": retriever_type,
            })

        answer = result.get("answer", "답변을 생성하지 못했습니다.")
        st.markdown(answer)

        # 소스 표시 (중복 제거됨)
        sources = result.get("retrieved_docs", [])
        if sources:
            with st.expander("참조 문서"):
                _render_sources(sources)

        # 레이턴시 표시
        latencies = result.get("latencies", {})
        if latencies:
            total = sum(latencies.values())
            with st.expander(f"소요 시간 (총 {total:.2f}s)"):
                _render_latencies(latencies)

    # 어시스턴트 메시지 저장
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "sources": sources,
        "latencies": latencies,
    })
