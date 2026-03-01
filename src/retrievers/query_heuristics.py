#!/usr/bin/env python3
"""리트리버 질의 휴리스틱 함수 모음.

workflow 오케스트레이터에서 직접 사용하던 규칙을 분리해
모듈 단위 관리/테스트를 가능하게 한다.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable


def needs_original_priority(query: str) -> bool:
    """원본 문서 기반 검색을 우선해야 하는 질의인지 판단한다."""
    q = (query or "").lower()
    keywords = [
        "사업비", "총사업비", "예산", "금액", "부가가치세",
        "저작권", "라이선스", "사용권", "책임", "부담", "지적재산", "이미지", "글꼴",
        "요구사항", "평가기준", "제안요청", "과업", "조항", "문구", "근거", "표",
        "단위", "수량", "주기", "횟수", "자주", "기한", "복구", "용량", "가이드",
    ]
    return any(k in q for k in keywords)


def is_budget_query(query: str) -> bool:
    normalized = unicodedata.normalize("NFKC", (query or "").lower())
    hard_markers = ["사업비", "총사업비", "사 업 비", "사업 금액", "부가가치세"]
    if any(marker in normalized for marker in hard_markers):
        return True

    if "금액" in normalized and any(token in normalized for token in ["얼마", "금액은", "금액이", "예산"]):
        return True
    if "예산" in normalized:
        if re.search(r"예산\s*(은|는|이|가|규모|금액|얼마)", normalized):
            return True
        if "얼마" in normalized and "예산회계" not in normalized:
            return True
    return False


def is_accuracy_mode_enabled(answer_quality_mode: str | None) -> bool:
    """정확도 우선 모드 활성 여부를 반환한다."""
    mode = unicodedata.normalize("NFKC", str(answer_quality_mode or "").strip().lower())
    return mode in {"accurate", "quality", "high_accuracy", "high-accuracy"}


def is_precision_fact_query(query: str) -> bool:
    """숫자/단위/규격/코드 앵커 중심 정밀 사실 질의 여부."""
    normalized = unicodedata.normalize("NFKC", (query or "").lower())
    if re.search(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", normalized, flags=re.IGNORECASE):
        return True
    precision_tokens = [
        "복구", "장애", "문자셋", "인코딩", "utf", "charset",
        "용량", "mb", "gb", "kb", "단위", "수량",
        "직무교육", "핵심투입인력", "핵심 인력", "사업관리자", "pm",
        "가이드", "guideline", "guide",
        "가용성", "무중단", "요구사항", "요건",
        "규격", "치수", "가로", "세로", "도면", "mm",
        "cpu", "xeon", "ghz", "core", "사양",
        "협상적격", "배점한도", "85%",
    ]
    return any(token in normalized for token in precision_tokens)


def has_owner_anchor_evidence(results: list[dict[str, Any]], top_n: int = 12) -> bool:
    """책임/부담 질의에서 주체+의무 표현 근거가 확보됐는지 판별."""
    if not results:
        return False
    owner_pair_patterns = [
        re.compile(
            r"(저작권|지식재산|지적재산|소유권|귀속|라이선스|사용권).{0,48}(부담|책임|주체|귀속|의무|제안사|사업자|주사업자|계약상대자|발주기관)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(부담|책임|주체|귀속|의무|제안사|사업자|주사업자|계약상대자|발주기관).{0,48}(저작권|지식재산|지적재산|소유권|귀속|라이선스|사용권)",
            re.IGNORECASE,
        ),
    ]
    for item in results[: max(1, top_n)]:
        text = str(item.get("text", "") or "")
        if not text:
            continue
        if any(pattern.search(text) for pattern in owner_pair_patterns):
            return True
    return False


def has_budget_evidence(results: list[dict[str, Any]], top_n: int = 12) -> bool:
    if not results:
        return False
    budget_markers = ["사업비", "총사업비", "예산", "사업 금액", "사 업 비", "금액"]
    budget_value_pattern = re.compile(
        r"(금\s*)?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:천원|백만원|만원|억원|원)",
        re.IGNORECASE,
    )
    for item in results[: max(1, top_n)]:
        text = str(item.get("text", "") or "")
        if not text:
            continue
        if any(marker in text for marker in budget_markers) and budget_value_pattern.search(text):
            return True
    return False


def is_comparison_query(query: str) -> bool:
    """다문서 비교형 질의 여부를 판별한다."""
    q = unicodedata.normalize("NFKC", (query or "").lower())
    has_compare_token = bool(re.search(r"비교(?!과)", q))
    strong_markers = ["차이", "공통", "모두 고려", "동시에", "두 문서", "서로 다른", "어떻게 다른"]
    has_doc_a = bool(re.search(r"(?<![a-z0-9])a\s*문서", q))
    has_doc_b = bool(re.search(r"(?<![a-z0-9])b\s*문서", q))
    if has_compare_token or any(marker in q for marker in strong_markers) or (has_doc_a and has_doc_b):
        return True
    if "각각" in q and (any(marker in q for marker in ["각 문서", "기관별", "두 문서"]) or has_doc_a or has_doc_b):
        return True
    return False


def is_single_doc_focus_query(query: str, target_org_count: int = 0) -> bool:
    """단일 문서 중심 질의인지 판별한다."""
    q = unicodedata.normalize("NFKC", (query or "").lower())
    if not q:
        return False
    if is_comparison_query(q):
        return False
    if target_org_count >= 2:
        return False
    multi_doc_markers = [
        "사업들과",
        "사업들",
        "각 사업",
        "각각",
        "동시에",
        "모두",
        "목록",
        "식별",
        "종합",
        "추진하는 사업 중",
    ]
    if any(marker in q for marker in multi_doc_markers):
        return False
    return True


def is_implicit_follow_up_query(query: str) -> bool:
    """주어 생략형 후속 질문(예: 마감일은?, 사업명은?)을 판별한다."""
    q = unicodedata.normalize("NFKC", (query or "").lower()).strip()
    if not q:
        return False

    fresh_query_markers = [
        "가장",
        "top",
        "순위",
        "랭킹",
        "기관 찾아",
        "관련 사업",
        "어떤 것이",
        "추천",
        "목록",
    ]
    if any(marker in q for marker in fresh_query_markers):
        return False

    follow_up_slots = [
        "마감일",
        "마감",
        "사업명",
        "사업비",
        "예산",
        "금액",
        "기한",
        "기간",
        "일정",
        "제출",
        "요건",
        "요구사항",
        "담당",
        "연락처",
        "주소",
        "위치",
        "언제",
        "얼마",
        "누가",
    ]
    if any(slot in q for slot in follow_up_slots):
        return True

    return len(q) <= 12 and q.endswith(("?", "요", "줘", "봐", "가요", "인가요"))


def looks_like_project_phrase(text: str) -> bool:
    """기관명이 아니라 사업/문서명으로 보이는 문구인지 판별."""
    normalized = unicodedata.normalize("NFKC", (text or "").lower())
    if not normalized:
        return False
    project_markers = [
        "시스템", "사업", "구축", "고도화", "용역", "재구축", "개선",
        "포털", "플랫폼", "조사", "연계", "기능",
    ]
    return any(marker in normalized for marker in project_markers)


def should_fallback_to_original(
    query: str,
    results: list[dict[str, Any]],
    infer_metadata_doc_type: Callable[[dict[str, Any]], str],
    *,
    needs_original_priority_fn: Callable[[str], bool] = needs_original_priority,
) -> bool:
    """CSV에만 치우친 결과면 원본 문서 재검색을 강제한다."""
    if not results:
        return True
    if not needs_original_priority_fn(query):
        return False
    has_original = any(
        infer_metadata_doc_type(item.get("metadata", {}) or {}) in {"pdf", "hwp"}
        for item in results[:8]
    )
    return not has_original
