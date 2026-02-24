"""LLM-as-Judge 평가 모듈.

RAG 응답을 4가지 기준(Correctness, Answer Coverage, Faithfulness, Context Relevance)으로 채점한다.
단일 LLM 호출로 JSON 형태의 점수(0~5) + 근거를 반환.
"""

from __future__ import annotations

import json
import os

from langchain_openai import ChatOpenAI

try:
    from src.utils.config import load_config
    from src.utils.env import get_openai_api_key, load_env
    UTILS_AVAILABLE = True
except ImportError:
    UTILS_AVAILABLE = False

JUDGE_SYSTEM_PROMPT = """\
당신은 RAG(Retrieval-Augmented Generation) 시스템의 응답 품질을 평가하는 전문 심사관입니다.

주어진 정보를 바탕으로 아래 4가지 기준을 각각 0~5점으로 채점하고, 각 점수에 대한 1줄 근거를 작성하세요.

## 채점 기준

### Correctness (정확성)
생성된 답변이 기대 답변과 의미적으로 일치하는 정도. 포함된 정보가 정확한가에 초점.
- 5: 기대 답변의 핵심 정보를 모두 정확히 포함
- 4: 대부분의 핵심 정보가 정확하나 사소한 부정확 있음
- 3: 핵심 정보의 절반 정도가 정확
- 2: 일부만 맞고 오류 포함
- 1: 거의 관련 없는 답변
- 0: 완전히 틀리거나 답변 거부

### Answer Coverage (답변 커버리지)
기대 답변의 핵심 정보가 생성 답변에 얼마나 누락 없이 포함되었는가. Correctness와 달리 빠진 정보가 있는가에 초점.
- 5: 기대 답변의 모든 핵심 포인트를 빠짐없이 포함
- 4: 대부분 포함하나 사소한 항목 1~2개 누락
- 3: 핵심 포인트의 절반 정도만 커버
- 2: 주요 정보 대부분 누락, 일부만 언급
- 1: 핵심 정보가 거의 없음
- 0: 관련 정보 전혀 없음 또는 답변 거부

### Faithfulness (충실성)
생성된 답변이 검색된 context에 근거하고 있는 정도 (환각 없는 정도).
- 5: 답변의 모든 내용이 context에서 직접 확인 가능
- 4: 대부분 context에 근거하나 사소한 추론 포함
- 3: 핵심은 context에 있으나 상당한 추론/일반화 포함
- 2: context와 부분적으로만 관련, 환각 포함
- 1: 대부분 환각이거나 context와 무관
- 0: 완전한 환각 또는 context 무시

### Context Relevance (검색 관련성)
검색된 context가 질문에 실제로 관련 있는 정도.
- 5: context가 질문에 완벽히 관련, 답변에 필요한 정보를 충분히 포함
- 4: 대부분 관련 있으나 일부 불필요한 내용 포함
- 3: 부분적으로 관련, 핵심 정보가 일부 부족
- 2: 관련성이 낮고 대부분 무관한 내용
- 1: 거의 관련 없는 문서
- 0: 완전히 무관한 문서

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요. 마크다운 코드블록(```)이나 다른 텍스트 없이 순수 JSON만 출력하세요.
reason은 반드시 한 문장으로 작성하세요.

{"correctness": {"score": 0, "reason": "..."}, "answer_coverage": {"score": 0, "reason": "..."}, "faithfulness": {"score": 0, "reason": "..."}, "context_relevance": {"score": 0, "reason": "..."}}"""

JUDGE_USER_TEMPLATE = """\
## 질문
{question}

## 기대 답변
{expected_answer}

## 검색된 Context
{context}

## 생성된 답변
{generated_answer}"""


