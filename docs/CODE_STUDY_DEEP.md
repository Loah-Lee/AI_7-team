# 입찰메이트 v17+ 코드 스터디 DEEP

> 대상: 프로젝트를 "동작 원리 + 운영 관점"까지 학습하려는 개발자
> 기준: 현재 워크트리 코드 (작성 시점 2026-02-23)
> 전체 파일 인덱스(프로젝트 전체 코드): `docs/CODE_STUDY_ALL.md`

## 0. 이 문서 사용법

- 목적:
  - 단순 코드 설명이 아니라 "왜 이 함수가 존재하는지"와 "왜 이 값으로 설정했는지"를 실행 관점으로 이해
- 읽기 순서:
  1. `app/main.py` (엔트리)
  2. `src/graph/workflow.py` (오케스트레이션)
  3. `src/retrievers/*`, `src/parsers/*` (핵심 엔진)
  4. `src/evaluation/*`, `scripts/*` (검증/운영)
- 표기:
  - `path:line` 참조는 현재 파일 기준이며, 코드 변경 시 줄 번호는 달라질 수 있음

---

## 1. 프로젝트 구동 전체 흐름

### 1.1 웹앱 실행 경로

1. `streamlit run app/main.py`
2. `app/main.py:127` `get_chatbot()`에서 `RAGChatbotV17` 생성
3. `src/graph/workflow.py:56` `__init__` 실행
4. `src/graph/workflow.py:103` `_load_documents()`로 인덱싱/복원
5. 사용자 질문 입력 시 `app/main.py:271` -> `chatbot.answer()`
6. `src/graph/workflow.py:645`에서 의도 파싱 -> 검색 -> 답변 생성 -> payload 반환
7. `app/main.py:283`에서 답변 렌더 + source badge 표시

### 1.2 CLI/운영 경로

- 재구축: `python3 scripts/rebuild_db.py`
  - `scripts/rebuild_db.py:44`에서 `RAGChatbotV17(...)` 재사용
- 평가: `python3 scripts/eval_retrieval.py`
  - `scripts/eval_retrieval.py:236` `run_evaluation()`
- HTML 리포트: `python3 scripts/build_eval_report.py`
  - `scripts/build_eval_report.py:510` `build_html_report()`

---

## 2. 설정/환경 DEEP (`config`, `.env`, `requirements`)

## 2.1 `src/utils/config.py` 핵심 값 해설

| 위치 | 항목 | 이유 | 부작용 |
|---|---|---|---|
| `src/utils/config.py:15` | `OPENAI_API_KEY` | OpenAI 경로 on/off 분기 키 | 키 없으면 local fallback 필요 |
| `src/utils/config.py:16` | `EMBEDDING_MODEL=text-embedding-3-small` | 1536차원 + 비용 균형 | 모델 변경 시 기존 벡터와 호환성 이슈 |
| `src/utils/config.py:17-18` | `DEFAULT_MODEL`, `REASONING_MODEL` | 기본/추론 모델 분리 가능 구조 | 둘을 다르게 두면 응답 성향 차이 발생 |
| `src/utils/config.py:74` | `MAX_PAGES=120` | 파서 비용 제한 + 대부분 문서 커버 | 긴 문서 말미 근거 누락 가능 |
| `src/utils/config.py:81` | `RETRIEVAL_EXPANSION_CAP=3` | 질의 확장 호출 상한 | 너무 낮으면 recall 하락 |
| `src/utils/config.py:82` | `RETRIEVAL_SEARCH_PASSES=1` | 기본 패스 최소화로 속도 확보 | 난질의에서 검색 부족 가능 |
| `src/utils/config.py:83-85` | `HIGH_RECALL_K_MULTIPLIER=0.8` | 어려운 질의에서 `k`를 동적 확대 | 과확대 시 지연 증가 |
| `src/utils/config.py:86` | `CONTEXT_TOP_RESULTS=6` | 근거 다양성/토큰 균형 | 너무 높이면 장문 컨텍스트로 품질 저하 가능 |
| `src/utils/config.py:87` | `CONTEXT_MAX_CHARS=700` | 문서당 컨텍스트 길이 제한 | 너무 낮으면 핵심 근거 잘림 |
| `src/utils/config.py:88` | `RETRIEVAL_MAX_HYBRID_CALLS=6` | 하이브리드 호출 예산화 | 예산 소진 시 추가 검색 못함 |
| `src/utils/config.py:89` | `KEYWORD_SCAN_LIMIT=1200` | 키워드 보조 검색 폭 제어 | 낮으면 precision 질의 miss 증가 |
| `src/utils/config.py:90` | `INTENT_REGEX_FIRST=true` | 빠른 질의는 regex로 비용/속도 절감 | 복잡 질의 오분류 가능 |
| `src/utils/config.py:92` | `ANSWER_QUALITY_MODE=balanced` | 운영 모드를 `balanced/accurate`로 분리 | 정확도 우선 모드에서 지연/recall 트레이드오프 발생 |
| `src/utils/config.py:126-135` | `get_default_db_path()` | 스키마/페이지/include 패턴별 DB 분리 | 설정 바꾸면 DB 경로가 달라져 재인덱싱 필요 |

