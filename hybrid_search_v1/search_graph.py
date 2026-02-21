"""전체 RAG 그래프

Judge → Retriever → Context Appender → Final Answer 적응형 검색 파이프라인.
"""

from typing import Any, Dict, TypedDict

import dotenv
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph

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

METADATA_KEYS = ('document_title', 'doc_id', 'section_level1', 'section_level2', 'uid')


def context_appender(state: RAGState):
    # LLM에는 text + 핵심 metadata만 전달
    search_result_for_llm = []
    for text, metadata in state['search_result']:
        filtered_meta = {k: metadata[k] for k in METADATA_KEYS if k in metadata}
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
            output += f"\n\t{i+1}. {meta['document_title']} 문서의 {meta['page_start']} 페이지부터 {meta['page_end']} 페이지 사이"
        output += "\n에 있습니다."
        result = result + output
    return {'final_answer': result}


# ============================================================
# 그래프 빌드
# ============================================================

def build_rag_graph():
    """전체 RAG 그래프를 빌드하고 컴파일한다."""
    builder = StateGraph(RAGState)

    builder.add_node("judge", llm1_node)
    builder.add_node('retriever', hybrid_app)
    builder.add_node('context_appender', context_appender)
    builder.add_node('final_answer', final_answer)

    builder.set_entry_point('judge')
    builder.add_conditional_edges('judge', router,
                                {
                                    'final_answer': 'final_answer',
                                    'next_search': 'retriever'
                                })
    builder.add_edge('retriever', 'context_appender')
    builder.add_edge('context_appender', 'judge')
    builder.set_finish_point('final_answer')

    return builder.compile()


app = build_rag_graph()
