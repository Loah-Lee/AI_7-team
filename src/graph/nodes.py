#!/usr/bin/env python3
"""입찰메이트 v17 - 그래프 노드."""

from __future__ import annotations

import sys
import json
import re
import os
from pathlib import Path
from typing import Any

# LangChain (LangSmith 트레이싱)
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# 설정
sys.path.insert(0, 'src')
from src.utils.config import DEFAULT_MODEL, REASONING_MODEL, OPENAI_API_KEY
from src.prompts.templates import INTENT_ANALYSIS_PROMPT, ANSWER_GENERATION_PROMPT, RFP_SYSTEM_PROMPT
from src.graph.state import QueryIntent


# ============================================================================
# 질문 의도 파싱 노드 (Query Intent Parsing)
# ============================================================================

class QueryIntentParser:
    """LLM을 사용하여 질문 의도를 파악하는 파서."""

    def __init__(self, llm: ChatOpenAI | None):
        self.llm = llm

    def parse(self, query: str) -> QueryIntent:
        """질문을 분석하여 의도를 파악합니다."""
        if not self.llm:
            return self._parse_with_regex(query)

        intent = self._parse_with_llm(query)

        if intent.confidence < 0.7:
            regex_intent = self._parse_with_regex(query)
            if regex_intent.confidence > intent.confidence:
                intent = regex_intent

        return intent

    def _parse_with_llm(self, query: str) -> QueryIntent:
        """LLM로 질문을 분석합니다."""
        try:
            prompt = INTENT_ANALYSIS_PROMPT.format(query=query)

            messages = [
                SystemMessage(content="당신은 JSON만 반환하는 분석 전문가입니다. JSON 외의 텍스트는 절대 출력하지 마세요."),
                HumanMessage(content=prompt)
            ]

            response = self.llm.invoke(messages)
            result = json.loads(response.content)

            return QueryIntent(
                query_type=result.get("query_type", "search"),
                org_name=result.get("org_name") or "",
                rank_order=result.get("rank_order") or "",
                amount_min=result.get("amount_min"),
                amount_max=result.get("amount_max"),
                qualifications=result.get("qualifications") or [],
                categories=result.get("categories") or [],
                raw_query=query,
                confidence=result.get("confidence", 0.8)
            )

        except Exception:
            return self._parse_with_regex(query)

    def _parse_with_regex(self, query: str) -> QueryIntent:
        """정규식으로 질문을 분석합니다."""
        from src.utils.config import RANKING_KEYWORDS, MAX_RANKING_KEYWORDS, MIN_RANKING_KEYWORDS

        intent = QueryIntent(raw_query=query, confidence=0.6)

        # 1. 랭킹 질문 우선 확인 ("가장 많은", "TOP5", "랭킹" 등)
        if any(kw in query.lower() for kw in RANKING_KEYWORDS):
            intent.query_type = "ranking"
            if any(kw in query.lower() for kw in MAX_RANKING_KEYWORDS):
                intent.rank_order = "desc"
            elif any(kw in query.lower() for kw in MIN_RANKING_KEYWORDS):
                intent.rank_order = "asc"
            return intent

        # 2. 기관명 포함 여부 확인 (등록된 기관명과 매칭 시도)
        org_name = self._extract_org_from_query(query)
        if org_name:
            intent.query_type = "org"
            intent.org_name = org_name
            intent.confidence = 0.8
            return intent

        # 3. 필터 질문 (금액 범위)
        range_patterns = [
            r'(\d+\.?\d*)\s*(억|만)\s*(?:에서|부터|~)\s*(\d+\.?\d*)\s*(억|만)',
            r'(\d+\.?\d*)\s*~\s*(\d+\.?\d*)\s*(억|만)',
        ]
        for pattern in range_patterns:
            match = re.search(pattern, query)
            if match:
                intent.query_type = "filter"
                intent.confidence = 0.8
                return intent

        if any(kw in query for kw in ['이상', '이하', '초과', '미만', '사이']):
            intent.query_type = "filter"
            intent.confidence = 0.7
            return intent

        # 4. 카테고리 질문
        category_keywords = {
            "IT": ["it", "정보시스템", "시스템", "it 관련"],
            "교육": ["교육", "대학", "학사"],
        }
        for cat, keywords in category_keywords.items():
            if any(kw in query.lower() for kw in keywords):
                intent.query_type = "category"
                intent.categories.append(cat)
                return intent

        return intent

    def _extract_org_from_query(self, query: str) -> str | None:
        """질문에서 기관명을 추출합니다. (정규식 방식)

        참고: 이 메서드는 VectorStore 인스턴스가 없을 때 사용하는 간단 버전입니다.
        실제 기관명 매칭은 RAGChatbotV17._extract_org_name_from_query()를 사용하세요.
        """
        from src.utils.config import ORG_ALIASES

        normalized_query = query
        for alias, standard in ORG_ALIASES.items():
            if alias in query:
                return standard

        # 일반적인 기관명 패턴 (대학, 시, 공사 등)
        org_patterns = [
            r'([가-힣]+대학교)',
            r'([가-힣]+대학)',
            r'([가-힣]+시)',
            r'([가-힣]+광역시)',
            r'([가-힣]+도)',
            r'([가-힣]+공사)',
            r'([가-힣]+연구원)',
            r'([가-힣]+센터)',
        ]

        for pattern in org_patterns:
            match = re.search(pattern, query)
            if match:
                return match.group(1)

        return None


# ============================================================================
# 답변 생성기 (Answer Generator)
# ============================================================================

class RFPAnswerGenerator:
    """간결한 RFP 답변을 생성하는 클래스."""

    def __init__(self, llm: ChatOpenAI | None) -> None:
        self.llm = llm

    def generate(self, query: str, context: str, history: str = "") -> str:
        """간결한 RFP 답변을 생성합니다."""
        if not self.llm:
            return "LLM 클라이언트가 없습니다."

        # history가 있으면 프롬프트에 포함
        if history:
            prompt = ANSWER_GENERATION_PROMPT.format(query=query, context=context, history=f"## 이전 대화 기록\n{history}")
        else:
            # history 없으면 빈 문자열로 처리
            prompt = ANSWER_GENERATION_PROMPT.format(query=query, context=context, history="")

        try:
            messages = [
                SystemMessage(content=RFP_SYSTEM_PROMPT),
                HumanMessage(content=prompt)
            ]

            response = self.llm.invoke(messages)
            answer = response.content
            return self._clean_final_answer(answer)

        except Exception as e:
            return f"오류: {str(e)}"

    @staticmethod
    def _clean_final_answer(answer: str) -> str:
        """답변에서 "최종 답변:" 태그를 제거합니다."""
        for indicator in ["## 최종 답변:", "최종 답변:"]:
            if indicator in answer:
                return answer.split(indicator)[-1].strip()
        return answer


def _token_limit_arg(model: str, max_tokens: int) -> dict[str, int]:
    """모델별 토큰 파라미터 키를 반환합니다."""
    normalized = (model or "").lower()
    if normalized.startswith("gpt-5"):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


def _is_gpt5_model(model: str) -> bool:
    return (model or "").lower().startswith("gpt-5")