def _parse_judge_response(content: str) -> dict:
    """LLM 응답에서 JSON을 추출하여 파싱한다."""
    text = content.strip()

    # 마크다운 코드블록 제거
    if "```" in text:
        lines = text.split("\n")
        json_lines = []
        inside = False
        for line in lines:
            if line.strip().startswith("```") and not inside:
                inside = True
                continue
            elif line.strip().startswith("```") and inside:
                break
            elif inside:
                json_lines.append(line)
        text = "\n".join(json_lines)

    parsed = json.loads(text)

    # 유효성 검증
    result = {}
    for key in ("correctness", "answer_coverage", "faithfulness", "context_relevance"):
        entry = parsed.get(key, {})
        score = int(entry.get("score", 0))
        score = max(0, min(5, score))
        reason = str(entry.get("reason", ""))
        result[key] = {"score": score, "reason": reason}

    return result


def judge_rag_response(
    question: str,
    expected_answer: str,
    generated_answer: str,
    context: str,
    model: str | None = None,
) -> dict:
    """RAG 응답을 LLM Judge로 4가지 기준 채점한다.

    Args:
        question: 사용자 질문.
        expected_answer: 기대 정답.
        generated_answer: RAG가 생성한 답변.
        context: 검색된 문서 컨텍스트.
        model: 평가에 사용할 LLM 모델 (기본: config의 모델).

    Returns:
        {
            "correctness": {"score": 0~5, "reason": str},
            "answer_coverage": {"score": 0~5, "reason": str},
            "faithfulness": {"score": 0~5, "reason": str},
            "context_relevance": {"score": 0~5, "reason": str},
        }
    """
    if UTILS_AVAILABLE:
        load_env()
        config = load_config()
        llm_cfg = config.get("llm", {})
        api_key = get_openai_api_key()
    else:
        llm_cfg = {}
        api_key = os.getenv("OPENAI_API_KEY", "")

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is required. Set it in environment variables "
            "or install src.utils.env module."
        )

    timeout_raw = os.getenv("LLM_JUDGE_TIMEOUT_SEC", "90").strip()
    try:
        request_timeout = max(15.0, float(timeout_raw))
    except Exception:
        request_timeout = 90.0

    llm = ChatOpenAI(
        model=model or llm_cfg.get("model", "gpt-5-mini"),
        temperature=0.0,
        max_tokens=4096,
        api_key=api_key,
        timeout=request_timeout,
        max_retries=0,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    # 컨텍스트가 너무 길면 잘라서 JSON 응답 안정성 확보
    max_context_len = 6000
    trimmed_context = context[:max_context_len] if context else "(검색 결과 없음)"
    if context and len(context) > max_context_len:
        trimmed_context += "\n\n... (이하 생략)"

    user_message = JUDGE_USER_TEMPLATE.format(
        question=question,
        expected_answer=expected_answer,
        generated_answer=generated_answer,
        context=trimmed_context,
    )

    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    max_retries = 2
    for attempt in range(max_retries):
        try:
            result = llm.invoke(messages)
            return _parse_judge_response(result.content)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            if attempt < max_retries - 1:
                print(f"[LLM Judge] 파싱 실패 (재시도 {attempt + 1}/{max_retries}): {e}")
                continue
            print(f"[LLM Judge] 응답 파싱 최종 실패: {e}")
            return {
                "correctness": {"score": 0, "reason": f"파싱 실패: {e}"},
                "answer_coverage": {"score": 0, "reason": f"파싱 실패: {e}"},
                "faithfulness": {"score": 0, "reason": f"파싱 실패: {e}"},
                "context_relevance": {"score": 0, "reason": f"파싱 실패: {e}"},
            }
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[LLM Judge] LLM 호출 에러 (재시도 {attempt + 1}/{max_retries}): {e}")
                continue
            print(f"[LLM Judge] LLM 호출 최종 실패: {e}")
            return {
                "correctness": {"score": 0, "reason": f"LLM 에러: {type(e).__name__}"},
                "answer_coverage": {"score": 0, "reason": f"LLM 에러: {type(e).__name__}"},
                "faithfulness": {"score": 0, "reason": f"LLM 에러: {type(e).__name__}"},
                "context_relevance": {"score": 0, "reason": f"LLM 에러: {type(e).__name__}"},
            }