## 2.2 `.env.example`와 런타임 연결

- `.env.example:4-7` 모델/키 기본값 -> `src/utils/config.py:15-18`에서 로드
- `.env.example:35-43` 튜닝값 -> `workflow.py` 검색/컨텍스트 로직에 직접 반영
- `.env.example:13-15` LangSmith -> `app/main.py:31-36`, `workflow.py:39-47`, `scripts/eval_retrieval.py:385-388`

## 2.3 `requirements.txt`에서 구동상 필수 의존성

- `requirements.txt:4-6` LangChain + OpenAI 래퍼 + LangSmith
- `requirements.txt:12` ChromaDB
- `requirements.txt:15-17` PDF/HWP fallback 처리 핵심
- `requirements.txt:23` Streamlit UI
- `requirements.txt:26` sentence-transformers (OpenAI 없는 환경 fallback)

---

## 3. 상태 계약 DEEP (`state.py`)

| 위치 | 요소 | 왜 필요한가 |
|---|---|---|
| `src/graph/state.py:15` `OrgInfo` | 기관별 정렬/랭킹/메타 표시의 최소 단위 |
| `src/graph/state.py:29` `MarkdownData` | CSV/원문 파서 출력 통일 |
| `src/graph/state.py:43` `QueryIntent` | 의도 파싱 결과 표준 구조 |
| `src/graph/state.py:57` `QuestionPlan` | 질의별 필수 슬롯 정의(품질 측정 기반) |
| `src/graph/state.py:66` `EvidenceSpan` | 근거 추적(출처/페이지/스니펫) |
| `src/graph/state.py:76` `AnswerDraft` | answer_mode/신뢰도/slot_fill 통합 |
| `src/graph/state.py:89` `ConversationContext` | 후속질문 컨텍스트 유지 |
| `src/graph/state.py:92` `max_history=5` | 대화 품질과 토큰 비용의 타협값 |

---

## 4. 질의 파싱/플래닝 DEEP (`nodes.py`)

### 4.1 QueryIntentParser

| 위치 | 함수 | 존재 이유 | 값/조건 이유 |
|---|---|---|---|
| `src/graph/nodes.py:35` | `parse()` | regex/LLM 하이브리드 의도 파싱 | `INTENT_REGEX_FIRST`로 운영 모드 전환 |
| `src/graph/nodes.py:43` | regex confidence `>=0.75` | 고신뢰 규칙 결과를 빠르게 채택 | 불필요한 LLM 호출 절감 |
| `src/graph/nodes.py:54` | LLM 저신뢰 임계 `0.7` | LLM 응답 품질 낮을 때 regex 보정 | 안정성 확보 |
| `src/graph/nodes.py:60` | `_parse_with_llm()` | 복잡 질의의 자연어 의도 추출 | JSON only 지시로 파싱 안정화 |
| `src/graph/nodes.py:88` | `_parse_with_regex()` | 비용/속도 유리한 기본 분기 | ranking/filter/category 고빈도 패턴 우선 |
| `src/graph/nodes.py:141` | `_extract_org_from_query()` | VectorStore 없어도 기관 후보 추출 | alias + 패턴 병행 |

### 4.2 QuestionPlanner

| 위치 | 함수 | 존재 이유 |
|---|---|---|
| `src/graph/nodes.py:178` `build()` | 질문을 `comparison/owner/deadline/fact_numeric/multi_doc/single_doc`로 구조화해 필수 슬롯을 지정 |

핵심:
- 의도(`QueryIntent`)와 계획(`QuestionPlan`)을 분리해, "무슨 질문인가"와 "답변 완성 기준이 뭔가"를 따로 다룸

### 4.3 AnswerGenerator

| 위치 | 함수 | 존재 이유 |
|---|---|---|
| `src/graph/nodes.py:236` `generate()` | LLM 호출과 프롬프트 조합을 workflow와 분리 |
| `src/graph/nodes.py:262` `_clean_final_answer()` | 모델이 붙이는 태그 정리 |
| `src/graph/nodes.py:270` `_token_limit_arg()` | GPT-5와 타모델 API 파라미터 호환 |
| `src/graph/nodes.py:278` `_is_gpt5_model()` | 모델 분기 유틸 |

---

