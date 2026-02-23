# src/graph — LangGraph RAG 파이프라인

## 아키텍처

LangGraph `StateGraph`를 사용한 **선형 4노드** 파이프라인.

```
analyze_query → retrieve → extract_evidence → generate → END
```

## 파일 구성

| 파일 | 역할 | 핵심 클래스/함수 |
|------|------|-----------------|
| `state.py` | 파이프라인 상태 정의 | `RFPState(TypedDict)`, `RetrievedDoc`, `MetadataFilter` |
| `nodes.py` | 4개 노드 함수 | `analyze_query()`, `retrieve()`, `extract_evidence()`, `generate()` |
| `workflow.py` | 그래프 조립 + 컴파일 | `build_graph()` |

## 상태 (RFPState)

`TypedDict(total=False)` — 각 노드는 partial state만 반환.

| 필드 | 타입 | 누적 방식 | 설명 |
|------|------|----------|------|
| `messages` | `list[BaseMessage]` | `add_messages` | 대화 히스토리 |
| `query` | `str` | 덮어쓰기 | 사용자 원본 질의 |
| `query_type` | `str` | 덮어쓰기 | `single_doc / multi_doc / comparison / out_of_scope` |
| `metadata_filter` | `MetadataFilter` | 덮어쓰기 | 검색 필터 조건 |
| `retrieved_docs` | `list[RetrievedDoc]` | `operator.add` | 검색된 문서 |
| `evidence` | `str` | 덮어쓰기 | 추출된 근거 |
| `answer` | `str` | 덮어쓰기 | 최종 답변 |
| `latencies` | `dict` | `merge_dicts` | 노드별 처리시간 |
| `llm_model` | `str` | 덮어쓰기 | UI에서 선택한 LLM 모델 |

## 노드 상세

### 1. `analyze_query`
- LLM에 `QUERY_ANALYSIS_PROMPT`로 질의 분석 요청
- JSON 응답에서 `query_type`, `institution`, `project_name`, `year`, `keywords` 추출
- 사이드바 기존 필터 우선, LLM 분석값은 빈 필드만 보충
- `out_of_scope` 판정 시 이후 검색 스킵

### 2. `retrieve`
- `search_with_metadata()` 호출 (metadata_filter.py)
- `top_k`, `search_type`은 state에서 UI 설정값 참조
- 검색 결과를 `RetrievedDoc` 딕셔너리로 변환
- 상세 verbose 로깅 (source, page, score, snippet)

### 3. `extract_evidence`
- `_filter_docs_by_score()`: score_threshold(0.3) 미만 청크 제거 (폴백: 상위 3개)
- LLM에 `EVIDENCE_EXTRACTION_PROMPT`로 핵심 근거 추출
- 빈 응답 시 원본 청크를 출처 포함하여 폴백

### 4. `generate`
- `out_of_scope` → `OUT_OF_SCOPE_PROMPT`
- 정상 → `RAG_GENERATION_PROMPT` (evidence + chat_history 포함)
- Langfuse 콜백 연동: AICR 점수 + 검색 지표 자동 기록

## 의존 관계

```
nodes.py → prompts/templates.py (4개 프롬프트)
nodes.py → retrievers/metadata_filter.py (search_with_metadata)
nodes.py → evaluation/langfuse_tracer.py (점수 기록)
nodes.py → evaluation/metrics.py (calculate_aicr)
nodes.py → utils/config.py, utils/env.py
workflow.py → nodes.py (4개 노드 함수)
```

## dev-yc 브랜치와의 차이

| 항목 | integration-eval-yc | dev-yc |
|------|---------------------|--------|
| 파이프라인 | LangGraph StateGraph | `RAGChatbotV17` 단일 클래스 |
| LLM 호출 | `ChatOpenAI` (LangChain) | `OpenAI` 직접 호출 |
| 검색 호출 | `search_with_metadata()` | `VectorStore.search()` + `balanced_search()` |
| 상태 관리 | TypedDict + 노드별 partial return | 인스턴스 변수 |
