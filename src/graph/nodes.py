#!/usr/bin/env python3
"""입찰메이트 v17 - 그래프 노드."""

from __future__ import annotations

import sys
import json
import re
import os
import time
import unicodedata
from pathlib import Path
from typing import Any

# LangChain (LangSmith 트레이싱)
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# 설정
sys.path.insert(0, 'src')
from src.utils.config import DEFAULT_MODEL, INTENT_REGEX_FIRST, REASONING_MODEL, OPENAI_API_KEY
from src.prompts.templates import (
    INTENT_ANALYSIS_PROMPT,
    INTENT_ANALYSIS_PROMPT_COMPACT,
    ANSWER_GENERATION_PROMPT,
    ANSWER_GENERATION_FROM_EVIDENCE_PROMPT,
    EVIDENCE_REFINEMENT_PROMPT,
    RFP_SYSTEM_PROMPT,
)
from src.graph.state import QueryIntent, QuestionPlan


# ============================================================================
# 질문 의도 파싱 노드 (Query Intent Parsing)
# ============================================================================

class QueryIntentParser:
    """LLM을 사용하여 질문 의도를 파악하는 파서."""

    def __init__(self, llm: ChatOpenAI | None):
        self.llm = llm
        self.last_parse_used_llm = False
        self.last_parse_elapsed = 0.0
        self._intent_cache_exact: dict[str, QueryIntent] = {}
        self._intent_cache_signature: dict[str, QueryIntent] = {}
        self._cache_max_entries = 256

    @staticmethod
    def _normalize_query_for_cache(query: str) -> str:
        normalized = unicodedata.normalize("NFKC", (query or "").lower()).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    @classmethod
    def _build_query_signature(cls, query: str) -> str:
        normalized = cls._normalize_query_for_cache(query)
        if not normalized:
            return ""
        tokens = re.findall(r"[0-9a-zA-Z가-힣]{2,}", normalized)
        stopwords = {
            "알려줘", "알려주세요", "알려", "요약", "정리", "설명", "질문", "문서", "기준",
            "이거", "그거", "그것", "해주세요", "해줘", "좀", "관련", "정보",
        }
        filtered = [tok for tok in tokens if tok not in stopwords]
        selected = filtered if filtered else tokens
        if not selected:
            return ""
        # 유사 질의 캐시를 위해 토큰 순서 영향은 줄이고, 과도한 충돌은 방지한다.
        uniq = sorted(set(selected))
        return "|".join(uniq[:12])

    @staticmethod
    def _clone_intent(intent: QueryIntent, query: str) -> QueryIntent:
        return QueryIntent(
            query_type=intent.query_type,
            org_name=intent.org_name,
            rank_order=intent.rank_order,
            amount_min=intent.amount_min,
            amount_max=intent.amount_max,
            qualifications=list(intent.qualifications or []),
            categories=list(intent.categories or []),
            raw_query=query,
            confidence=float(intent.confidence or 0.0),
        )

    def _cache_get(self, query: str) -> QueryIntent | None:
        key = self._normalize_query_for_cache(query)
        if not key:
            return None
        cached = self._intent_cache_exact.get(key)
        if cached:
            return self._clone_intent(cached, query)

        sig = self._build_query_signature(query)
        if not sig:
            return None
        cached_sig = self._intent_cache_signature.get(sig)
        if cached_sig:
            return self._clone_intent(cached_sig, query)
        return None

    @staticmethod
    def _cache_trim(cache_map: dict[str, QueryIntent], max_entries: int) -> None:
        while len(cache_map) > max_entries:
            first_key = next(iter(cache_map))
            cache_map.pop(first_key, None)

    def _cache_put(self, query: str, intent: QueryIntent) -> None:
        if not query:
            return
        cached_intent = self._clone_intent(intent, query)
        key = self._normalize_query_for_cache(query)
        if key:
            self._intent_cache_exact[key] = cached_intent
            self._cache_trim(self._intent_cache_exact, self._cache_max_entries)

        sig = self._build_query_signature(query)
        if sig:
            self._intent_cache_signature[sig] = cached_intent
            self._cache_trim(self._intent_cache_signature, self._cache_max_entries)

    @staticmethod
    def _has_intent_conflict_markers(query: str) -> bool:
        normalized = unicodedata.normalize("NFKC", (query or "").lower()).strip()
        if not normalized:
            return False

        has_ranking = bool(re.search(r"(top\s*\d+|\d+\s*(위|곳|개)|순위|랭킹|상위|하위|가장)", normalized))
        has_filter = bool(re.search(r"(이상|이하|초과|미만|사이|부터|~|범위)", normalized))
        has_category = any(marker in normalized for marker in ["관련 사업", "분야", "추천", "목록", "기관 찾아"])
        has_org = bool(re.search(r"[가-힣]+(대학교|대학|공사|공단|재단|위원회|연구원|진흥원|협회|센터)", normalized))
        has_fact = any(marker in normalized for marker in ["얼마", "언제", "마감", "기한", "요구사항", "요건", "누가"])

        flag_count = sum([has_ranking, has_filter, has_category, has_org, has_fact])
        if flag_count <= 1:
            return False
        if has_org and has_fact and flag_count == 2:
            return False
        return True

    def _should_call_llm(self, query: str, regex_intent: QueryIntent) -> bool:
        if not self.llm:
            return False
        if self._has_intent_conflict_markers(query):
            return True

        confidence = float(regex_intent.confidence or 0.0)
        if confidence < 0.78:
            return True
        if regex_intent.query_type == "search" and confidence < 0.82:
            return True
        return False

    @staticmethod
    def _safe_load_intent_json(payload: str) -> dict[str, Any] | None:
        text = str(payload or "").strip()
        if not text:
            return None
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def parse(self, query: str) -> QueryIntent:
        """질문을 분석하여 의도를 파악합니다."""
        started = time.perf_counter()
        self.last_parse_used_llm = False
        try:
            cached = self._cache_get(query)
            if cached:
                return cached

            regex_intent = self._parse_with_regex(query)
            if not self._should_call_llm(query, regex_intent):
                self._cache_put(query, regex_intent)
                return regex_intent

            llm_intent = self._parse_with_llm(query, fallback=regex_intent)
            llm_conf = float(llm_intent.confidence or 0.0)
            regex_conf = float(regex_intent.confidence or 0.0)
            llm_margin = 0.03
            use_llm = llm_conf >= max(0.7, regex_conf + llm_margin)
            final_intent = llm_intent if use_llm else regex_intent
            self.last_parse_used_llm = use_llm
            self._cache_put(query, final_intent)
            return final_intent
        finally:
            self.last_parse_elapsed = time.perf_counter() - started

    def _parse_with_llm(self, query: str, fallback: QueryIntent | None = None) -> QueryIntent:
        """LLM로 질문을 분석합니다."""
        try:
            prompt = INTENT_ANALYSIS_PROMPT_COMPACT.format(query=query)

            messages = [
                SystemMessage(content="JSON 객체 하나만 출력하세요. 설명 문장과 코드블록은 금지입니다."),
                HumanMessage(content=prompt)
            ]

            response = self.llm.invoke(messages)
            result = self._safe_load_intent_json(getattr(response, "content", ""))
            if not result:
                return fallback or self._parse_with_regex(query)

            query_type = str(result.get("query_type", "search") or "search").strip().lower()
            if query_type not in {"org", "ranking", "filter", "category", "search"}:
                query_type = "search"
            confidence_raw = result.get("confidence", 0.75)
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.75
            confidence = max(0.0, min(1.0, confidence))

            return QueryIntent(
                query_type=query_type,
                org_name=str(result.get("org_name") or "").strip(),
                rank_order=str(result.get("rank_order") or "").strip(),
                amount_min=result.get("amount_min"),
                amount_max=result.get("amount_max"),
                qualifications=result.get("qualifications") or [],
                categories=result.get("categories") or [],
                raw_query=query,
                confidence=confidence,
            )

        except Exception:
            return fallback or self._parse_with_regex(query)

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
        # "비교과시스템"처럼 단어 내부의 "비교"는 비교 질의로 보지 않는다.
        has_compare_token = bool(re.search(r"비교(?!과)", normalized))

        is_comparison = has_compare_token or any(
            k in normalized for k in ["차이", "공통", "모두 고려", "동시에", "두 문서"]
        )
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
        self.last_generation_elapsed = 0.0
        self.last_generation_llm_calls = 0

    @staticmethod
    def _is_descriptive_query(query: str) -> bool:
        q = (query or "").strip().lower()
        descriptive_keywords = [
            "요약", "정리", "설명", "배경", "목적", "개선", "현황",
            "분석", "절차", "항목", "포함", "비교하여", "비교해서", "어떻게 적용",
        ]
        concise_keywords = ["얼마", "몇", "언제", "누가", "마감", "기한", "시간", "주기", "용량", "단위", "비율"]
        if any(k in q for k in descriptive_keywords):
            return True
        if any(k in q for k in concise_keywords):
            return False
        return False

    @classmethod
    def _resolve_answer_style(cls, query: str, answer_style_hint: str = "") -> str:
        hinted = str(answer_style_hint or "").strip().lower()
        if hinted in {"concise", "guide"}:
            return hinted
        if hinted == "descriptive":
            return "guide"
        return "guide" if cls._is_descriptive_query(query) else "concise"

    @classmethod
    def _answer_style_instruction(cls, query: str, answer_style_hint: str = "") -> str:
        if cls._resolve_answer_style(query, answer_style_hint) == "guide":
            return (
                "- 설명형 질문입니다. 약술형 장문 대신 가이드/에이전트형으로 답하세요.\n"
                "- 첫 줄은 결론 1문장으로 쓰고, 이어서 핵심 키워드가 보이도록 불릿 2~4개를 제시하세요.\n"
                "- 질문의 핵심 키워드(주체/조건/기준값)는 첫 문장에 그대로 반영하세요.\n"
                "- `결론:`/`요약:`/`근거:`/`출처:` 같은 라벨은 출력하지 마세요. 근거는 내부 검증에만 사용하세요.\n"
                "- 문맥에 없는 추가 문장/해석/권고는 생성하지 말고, 근거 문장 범위 안에서만 재서술하세요.\n"
                "- 질문의 필수 항목이 실제로 누락된 경우에만 `문서에서 확인되지 않습니다.`를 짧게 명시하세요."
            )
        return (
            "- 단답형 질문입니다. 핵심 답을 1~2문장으로 짧게 제시하세요.\n"
            "- 불필요한 배경 설명은 생략하고 값/조건/주체를 우선 제시하세요.\n"
            "- 질문의 핵심 키워드(주체/조건/기준값)는 첫 문장에 그대로 반영하세요.\n"
            "- 문맥에 없는 추가 문장/해석/권고는 생성하지 말고, 근거 문장 범위 안에서만 재서술하세요.\n"
            "- `결론:`/`요약:`/`근거:`/`출처:` 라벨은 출력하지 마세요. 필수 값이 실제로 없을 때만 `문서에서 확인되지 않습니다.`를 사용하세요."
        )

    @classmethod
    def _evidence_style_instruction(cls, query: str, answer_style_hint: str = "") -> str:
        if cls._resolve_answer_style(query, answer_style_hint) == "guide":
            return "- 가이드형 답변을 위해 근거를 최대 8개까지 보존해 핵심 키워드 누락을 줄이세요."
        return "- 단답형 질문이므로 근거는 핵심 3개 이내로 압축하세요."

    def generate(
        self,
        query: str,
        context: str,
        history: str = "",
        extractive_draft: str = "",
        answer_style_hint: str = "",
    ) -> str:
        """간결한 RFP 답변을 생성합니다."""
        started = time.perf_counter()
        llm_calls = 0
        try:
            if not self.llm:
                return "LLM 클라이언트가 없습니다."

            prompt_history = history or ""
            if extractive_draft:
                prompt_history = (
                    f"{prompt_history}\n\n## 추출 초안 (문서 근거를 유지한 채 정제)\n{extractive_draft}"
                    if prompt_history
                    else f"## 추출 초안 (문서 근거를 유지한 채 정제)\n{extractive_draft}"
                )

            try:
                # 1) 근거를 먼저 추려서 압축한다.
                evidence_prompt = EVIDENCE_REFINEMENT_PROMPT.format(
                    query=query,
                    context=context,
                    extractive_draft=extractive_draft or "없음",
                )
                evidence_prompt = (
                    f"{evidence_prompt}\n\n"
                    f"## 답변 스타일 힌트\n{self._evidence_style_instruction(query, answer_style_hint)}"
                )
                evidence_messages = [
                    SystemMessage(content=RFP_SYSTEM_PROMPT),
                    HumanMessage(content=evidence_prompt),
                ]
                llm_calls += 1
                evidence_resp = self.llm.invoke(evidence_messages)
                refined_evidence = str(getattr(evidence_resp, "content", "") or "").strip()
                if not refined_evidence:
                    refined_evidence = extractive_draft or "관련 근거 없음"

                # 2) 추려진 근거를 바탕으로 최종 답변을 생성한다.
                if prompt_history:
                    prompt = ANSWER_GENERATION_FROM_EVIDENCE_PROMPT.format(
                        query=query,
                        context=context,
                        evidence=refined_evidence,
                        history=f"## 이전 대화 기록\n{prompt_history}",
                    )
                else:
                    prompt = ANSWER_GENERATION_FROM_EVIDENCE_PROMPT.format(
                        query=query,
                        context=context,
                        evidence=refined_evidence,
                        history="",
                    )
                prompt = f"{prompt}\n\n## 답변 스타일 힌트\n{self._answer_style_instruction(query, answer_style_hint)}"

                messages = [
                    SystemMessage(content=RFP_SYSTEM_PROMPT),
                    HumanMessage(content=prompt)
                ]

                llm_calls += 1
                response = self.llm.invoke(messages)
                answer = response.content
                return self._clean_final_answer(answer)

            except Exception as e:
                # 2단계 생성이 실패하면 기존 단일 생성 경로로 fallback
                try:
                    fallback_prompt = ANSWER_GENERATION_PROMPT.format(
                        query=query,
                        context=context,
                        history=f"## 이전 대화 기록\n{prompt_history}" if prompt_history else "",
                    )
                    fallback_prompt = (
                        f"{fallback_prompt}\n\n"
                        f"## 답변 스타일 힌트\n{self._answer_style_instruction(query, answer_style_hint)}"
                    )
                    fallback_messages = [
                        SystemMessage(content=RFP_SYSTEM_PROMPT),
                        HumanMessage(content=fallback_prompt),
                    ]
                    llm_calls += 1
                    fallback_resp = self.llm.invoke(fallback_messages)
                    return self._clean_final_answer(str(getattr(fallback_resp, "content", "") or ""))
                except Exception:
                    return f"오류: {str(e)}"
        finally:
            self.last_generation_elapsed = time.perf_counter() - started
            self.last_generation_llm_calls = llm_calls

    @staticmethod
    def _clean_final_answer(answer: str) -> str:
        """답변에서 "최종 답변:" 태그를 제거합니다."""
        for indicator in ["## 최종 답변:", "최종 답변:"]:
            if indicator in answer:
                return answer.split(indicator)[-1].strip()
        return answer
