#!/usr/bin/env python3
"""입찰메이트 v17 - 그래프 노드."""

from __future__ import annotations

import sys
import json
import re
from pathlib import Path
from typing import Any

# OpenAI
from openai import OpenAI

# 설정
sys.path.insert(0, 'src')
from src.utils.config import REASONING_MODEL
from src.prompts.templates import INTENT_ANALYSIS_PROMPT, ANSWER_GENERATION_PROMPT, RFP_SYSTEM_PROMPT
from src.graph.state import QueryIntent


# ============================================================================
# 질문 의도 파싱 노드 (Query Intent Parsing)
# ============================================================================

class QueryIntentParser:
    """LLM을 사용하여 질문 의도를 파악하는 파서."""

    def __init__(self, client: OpenAI | None):
        self.client = client

    def parse(self, query: str) -> QueryIntent:
        """질문을 분석하여 의도를 파악합니다."""
        if not self.client:
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

            response = self.client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": "당신은 JSON만 반환하는 분석 전문가입니다. JSON 외의 텍스트는 절대 출력하지 마세요."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

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

        if any(kw in query.lower() for kw in RANKING_KEYWORDS):
            intent.query_type = "ranking"
            if any(kw in query.lower() for kw in MAX_RANKING_KEYWORDS):
                intent.rank_order = "desc"
            elif any(kw in query.lower() for kw in MIN_RANKING_KEYWORDS):
                intent.rank_order = "asc"
            return intent

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

        category_keywords = {
            "IT": ["it", "정보시스템", "시스템"],
            "교육": ["교육", "대학", "학사"],
        }
        for cat, keywords in category_keywords.items():
            if any(kw in query.lower() for kw in keywords):
                intent.query_type = "category"
                intent.categories.append(cat)
                return intent

        return intent


# ============================================================================
# 답변 생성기 (Answer Generator)
# ============================================================================

class RFPAnswerGenerator:
    """간결한 RFP 답변을 생성하는 클래스."""

    def __init__(self, client: OpenAI | None) -> None:
        self.client = client

    def generate(self, query: str, context: str) -> str:
        """간결한 RFP 답변을 생성합니다."""
        if not self.client:
            return "LLM 클라이언트가 없습니다."

        prompt = ANSWER_GENERATION_PROMPT.format(query=query, context=context)

        try:
            response = self.client.chat.completions.create(
                model=REASONING_MODEL,
                messages=[
                    {"role": "system", "content": RFP_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=2000   # 더 긴 답변 허용
            )
            answer = response.choices[0].message.content
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