## 5. 오케스트레이션 DEEP (`workflow.py`)

## 5.1 클래스 목적

- `src/graph/workflow.py:53` `RAGChatbotV17`:
  - 문서 로딩
  - 검색
  - 답변 생성
  - 후처리
  - 성능 계측
  을 하나의 트랜잭션으로 관리

## 5.2 초기화/인덱싱 함수 인덱스

| 위치 | 함수 |
|---|---|
| `src/graph/workflow.py:56` | `__init__` |
| `src/graph/workflow.py:103` | `_load_documents` |
| `src/graph/workflow.py:129` | `_load_csv_files` |
| `src/graph/workflow.py:163` | `_index_csv_metadata` |
| `src/graph/workflow.py:188` | `_lookup_csv_metadata` |
| `src/graph/workflow.py:203` | `_register_csv_orgs` |
| `src/graph/workflow.py:209` | `_add_csv_chunks` |
| `src/graph/workflow.py:249` | `_hydrate_org_registry_from_existing_chunks` |
| `src/graph/workflow.py:274` | `_split_text_for_retrieval` |
| `src/graph/workflow.py:291` | `_persist_unified_markdown` |
| `src/graph/workflow.py:339` | `_create_org_info_from_markdown` |
| `src/graph/workflow.py:354` | `_list_document_files` |
| `src/graph/workflow.py:377` | `_build_file_signature` |
| `src/graph/workflow.py:388` | `_load_failed_sources_registry` |
| `src/graph/workflow.py:433` | `_save_failed_sources_registry` |
| `src/graph/workflow.py:449` | `_is_source_in_failed_registry` |
| `src/graph/workflow.py:467` | `_mark_source_failed` |
| `src/graph/workflow.py:480` | `_clear_source_failed` |
| `src/graph/workflow.py:486` | `_has_unindexed_document_files` |
| `src/graph/workflow.py:500` | `_load_document_files` |

### 5.2.1 왜 중요한가

- 이 구간이 있어야 앱 재시작 시 "이미 처리한 파일 재변환"을 피하고, 실패 파일을 영구 스킵하여 운영 안정성을 확보
- `source signature(size,mtime)` 방식(`workflow.py:377-386`)은 파일이 바뀌면 자동 재시도되도록 설계

## 5.3 질의 처리 메인 함수들

| 위치 | 함수 | 핵심 이유 |
|---|---|---|
| `src/graph/workflow.py:645` | `answer()` | 모든 질의의 트랜잭션 루프(의도->검색->답변) |
| `src/graph/workflow.py:775` | `_log_perf_stats()` | 실험 모드에서 병목 파악 |
| `src/graph/workflow.py:791` | `_answer_with_results()` | 비교/추출/생성 분기 중앙화 |
| `src/graph/workflow.py:912` | `_build_non_llm_answer()` | 사실형 질의의 추출 우선 응답 |
| `src/graph/workflow.py:989` | `_format_first_source()` | 근거 출처 문자열 표준화 |
| `src/graph/workflow.py:998` | `_pick_slot_for_evidence()` | EvidenceSpan의 슬롯 태깅 |
| `src/graph/workflow.py:1011` | `_build_evidence_spans()` | evidence payload 생성 |
| `src/graph/workflow.py:1046` | `_should_try_extractive_first()` | 어떤 질의를 추출 우선할지 결정 |
| `src/graph/workflow.py:1064` | `_has_comparison_structure()` | 비교 답변 템플릿 검사 |
| `src/graph/workflow.py:1069` | `_enforce_comparison_template()` | 비교 형식 강제 |
| `src/graph/workflow.py:1080` | `_build_comparison_answer_from_results()` | 비교형 비LLM fallback 구성 |
| `src/graph/workflow.py:1171` | `_build_answer_payload()` | 최종 응답 스키마 표준화 |
| `src/graph/workflow.py:1210` | `_format_answer_for_readability()` | 섹션 제목/출처 bullet 정규화 |
| `src/graph/workflow.py:1244` | `_estimate_slot_fill_rate()` | 답변 완성도 정량화 |
| `src/graph/workflow.py:1293` | `_estimate_confidence()` | 근거 기반 신뢰 점수 |

## 5.4 검색/재랭크 함수들

