# hybrid_search_v2.2 사용 가이드

## 개요

v1의 hybrid search(Dense + Sparse + RRF)에 **CSV 구조화 검색** 채널을 추가한 RAG 파이프라인.
금액 순위, 범위 필터링, 기관별 집계 등 v1이 처리하지 못했던 크로스 문서 질의를 지원한다.
v2.1에서 Streamlit 채팅 UI, v2.2에서 **세션 메모리**(최근 5건 로그 누적)와 **query_modifier**(대화 맥락 기반 쿼리 교정)가 추가되었다.

## 아키텍처

```
query_modifier (LLM, 1회) → judge (LLM) → routing_llm (LLM) → csv_search   → context_appender → judge
                                                              → retriever                         ↓ (can_answer=true)
                                                                                             final_answer
```

- **query_modifier**: 이전 대화 로그(memory)를 참조하여 불완전한 쿼리를 재작성 (1회만 실행, 루프 밖)
- **judge**: 현재 context로 답변 가능 여부를 판단하고, 부족하면 search_query를 생성
- **routing_llm**: search_query와 last_query를 참조하여 CSV 검색 또는 기존 retriever로 라우팅
- **csv_search**: 구조화된 csv_query를 받아 DataFrame 연산 수행 (LLM 호출 없음)
- **retriever**: 기존 hybrid search (Dense + Sparse → RRF)
- **context_appender**: 검색 결과 중 유의미한 context를 선별하여 누적
- **final_answer**: 누적된 context 기반으로 최종 답변 생성

## 실행 방법

### Streamlit UI (app.py)

```bash
cd hybrid_search_v2.2
conda run -n langc streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속 후 채팅창에 질문을 입력한다.
그래프 실행 결과 중 `final_answer`만 표시된다.

### 노트북 (minimum.ipynb)

셀을 위에서 아래로 순차 실행한다.

```
Cell 0   : import (typing, langgraph, langchain)
Cell 1   : dotenv
Cell 2-3 : Langfuse 설정
Cell 4   : hybrid search 정의 (SearchState, dense/sparse/rrf)
Cell 5   : empty 노드
Cell 6-7 : hybrid search 그래프 빌드/컴파일
Cell 8   : RAGState 정의 + JsonOutputParser import
Cell 9   : LLM + judge 노드 (prompt1 + llm1_node)
Cell 10  : router (can_answer 분기)
Cell 11  : routing_llm 노드 (routing_prompt + routing_llm_node + search_router)  ← NEW
Cell 12  : context_appender 노드 (prompt2 + compress_chain)
Cell 13  : final_answer 노드 (prompt3 + final_chain)
Cell 14  : csv_search import  ← NEW
Cell 15  : 그래프 빌드 + 첫 번째 테스트 실행
Cell 16+ : 추가 테스트 쿼리
```

### 스크립트 (search_graph.py)

```python
import dotenv
dotenv.load_dotenv()

from search_graph import app

result = app.invoke({
    'query': '사업비가 가장 많은 3곳은?',
    'context': [],
    'iteration': 0,
    'use_csv': False,
    'csv_query': None
})

print(result['final_answer'])
```

### CSV 검색 단독 테스트

```python
from csv_search import csv_search

result = csv_search({
    'csv_query': {
        'filters': [{'column': '사업 금액', 'op': '>=', 'value': 1e9}],
        'sort': {'column': '사업 금액', 'order': 'desc'},
        'limit': 5
    }
})

for text, meta in result['search_result']:
    print(f"{text} | {meta['사업금액_억']:.2f}억 | {meta['발주 기관']}")
