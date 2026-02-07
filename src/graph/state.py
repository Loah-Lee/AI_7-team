"""LangGraph State 정의.

RFP RAG 파이프라인의 상태를 관리하는 TypedDict.
각 노드는 partial state만 반환할 수 있도록 total=False로 설정.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class RetrievedDoc(TypedDict):
    """검색된 문서 청크."""

    content: str
    source: str
    page: int | None
    score: float
    metadata: dict


class MetadataFilter(TypedDict, total=False):
    """메타데이터 필터링 조건."""

    institution: str       # 발주 기관명
    project_name: str      # 사업명
    year: str              # 연도
    keywords: list[str]    # 키워드


def merge_dicts(left: dict, right: dict) -> dict:
    """두 딕셔너리를 병합한다. 노드별 레이턴시 누적에 사용."""
    merged = left.copy()
    merged.update(right)
    return merged


class RFPState(TypedDict, total=False):
    """RFP RAG 파이프라인 상태.

    Attributes:
        messages: 대화 히스토리 (add_messages로 자동 누적)
        query: 사용자 원본 질의
        query_type: 질의 유형 (single_doc, multi_doc, comparison, out_of_scope)
        metadata_filter: 메타데이터 필터 조건
        retrieved_docs: 검색된 문서 목록 (operator.add로 누적)
        evidence: 추출된 근거 텍스트
        answer: 최종 생성 답변
        is_out_of_scope: 범위 밖 질문 여부
        latencies: 노드별 레이턴시 (merge_dicts로 누적)
    """

    messages: Annotated[list[BaseMessage], add_messages]
    query: str
    query_type: str
    metadata_filter: MetadataFilter
    retrieved_docs: Annotated[list[RetrievedDoc], operator.add]
    evidence: str
    answer: str
    is_out_of_scope: bool
    latencies: Annotated[dict, merge_dicts]