| 위치 | 함수 |
|---|---|
| `src/graph/workflow.py:1307` `_extract_evidence_lines` |
| `src/graph/workflow.py:1378` `_normalize_text_for_match` |
| `src/graph/workflow.py:1383` `_is_noise_line` |
| `src/graph/workflow.py:1434` `_extract_query_keywords` |
| `src/graph/workflow.py:1490` `_extract_direct_fact_from_results` |
| `src/graph/workflow.py:1921` `_looks_uncertain_answer` |
| `src/graph/workflow.py:1937` `_infer_responsibility_owner` |
| `src/graph/workflow.py:1948` `_expand_query_terms` |
| `src/graph/workflow.py:2000` `_resolve_expansion_cap` |
| `src/graph/workflow.py:2015` `_has_source_diversity` |
| `src/graph/workflow.py:2032` `_has_comparison_coverage` |
| `src/graph/workflow.py:2060` `_should_stop_retrieval_early` |
| `src/graph/workflow.py:2090` `_should_run_combined_fallback` |
| `src/graph/workflow.py:2106` `_consume_hybrid_budget` |
| `src/graph/workflow.py:2117` `_record_hybrid_call_stats` |
| `src/graph/workflow.py:2126` `_run_retrieval_call` |
| `src/graph/workflow.py:2153` `_retrieve_results` |
| `src/graph/workflow.py:2276` `_diversify_comparison_results` |
| `src/graph/workflow.py:2323` `_rerank_results` |
| `src/graph/workflow.py:2342` `_score_result` |
| `src/graph/workflow.py:2438` `_result_key` |
| `src/graph/workflow.py:2448` `_merge_results` |
| `src/graph/workflow.py:2468` `_needs_original_priority` |
| `src/graph/workflow.py:2479` `_is_comparison_query` |
| `src/graph/workflow.py:2485` `_should_fallback_to_original` |
| `src/graph/workflow.py:2497` `_build_context` |
| `src/graph/workflow.py:2527` `_extract_relevant_excerpt` |
| `src/graph/workflow.py:2567` `_infer_source_type` |
| `src/graph/workflow.py:2574` `_handle_ranking_query` |
| `src/graph/workflow.py:2638` `_org_names_loosely_match` |
| `src/graph/workflow.py:2647` `_resolve_known_org_name` |
| `src/graph/workflow.py:2671` `_ensure_org_coverage` |
| `src/graph/workflow.py:2718` `_extract_org_names_from_query` |
| `src/graph/workflow.py:2780` `_extract_org_name_from_query` |
| `src/graph/workflow.py:2785` `_create_multi_org_summary` |
| `src/graph/workflow.py:2816` `main` |

### 5.4.1 핵심 파라미터가 함수에 반영되는 지점

- `RETRIEVAL_EXPANSION_CAP` -> `workflow.py:2000`
- `RETRIEVAL_MAX_HYBRID_CALLS` -> `workflow.py:2106`
- `CONTEXT_TOP_RESULTS`, `CONTEXT_MAX_CHARS` -> `workflow.py:2505-2507`
- `KEYWORD_SCAN_LIMIT`는 `vectorstore.py:232`에서 반영
- `CSV_SHORTCIRCUIT_ENABLED` -> `workflow.py:233`
- `HYBRID_LEXICAL_PREFILTER_K`, `HYBRID_LEXICAL_MIN_HITS`, `HYBRID_RERANK_TOP_MULTIPLIER` -> `vectorstore.py:295`

### 5.5 2026-02-23 정확도 보호 패치(기관 고정 + 사업비 보정)

핵심 변경:
- 단일 기관 질의는 전역 fallback 후에도 기관 필터를 재적용한다.
- 미등록 기관 질의는 애매한 추정 대신 명시적 `not found` payload로 종료한다.
- 사업비 질의는 전용 판별/근거 체크/재랭크 규칙을 사용해 시간 수치 오탐(`60분`)을 방지한다.

주요 코드 지점:
- 질의 초반 기관 정규화/가드: `workflow.py:670-705`
- fallback 후 기관 필터 강제: `workflow.py:771-776`
- 사업비 전용 사실 추출 경로: `workflow.py:1512-1803`
- 사업비 질의 확장어 추가: `workflow.py:2045-2046`
- 사업비 근거 기반 early-stop 제어: `workflow.py:2163-2170`
- 사업비 재랭크 가중치/패널티: `workflow.py:2489-2506`
- 사업비 판별/근거 함수: `workflow.py:2588-2608`
- 기관 필터 유틸/실패 payload: `workflow.py:2779-2804`

### 5.6 2026-02-23 2차 패치(CSV fast-path + lexical->vector hybrid)

핵심 변경:
- `answer()`에서 의도 파악 직후 CSV 단축 경로를 먼저 시도한다.
- 단축은 구조화 필드 질의에만 허용하고, 비교/다문서/요구사항 코드 질의는 강제 차단한다.
- 하이브리드 검색은 `렉시컬 후보 축소 -> 벡터 재정렬 -> semantic fallback`으로 전환했다.

