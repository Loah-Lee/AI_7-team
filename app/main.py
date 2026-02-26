#!/usr/bin/env python3
"""입찰메이트 RFP UI - Streamlit App"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from components import (
    FAQ_QUESTIONS,
    build_checklist_csv_bytes,
    build_dummy_pdf_bytes,
    infer_summary_cards,
    inject_styles,
    real_bids_dataframe,
    render_answer_sections,
    render_summary_cards,
)
from storage import (
    add_item,
    add_project,
    delete_project,
    items_by_project,
    list_projects,
    load_store,
)


_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))


def _load_runtime_env() -> None:
    project_root = Path(_PROJECT_ROOT).resolve()
    parent_root = project_root.parent
    load_dotenv(project_root / ".env", override=False)
    load_dotenv(parent_root / ".env", override=False)
    load_dotenv(override=False)


_load_runtime_env()

from src.utils.config import (
    LANGSMITH_API_KEY,
    LANGSMITH_ENDPOINT,
    LANGSMITH_PROJECT,
    LANGSMITH_TRACING,
    get_data_dir,
    get_default_db_path,
)

if LANGSMITH_TRACING and LANGSMITH_API_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY
    os.environ["LANGCHAIN_ENDPOINT"] = LANGSMITH_ENDPOINT
    os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT


st.set_page_config(
    page_title="입찰메이트 RFP 업무도구",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_chatbot():
    from src.graph.workflow import RAGChatbotV17

    data_dir = str(get_data_dir())
    db_path = str(Path(get_default_db_path()).resolve())
    return RAGChatbotV17(data_dir=data_dir, db_path=db_path)


def init_session_state() -> None:
    st.session_state.setdefault("uploaded_docs", [])
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("last_query", "")
    st.session_state.setdefault("analysis_cards", None)


def run_query(chatbot: Any, query: str) -> dict[str, Any] | None:
    if not query.strip():
        return None

    with st.spinner("AI가 문서를 분석하고 있습니다..."):
        try:
            result = chatbot.answer(query.strip(), top_k=16)
        except Exception as exc:
            st.error(f"질의 처리 중 오류가 발생했습니다: {exc}")
            return None

    st.session_state.last_result = result
    st.session_state.last_query = query.strip()
    return result


def _upsert_uploaded_docs(new_files: list[Any]) -> None:
    existing_names = {d["name"] for d in st.session_state.uploaded_docs}
    for f in new_files:
        if f.name in existing_names:
            continue
        doc_type = Path(f.name).suffix.lower().replace(".", "").upper() or "N/A"
        st.session_state.uploaded_docs.append(
            {
                "name": f.name,
                "type": doc_type,
                "size_kb": round((f.size or 0) / 1024, 1),
                "status": "업로드 완료(UI)",
                "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )


def _step_label(num: int, text: str) -> None:
    st.markdown(
        f'<div class="step-label"><span class="step-num">{num}</span>{text}</div>',
        unsafe_allow_html=True,
    )


def _get_index_stats(vector_store: Any) -> tuple[int, int]:
    """ChromaDB에서 실제 인덱스 통계(등록 기관 수, 전체 청크 수)를 조회합니다.

    org_registry는 런타임 중 문서 처리 시에만 채워지므로, 앱 재시작 후에는
    비어 있을 수 있습니다. 이 경우 ChromaDB 메타데이터에서 직접 조회합니다.
    """
    total_chunks: int = getattr(vector_store, "count", 0)

    registry: dict = getattr(vector_store, "org_registry", {})
    if registry:
        return len(registry), total_chunks

    if total_chunks > 0:
        try:
            result = vector_store.collection.get(include=["metadatas"])
            metas: list[dict] = result.get("metadatas") or []
            orgs = {
                m.get("org", "").strip()
                for m in metas
                if isinstance(m, dict) and m.get("org", "").strip()
            }
            if orgs:
                return len(orgs), total_chunks
            sources = {
                m.get("source", "").strip()
                for m in metas
                if isinstance(m, dict) and m.get("source", "").strip()
            }
            return len(sources), total_chunks
        except Exception:
            pass

    return 0, total_chunks


def render_sidebar(chatbot: Any) -> None:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
                <div class="sidebar-brand-icon">📑</div>
                <div class="sidebar-brand-name">입찰메이트</div>
                <div class="sidebar-brand-sub">AI RFP 업무 도구 v1.0</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="sidebar-section">📊 문서 인덱스 현황</div>', unsafe_allow_html=True)
        try:
            total_orgs, total_chunks = _get_index_stats(chatbot.vector_store)
            st.markdown(
                f"""<div class="sidebar-stat-grid">
                    <div class="sidebar-stat-card">
                        <div class="sidebar-stat-value">{total_orgs:,}</div>
                        <div class="sidebar-stat-label">등록 기관</div>
                    </div>
                    <div class="sidebar-stat-card">
                        <div class="sidebar-stat-value">{total_chunks:,}</div>
                        <div class="sidebar-stat-label">전체 청크</div>
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )
        except Exception:
            st.caption("벡터스토어 정보를 불러오지 못했습니다.")

        st.markdown('<div class="sidebar-section">📖 사용 안내</div>', unsafe_allow_html=True)
        st.markdown(
            """
            **RFP 분석**
            문서를 업로드하고 AI에게 자유롭게 질의

            **입찰 현황**
            공고 필터링, 마감 임박 확인 및 저장

            **내 프로젝트**
            분석 결과와 공고를 프로젝트별로 관리
            """
        )

        st.divider()
        st.caption("© 2026 입찰메이트 · AI RFP 분석 도구")


