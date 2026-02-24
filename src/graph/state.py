#!/usr/bin/env python3
"""입찰메이트 v17 - 상태 관리 및 데이터 클래스."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================================
# 데이터 클래스 (Data Classes)
# ============================================================================

@dataclass
class OrgInfo:
    """기관 정보를 저장하는 데이터 클래스."""
    name: str
    amount: str = ""
    amount_numeric: float = 0
    project_name: str = ""
    summary: str = ""
    open_date: str = ""
    file_format: str = ""
    has_pdf: bool = False
    has_hwp: bool = False


@dataclass
class MarkdownData:
    """마크다운 변환 결과를 저장하는 데이터 클래스."""
    markdown: str
    org_name: str
    project_name: str
    amount: str
    summary: str = ""
    filename: str = ""
    file_format: str = ""
    row_num: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryIntent:
    """사용자 질문의 의도를 저장하는 데이터 클래스."""
    query_type: str = "search"  # org, ranking, filter, category, search
    org_name: str = ""
    rank_order: str = ""  # asc, desc
    amount_min: int | None = None
    amount_max: int | None = None
    qualifications: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    raw_query: str = ""
    confidence: float = 0.0


@dataclass
class QuestionPlan:
    """질문 처리 계획(유형/필수 슬롯/비교 여부)."""
    query_kind: str = "single_doc"  # fact_numeric, deadline, owner, single_doc, multi_doc, comparison
    required_slots: list[str] = field(default_factory=list)
    is_comparison: bool = False
    target_org: str = ""


@dataclass
class EvidenceSpan:
    """답변 근거 span."""
    source: str
    page: int | None
    text: str
    slot: str = ""
    score: float = 0.0


@dataclass
class AnswerDraft:
    """최종 답변 초안 메타데이터."""
    final_answer: str = ""
    slot_fill_rate: float = 0.0
    confidence: float = 0.0
    evidence_refs: list[EvidenceSpan] = field(default_factory=list)
    answer_mode: str = "generative"  # extractive|hybrid|generative


# ============================================================================
# 대화 컨텍스트 (Conversation Context)
# ============================================================================

class ConversationContext:
    """대화 컨텍스트를 관리하는 클래스."""

    def __init__(self, max_history: int = 5) -> None:
        self.max_history = max_history
        self.history: list[dict[str, Any]] = []
        self.last_org: str | None = None
        self.last_query_type: str | None = None

    def add_exchange(self, query: str, answer: str, intent: QueryIntent | None = None) -> None:
        """대화 기록을 추가합니다."""
        self.history.append({
            "query": query,
            "answer": answer,
            "query_type": intent.query_type if intent else None,
            "org_name": intent.org_name if intent else None
        })

        if len(self.history) > self.max_history:
            self.history.pop(0)

        if intent:
            self.last_org = intent.org_name
            self.last_query_type = intent.query_type

    def get_context_summary(self) -> str:
        """대화 컨텍스트 요약을 반환합니다."""
        if not self.history:
            return ""

        summary_parts = []
        for exchange in self.history[-3:]:
            summary_parts.append(f"Q: {exchange['query']}")
            summary_parts.append(f"A: {exchange['answer'][:100]}...")

        return "\n".join(summary_parts)

    def get_follow_up_context(self, current_query: str) -> dict[str, Any]:
        """후속 질문을 위한 컨텍스트를 반환합니다."""
        context = {
            "has_previous": len(self.history) > 0,
            "last_org": self.last_org,
            "last_query_type": self.last_query_type,
            "is_follow_up": False
        }

        follow_up_keywords = [
            "그거", "그것", "그", "거기", "그곳",
            "언제", "얼마", "어디", "누구",
            "더", "또", "다른"
        ]

        if context["has_previous"]:
            query_lower = current_query.lower()
            if any(kw in query_lower for kw in follow_up_keywords):
                context["is_follow_up"] = True

        return context