주요 코드 지점:
- CSV 단축 대상 판별: `workflow.py:233`
- CSV 단축 payload 생성: `workflow.py:365`
- CSV fast-path 실행: `workflow.py:417`
- `answer()` fast-path 연결: `workflow.py:965`
- perf 로그 카운터(`csv_short_circuit_hit`): `workflow.py:889`, `workflow.py:1086`
- 하이브리드 엔진 본체: `vectorstore.py:295`
- 렉시컬 후보 검색: `vectorstore.py:215`
- 벡터 재정렬: `vectorstore.py:458`
- 후보 임베딩 재조회: `vectorstore.py:432`

### 5.7 2026-02-23 3차 패치(정확도 우선 모드 + 정밀 사실/비교 커버리지 강화)

핵심 변경:
- `ANSWER_QUALITY_MODE`로 정확도 우선 모드를 토글하고 검색/후처리 강도를 분리한다.
- 정밀 사실 질의(`용량/단위/문자셋/복구기한/요구사항 코드`)는 앵커 근거 검증을 통과해야만 직접 추출 응답을 허용한다.
- 비교 질의에서 기관명 추출 실패 시 프로젝트 힌트(따옴표/괄호/구문 패턴)로 기관 후보를 복원하고 기관별 커버리지를 강제 보완한다.

주요 코드 지점:
- 정확도 모드 판별: `workflow.py:3361-3367`
- 정밀 사실 질의/앵커 검증: `workflow.py:3367-3431`
- 사실 추출 분기 강화(UTF/용량/단위수량/복구기한/가이드/핵심투입인력): `workflow.py:2006-2683`
- 비교 커버리지 가드: `workflow.py:2801-2868`
- 프로젝트 힌트 추출: `workflow.py:3710-3739`
- 기관별 커버리지 보정: `workflow.py:3741-3803`
- 기관명 추출 보강(법인 표기/프로젝트 fallback): `workflow.py:3805-3895`
- 회귀 테스트: `tests/test_workflow_fact_and_org.py`

---

## 6. 벡터 저장소 DEEP (`vectorstore.py`, `embeddings.py`)

### 6.1 `src/retrievers/embeddings.py`

| 위치 | 함수 | 이유 |
|---|---|---|
| `src/retrievers/embeddings.py:22` `__init__` | OpenAI/로컬 임베딩 경로 선택 |
| `src/retrievers/embeddings.py:29` `FORCE_LOCAL_EMBEDDINGS` | 운영중 강제 로컬 테스트 지원 |
| `src/retrievers/embeddings.py:35` `_init_local_model` | sentence-transformers fallback |
| `src/retrievers/embeddings.py:43` `embed_texts` | 통합 임베딩 진입점 |
| `src/retrievers/embeddings.py:71` `_embed_with_openai` | 원격 임베딩 + 배치 호출 |
| `src/retrievers/embeddings.py:85` `batch_size=64` | 요청 안정성과 처리량 균형 |
| `src/retrievers/embeddings.py:95` `_embed_with_local` | API 장애/무키 환경 생존 경로 |
| `src/retrievers/embeddings.py:111` `dimension` | backend별 벡터 차원 확인 |

### 6.2 `src/retrievers/vectorstore.py`

| 위치 | 함수 | 이유 |
|---|---|---|
| `src/retrievers/vectorstore.py:29` `__init__` | DB 초기화 + 컬렉션 로딩 + 변환기 결합 |
| `src/retrievers/vectorstore.py:37` `collection_name` backend 포함 | 임베딩 백엔드 혼용 충돌 방지 |
| `src/retrievers/vectorstore.py:39-42` Chroma collection | cosine 공간 고정 |
| `src/retrievers/vectorstore.py:67` `add_documents` | upsert 기반 안정 인덱싱 |
| `src/retrievers/vectorstore.py:104` `_clip_for_embedding(2500)` | 임베딩 입력 길이 안전컷 |
| `src/retrievers/vectorstore.py:112` `_build_chunk_id` | source/page/text 해시로 안정적인 중복 제어 |
| `src/retrievers/vectorstore.py:131` `register_org` | 기관 메타 병합 로직 진입점 |
| `src/retrievers/vectorstore.py:142` `_update_org_fields` | 기존 값 보존 + 더 좋은 값 업데이트 |
| `src/retrievers/vectorstore.py:168` `search` | 순수 벡터 검색 |
| `src/retrievers/vectorstore.py:215` `search_keyword` | 렉시컬 prefilter 후보(`id`, `lexical_score`) 생성 |
| `src/retrievers/vectorstore.py:295` `search_hybrid` | lexical prefilter -> vector rerank -> semantic fallback |
| `src/retrievers/vectorstore.py:374` `_build_where_filter` | org/doc_type 필터를 모든 단계에서 공통 적용 |
| `src/retrievers/vectorstore.py:401` `_merge_dedup_results` | 결과 병합 시 dedup key 유지 |
| `src/retrievers/vectorstore.py:432` `_fetch_candidates_by_ids` | 후보 ID 기반 임베딩 조회 |
| `src/retrievers/vectorstore.py:458` `_rerank_lexical_candidates` | 질의 유형별 lexical/vector 가중치로 재정렬 |
| `src/retrievers/vectorstore.py:524` `count_chunks_by_type` | csv/pdf/hwp 인덱싱 상태 점검 |
| `src/retrievers/vectorstore.py:535` `get_indexed_sources` | 증분 인덱싱 스킵 기준 |
| `src/retrievers/vectorstore.py:558` `collect_org_stats` | 기존 컬렉션에서 org_registry 복원 |
| `src/retrievers/vectorstore.py:581` `_parse_search_results` | Chroma 응답을 앱 공통 포맷으로 정규화 |
| `src/retrievers/vectorstore.py:600` `get_ranking` | 랭킹 계산 |
| `src/retrievers/vectorstore.py:610` `normalize_org_name` | alias 정규화 |

