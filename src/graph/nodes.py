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
from src.utils.config import DEFAULT_MODEL, INTENT_REGEX_FIRST, REASONING_MODEL, OPENAI_API_KEY
from src.prompts.templates import INTENT_ANALYSIS_PROMPT, ANSWER_GENERATION_PROMPT, RFP_SYSTEM_PROMPT
from src.graph.state import QueryIntent, QuestionPlan


# ============================================================================
# 질문 의도 파싱 노드 (Query Intent Parsing)
# ============================================================================

class QueryIntentParser:
    """LLM을 사용하여 질문 의도를 파악하는 파서."""

    def __init__(self, llm: ChatOpenAI | None):
        self.llm = llm
        self.last_parse_used_llm = False

    def parse(self, query: str) -> QueryIntent:
        """질문을 분석하여 의도를 파악합니다."""
        self.last_parse_used_llm = False
        if not self.llm:
            return self._parse_with_regex(query)

        if INTENT_REGEX_FIRST:
            regex_intent = self._parse_with_regex(query)
            if regex_intent.confidence >= 0.75:
                return regex_intent

            llm_intent = self._parse_with_llm(query)
            if llm_intent.confidence >= regex_intent.confidence:
                self.last_parse_used_llm = True
                return llm_intent
            return regex_intent

        llm_intent = self._parse_with_llm(query)
        self.last_parse_used_llm = True
        if llm_intent.confidence < 0.7:
            regex_intent = self._parse_with_regex(query)
            if regex_intent.confidence > llm_intent.confidence:
                return regex_intent
        return llm_intent

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
        normalized_query = query.lower().strip()

        # 0. 기관명 포함 여부 확인 (명시 기관이 있으면 우선 기관 질문으로 분류)
        org_name = self._extract_org_from_query(query)
        if org_name:
            intent.query_type = "org"
            intent.org_name = org_name
            intent.confidence = 0.82
            return intent

        # 1. 랭킹 질문 확인 ("가장 많은", "TOP5", "순위" 등)
        ranking_pattern = bool(re.search(r"(top\s*\d+|\d+\s*(?:위|곳|개))", normalized_query))
        strong_ranking_markers = ["top", "순위", "랭킹", "상위", "하위"]
        rank_context_markers = ["기관", "사업", "곳", "개", "순", "목록", "추천"]
        extreme_markers = ["가장", "최고", "최저", "많은", "적은", "높은", "낮은", "최대", "최소"]
        fact_blockers = [
            "사양", "cpu", "메모리", "용량", "치수", "규격", "가로", "세로",
            "기한", "마감", "언제", "얼마", "몇", "요구사항", "가이드",
        ]
        ranking_keyword_hit = (
            any(marker in normalized_query for marker in strong_ranking_markers)
            or (
                any(marker in normalized_query for marker in extreme_markers)
                and any(ctx in normalized_query for ctx in rank_context_markers)
            )
            or any(kw in normalized_query for kw in RANKING_KEYWORDS)
        )
        is_ranking_query = ranking_pattern or ranking_keyword_hit
        if is_ranking_query and not any(blocker in normalized_query for blocker in fact_blockers):
            intent.query_type = "ranking"
            intent.confidence = 0.95
            if any(kw in normalized_query for kw in MAX_RANKING_KEYWORDS):
                intent.rank_order = "desc"
            elif any(kw in normalized_query for kw in MIN_RANKING_KEYWORDS):
                intent.rank_order = "asc"
            return intent

        # 2. 필터 질문 (금액 범위)
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

        # 3. 카테고리 질문 (탐색형 표현이 있을 때만)
        broad_discovery_markers = ["관련 사업", "분야", "기관 찾아", "찾아줘", "추천", "목록", "어떤 것이", "보여줘"]
        is_discovery_query = any(marker in normalized_query for marker in broad_discovery_markers)
        category_keywords = {
            "IT": ["it", "정보시스템", "디지털", "ai", "데이터", "클라우드", "플랫폼"],
            "교육": ["교육", "대학", "학사"],
        }
        if is_discovery_query:
            for cat, keywords in category_keywords.items():
                if any(kw in normalized_query for kw in keywords):
                    intent.query_type = "category"
                    intent.confidence = 0.82
                    intent.categories.append(cat)
                    return intent

        # 4. 주어 생략형 후속 질문은 검색형으로 빠르게 처리 (LLM 파싱 우회)
        follow_up_markers = [
            "마감", "마감일", "사업명", "사업비", "예산", "금액", "기한",
            "기간", "일정", "언제", "얼마", "누가", "요건", "요구사항",
        ]
        if any(marker in normalized_query for marker in follow_up_markers):
            intent.query_type = "search"
            intent.confidence = 0.82
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
            r'([가-힣]+광역시)',
            r'([가-힣]+특별시)',
            r'([가-힣]+특별자치시)',
            r'([가-힣]+특별자치도)',
            r'([가-힣]+공사)',
            r'([가-힣]+연구원)',
            r'([가-힣]+재단)',
            r'([가-힣]+공단)',
            r'([가-힣]+위원회)',
            r'([가-힣]+협회)',
            r'([가-힣]+진흥원)',
            r'([가-힣]+기술원)',
            r'([가-힣]+서비스원)',
            r'([가-힣]+조직위원회)',
            r'([가-힣]+사무국)',
            r'([가-힣]+센터)',
        ]

        for pattern in org_patterns:
            match = re.search(pattern, query)
            if match:
                return match.group(1)

        return None


