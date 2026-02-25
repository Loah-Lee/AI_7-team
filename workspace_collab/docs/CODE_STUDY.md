# CODE_STUDY

현재 협업 코드(`workspace_collab`)를 빠르게 따라가기 위한 파일 순서입니다.

## 1) 앱 엔트리

- `app/main.py`
- 질문 입력/버튼 처리, 챗봇 캐시, 응답 렌더링

## 2) 핵심 워크플로우

- `src/graph/workflow.py`
- `RAGChatbotV17.answer()`를 먼저 읽으면 전체 흐름을 파악하기 쉽습니다.

핵심 메서드:

- `_try_csv_short_circuit`
- `_try_org_overview_short_circuit`
- `_run_retrieval_call`
- `_retrieve_results`
- `_answer_with_results`

## 3) 노드/플래너

- `src/graph/nodes.py`
- 질문 타입 분류(regex + LLM fallback), 질문 플래너, 생성기

## 4) 검색 계층

- `src/retrievers/vectorstore.py`
- Chroma 검색, org 레지스트리, 하이브리드 검색 보조 로직

## 5) 상태 타입

- `src/graph/state.py`
- `QueryIntent`, `QuestionPlan`, `OrgInfo`, `ConversationContext`

## 6) 프롬프트

- `src/prompts/templates.py`
- 의도 분석/최종 답변 생성 프롬프트

## 7) 추천 디버깅 순서

1. `DEBUG_RETRIEVAL_TIMING=true`로 단계별 시간 확인
2. `answer_mode`가 `extractive`/`generative` 중 무엇인지 확인
3. 후속질문 시 `last_org` 문맥이 유지되는지 확인