---

## 7. 파서 계층 DEEP

### 7.1 `src/parsers/csv_loader.py`

함수 목록 및 이유:

- `extract_org_name`(`csv_loader.py:23`): 파일명 기반 기관 추출
- `split_markdown_sections`(`csv_loader.py:31`): 섹션 단위 인덱싱 준비
- `filter_valid_sections`(`csv_loader.py:36`): 짧은 노이즈 섹션 제거
- `convert_row`(`csv_loader.py:40`): CSV row -> `MarkdownData` 표준 구조
- `convert_file`(`csv_loader.py:99`): 파일 전체 변환 + 행별 예외 처리
- `_format_date`(`csv_loader.py:124`): 날짜 단순화
- `_format_summary`(`csv_loader.py:131`): 요약 불릿 구조 보정
- `_format_amount_value`(`csv_loader.py:140`): 금액 표시 포맷 정규화
- `_truncate_text`(`csv_loader.py:153`): 과도한 원문 길이 제한

### 7.2 `src/parsers/pdf_loader.py`

- `extract_org_name`(`pdf_loader.py:21`): 파일명 기관 추출
- `split_markdown_sections`(`pdf_loader.py:29`), `filter_valid_sections`(`pdf_loader.py:34`): 섹션 청킹 지원
- `_sanitize_cell`(`pdf_loader.py:39`): 표 셀 텍스트 정규화
- `_table_to_markdown`(`pdf_loader.py:46`): 표를 LLM 친화 텍스트로 변환
- `extract_pages`(`pdf_loader.py:74`): 페이지/표 단위 추출 핵심
- `convert`(`pdf_loader.py:121`): 마크다운 문서 생성

### 7.3 `src/parsers/hwp_loader.py`

핵심 함수별 존재 이유:

- 변환기 탐색
  - `_find_hwp5txt`(`hwp_loader.py:38`)
  - `_find_hwp5html`(`hwp_loader.py:57`)
  - `_find_libreoffice`(`hwp_loader.py:87`)
  - 목적: 환경별 실행 파일 위치 차이 흡수
- 변환/품질
  - `_convert_with_libreoffice`(`hwp_loader.py:115`)
  - `_is_pdf_quality_acceptable`(`hwp_loader.py:289`)
  - `convert_to_pdf`(`hwp_loader.py:308`)
  - 목적: "변환 성공"이 아니라 "검색 가능한 품질" 보장
- fallback 렌더
  - `_choose_reportlab_font`(`hwp_loader.py:159`)
  - `_wrap_text_line`(`hwp_loader.py:187`)
  - `_render_text_pages_to_pdf`(`hwp_loader.py:213`)
  - `_build_pdf_from_hwp_text`(`hwp_loader.py:267`)
  - 목적: LibreOffice 실패 시에도 최소 텍스트 기반 PDF 확보
- 추출
  - `_extract_with_hwp5txt`(`hwp_loader.py:378`)
  - `_extract_with_hwp5html`(`hwp_loader.py:400`)
  - `extract_pages`(`hwp_loader.py:437`)
  - 목적: HTML 추출 우선, 실패 시 PDF 경유 fallback
- 기타
  - `convert`(`hwp_loader.py:468`)
  - `_extract_fallback`(`hwp_loader.py:501`)
  - `extract_org_name`(`hwp_loader.py:548`)
  - `split_markdown_sections`(`hwp_loader.py:556`)
  - `filter_valid_sections`(`hwp_loader.py:561`)

### 7.4 `src/parsers/preprocessor.py`