def render_header() -> None:
    st.markdown(
        """
        <div class="app-header">
            <div class="app-header-title">📑 입찰메이트 RFP 업무 도구</div>
            <div class="app-header-sub">AI 기반 RFP 문서 분석 · 입찰 현황 추적 · 프로젝트 관리</div>
            <span class="app-header-badge">Beta v1.0</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def tab_rfp_analysis(chatbot: Any, store: dict[str, Any]) -> None:
    # ── Step 1: 문서 업로드 ──────────────────────────────────────────────
    with st.container(border=True):
        _step_label(1, "문서 업로드 (PDF / HWP)")
        files = st.file_uploader(
            "RFP 문서를 업로드하세요",
            type=["pdf", "hwp", "hwpx"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if files:
            _upsert_uploaded_docs(files)

        if st.session_state.uploaded_docs:
            st.dataframe(
                pd.DataFrame(st.session_state.uploaded_docs),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.markdown(
                """<div class="empty-state">
                    <div class="empty-state-icon">📂</div>
                    <div class="empty-state-text">업로드된 문서가 없습니다</div>
                    <div class="empty-state-sub">PDF 또는 HWP 파일을 드래그하거나 선택하세요</div>
                </div>""",
                unsafe_allow_html=True,
            )

    # ── Step 2: 핵심 요약 카드 ───────────────────────────────────────────
    with st.container(border=True):
        col_title, col_btn = st.columns([5, 1])
        with col_title:
            _step_label(2, "자동 핵심 요약 카드")
        with col_btn:
            if st.button("새로고침", use_container_width=True):
                st.session_state.analysis_cards = infer_summary_cards(chatbot)

        cards = st.session_state.analysis_cards or infer_summary_cards(chatbot)
        render_summary_cards(cards)

    # ── Step 3: 자유 질의 ────────────────────────────────────────────────
    with st.container(border=True):
        _step_label(3, "자유 질의")
        query = st.text_input(
            "질의 입력",
            placeholder="예: 제출서류와 평가항목을 정리해줘",
            key="rfp_query",
            label_visibility="collapsed",
        )

        st.caption("자주 묻는 질문")
        faq_cols = st.columns(3)
        selected_faq = None
        for idx, q in enumerate(FAQ_QUESTIONS):
            with faq_cols[idx % 3]:
                if st.button(q, key=f"faq_{idx}", use_container_width=True):
                    selected_faq = q

        st.write("")
        run_query_text = selected_faq or (
            query if st.button("질의 실행", type="primary", use_container_width=True) else ""
        )
        if run_query_text:
            run_query(chatbot, run_query_text)

    # ── Step 4: 답변 결과 ────────────────────────────────────────────────
    with st.container(border=True):
        _step_label(4, "답변 결과")
        last_result = st.session_state.last_result
        if last_result:
            if st.session_state.last_query:
                st.info(f"질의: {st.session_state.last_query}", icon="💬")
            render_answer_sections(last_result)

            st.write("")
            summary_for_export = str(last_result.get("answer", ""))[:1000]
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    "⬇️ 요약 PDF 다운로드",
                    data=build_dummy_pdf_bytes(summary_for_export),
                    file_name="rfp_summary_dummy.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )
            with col2:
                st.download_button(
                    "⬇️ 체크리스트 CSV",
                    data=build_checklist_csv_bytes(),
                    file_name="rfp_checklist.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

            st.divider()
            projects = list_projects(store)
            if projects:
                project_label_map = {p["name"]: p["id"] for p in projects}
                target_name = st.selectbox(
                    "프로젝트에 저장",
                    options=list(project_label_map.keys()),
                    key="save_result_project",
                )
                if st.button("분석 결과 저장", type="primary", use_container_width=True):
                    add_item(
                        store,
                        {
                            "project_id": project_label_map[target_name],
                            "type": "qa_result",
                            "title": st.session_state.last_query or "RFP 질의 결과",
                            "payload": last_result,
                        },
                    )
                    st.success("프로젝트에 저장했습니다.")
            else:
                st.info("저장하려면 먼저 '내 프로젝트' 탭에서 폴더를 생성하세요.", icon="💡")
        else:
            st.markdown(
                """<div class="empty-state">
                    <div class="empty-state-icon">🤖</div>
                    <div class="empty-state-text">질의를 실행하면 여기에 결과가 표시됩니다</div>
                    <div class="empty-state-sub">요약 · 핵심 포인트 · 근거 문장을 확인할 수 있습니다</div>
                </div>""",
                unsafe_allow_html=True,
            )


def _urgency_label(days: int) -> str:
    if days <= 3:
        return "🔴 긴급"
    if days <= 7:
        return "🟡 임박"
    return "🟢 여유"


def tab_bid_status(chatbot: Any, store: dict[str, Any]) -> None:
    df = real_bids_dataframe(chatbot)

    today = date.today()
    df["D_day"] = df["마감일"].apply(
        lambda d: (d - today).days if d is not None else None
    )

    # ── 상단 지표 ─────────────────────────────────────────────────────────
    has_dday = df["D_day"].notna().any()
    urgent_count = int((df["D_day"].notna() & (df["D_day"] <= 7)).sum()) if has_dday else 0
    col_a, col_b = st.columns(2)
    with col_a:
        st.metric("총 공고", f"{len(df)}건")
    with col_b:
        st.metric("마감 임박 (7일 이내)", f"{urgent_count}건")

    st.write("")

    # ── 필터 ─────────────────────────────────────────────────────────────
    has_budget = df["예산"].notna().any()
    with st.container(border=True):
        st.markdown("**🔍 필터 & 정렬**")

        if has_budget:
            budget_vals = df["예산"].dropna()
            b_min, b_max = int(budget_vals.min()), int(budget_vals.max())
            if b_min < b_max:
                budget_range: tuple[int, int] = st.slider(
                    "예산 범위",
                    b_min, b_max,
                    (b_min, b_max),
                    step=10_000_000,
                    format="%d원",
                )
            else:
                budget_range = (b_min, b_max)
                st.caption(f"예산 정보: {b_min:,}원")
        else:
            budget_range = st.slider(
                "예산 범위",
                0, 5_000_000_000,
                (0, 5_000_000_000),
                step=100_000_000,
                format="%d원",
            )
            st.caption("📌 인덱싱된 예산 데이터가 없습니다. 문서 인덱싱 후 자동 갱신됩니다.")

        sort_options = ["마감일순", "기관명순", "사업명순", "예산순"]

        col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
        with col_f1:
            keyword = st.text_input("키워드", placeholder="사업명 또는 기관 검색")
        with col_f2:
            sort_by = st.selectbox("정렬 기준", options=sort_options)
        with col_f3:
            st.write("")
            urgent_only = st.checkbox("임박만", value=False) if has_dday else False

    # ── 필터링 ───────────────────────────────────────────────────────────
    filtered = df.copy()

    if has_budget and budget_range is not None:
        filtered = filtered[
            filtered["예산"].isna()
            | ((filtered["예산"] >= budget_range[0]) & (filtered["예산"] <= budget_range[1]))
        ]

    if urgent_only:
        filtered = filtered[filtered["D_day"].notna() & (filtered["D_day"] <= 7)]

    if keyword.strip():
        k = keyword.strip().lower()
        filtered = filtered[
            filtered["사업명"].str.lower().str.contains(k)
            | filtered["기관"].str.lower().str.contains(k)
        ]

    if sort_by == "마감일순":
        filtered = filtered.sort_values("D_day", ascending=True, na_position="last")
    elif sort_by == "예산순":
        filtered = filtered.sort_values("예산", ascending=False, na_position="last")
    elif sort_by == "기관명순":
        filtered = filtered.sort_values("기관", ascending=True)
    else:
        filtered = filtered.sort_values("사업명", ascending=True)

    # ── 표시 ─────────────────────────────────────────────────────────────
    if filtered.empty:
        st.markdown(
            """<div class="empty-state">
                <div class="empty-state-icon">🔍</div>
                <div class="empty-state-text">조건에 맞는 공고가 없습니다</div>
                <div class="empty-state-sub">필터 조건을 조정해보세요</div>
            </div>""",
            unsafe_allow_html=True,
        )
    else:
        display_df = filtered.copy()
        display_df["긴급도"] = display_df["D_day"].apply(
            lambda d: _urgency_label(int(d)) if pd.notna(d) else "⚪ 미확인"
        )
        display_df["D-day"] = display_df["D_day"].apply(
            lambda d: f"D-{int(d)}" if pd.notna(d) else "-"
        )
        display_df["예산"] = display_df["예산"].apply(
            lambda x: f"{int(x):,}원" if pd.notna(x) else "미확인"
        )
        display_df["마감일"] = display_df["마감일"].apply(
            lambda d: str(d) if d is not None else "미확인"
        )
        st.dataframe(
            display_df[["긴급도", "D-day", "공고번호", "사업명", "기관", "예산", "마감일"]],
            use_container_width=True,
            hide_index=True,
        )

    # ── 저장 ─────────────────────────────────────────────────────────────
    with st.container(border=True):
        projects = list_projects(store)
        if not projects:
            st.info("저장하려면 먼저 '내 프로젝트' 탭에서 폴더를 생성하세요.", icon="💡")
            return
        if filtered.empty:
            st.caption("저장 가능한 항목이 없습니다.")
            return

        st.markdown("**📁 선택 공고 저장**")
        project_label_map = {p["name"]: p["id"] for p in projects}
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            selected_project = st.selectbox(
                "프로젝트", options=list(project_label_map.keys()), key="bid_save_project"
            )
        with col_s2:
            selected_bid = st.selectbox("공고 선택", options=filtered["공고번호"].tolist())

        if st.button("선택 공고 저장", type="primary", use_container_width=True):
            row = filtered[filtered["공고번호"] == selected_bid].iloc[0].to_dict()
            row["마감일"] = str(row["마감일"]) if row.get("마감일") else "미확인"
            row.pop("D_day", None)
            add_item(
                store,
                {
                    "project_id": project_label_map[selected_project],
                    "type": "bid_item",
                    "title": f"{row['공고번호']} | {row['사업명']}",
                    "payload": row,
                },
            )
            st.success("내 프로젝트에 저장했습니다.")


def tab_projects(store: dict[str, Any]) -> None:
    projects = list_projects(store)

    # ── 프로젝트 생성/삭제 ────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**📁 프로젝트 관리**")
        col1, col2 = st.columns([3, 1])
        with col1:
            new_project_name = st.text_input(
                "새 프로젝트명", placeholder="예: 2026 지자체 통합입찰", label_visibility="collapsed"
            )
        with col2:
            if st.button("+ 생성", type="primary", use_container_width=True):
                if new_project_name.strip():
                    add_project(store, new_project_name)
                    st.rerun()
                else:
                    st.warning("프로젝트명을 입력하세요.")

        if projects:
            st.divider()
            label_map = {f"{p['name']}  ({p['created_at'][:10]})": p["id"] for p in projects}
            col_d1, col_d2 = st.columns([3, 1])
            with col_d1:
                delete_target = st.selectbox(
                    "삭제할 프로젝트", options=list(label_map.keys()), label_visibility="collapsed"
                )
            with col_d2:
                if st.button("삭제", type="secondary", use_container_width=True):
                    delete_project(store, label_map[delete_target])
                    st.rerun()
        else:
            st.markdown(
                """<div class="empty-state">
                    <div class="empty-state-icon">📂</div>
                    <div class="empty-state-text">생성된 프로젝트가 없습니다</div>
                    <div class="empty-state-sub">위에서 프로젝트명을 입력해 시작하세요</div>
                </div>""",
                unsafe_allow_html=True,
            )
            return

    # ── 항목 목록 ─────────────────────────────────────────────────────────
    projects = list_projects(load_store())
    if not projects:
        return

    with st.container(border=True):
        st.markdown("**🗂 저장된 항목 조회**")
        project_name_map = {p["name"]: p["id"] for p in projects}
        selected_name = st.selectbox(
            "프로젝트 선택", options=list(project_name_map.keys()), label_visibility="collapsed"
        )
        selected_id = project_name_map[selected_name]

        rows = items_by_project(load_store(), selected_id)
        if not rows:
            st.markdown(
                """<div class="empty-state">
                    <div class="empty-state-icon">📋</div>
                    <div class="empty-state-text">저장된 항목이 없습니다</div>
                    <div class="empty-state-sub">RFP 분석 결과 또는 입찰 공고를 저장해보세요</div>
                </div>""",
                unsafe_allow_html=True,
            )
            return

        summary_rows = [
            {
                "저장 시각": r.get("saved_at", ""),
                "유형": r.get("type", ""),
                "제목": r.get("title", ""),
            }
            for r in rows
        ]
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    # ── 상세 보기 ─────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**🔎 상세 보기**")
        item_options = {f"{r.get('saved_at', '')[:16]}  |  {r.get('title', '')}": r for r in rows}
        selected_item_label = st.selectbox(
            "항목 선택", options=list(item_options.keys()), label_visibility="collapsed"
        )
        selected_item = item_options[selected_item_label]

        st.json(selected_item.get("payload", {}))

        st.write("")
        payload = selected_item.get("payload", {})
        summary_text = str(payload.get("answer", selected_item.get("title", "")))
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "⬇️ 요약 PDF",
                data=build_dummy_pdf_bytes(summary_text),
                file_name="project_item_summary_dummy.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
        with col2:
            st.download_button(
                "⬇️ 체크리스트 CSV",
                data=build_checklist_csv_bytes(),
                file_name="project_item_checklist.csv",
                mime="text/csv",
                use_container_width=True,
            )


def main() -> None:
    inject_styles()
    init_session_state()

    chatbot = get_chatbot()
    if not chatbot:
        st.error("챗봇을 로드하지 못했습니다.")
        return

    store = load_store()

    render_sidebar(chatbot)
    render_header()

    tabs = st.tabs(["🔍 RFP 분석", "📋 입찰 현황", "📁 내 프로젝트"])

    with tabs[0]:
        tab_rfp_analysis(chatbot, store)
    with tabs[1]:
        tab_bid_status(chatbot, store)
    with tabs[2]:
        tab_projects(store)


if __name__ == "__main__":
    main()
