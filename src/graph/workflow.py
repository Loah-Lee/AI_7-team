"""LangGraph 워크플로우 조립.

StateGraph를 구성하고 compile하여 실행 가능한 그래프를 반환한다.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.graph.nodes import analyze_query, extract_evidence, generate, retrieve
from src.graph.state import RFPState


def build_graph() -> StateGraph:
    """RFP RAG 파이프라인 그래프를 빌드하고 컴파일한다.

    흐름: analyze_query → retrieve → extract_evidence → generate → END

    Returns:
        컴파일된 StateGraph.
    """
    graph = StateGraph(RFPState)

    # 노드 등록
    graph.add_node("analyze_query", analyze_query)
    graph.add_node("retrieve", retrieve)
    graph.add_node("extract_evidence", extract_evidence)
    graph.add_node("generate", generate)

    # 엣지 연결 (선형 흐름)
    graph.set_entry_point("analyze_query")
    graph.add_edge("analyze_query", "retrieve")
    graph.add_edge("retrieve", "extract_evidence")
    graph.add_edge("extract_evidence", "generate")
    graph.add_edge("generate", END)

    return graph.compile()