- `UnifiedCorpusPreprocessor.__init__`(`preprocessor.py:19`): 입출력 디렉터리/변환기 구성
- `build`(`preprocessor.py:30`): 전체 통합 코퍼스 생성 진입점
- `_find_csv_path`(`preprocessor.py:58`): CSV 자동 탐색
- `_resolve_source_file`(`preprocessor.py:66`): CSV 행과 원본 파일 연결
- `_safe_name`(`preprocessor.py:80`): 안전 파일명 생성
- `_build_record`(`preprocessor.py:84`): 행 단위 매니페스트 레코드 생성
- `_build_unified_markdown`(`preprocessor.py:132`): CSV 메타 + 원문 내용 통합 문서 생성

### 7.5 보조 파서

- `src/parsers/chunker.py`
  - `Chunk`(`chunker.py:17`), `MarkdownChunker`(`chunker.py:52`)
  - 목적: 섹션/길이 기준 청킹 전략 캡슐화
- `src/parsers/text_cleaner.py`
  - `TextCleaner`(`text_cleaner.py:14`)
  - 목적: 공백/특수문자/문장/키워드 추출 보조

---

## 8. 프롬프트 DEEP (`templates.py`)

- `MARKDOWN_TEMPLATE`(`templates.py:10`)
  - CSV를 문서 검색 가능한 표준 텍스트로 변환
- `RFP_SYSTEM_PROMPT`(`templates.py:37`)
  - 환각 억제 + 사실형/책임형/비교형 출력 규칙 고정
- `ANSWER_GENERATION_PROMPT`(`templates.py:81`)
  - 최종 섹션 포맷(핵심/근거/출처) 유도
- `INTENT_ANALYSIS_PROMPT`(`templates.py:116`)
  - JSON 스키마 강제 + 금액 단위 변환 규칙 제공

핵심 설계 포인트:
- 프롬프트에서 형식을 미리 강제하고,
- `workflow.py:1210`에서 2차 정규화하여,
- 모델 편차를 이중으로 흡수한다.

---

## 9. 앱/UI DEEP (`app/main.py`)

| 위치 | 함수 | 이유 |
|---|---|---|
| `app/main.py:127` `get_chatbot()` | `st.cache_resource`로 무거운 초기화 재사용 |
| `app/main.py:146` `render_answer()` | 마크다운 + source badge 분리 렌더 |
| `app/main.py:154` `render_metric_card()` | UI 카드 공통 컴포넌트 |
| `app/main.py:189` `render_sidebar()` | 빠른질문/기관통계 제공 |
| `app/main.py:243` `render_header()` | 상단 브랜딩 렌더 |
| `app/main.py:252` `render_metrics()` | 인덱싱 상태 가시화 |
| `app/main.py:271` `process_user_query()` | 사용자 입력 처리 트랜잭션 |
| `app/main.py:300` `main()` | 페이지 조립 + 상태 관리 |

UI 값 설계:
- `layout="wide"`(`main.py:46`): 문서형 답변 가독성 확보
- source 배지(`main.py:139-143`): CSV/PDF/HWP 출처 즉시 인지

---

## 10. 평가 모듈 DEEP

### 10.1 `src/evaluation/metrics.py`

함수별 목적:
- `_normalize_source_name`(`metrics.py:16`): source 문자열 정규화
- `_is_same_source`(`metrics.py:23`): 완전일치+포함관계 허용 매칭
- `_is_same_page`(`metrics.py:35`): ±1 page 허용
- `calculate_recall_at_k`(`metrics.py:129`), `calculate_mrr`(`metrics.py:157`): 검색 품질 핵심 지표

### 10.2 `src/evaluation/llm_judge.py`

- `_parse_judge_response`(`llm_judge.py:81`): 코드블록/타입 변형 대응
- `judge_rag_response`(`llm_judge.py:120`): 모델 호출, 길이 제한, 재시도 처리
- GPT-5 분기(`llm_judge.py:166-170`): 토큰 파라미터 호환

### 10.3 트레이싱

- `setup_langsmith_tracing`(`langsmith_tracer.py:10`)
- `get_langfuse_client`(`langfuse_tracer.py:19`)
- `log_score`(`langfuse_tracer.py:52`)
- `log_retrieval_metrics`(`langfuse_tracer.py:78`)

---

## 11. 운영 스크립트 DEEP

### 11.1 `scripts/rebuild_db.py`

- `main`(`rebuild_db.py:21`): 안전 삭제 확인 후 재구축
- 핵심: `get_default_db_path`를 그대로 사용(`rebuild_db.py:23`)

### 11.2 `scripts/build_unified_corpus.py`

- `main`(`build_unified_corpus.py:16`): 통합 전처리 CLI 엔트리

### 11.3 `scripts/preprocess_hwp_pdf.py`

