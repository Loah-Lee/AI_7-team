from __future__ import annotations

ANSWER_JSON_PROMPT = (
    "반드시 JSON으로만 답하세요. "
    "키는 status, answer, citations를 사용하세요. "
    "status는 'ok', 'partial', 'not_found' 중 하나만 사용하세요. "
    "정확한 값은 없지만 관련 문맥이 있으면 partial로 답하세요. "
    "근거가 전혀 없으면 answer를 '문서에 해당 정보가 없습니다.'로 반환하세요."
)
