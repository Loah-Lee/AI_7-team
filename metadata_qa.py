"""
Metadata QA Module - Verifies Metadata Analyst's analysis results

검증 항목:
1. Schema Alignment: 선택 컬럼이 질문을 올바르게 대변하는가?
2. Logic Consistency: 필터링 로직이 정확한가?
3. Data Completeness: 검색 범위가 충분한가?
"""

import json
import os
from typing import Dict, Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


class MetadataQAValidator:
    """Metadata Analyst 결과 검증 엔진"""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model
        self.llm = ChatOpenAI(
            model=model,
            temperature=0,
            api_key=OPENAI_API_KEY
        )
    
    def verify_analysis(
        self,
        question: str,
        analyst_reasoning: str,
        dynamic_view: str,
        retry_count: int = 0
    ) -> Dict[str, Any]:
        """
        Metadata Analyst의 분석 결과를 검증합니다.
        
        Args:
            question: 사용자 원래 질문
            analyst_reasoning: Analyst의 사고 과정 로그
            dynamic_view: 생성된 Markdown 테이블
            retry_count: 현재 재시도 횟수
        
        Returns:
            Dict with keys:
            - status: "PASS" 또는 "FAIL"
            - feedback: 상세 피드백 또는 수정 제안
            - reason: 판정 사유
            - should_retry: 재시도 여부 (FAIL && retry_count < 3)
        """
        
        print(f"\n🔍 [Metadata QA] 분석 검증 중... (Retry #{retry_count})")
        
        qa_prompt = f"""당신은 Metadata Analyst의 분석 결과를 검증하는 QA 엔지니어입니다.

### 검증 대상:

**사용자 질문:**
"{question}"

**Analyst의 사고 과정:**
{analyst_reasoning}

**생성된 데이터 뷰 (Markdown Table):**
{dynamic_view}

---

### 검증 항목:

1. **Schema Alignment (스키마 정렬)**: 
   - Analyst가 선택한 컬럼이 질문의 핵심 키워드를 올바르게 대변하는가?
   - 예시 오류: "학교"를 찾아야 하는데 '입찰마감일시' 컬럼(날짜)을 조회함

2. **Logic Consistency (논리적 정합성)**:
   - 자연어 제약 조건이 올바른 필터링 연산으로 변환되었는가?
   - 예시 오류: "5억 이상"이라는 수치 조건을 텍스트 포함 검색으로 처리함

3. **Data Completeness (데이터 완전성)**:
   - 검색 범위가 충분하여 데이터 누락이 없는가?
   - 특정 기관명(예: "고려대")이 질문에 있는데 관련 데이터가 없으면 "재검색 필요"로 판정

---

### 판정 기준:

**PASS**: 분석이 논리적으로 타당하고 질문을 완전히 해결
**FAIL**: 논리적 오류, 데이터 타입 불일치, 또는 데이터 누락이 있음

---

### 응답 형식 (반드시 JSON):

{{
  "status": "PASS 또는 FAIL",
  "reason": "판정 사유 (1-2문장)",
  "feedback": "상세 피드백 및 구체적 수정 방향 (FAIL인 경우 필수)"
}}

### 중요: 
- FAIL이면 Analyst가 참고할 수 있도록 **구체적인 수정 제안**을 기술하세요.
  예: "2글자 이하 검색어 '서' 처리 누락", "발주처 컬럼이 아닌 다른 컬럼을 확인 필요" 등
- 특별히 '데이터 없음' 결과가 반환되었을 때, 이것이 실제 부재인지 아니면 검색 실패인지 판별하세요.
"""

        try:
            messages = [
                SystemMessage(content="당신은 데이터 분석 검증 전문 QA입니다."),
                HumanMessage(content=qa_prompt)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content.strip()
            
            print(f"   📊 QA 응답 (처음 100자): {response_text[:100]}...")
            
            # Parse JSON from response
            json_str = response_text
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(json_str)
            
            # Determine if we should retry
            status = result.get("status", "PASS").upper()
            should_retry = (status == "FAIL") and (retry_count < 3)
            
            result["should_retry"] = should_retry
            result["response_text"] = response_text
            
            verdict = "✅ PASS" if status == "PASS" else "❌ FAIL"
            print(f"   {verdict} {result.get('reason', '')}")
            
            if should_retry:
                print(f"   🔄 재시도 가능: {retry_count + 1}/3회")
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"   ⚠️ JSON 파싱 실패: {str(e)}")
            return {
                "status": "FAIL",
                "reason": "QA 응답 파싱 실패",
                "feedback": "JSON 형식의 응답을 받지 못했습니다.",
                "should_retry": retry_count < 3,
                "response_text": response_text
            }
        
        except Exception as e:
            print(f"   ❌ QA 검증 오류: {str(e)}")
            return {
                "status": "FAIL",
                "reason": f"검증 중 오류 발생: {str(e)}",
                "feedback": "QA 모듈 오류로 인해 기본값으로 FAIL 판정",
                "should_retry": retry_count < 3,
                "response_text": ""
            }


# ============================================================================
# 싱글톤 인스턴스 (전역 사용)
# ============================================================================
_qa_validator = None

def get_qa_validator() -> MetadataQAValidator:
    """lazily initialize and return the global QA validator instance"""
    global _qa_validator
    if _qa_validator is None:
        _qa_validator = MetadataQAValidator()
    return _qa_validator


def verify_analysis(
    question: str,
    analyst_reasoning: str,
    dynamic_view: str,
    retry_count: int = 0
) -> Dict[str, Any]:
    """
    Verify Metadata Analyst analysis result.
    
    Convenience function that uses the global QA validator.
    """
    validator = get_qa_validator()
    return validator.verify_analysis(question, analyst_reasoning, dynamic_view, retry_count)


__all__ = ["MetadataQAValidator", "verify_analysis", "get_qa_validator"]
