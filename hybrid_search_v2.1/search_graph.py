"""전체 RAG 그래프 (v2)

Judge → Routing LLM → {CSV Search | Retriever} → Context Appender → Judge 적응형 검색 파이프라인.
CSV 구조화 검색 채널을 추가하여, 금액/기관/날짜 기반 크로스 문서 질의를 지원한다.
"""

from typing import Any, Dict, TypedDict

import dotenv
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph

from csv_search import csv_search
from hybrid_search import hybrid_app

dotenv.load_dotenv()


# ============================================================
# State 정의
# ============================================================

class RAGState(TypedDict):
    query: str
    context: list[str]
    last_search_query: str | None
    search_result: list[str] | None
    can_answer: bool
    next_query: str
    iteration: int

    # v2: CSV 라우팅
    use_csv: bool
    csv_query: dict | None

    final_answer: str


# ============================================================
# LLM
# ============================================================

llm = ChatOpenAI(model="gpt-5-mini", temperature=0)


# ============================================================
# Judge 노드 (prompt1)
# ============================================================

prompt1 = ChatPromptTemplate.from_messages([
    ("system", """
너는 RAG 시스템의 판단 노드다.

역할:
1. 현재 context만으로 original_query에 답할 수 있는지 판단하라.
2. 충분하거나, iteration이 6이면 can_answer=true로 설정하라.
3. 부족하다면 can_answer=false로 설정하고
   last_query가 빈 문자열이 아닌 경우 참조하여
   답을 얻기 위해 필요한 검색 질의(search_query)를 하나 생성하라.

주의:
- 절대 최종 답변을 생성하지 마라.
- reasoning을 출력하지 마라.
- 반드시 다음과 같은 형식의 JSON 형식으로만 출력하라.
    {{
        "can_answer": bool,
        "search_query": str | None
    }}
"""),
    ("human", """
[Original Query]
{original_query}

[Current Context]
{context}
     
[Last Query]
{last_query}

Iteration: {iteration}
""")
])

define_chain = prompt1 | llm | JsonOutputParser()


def llm1_node(state: Dict[str, Any]) -> Dict[str, Any]:
    if 'next_query' in state:
        last_search_query = state['next_query']
    else:
        last_search_query = ''

    result = define_chain.invoke({
        "original_query": state["query"],
        "context": state["context"],
        "iteration": state["iteration"],
        'last_query': last_search_query
    })

    return {
        "can_answer": result["can_answer"],
        "last_search_query": last_search_query,
        "next_query": result["search_query"],
        "iteration": state["iteration"] + 1
    }


# ============================================================
# Router
# ============================================================

def router(state: RAGState):
    if state['can_answer']:
        return 'final_answer'
    return 'next_search'


# ============================================================
# Routing LLM 노드
# ============================================================

routing_prompt = ChatPromptTemplate.from_messages([
    ("system", """
너는 RAG 시스템의 라우팅 노드다.

역할:
judge 노드가 생성한 search_query를 분석하여,
CSV 구조화 검색과 문서 검색(retriever) 중 적합한 채널을 결정하라.
이때, last_query를 참조하여 결정하라.

## CSV 데이터 컬럼 정보
- 사업명: str (프로젝트 이름)
- 사업 금액: int (원 단위, 일부 null)
- 발주 기관: str (발주처)
- 공개 일자: datetime
- 입찰 참여 시작일: datetime (일부 null)
- 입찰 참여 마감일: datetime (일부 null)
- 사업 요약: str (사업 요약문)

## 라우팅 기준
CSV를 선택해야 하는 경우:
- 금액 기반 질의: 순위(TOP N), 범위(N억 이상/이하/사이), 비교
- 기관/날짜 기반 필터링 또는 집계
- 복수 문서에 걸친 메타데이터 비교

retriever를 선택해야 하는 경우:
- 특정 문서의 내용(본문, 조항, 요구사항 등)에 대한 질의
- 기술적 세부사항, 사업 범위, 계약 조건 등

## csv_query 스키마 (CSV 선택 시 반드시 생성)
    {{
        "filters": [{{"column": str, "op": str, "value": any}}],
        "sort": {{"column": str, "order": "asc" | "desc"}},
        "limit": int,
        "keyword": str
    }}
- filters.op: >=, <=, >, <, ==, contains, between
- 질의가 특정 컬럼을 지정하는 경우 해당 컬럼에 대한 filter를 사용하라.
  - 숫자/날짜 컬럼: >=, <=, >, <, ==, between
  - 문자열 컬럼(사업명, 발주 기관, 사업 요약): contains (부분 일치)
- 질의가 특정 컬럼을 지정하지 않는 일반 텍스트 검색은 keyword를 사용하라.
  keyword는 사업명, 발주 기관, 사업 요약 전체에서 부분 일치로 검색한다.
- between일 때 value는 [min, max] 배열
- 금액 변환: "10억" → 1000000000, "5천만원" → 50000000
- 날짜는 ISO 형식: "2024-01-01"
- 불필요한 필드는 생략 가능

주의:
- reasoning을 출력하지 마라.
- 반드시 다음 JSON 형식으로만 출력하라.
    {{
        "use_csv": bool,
        "csv_query": dict | null
    }}
"""),
    ("human", """
[Original Query]
{original_query}

[Search Query]
{search_query}
     
[Last Query]
{last_query}
""")
])

routing_chain = routing_prompt | llm | JsonOutputParser()


def routing_llm_node(state: Dict[str, Any]) -> Dict[str, Any]:
    result = routing_chain.invoke({
        "original_query": state["query"],
        "search_query": state["next_query"],
        "last_query": state["last_search_query"],
    })

    return {
        "use_csv": result["use_csv"],
        "csv_query": result.get("csv_query"),
    }


