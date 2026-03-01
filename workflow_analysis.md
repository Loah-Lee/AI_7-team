# 입찰메이트 앱 워크플로우 분석

사용자가 `app/main.py`를 통해 임의의 쿼리를 입력하여 답변을 받기까지의 처리 흐름을 단계별, 경우의 수별로 정리한 문서입니다. 메인 로직은 `src/graph/workflow.py`의 `RAGChatbotV17.answer` 메서드에 위치합니다.

---

## 1. 진입점 (UI ➔ 라우팅)
- **경로**: `app/main.py` ➔ `run_query(chatbot, query)`
- **동작 방식**:
  1. Streamlit UI 텍스트 인풋에서 `query` 문자열을 받습니다.
  2. 캐싱된 `chatbot` 인스턴스(즉, `RAGChatbotV17`)의 `answer` 메서드를 호출하여 답변을 요청합니다. (`top_k=10` 전달)

---

## 2. 핵심 로직 (RAGChatbotV17.answer 구조)
- **경로**: `src/graph/workflow.py` ➔ `RAGChatbotV17.answer`
- 여기에서 질문(query)의 의도에 따라 다음과 같은 분기를 거치게 됩니다.

### 2.1. 질문 의도 파악 (Intent Parsing)
- **경로**: `src/graph/nodes.py` ➔ `QueryIntentParser.parse(query)`
- **동작 방식 및 분기**:
  - LLM(`intent_llm`)이나 규칙 기반으로 쿼리의 의도(Intent)와 관련된 조직(org_name) 등을 추출합니다.
  - **랭킹 질의 (`query_type == "ranking"`)**: 
    - "사업비가 가장 많은 3곳은?" 같은 의도의 경우 로컬 캐시/CSV를 기반으로 즉시 `_handle_ranking_query(intent)`를 호출해 결과를 리턴. (검색 비용 최소화)
    - *예외조건*: 명시적인 대상 기관 이름이 특정된 경우 정밀도를 위해 일반 검색(Search)으로 우회.
  - **카테고리 질의 (`query_type == "category"`)**: 
    - 문서 종류/구분 등에 대한 경우 `_handle_category_query(intent)` 호출 후 즉시 리턴.

### 2.2. 후속 질문 맥락 판단 및 답변 계획 수립
- **경로**: `src/graph/workflow.py` 내 `QuestionPlanner`, `ConversationContext` 활용
- **동작 방식**: 
  - `self.conversation.get_follow_up_context(query)`를 통해 사용자가 앞서 묻던 기관/문서인지 파악.
  - `question_plan = self.question_planner.build(query, target_org)`를 호출하여, 질의가 **"수치 확인"**, **"일정(Deadline)"**, **"다문서 비교(Comparison)"** 중 어떤 답변 형태에 적합한지 플랜을 만듭니다.

### 2.3. 단문/특정 형태 단축 처리 (Short-Circuits)
벡터 검색(Retrieval)이 필요치 않거나 메타데이터 만으로 충분히 처리할 수 있는 간단한 질의에 대한 최적화 우회 로직.
- **`_try_csv_short_circuit`**: CSV 인덱스에 매칭되는 기본 사업비/기간 등의 메타데이터 질의.
- **`_try_org_overview_short_circuit`**: "특정 기관의 전체 개요" 질의 시 메타데이터 요약으로 리턴.
- **`_try_chunk_budget_short_circuit`**: 청크/예산 관련 질의.
- **`_try_org_document_scan_short_circuit`**: 서류/평가 기준 등에 대한 스캔.
- *조건*: 위 함수 중 하나라도 성공적인 답변 페이로드를 만들면 그 즉시 LLM 및 VectorStore 검색 단계를 건너뛰고 마무리 단계로 이동합니다.