```

## csv_query 스키마

routing_llm이 생성하는 구조화된 쿼리 형식:

```json
{
    "filters": [{"column": "사업 금액", "op": ">=", "value": 1000000000}],
    "sort": {"column": "사업 금액", "order": "desc"},
    "limit": 10,
    "keyword": "고려대"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `filters` | `list[dict]` | 컬럼별 필터 조건. `op`: `>=`, `<=`, `>`, `<`, `==`, `contains`, `between` |
| `sort` | `dict` | 정렬 기준. `order`: `"asc"` 또는 `"desc"` |
| `limit` | `int` | 반환 행 수 (생략 시 전체 반환) |
| `keyword` | `str` | 사업명/발주기관/사업요약 전체에서 부분 일치 검색 |

모든 필드는 생략 가능하다.

### filter op vs keyword 사용 기준

- 질의가 **특정 컬럼을 지정**하는 경우 → `filters` 사용
  - 숫자/날짜 컬럼: `>=`, `<=`, `>`, `<`, `==`, `between`
  - 문자열 컬럼(사업명, 발주 기관, 사업 요약): `contains` (부분 일치)
- 질의가 **특정 컬럼을 지정하지 않는** 일반 텍스트 검색 → `keyword` 사용

### 금액 변환 규칙

- `"10억"` → `1000000000`
- `"5천만원"` → `50000000`
- `"3,575만원"` → `35750000`
- 단위는 항상 **원(₩)** 기준

## CSV 데이터 사양

- **원본**: `data/data_list.csv` (100행 × 12열, UTF-8 BOM)
- **사업 금액**: 3,575만원 ~ 141.07억원 (1천만원 미만은 NaN 처리, 총 8건 null)
- **발주 기관**: 87개 고유 기관
- **날짜**: `datetime64[ns]`로 변환 (공개 일자, 입찰 참여 시작일, 입찰 참여 마감일)
- **텍스트 열**: 제외 (이미 DB에 chunking 완료)
- **캐시**: `csv_cache.pkl` (CSV 수정 시 자동 재생성)

## RAGState 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `original_query` | `str` | 사용자 원본 질의 (교정 전) **(v2.2 신규)** |
| `query` | `str` | 실제 사용되는 질의 (query_modifier가 교정한 결과 또는 원본) |
| `memory` | `list[dict]` | 이전 대화 로그 (최대 5건, query_modifier가 참조) **(v2.2 신규)** |
| `context` | `list` | 누적된 `(text, metadata)` 튜플 리스트 |
| `last_search_query` | `str \| None` | 이전 검색 쿼리 |
| `search_result` | `list \| None` | 현재 검색 결과 (루프마다 초기화) |
| `can_answer` | `bool` | judge가 판단한 답변 가능 여부 |
| `next_query` | `str` | judge가 생성한 다음 검색 쿼리 |
| `iteration` | `int` | 루프 반복 횟수 (max 6) |
| `use_csv` | `bool` | routing_llm이 설정한 CSV 라우팅 여부 **(v2 신규)** |
| `csv_query` | `dict \| None` | routing_llm이 생성한 구조화 쿼리 **(v2 신규)** |
| `final_answer` | `str` | 최종 답변 |

## 파일 구조

```
hybrid_search_v2.2/
├── app.py                 # Streamlit 채팅 UI + 세션 메모리 (v2.2)
├── csv_preprocessor.py    # CSV 로드/정제/캐싱
├── csv_search.py          # CSV 구조화 검색 노드
├── hybrid_search.py       # Dense + Sparse + RRF (v1 기존)
├── search_graph.py        # 전체 RAG 그래프 (v2)
├── minimum.ipynb          # 대화형 테스트 노트북
├── csv_cache.pkl          # CSV 캐시 (자동 생성)
└── USAGE.md               # 본 문서
```

## 변경 내역

### v2.0 — CSV 구조화 검색 채널 추가

#### 신규 파일
- **`csv_preprocessor.py`**: CSV 전처리 모듈
  - `data/data_list.csv` 로드 → 텍스트 열 제외, 날짜 datetime 변환, 공고차수 Int64 변환
  - 사업 금액 1천만원 미만 → NaN 처리
  - `사업금액_억` 편의 컬럼 추가
  - pickle 캐싱 (CSV mtime 기반 자동 갱신)

- **`csv_search.py`**: CSV 검색 노드
  - routing_llm이 생성한 `csv_query` dict를 받아 DataFrame 연산 수행
  - 필터(`>=`, `<=`, `between` 등), 정렬, 제한, 키워드 검색 지원
  - 반환 형식: `[(사업명, {전체 CSV 컬럼 + uid + source}), ...]`
  - LLM 호출 없음 — 순수 실행 로직

#### 수정 파일
- **`search_graph.py`**:
  - `RAGState`에 `use_csv: bool`, `csv_query: dict | None` 추가
  - `routing_llm_node` 추가: search_query + last_query를 참조하여 CSV/retriever 분류
  - `search_router` 추가: `use_csv` 기반 조건부 분기
  - `context_appender`: source 기반 metadata 키 분기 (`METADATA_KEYS_HYBRID` / `METADATA_KEYS_CSV`)
  - `final_answer`: CSV 결과는 `발주 기관` 기반 출처 표시, hybrid 결과는 기존 `문서명 + 페이지` 표시
  - 그래프: `judge → routing_llm → {csv_search | retriever} → context_appender → judge` 구조
  - `from csv_search import csv_search` 추가

- **`minimum.ipynb`**:
  - Cell 8: `RAGState`에 `use_csv`, `csv_query` 필드 추가
  - Cell 11 (신규): `routing_llm` 노드 (프롬프트 + 체인 + 노드 함수 + search_router)
  - Cell 12: `context_appender`에 source 기반 metadata 키 분기 + source 태깅
  - Cell 13: `final_answer`에 CSV 출처 처리 추가
  - Cell 14 (신규): `csv_search` import
  - Cell 15: 그래프 빌드에 `routing_llm`, `csv_search` 노드 및 조건부 엣지 추가
  - Cell 23-27: CSV 단독 테스트 셀 (4개 테스트 케이스)
  - 모든 테스트 셀에 `use_csv`, `csv_query` 초기값 추가

#### v1 대비 개선 결과

| 질의 | v1 결과 | v2 결과 |
|---|---|---|
| 사업비가 가장 많은 3곳은? | ❌ iteration=7, context=0, 답변 불가 | ✅ 3건 정확 반환 (141억, 112억, 67억) |
| 10억 이상인 사업은? | ❌ 1건만 발견 (고려대) | ✅ 10건 반환 |
| 5억에서 10억 사이 | ❌ 예약발매 역사 등 무관한 결과 | ✅ 10건 정확 반환 (CSV 기반) |
| 고려대학교에서 발주한 프로젝트 | ✅ 정상 | ✅ 정상 (CSV 경유) |

#### 설계 결정 사항
- routing_llm → csv_search는 **Approach B**: LLM이 `csv_query` 파라미터까지 생성, csv_search는 순수 실행
- `source` 필드 (`"csv"` / `"hybrid"`)로 데이터 출처 추적
- `use_csv: bool`을 별도 state 필드로 분리하여 조건부 엣지 감지
- CSV의 `텍스트` 열은 제외 (이미 DB에 chunking 완료)
- 사업 금액 1천만원 미만은 NaN 처리 (의미 없는 0/1 값 방지)
- DataFrame 방식 채택 (SQLite/벡터 DB 불필요 — 정확한 수치 연산 목적)

### v2.1 — Streamlit 채팅 UI + CSV 문자열 검색 개선

#### 신규 파일
- **`app.py`**: Streamlit 채팅 UI
  - `st.chat_input` → `rag_app.invoke()` → `final_answer`만 표시
  - `st.session_state`로 대화 히스토리 유지
  - 오류 발생 시 에러 메시지를 채팅 형식으로 표시
  - `final_answer` 줄바꿈을 Markdown line break(`  \n`)로 변환하여 렌더링

#### 수정 파일
- **`search_graph.py`**:
  - 상대경로 import(`.csv_search`, `.hybrid_search`) → 절대경로 import로 변경
  - routing_prompt: `contains` op 추가, 컬럼 지정 여부에 따른 filter/keyword 분기 안내
- **`csv_search.py`**:
  - 상대경로 import(`.csv_preprocessor`) → 절대경로 import로 변경
  - `_apply_filters`에 `contains` op 추가 (문자열 컬럼 부분 일치)
- **`USAGE.md`**: Streamlit 실행 방법 추가, csv_query 스키마 갱신, 파일 구조 갱신

### v2.2 — 세션 메모리 + Query Modifier

#### 수정 파일
- **`search_graph.py`**:
  - `RAGState`에 `original_query: str`, `memory: list[dict]` 추가
  - `query_modifier_node` 추가: memory 기반 쿼리 교정 (루프 밖, 1회 실행)
    - memory가 비어 있으면 LLM 호출 없이 `original_query`만 설정하고 통과
    - memory가 있으면 LLM이 쿼리의 불완전성을 판단하여 재작성 또는 그대로 반환
    - 판단 기준: 대명사/지시어로 인한 참조 불완전, 주어 누락
    - 재작성이 필요하지만 memory가 없는 경우 그대로 반환 (방어적 처리)
    - memory에서 `query`와 `final_answer`만 LLM에 전달 (context 배열 제외)
  - 그래프 entry point: `judge` → `query_modifier`로 변경
  - `query_modifier → judge` 엣지 추가
- **`app.py`**:
  - `st.session_state.memory`: 최근 5건의 실행 로그를 누적하는 배열
  - 각 로그 항목: `{log_id, query, context, final_answer}`
  - `log_id`는 1부터 단조 증가 (세션 내 고유)
  - 최대 5건 유지 — 초과 시 가장 오래된 로그부터 삭제 (`[-5:]` 슬라이싱)
  - invoke 시 `memory=st.session_state.memory` 전달
  - 쿼리 교정 발생 시 `(쿼리 교정: 원본 → 교정)` 캡션 표시
  - 예외 발생 시에도 `context=[]`로 안전하게 기록
