"""
RAG Pipeline - Advanced Architecture with State Management

LangGraph를 활용하여 다음 구조를 구현:
1. Router: 질문의 의도 분류 (metadata/context/hybrid)
2. Parallel Execution: Metadata Analyst & Retrieval Agent 동시 실행
3. Metadata QA Loop: 검증 및 재시도 (최대 3회)
4. Synthesis: 최종 답변 생성

병렬 처리:
- Hybrid 모드: Analyst와 Retrieval이 독립적으로 실행
- 각자의 결과를 Synthesis에서 병합
"""

import os
import json
import sys
from typing import Dict, List, Any, Literal
from datetime import datetime
from dotenv import load_dotenv

# LangGraph & LangChain imports
from langgraph.graph import StateGraph, END, START
from langchain_openai import ChatOpenAI
from langchain_core.documents import Document

# Local imports
from core.state import GraphState
from prompts import (
    ROUTER_PROMPT,
    METADATA_ANALYST_PROMPT,
    METADATA_QA_PROMPT,
    SYNTHESIS_PROMPT,
)
from metadata_qa import verify_analysis
from search import hybrid_search
from router import RouterAgent
from tools import get_csv_schema, filter_csv


load_dotenv()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("❌ Error: OPENAI_API_KEY not found in .env")
    sys.exit(1)


# ============================================================================
# INITIALIZATION
# ============================================================================