### 2.4. 문서 벡터 검색 (Document Retrieval)
주요 분기와 단축 처리를 뚫고 내려온 본격적인 문서 질의는 여기서 문서를 탐색합니다.
- **경로**: `src/graph/workflow.py` ➔ `_retrieve_results`
- **동작 방식 및 분기**:
  - **비교(Comparison) / 다문서(Multi-doc) 대상**: 기관 명을 한 곳에 특정하지 않거나, 대상을 병합(coverage_targets 결합)하여 더 넓은 범위를 검색. `top_k`를 최대 30~48까지 상향 조정.
  - **단일 기관 (Single Org)**:
    1. 특정 `org_name`으로 스코프를 제한하여 `_retrieve_results`를 호출.
    2. *예외조건*: 검색 결과가 부족하면 전역(global) 검색으로 확대한 후 `_filter_results_by_org`로 다시 한 번 보완 탐색 시도.
  - 추가적으로, 문서가 너무 청크에만 의존할 경우 원본 문서(`pdf`, `hwp`)에 가산점을 부여하거나(`prefer_original`), 원본 전용 재조회 모델을 실행하여 결과를 취합.

### 2.5. 결과 기반 응답 생성 과정
검색된 청크/문서 정보를 컨텍스트로 변환해 응답을 만듭니다.
- **경로**: `src/graph/workflow.py` ➔ `_answer_with_results`
- **분기 조건 (답변 형식에 따라)**:
  1. **비교 질의 (`is_multi_target == True`)**:
     - `_build_comparison_answer_from_results` 호출.
     - 두 개 외 이상의 문서를 대조하여 표 형식이거나 구조화된 비교문을 생성합니다. 한 곳의 근거가 없으면 경고(warning)와 함께 하나의 정보만 표출.
  2. **사실 기반 단문형(`Extractive First`)**:
     - 비용, 마감기한 등 수치 데이터의 경우 LLM을 태우기 전 `_build_non_llm_answer`로 정규식 기반 추출 시도. (추출된 답변 `extractive_draft`) 추출이 명확할 경우 비용 절감을 위해 이 단계에서 반환 준비.
  3. **일반/서술형 질의 (`Generative LLM`)**:
     - `self.answer_generator.generate(query, context, history, extractive_draft)` 호출. (실제 `src/graph/nodes.py`의 `RFPAnswerGenerator` 실행).
     - 검색된 Context와 LLM을 조합하여 완성된 형태의 답변 생성.

### 2.6. 최종 후처리 및 다듬기
결론, 근거, 불필요한 라벨(`요약:`, `출처:` 등)을 다듬고 톤 앤 매너(Tone & Manner)를 조정합니다.
- **경로**: `RAGChatbotV17.answer` 내 중첩 함수 `_finalize_payload`
- **동작 방식**:
  - LLM 모델(`self.llm`)이 존재하고 답변이 Generative 모드인 경우, 요약 질의(`_is_summary_focus_query`)가 아니라면 `_polish_answer_with_llm`를 통해 가독성 높은 한국어로 어투 조정. (Concise / Guide 스타일 분기 적용).
  - LLM을 쓰지 않거나 부적합할 경우 정규식 기반 `_compact_answer_sections`을 사용하여 라벨 제거.
  - 수치나 단답형(`_is_single_value_query`)인 경우, 문맥(Context)을 앞뒤로 소량 덧붙여 너무 기계적이지 않도록 문장 완성.
  - 응답 Latency 등의 통계 값을 페이로드(`payload`)에 담아 `app/main.py` 리턴.

---

## 요약 (TL;DR)
1. **의도 분석 / 기획**: 무엇을 물어보는지 확인 (일정? 예산? 비교? 요약?)
2. **사전 차단 (우회)**: 단순 메타데이터만으로 대답할 수 있으면 LLM/DB 검색 생략 (`Short-Circuit`).
3. **분석 및 검색**: 단일 문서인지 비교 문서인지에 맞추어 벡터DB 질의. 확장 조회 필요시 자동 결합.
4. **추출 및 생성**: 추출만으로 가능하면 정규식 기반 가공(`_build_non_llm_answer`); 서술형이면 LLM에 Context를 주어 답변 생성.
5. **어투 정리**: 최종 응답 전, 안내형/간결형 톤으로 응답 스타일 정리 후 UI (Streamlit)로 전달.