def search_router(state: RAGState):
    if state['use_csv']:
        return 'csv_search'
    return 'retriever'


# ============================================================
# Context Appender 노드 (prompt2)
# ============================================================

prompt2 = ChatPromptTemplate.from_messages([
    ("system", """
너는 RAG 시스템의 context 결정 노드다.

역할:
1. search_result는 여러 context로 구성되는 배열이다. 각 context는 'text', 'metadata'로 구성되는 배열이다.
    original_query에 대한 답변에 직접적으로 기여하는 context만 선택하라.
    search_query는 original_query에 답하기 위해 생성된 검색 쿼리이므로, 참고만 하라.
    - 먼저 나오는 context부터 순서대로 추가 여부를 결정한다.
    - 새로운 정보를 제공하지 않는 중복 context는 선택하지 않는다.
    - 단순히 동일 키워드를 포함하는 것만으로는 선택하지 않는다.
2. 추가할 context들의 index를 반환하라.

주의:
- 절대 최종 답변을 생성하지 마라.
- reasoning을 출력하지 마라.
- 반드시 다음과 같은 형식의 JSON 형식으로만 출력하라.
    {{
        "indices": list[int]
    }}
"""),
    ("human", """
[Original Query]
{original_query}

[Search Query]
{search_query}

[Search Result]
{search_result}
""")
])

compress_chain = prompt2 | llm | JsonOutputParser()

METADATA_KEYS_HYBRID = ('document_title', 'doc_id', 'section_level1', 'section_level2', 'uid')
METADATA_KEYS_CSV = ('uid', 'source', '사업명', '사업 금액', '사업금액_억', '발주 기관', '공개 일자')


def context_appender(state: RAGState):
    search_result_for_llm = []
    for text, metadata in state['search_result']:
        keys = METADATA_KEYS_CSV if metadata.get('source') == 'csv' else METADATA_KEYS_HYBRID
        filtered_meta = {k: metadata[k] for k in keys if k in metadata}
        search_result_for_llm.append({'text': text, 'metadata': filtered_meta})

    result = compress_chain.invoke({
        'original_query': state['query'],
        'search_query': state['next_query'],
        'search_result': search_result_for_llm
    })

    # 기존 context의 uid 집합으로 중복 방지
    existing_uids = {c[1]['uid'] for c in state['context'] if len(c) > 1 and isinstance(c[1], dict)}
    new_items = []
    for idx in result['indices']:
        item = state['search_result'][idx]
        uid = item[1].get('uid') if len(item) > 1 and isinstance(item[1], dict) else None
        if uid and uid not in existing_uids:
            if isinstance(item[1], dict):
                item[1].setdefault('source', 'hybrid')
            new_items.append(item)
            existing_uids.add(uid)

    context = list(state['context']) + new_items
    return {
        'context': context,
        'search_result': []
    }


# ============================================================
# Final Answer 노드 (prompt3)
# ============================================================

prompt3 = ChatPromptTemplate.from_messages([
    ("system", """
너는 RAG 시스템의 최종 답변 노드다.

역할:
1. context를 활용하여, original_query에 대한 답변을 구상하라.
2. context 내부의 정보만으로는 답변에 필요한 정보가 충분하지 않다면 반드시 final_answer="답변을 위한 정보가 부족합니다."로 설정한다.

주의:
- reasoning을 출력하지 마라.
- 반드시 context에 있는 정보만을 활용하라.
- 답이 있을 경우 반드시 다음 형식의 string으로 값을 출력하라.
    
    질문 주신 내용에 대한 답은 {{final_answer}}입니다.
     
- 답이 없을 경우 final_answer만 다음처럼 출력하라.
     
    질문 주신 내용은 {{final_answer}}
"""),
    ("human", """
[Search Query]
{search_query}

[Context]
{context}
""")
])

final_chain = prompt3 | llm | StrOutputParser()


def final_answer(state: RAGState):
    result = final_chain.invoke({
        'search_query': state['query'],
        'context': state['context']
    })
    if result != '질문 주신 내용은 답변을 위한 정보가 부족합니다.':
        output = ""
        for i, c in enumerate(state['context']):
            meta = c[1]
            source = meta.get('source', 'hybrid')
            if source == 'csv':
                agency = meta.get('발주 기관', '알 수 없음')
                output += f"\n\t{i+1}. CSV 데이터 (발주 기관: {agency})"
            else:
                output += f"\n\t{i+1}. {meta['document_title']} 문서의 {meta['page_start']} 페이지부터 {meta['page_end']} 페이지 사이"
        output += "\n에 있습니다."
        result = result + output
    return {'final_answer': result}


# ============================================================
# 그래프 빌드
# ============================================================

def build_rag_graph():
    builder = StateGraph(RAGState)

    builder.add_node("judge", llm1_node)
    builder.add_node('routing_llm', routing_llm_node)
    builder.add_node('csv_search', csv_search)
    builder.add_node('retriever', hybrid_app)
    builder.add_node('context_appender', context_appender)
    builder.add_node('final_answer', final_answer)

    builder.set_entry_point('judge')

    builder.add_conditional_edges('judge', router,
                                {
                                    'final_answer': 'final_answer',
                                    'next_search': 'routing_llm'
                                })

    builder.add_conditional_edges('routing_llm', search_router,
                                {
                                    'csv_search': 'csv_search',
                                    'retriever': 'retriever'
                                })

    builder.add_edge('csv_search', 'context_appender')
    builder.add_edge('retriever', 'context_appender')
    builder.add_edge('context_appender', 'judge')
    builder.set_finish_point('final_answer')

    return builder.compile()


app = build_rag_graph()