class QuestionPlanner:
    """질문 유형과 필수 슬롯을 결정하는 경량 플래너."""

    @staticmethod
    def build(query: str, target_org: str = "") -> QuestionPlan:
        q = (query or "").lower()
        normalized = re.sub(r"\s+", " ", q)

        is_comparison = any(k in normalized for k in ["비교", "차이", "공통", "모두 고려", "동시에", "두 문서"])
        if not is_comparison and "각각" in normalized:
            is_comparison = any(marker in normalized for marker in ["두 문서", "각 문서", "기관별", "a 문서", "b 문서"])
        if is_comparison:
            return QuestionPlan(
                query_kind="comparison",
                required_slots=["docA_claim", "docB_claim", "comparison_point"],
                is_comparison=True,
                target_org=target_org,
            )

        if any(k in normalized for k in ["누가", "부담", "책임", "소유권", "귀속"]):
            return QuestionPlan(
                query_kind="owner",
                required_slots=["owner", "evidence"],
                target_org=target_org,
            )

        if any(k in normalized for k in ["언제", "마감", "기한", "이내", "시간", "주기", "횟수"]):
            return QuestionPlan(
                query_kind="deadline",
                required_slots=["value", "unit", "evidence"],
                target_org=target_org,
            )

        if any(k in normalized for k in ["얼마", "수량", "단위", "용량", "몇", "비율", "퍼센트"]):
            return QuestionPlan(
                query_kind="fact_numeric",
                required_slots=["value", "unit", "evidence"],
                target_org=target_org,
            )

        # "과" 한 글자 포함만으로 multi_doc로 분류되면
        # "고려대학교" 같은 단일 기관 질의가 오분류된다.
        has_multi_connector = (
            "둘 다" in normalized
            or "복수" in normalized
            or bool(re.search(r"[가-힣a-z0-9]{2,}\s*(및|또는)\s*[가-힣a-z0-9]{2,}", normalized))
            or bool(re.search(r"[가-힣a-z0-9]{2,}(와|과)\s+[가-힣a-z0-9]{2,}", normalized))
        )
        if has_multi_connector:
            return QuestionPlan(
                query_kind="multi_doc",
                required_slots=["key_points", "evidence"],
                target_org=target_org,
            )

        return QuestionPlan(
            query_kind="single_doc",
            required_slots=["key_points", "evidence"],
            target_org=target_org,
        )


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