- `collect_hwp_files`(`preprocess_hwp_pdf.py:18`)
- `main`(`preprocess_hwp_pdf.py:24`): HWP 변환 품질 매니페스트 생성

### 11.4 `scripts/eval_retrieval.py`

핵심 함수:
- 데이터셋 로드/슬라이스: `load_eval_dataset(58)`, `filter_dataset(68)`
- retrieval 결과 정규화: `_normalize_retrieved_docs(89)`
- 지표 계산: `calculate_retrieval_metrics(129)`
- judge 평가: `evaluate_with_llm_judge(194)`
- 전체 실행: `run_evaluation(236)`, `main(362)`

### 11.5 `scripts/build_eval_report.py`

- 색상 계산: `get_score_color(448)`
- 결과 카드: `build_result_card(466)`
- HTML 조립: `build_html_report(510)`
- 엔트리: `main(564)`

---

## 12. 튜닝 실전 가이드 (값 변경 -> 어떤 함수가 바뀌나)

| 변경값 | 직접 영향 함수 |
|---|---|
| `INTENT_REGEX_FIRST` | `src/graph/nodes.py:35-59` |
| `RETRIEVAL_MAX_HYBRID_CALLS` | `src/graph/workflow.py:2106-2145` |
| `RETRIEVAL_EXPANSION_CAP` | `src/graph/workflow.py:1948-2013` |
| `CONTEXT_TOP_RESULTS`, `CONTEXT_MAX_CHARS` | `src/graph/workflow.py:2497-2525` |
| `KEYWORD_SCAN_LIMIT` | `src/retrievers/vectorstore.py:228-233` |
| `MAX_PAGES` | `src/parsers/pdf_loader.py:83-89`, `src/parsers/hwp_loader.py:444-445` |

---

## 13. 디버깅 체크리스트 (실무형)

1. 답변이 느릴 때
- `DEBUG_RETRIEVAL_TIMING=true` 설정
- `workflow.py:775` 로그에서 `hybrid_calls`, `llm_calls`, `budget_exhausted` 확인

2. 답변이 근거 없이 두루뭉술할 때
- `workflow.py:1046` 추출우선 조건 충족 여부 확인
- `workflow.py:1210` 출력 정규화 후 출처 섹션 보정 여부 확인

3. HWP가 비어서 들어올 때
- `hwp_loader.py:289` 품질 판정으로 fallback 탔는지 확인
- `preprocess_hwp_pdf.py` 매니페스트에서 `pdf_generation_mode` 점검

4. 재실행마다 인덱싱을 다시 할 때
- `workflow.py:486` 미인덱싱 판정
- `vectorstore.py:349` indexed sources 집합 확인
- `workflow.py:449` 실패 레지스트리 시그니처 갱신 여부 확인

---

## 14. 실습 과제 (DEEP)

1. `INTENT_REGEX_FIRST`를 `false`로 바꾼 뒤 응답시간/정확도 비교
2. `RETRIEVAL_MAX_HYBRID_CALLS=2/6/10` 실험으로 latency-recall 곡선 작성
3. `CONTEXT_MAX_CHARS=500/700/1200`에서 judge 점수 변동 확인
4. HWP 실패 파일 1개를 수정해 시그니처 변경 후 재처리 동작 검증

---

## 15. 구동 필수 파일 전체 카탈로그 (최종)

- 엔트리/UI: `app/main.py`
- 코어: `src/graph/workflow.py`, `src/graph/nodes.py`, `src/graph/state.py`
- 설정/유틸: `src/utils/config.py`, `src/utils/helpers.py`
- 검색: `src/retrievers/vectorstore.py`, `src/retrievers/embeddings.py`, `src/retrievers/metadata_filter.py`
- 파서: `src/parsers/csv_loader.py`, `src/parsers/pdf_loader.py`, `src/parsers/hwp_loader.py`, `src/parsers/preprocessor.py`, `src/parsers/chunker.py`, `src/parsers/text_cleaner.py`
- 프롬프트: `src/prompts/templates.py`
- 평가: `src/evaluation/metrics.py`, `src/evaluation/llm_judge.py`, `src/evaluation/langsmith_tracer.py`, `src/evaluation/langfuse_tracer.py`
- 운영 스크립트: `scripts/rebuild_db.py`, `scripts/build_unified_corpus.py`, `scripts/preprocess_hwp_pdf.py`, `scripts/eval_retrieval.py`, `scripts/build_eval_report.py`
- 환경: `.env.example`, `requirements.txt`

---

## 16. 한 줄 요약

이 프로젝트는 LLM 자체보다, `workflow.py` 중심의 운영 설계(증분 인덱싱, 검색 예산화, 규칙 기반 추출, 출력 정규화)가 품질/속도를 만든다.
