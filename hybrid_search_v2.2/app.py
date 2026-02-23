"""Streamlit 채팅 UI (v2.2)

RAG 그래프에 쿼리를 전달하고, final_answer만 채팅 형식으로 표시한다.
실행마다 query, context, final_answer를 메모리에 누적한다 (최대 5건).

실행:
    cd hybrid_search_v2.2
    conda run -n langc streamlit run app.py
"""

import streamlit as st

from langfuse import get_client
 
langfuse = get_client()
 
# Verify connection
if langfuse.auth_check():
    print("Langfuse client is authenticated and ready!")
else:
    print("Authentication failed. Please check your credentials and host.")

from langfuse.langchain import CallbackHandler


langfuse_handler = CallbackHandler()

from search_graph import app as rag_app

# ============================================================
# 페이지 설정
# ============================================================

st.set_page_config(
    page_title="RFP RAG 검색",
    page_icon="🔍",
    layout="centered",
)

st.title("RFP 문서 검색")
st.caption("RFP 문서 및 CSV 데이터를 기반으로 질문에 답변합니다.")

# ============================================================
# 세션 상태 초기화
# ============================================================

if "messages" not in st.session_state:
    st.session_state.messages = []
if "memory" not in st.session_state:
    st.session_state.memory = []
if "log_counter" not in st.session_state:
    st.session_state.log_counter = 0

# ============================================================
# 기존 대화 히스토리 렌더링
# ============================================================

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ============================================================
# 사용자 입력 처리
# ============================================================

if query := st.chat_input("질문을 입력하세요"):
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        with st.spinner("검색 중..."):
            context = []
            result = {}
            try:
                result = rag_app.invoke({
                    "query": query,
                    "original_query": "",
                    "memory": st.session_state.memory,
                    "context": [],
                    "iteration": 0,
                    "use_csv": False,
                    "csv_query": None,
                }, config={"callbacks": [langfuse_handler]})
                answer = result.get("final_answer", "답변을 생성할 수 없습니다.")
                context = result.get("context", [])
            except Exception as e:
                answer = f"오류가 발생했습니다: {e}"

        st.markdown(answer.replace("\n", "  \n"))

    st.session_state.messages.append({"role": "assistant", "content": answer})

    st.session_state.log_counter += 1
    st.session_state.memory.append({
        "log_id": st.session_state.log_counter,
        "query": query,
        "context": context,
        "final_answer": answer,
    })
    st.session_state.memory = st.session_state.memory[-5:]

    original_q = result.get("original_query", "") if context else ""
    rewritten_q = result.get("query", "") if context else ""
    if original_q and original_q != rewritten_q:
        st.caption(f"(쿼리 교정: {original_q} → {rewritten_q})")