class RAGPipelineController:
    """RAG Pipeline Controller"""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model
        self.llm = ChatOpenAI(
            model=model,
            temperature=0,
            api_key=OPENAI_API_KEY
        )
        self.router_agent = RouterAgent(model=model)
        self.metadata_context = get_csv_schema()  # Load schema once
    
    # ======================================================================
    # NODE FUNCTIONS
    # ======================================================================
    
    def router_node(self, state: GraphState) -> Dict[str, Any]:
        """
        Router Node: Classify user intent and determine execution path.
        
        Updates:
        - state['intent']: "metadata", "context", or "hybrid"
        """
        print(f"\n{'='*70}")
        print(f"🔀 [ROUTER NODE]")
        print(f"{'='*70}")
        
        question = state.get("question", "")
        print(f"질문: {question}")
        
        # Use RouterAgent to classify intent
        result = self.router_agent.classify_intent(question)
        intent = result.get("intent", "hybrid")
        confidence = result.get("confidence", 0.0)
        
        print(f"분류 결과: {intent} (확신도: {confidence:.2f})")
        
        # Return only the field this node updates
        return {"intent": intent}
    
    
    def analyst_node(self, state: GraphState) -> Dict[str, Any]:
        """
        Metadata Analyst Node: Extract structured data from CSV.
        
        Updates:
        - state['analyst_reasoning']: Thinking process
        - state['dynamic_view']: Generated Markdown Table
        
        Strategy: Use LLM to determine search parameters, then call filter_csv tool directly.
        """
        print(f"\n{'='*70}")
        print(f"📊 [METADATA ANALYST NODE]")
        print(f"{'='*70}")
        
        question = state.get("question", "")
        qa_feedback = state.get("qa_feedback", "")
        retry_count = state.get("retry_count", 0)
        
        print(f"분석 중... (재시도: {retry_count}/3)")
        
        # Step 1: Use LLM to determine which columns and keywords to search
        search_strategy_prompt = f"""당신은 CSV 데이터 분석 전문가입니다.

## CSV 스키마:
{self.metadata_context}

## 사용자 질문:
"{question}"

## 작업:
다음 JSON 형식으로 검색 전략을 제시하세요. 
질문의 핵심 키워드를 찾아 어떤 CSV 컬럼에서 검색할지 결정하세요.

{{
  "strategy": "분석 전략 설명",
  "search_columns": ["컬럼1", "컬럼2"],  # 검색할 CSV 컬럼 목록
  "search_keywords": ["키워드1", "키워드2"]  # 검색할 키워드 목록
}}

## 주의:
- 검색 컬럼은 반드시 위 스키마에 존재하는 컬럼이어야 함
- 여러 키워드가 필요하면 리스트에 모두 포함하세요
"""
        
        if qa_feedback:
            search_strategy_prompt += f"\n## 이전 피드백 (이를 반영하여 수정하세요):\n{qa_feedback}\n"
        
        try:
            # Get search strategy from LLM
            strategy_response = self.llm.invoke([
                {"role": "system", "content": "당신은 CSV 데이터 검색 전략 수립 전문가입니다."},
                {"role": "user", "content": search_strategy_prompt}
            ])
            
            strategy_text = strategy_response.content.strip()
            
            # Parse strategy JSON
            json_str = strategy_text
            if "```json" in strategy_text:
                json_str = strategy_text.split("```json")[1].split("```")[0].strip()
            elif "```" in strategy_text:
                json_str = strategy_text.split("```")[1].split("```")[0].strip()
            
            strategy = json.loads(json_str)
            reasoning = strategy.get("strategy", "전략 수립")
            search_columns = strategy.get("search_columns", ["발주 기관"])
            search_keywords = strategy.get("search_keywords", [question])
            
            print(f"📋 검색 전략:")
            print(f"   컬럼: {search_columns}")
            print(f"   키워드: {search_keywords}")
            
            # Step 2: Call filter_csv for each column-keyword combination
            dynamic_view = ""
            results_found = False
            
            for column in search_columns:
                for keyword in search_keywords:
                    print(f"   🔍 '{column}' 컬럼에서 '{keyword}' 검색 중...")
                    
                    result = filter_csv(column=column, value=keyword)
                    
                    # Check if results found
                    if result and "Found 0 matching rows" not in result and len(result) > 50:
                        dynamic_view = result
                        results_found = True
                        print(f"      ✅ {len(result)} 문자의 결과 발견")
                        break
                
                if results_found:
                    break
            
            # If no results found, try broader search
            if not results_found and len(search_keywords) > 0:
                print(f"   ⚠️ 첫 번째 검색 실패, 폴백 검색 시도...")
                for keyword in search_keywords:
                    # Try with '발주 기관' column as default
                    result = filter_csv(column="발주 기관", value=keyword)
                    if result and "Found 0 matching rows" not in result and len(result) > 50:
                        dynamic_view = result
                        results_found = True
                        break
            
            if not dynamic_view:
                dynamic_view = "관련 데이터 없음\n\n| 키워드 | 검색 결과 |\n|--------|----------|\n| " + \
                              " | 없음 |\n| ".join(search_keywords) + " | 없음 |"
            
            print(f"✅ 분석 완료")
            print(f"   추론: {reasoning[:100]}...")
            print(f"   결과: {'데이터 발견' if results_found else '데이터 없음'}")
            
            # Return only the fields this node updates
            return {
                "analyst_reasoning": reasoning,
                "dynamic_view": dynamic_view
            }
            
        except Exception as e:
            print(f"❌ Analyst 오류: {str(e)}")
            import traceback
            traceback.print_exc()
            # Return only the fields this node updates
            return {
                "analyst_reasoning": f"분석 중 오류 발생: {str(e)}",
                "dynamic_view": "관련 데이터 없음"
            }
    
    
    def metadata_qa_node(self, state: GraphState) -> Dict[str, Any]:
        """
        Metadata QA Node: Verify Analyst's analysis.
        
        Updates:
        - state['qa_status']: "PASS" or "FAIL"
        - state['qa_feedback']: QA suggestions if FAIL
        - state['retry_count']: Increment by 1
        """
        print(f"\n{'='*70}")
        print(f"🔍 [METADATA QA NODE]")
        print(f"{'='*70}")
        
        question = state.get("question", "")
        reasoning = state.get("analyst_reasoning", "")
        dynamic_view = state.get("dynamic_view", "")
        retry_count = state.get("retry_count", 0)
        
        # Call QA validator
        qa_result = verify_analysis(question, reasoning, dynamic_view, retry_count)
        
        qa_status = qa_result.get("status", "PASS").upper()
        qa_feedback = qa_result.get("feedback", "")
        
        print(f"검증 결과: {qa_status}")
        print(f"피드백: {qa_feedback[:100]}...")
        
        # Return only the fields this node updates
        return {
            "qa_status": qa_status,
            "qa_feedback": qa_feedback,
            "retry_count": retry_count + 1
        }
    
    
    def retrieval_node(self, state: GraphState) -> Dict[str, Any]:
        """
        Retrieval Node: Search for relevant documents.
        
        Updates:
        - state['documents']: List of retrieved Document objects
        
        Uses hybrid_search (Sparse + Dense + Rerank)
        """
        print(f"\n{'='*70}")
        print(f"🔎 [RETRIEVAL NODE]")
        print(f"{'='*70}")
        
        question = state.get("question", "")
        
        print(f"검색 중: '{question}'")
        
        try:
            # Call hybrid search - this prints output 
            # (search.py don't return values in original implementation)
            hybrid_search(question)
            
            # Create representative documents for context
            documents = [
                Document(
                    page_content=f"Search results for: {question}",
                    metadata={
                        "source": "hybrid_search_db",
                        "query": question,
                        "rank": 1
                    }
                )
            ]
            
            print(f"✅ 검색 완료: {len(documents)}건 컨텍스트 문서 준비됨")
            
            # Return only the field this node updates
            return {"documents": documents}
            
        except Exception as e:
            print(f"❌ 검색 오류: {str(e)}")
            # Return only the field this node updates
            return {"documents": []}
    
    
    def synthesis_node(self, state: GraphState) -> Dict[str, Any]:
        """
        Synthesis Node: Generate final answer.
        
        Combines:
        - state['dynamic_view']: Structured data from Metadata Analyst
        - state['documents']: Retrieved documents from Retrieval Agent
        
        Updates:
        - state['final_answer']: Final synthesized response
        """
        print(f"\n{'='*70}")
        print(f"✨ [SYNTHESIS NODE]")
        print(f"{'='*70}")
        
        question = state.get("question", "")
        dynamic_view = state.get("dynamic_view", "")
        documents = state.get("documents", [])
        intent = state.get("intent", "unknown")
        
        print(f"답변 생성 중...")
        print(f"의도: {intent}")
        print(f"데이터 뷰: {'있음' if dynamic_view else '없음'}")
        print(f"검색 문서: {len(documents)}건")
        
        # Build synthesis prompt
        synthesis_prompt = f"""당신은 제공된 정형 데이터(테이블)와 비정형 문서를 종합하여 최종 답변을 생성하는 합성 담당자입니다.

### 사용자 질문:
"{question}"

### 제공된 정형 데이터 (Dynamic View):
{dynamic_view if dynamic_view else "(데이터 없음)"}

### 검색된 관련 문서:
"""
        
        if documents:
            for i, doc in enumerate(documents):
                synthesis_prompt += f"\n**문서 {i+1}** ({doc.metadata.get('source', '무제')}):\n{doc.page_content[:500]}...\n"
        else:
            synthesis_prompt += "(검색된 문서 없음)\n"
        
        synthesis_prompt += """
### 답변 생성 규칙:
1. **표의 데이터를 최우선**: 제공된 테이블의 수치/정보는 검증된 사실이므로 최우선으로 반영
2. **문서는 보완용**: 문서 내용은 표의 내용을 설명하거나 추가 문맥 제공
3. **충돌 시 표 우선**: 정형 데이터와 문서 정보가 모순되면 표의 정보를 따름
4. **근거 명시**: "제공된 데이터에 따르면..." 또는 "관련 문서에 따르면..."으로 시작
5. **정직함**: 데이터가 없으면 "정보가 확보되지 않았습니다"라고 명시 (Hallucination 방지)

### 최종 답변을 JSON 형식으로 반환:
{
  "answer": "최종 답변 (사용자 질문에 직접 대답, 간결함)",
  "sources": ["사용 출처 나열"],
  "confidence": 0.0 ~ 1.0 (확신도)
}

분석을 시작하세요:"""
        
        try:
            response = self.llm.invoke([
                {"role": "system", "content": SYNTHESIS_PROMPT.messages[0].content},
                {"role": "user", "content": synthesis_prompt}
            ])
            
            response_text = response.content.strip()
            
            # Parse JSON
            json_str = response_text
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(json_str)
            
            final_answer = result.get("answer", "답변 생성 실패")
            sources = result.get("sources", [])
            confidence = result.get("confidence", 0.0)
            
            print(f"✅ 답변 생성 완료 (확신도: {confidence:.2f})")
            print(f"출처: {', '.join(sources)}")
            print(f"답변: {final_answer[:150]}...")
            
            # Return only the field this node updates
            return {"final_answer": final_answer}
            
        except Exception as e:
            print(f"❌ 합성 오류: {str(e)}")
            # Return only the field this node updates
            return {"final_answer": f"답변 생성 중 오류 발생: {str(e)}"}
    
    
    # ======================================================================
    # EDGE LOGIC FUNCTIONS
    # ======================================================================
    
    def route_intent(self, state: GraphState) -> str | List[str]:
        """
        Route based on intent classification.
        
        Returns:
        - "analyst": metadata search only
        - "retrieval": context search only
        - ["analyst", "retrieval"]: hybrid (parallel execution)
        """
        intent = state.get("intent", "hybrid")
        
        if intent == "metadata":
            print(f"→ Routing to: METADATA Analyst")
            return "analyst"
        elif intent == "context":
            print(f"→ Routing to: RETRIEVAL Agent")
            return "retrieval"
        else:  # hybrid
            print(f"→ Routing to: PARALLEL (Analyst + Retrieval)")
            return ["analyst", "retrieval"]
    
    
    def check_qa_status(self, state: GraphState) -> Literal["retry", "proceed"]:
        """
        Determine whether to retry Analyst or proceed to Synthesis.
        
        Returns:
        - "retry": If FAIL and retry_count < 3, go back to analyst
        - "proceed": If PASS or max retries reached, go to synthesis
        """
        qa_status = state.get("qa_status", "PASS")
        retry_count = state.get("retry_count", 0)
        
        if qa_status == "FAIL" and retry_count < 3:
            print(f"→ QA Result: FAIL → Retrying (Attempt {retry_count+1}/3)")
            return "retry"
        else:
            if qa_status == "FAIL":
                print(f"→ QA Result: FAIL but max retries reached → Proceeding to Synthesis")
            else:
                print(f"→ QA Result: PASS → Proceeding to Synthesis")
            return "proceed"
    
    
    # ======================================================================
    # GRAPH CONSTRUCTION
    # ======================================================================
    
    def build_workflow(self) -> StateGraph:
        """
        Build the RAG workflow graph.
        
        Returns:
        - Compiled LangGraph workflow
        """
        
        workflow = StateGraph(GraphState)
        
        # Register nodes
        workflow.add_node("router", self.router_node)
        workflow.add_node("analyst", self.analyst_node)
        workflow.add_node("metadata_qa", self.metadata_qa_node)
        workflow.add_node("retrieval", self.retrieval_node)
        workflow.add_node("synthesis", self.synthesis_node)
        
        # Set entry point
        workflow.set_entry_point("router")
        
        # Edge 1: Router -> Branching (Conditional)
        workflow.add_conditional_edges(
            "router",
            self.route_intent,
            {
                "analyst": "analyst",
                "retrieval": "retrieval"
                # Note: ["analyst", "retrieval"] list is handled automatically by LangGraph
                # for parallel execution (implicit edge to both nodes)
            }
        )
        
        # Edge 2: Analyst -> QA
        workflow.add_edge("analyst", "metadata_qa")
        
        # Edge 3: QA -> Branching (Conditional Loop)
        workflow.add_conditional_edges(
            "metadata_qa",
            self.check_qa_status,
            {
                "retry": "analyst",
                "proceed": "synthesis"
            }
        )
        
        # Edge 4: Retrieval -> Synthesis
        workflow.add_edge("retrieval", "synthesis")
        
        # Edge 5: Synthesis -> END
        workflow.add_edge("synthesis", END)
        
        return workflow