---

## 3. 누락되기 쉬운 핵심 분기 (추가)

### 3.1. `answer()` 진입 직후 공통 처리
- 질의 문자열을 `strip()` 했을 때 비어 있으면 즉시 `"질문을 입력해 주세요."` 페이로드를 반환합니다.
- 질의마다 `self.vector_store.last_search_results`를 초기화하고, `perf_stats`(LLM 호출 수/검색 시간/예산 소진 여부 등)를 새로 만듭니다.

### 3.2. Intent Parser 내부 실제 선택 로직
- `QueryIntentParser.parse()`는 아래 순서로 실행됩니다.
  1. **캐시 확인**: exact cache / signature cache hit 시 즉시 반환
  2. **Regex 파싱**
  3. **LLM 호출 필요성 판단** (`_should_call_llm`)
  4. 필요 시 LLM 파싱 수행 후, `llm_conf >= max(0.7, regex_conf + 0.03)`일 때만 LLM 결과 채택
- 즉, "LLM이 항상 최종 결정"이 아니라 confidence margin 비교로 regex 결과가 유지될 수 있습니다.

### 3.3. 후속질문/기관명 보정 분기
- `ConversationContext.get_follow_up_context()`로 후속질문 여부를 판별하고, 명시 기관이 없으면 직전 기관(`last_org`)을 질의에 주입할 수 있습니다.
- `QuestionPlanner.build()`는 `comparison / owner / deadline / fact_numeric / multi_doc / single_doc`를 구분합니다.
- `comparison_like_query` 계산 시 예외가 중요합니다.
  - 단일 기관 예산 질문, 단일 기관 시각질문은 비교 플래그를 강제로 끕니다.
  - 다기관 질의인 경우 `coverage_targets`(비교 대상 기관 목록)를 복원하고, 필요 시 `org_name` 스코프를 해제해 전역 비교 검색으로 전환합니다.

### 3.4. Short-circuit 우회(bypass)와 재허용(override)
- 요약 질의라도 `"본문/원문/조항/근거/페이지"` 같은 근거 직접 검증 요청이 있으면 short-circuit를 우회하고 본문 RAG 경로로 보냅니다.
- 단, CSV 매칭 신뢰도가 충분하면 `_can_override_short_circuit_bypass()`가 우회를 다시 해제하여 short-circuit를 허용합니다.
- short-circuit는 아래 순서로 시도합니다.
  1. `_try_csv_short_circuit`
  2. `_try_org_overview_short_circuit`
  3. `_try_chunk_budget_short_circuit`
  4. `_try_org_document_scan_short_circuit`

### 3.5. Retrieval 내부 다중 패스/재시도
- `_retrieve_results()`는 단일 1회 검색이 아니라 동적 전략 기반 다단계입니다.
  1. 질의 확장 (`_expand_query_terms`) + 확장 개수 cap (`_resolve_expansion_cap`)
  2. 다중 pass 검색 (`RETRIEVAL_SEARCH_PASSES`)과 pass별 `k` 증대
  3. 조건부 CSV boost pass
  4. 조건부 fallback pass(pdf/hwp/csv 재조합)
  5. 조건부 asset-sidecar pass(시각/정밀 질의 보강)
  6. 조건부 source-local probe(같은 source 내부 청크 재스캔)
  7. rerank + anchor promotion + comparison diversity 보정
- 조기 종료(`_should_stop_retrieval_early`)도 엄격 조건을 만족할 때만 동작합니다.
  - 정밀 사실 질의나 책임 주체 질의에서 anchor evidence가 부족하면 조기 종료를 막습니다.

