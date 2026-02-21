# hybrid_search_v1 사용 설명서

## 개요

한국어 RFP(제안요청서) 문서를 대상으로 하는 적응형 RAG 파이프라인이다.
Dense(벡터) + Sparse(BM25) 하이브리드 검색 후 RRF로 결합하고, LLM이 반복적으로 검색-판단-답변을 수행한다.

## 환경 요구사항

- Python 3.10 (conda env `langc`)
- GPU: 임베딩 모델 로딩 시 사용 (없으면 CPU fallback)
- `.env` 파일에 `OPENAI_API_KEY` 필수
- DB: `DB/document.db` (v2.1.3, 전처리 파이프라인으로 생성)

### 의존 패키지

```
langchain-openai
langchain-community
langgraph
sentence-transformers
kiwipiepy
sqlite-vec
numpy
python-dotenv
```

## 파일 구조

```
hybrid_search_v1/
  hybrid_search.py    # 검색 그래프 (Dense + Sparse + RRF)
  search_graph.py     # 전체 RAG 그래프 (Judge → Retriever → Context Appender → Final Answer)
  minimum.ipynb       # 개발/테스트용 노트북
```

## 아키텍처

### 검색 그래프 (`hybrid_search.py`)

```
entry → empty → dense  ─→ rrf → end
              → sparse ─↗
```

- **empty**: LangGraph 단일 진입점 (fan-out용)
- **dense**: `jhgan/ko-sroberta-multitask` (768d) 임베딩으로 `chunks_vec` 테이블에서 코사인 유사도 top-30 검색
- **sparse**: `kiwipiepy` 명사 추출 후 FTS5 `sparse` 테이블에서 BM25 top-30 검색
- **rrf**: Dense:Sparse = 1:1 동일 가중치, `RRF_K=20`, top-10 반환

### RAG 그래프 (`search_graph.py`)

```
entry → judge ─(can_answer=true)──→ final_answer → end
          ↑    ─(can_answer=false)─→ retriever → context_appender ─┘
          └────────────────────────────────────────────────────────┘
```

- **judge** (`prompt1`): 현재 context로 답변 가능한지 판단. 불가 시 검색 쿼리 생성. 최대 6회 반복.
- **retriever**: 검색 그래프(`hybrid_app`)를 서브그래프로 실행
- **context_appender** (`prompt2`): 검색 결과에서 `original_query`에 직접 기여하는 청크만 선택. uid 기반 중복 방지.
- **final_answer** (`prompt3`): context 기반 최종 답변 생성. 출처(문서명, 페이지) 포함.

## 사용법

### 기본 실행

```python
# hybrid_search_v1/ 디렉토리에서 실행
from search_graph import app

result = app.invoke({
    'query': '고려대학교에서 발주한 프로젝트의 이름',
    'context': [],
    'iteration': 0
})

print(result['final_answer'])
```

### Langfuse 연동

```python
from langfuse.langchain import CallbackHandler

langfuse_handler = CallbackHandler()

result = app.invoke(
    {
        'query': '고려대학교 사업비는?',
        'context': [],
        'iteration': 0
    },
    config={"callbacks": [langfuse_handler]}
)
```

### 검색 그래프만 단독 실행

```python
from hybrid_search import hybrid_app

search_result = hybrid_app.invoke({
    'query': '차세대 포털 학사 정보시스템'
})

for text, metadata in search_result['search_result']:
    print(f"[{metadata['document_title']}] p.{metadata['page_start']}")
    print(text[:100])
    print()
```

## 설정값

| 항목 | 값 | 위치 |
|------|-----|------|
| 임베딩 모델 | `jhgan/ko-sroberta-multitask` (768d) | `hybrid_search.py` |
| LLM | `gpt-5-mini` (temperature=0) | `search_graph.py` |
| RRF_K | 20 | `hybrid_search.py` |
| Dense/Sparse 가중치 | 1:1 (동일) | `hybrid_search.py` |
| 검색 top-k | 30 (Dense, Sparse 각각) | `hybrid_search.py` |
| RRF 반환 수 | 10 | `hybrid_search.py` |
| 최대 반복 횟수 | 6 | `search_graph.py` (prompt1에서 제어) |
| DB 경로 | `/home/codeitDev/project/AI_7-team/DB/document.db` | `hybrid_search.py` |

## 출력 형식

### 답변 가능 시

```
질문 주신 내용에 대한 답은 {답변}입니다.
    1. {문서명} 문서의 {시작페이지} 페이지부터 {끝페이지} 페이지 사이
    2. ...
에 있습니다.
```

### 답변 불가 시

```
질문 주신 내용은 답변을 위한 정보가 부족합니다.
```

## 제한사항

- 검색 그래프는 항상 `query` (원본 질문)로 검색한다. judge가 생성한 `next_query`는 context_appender의 필터링에만 사용된다.
- 다수 문서에 걸친 집계 질문 (예: "사업비가 가장 많은 3곳은?")은 단일 검색으로 답변이 어렵다.
- `sparse` 테이블의 명사 추출은 단어 단위 OR 매칭이며, bigram 전환은 추후 예정이다.