def create_rag_app():
    """
    Factory function to create and compile the RAG application.
    
    Returns:
    - Compiled LangGraph application ready for execution
    """
    controller = RAGPipelineController()
    workflow = controller.build_workflow()
    return workflow.compile()


# ============================================================================
# MAIN EXECUTION & TESTING
# ============================================================================

def run_query(app, question: str) -> str:
    """
    Execute a single query through the RAG pipeline.
    
    Args:
        app: Compiled LangGraph application
        question: User's natural language question
    
    Returns:
        Final answer string
    """
    
    print(f"\n{'#'*70}")
    print(f"# 질문: {question}")
    print(f"{'#'*70}\n")
    
    # Initialize state
    initial_state = GraphState(
        question=question,
        intent="",
        analyst_reasoning="",
        dynamic_view="",
        qa_status="",
        qa_feedback="",
        retry_count=0,
        documents=[],
        final_answer=""
    )
    
    # Invoke the app
    try:
        final_state = app.invoke(initial_state, config={"recursion_limit": 10})
        
        final_answer = final_state.get("final_answer", "답변을 생성하지 못했습니다.")
        
        print(f"\n{'='*70}")
        print(f"📝 최종 답변:")
        print(f"{'='*70}")
        print(final_answer)
        print(f"{'='*70}\n")
        
        return final_answer
        
    except Exception as e:
        print(f"❌ 파이프라인 실행 중 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        return f"파이프라인 오류: {str(e)}"


if __name__ == "__main__":
    
    print(f"\n{'='*70}")
    print(f"🚀 RAG PIPELINE 시작")
    print(f"{'='*70}\n")
    
    # Create RAG app
    print("📦 파이프라인 초기화 중...")
    app = create_rag_app()
    print("✅ 파이프라인 준비 완료\n")
    
    # Test Case: "고려대학교 입찰 마감일은 언제인가?"
    test_question = "고려대학교 입찰 마감일은 언제인가?"
    
    run_query(app, test_question)