### 3.6. `_answer_with_results`의 실제 폴백 순서
- 비교 질의이면서 양측 커버리지가 부족하면 단정 비교를 금지하고 warning 응답으로 종료합니다.
- 사실형/기한형/책임형은 `extractive-first`를 우선 시도합니다.
  - `extractive_draft`가 확보되고 요약 집중 질의가 아니면 LLM 생성을 건너뛰고 추출답으로 종료할 수 있습니다.
- LLM이 없으면 규칙 기반(`_build_non_llm_answer`) -> 실패 시 최소 요약(`_create_multi_org_summary`) 순서.
- LLM이 있으면 `RFPAnswerGenerator.generate()`를 타며, 내부는
  1. 근거 정제
  2. 최종 답변 생성
  3. 실패 시 단일 생성 프롬프트 fallback
  로 구성됩니다.
- 생성 결과가 불확실/오류면 추출 초안으로 되돌리는 하이브리드 폴백이 다시 적용됩니다.

### 3.7. `_finalize_payload` 최종 정리 분기
- 조건을 만족하면 `_polish_answer_with_llm`로 문장 다듬기, 아니면 `_compact_answer_sections`로 정리합니다.
- 단일값 질의는 `_extract_single_value_from_fact_answer` + `_render_single_value_answer`로 문장형 단답을 강제합니다.
- 생성 답변(`answer_mode == generative`)은 `_restrict_answer_to_evidence`로 evidence 정합성을 재검증합니다.
- 모든 경로에서 `latencies`와 `retrieved_docs`를 보정해 UI/평가 파이프라인이 공통 포맷을 받도록 맞춥니다.

### 3.8. 결과 미탐색 시 최종 종료 조건
- 기관 스코프 검색 실패 시 전역 재시도 + 기관 필터링까지 수행한 뒤에도 없으면 `_build_org_not_found_payload`를 반환합니다.
- 전역 검색까지 모두 실패하면 `"관련 정보를 찾을 수 없습니다."`로 종료합니다.

---

## 4. 모듈 분리 반영 (2026-03-01)
이번 변경으로 `workflow.py`는 오케스트레이션 중심으로 유지하고, 공통 로직을 `src/*` 모듈로 분리했습니다.

### 4.1. 분리된 모듈
- `src/utils/text_ops.py`
  - `normalize_text_for_match`, `clip_text_safely`, `looks_incomplete_clause`
  - `clean_extracted_line`, `is_noise_line`
- `src/parsers/csv_runtime_utils.py`
  - CSV 값/시간 정규화, VAT 추출, 메타 필드 추출, 공고번호 추출, 답변용 시간 포맷
- `src/prompts/answer_postprocess.py`
  - `format_answer_for_readability`, `compact_answer_sections`
  - `enforce_honorific_tone`, `normalize_answer_for_compare`
- `src/evaluation/runtime_diagnostics.py`
  - `estimate_slot_fill_rate`, `estimate_confidence`
  - `collect_answer_content_lines`, `looks_uncertain_answer`
  - `should_fallback_to_extractive_draft`

### 4.2. workflow.py 변경 포인트
- 기존 내부 메서드는 대다수를 래퍼 형태로 유지하여 외부 호출 계약(메서드명/시그니처)을 깨지 않도록 했습니다.
- 응답 생성/후처리/평가 보조 로직은 각 모듈 함수를 import해 호출하도록 전환했습니다.
- 결과적으로 향후 `retrievers/prompts/parsers/evaluation/utils` 단위 실험 및 회귀 확인이 쉬워졌습니다.

### 4.3. 안정성 검증
- `python3 -m compileall src` 통과
- `from src.graph.workflow import RAGChatbotV17` import 스모크 통과
- 평가 산출물: `eval_results_full20_chunk_synced_after_module_split_phase2_20260301.json`
