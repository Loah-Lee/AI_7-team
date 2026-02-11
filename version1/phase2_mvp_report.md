# Phase 2 MVP 구현 보고서

**작성일**: 2026-02-11
**브랜치**: `feature/kt2`
**명세서**: `설계/phase2_agents.md`

---

## 1. 개요

Phase 2 RAG 파이프라인의 MVP를 구현했다. 기존 검증 코드(minimum.ipynb)의 Stage 1, Stage 2를 재사용하고, 신규 CoT 분해 + Step 루프 + 답변 생성 에이전트를 추가하여 **총 6개 에이전트**로 구성된 end-to-end 파이프라인을 완성했다.

### 파이프라인 아키텍처

```
START → [expand] → [build_cot] → [prepare_step] → [search_and_rerank] → [step_router]
                                       ↑                                       |
                                       └──── continue (다음 step 존재) ────────┘
                                                                               |
                                                          done ───→ [infer_answer] → END
```

---

## 2. 산출물

| 파일 | 줄 수 | 설명 |
|------|-------|------|
| `version1/phase2_state.py` | 89줄 | Phase2State TypedDict + merge_context_dedup reducer |
| `version1/prompts.py` | 144줄 | 프롬프트 6개 (Stage1 4개 + COT_BUILDER + ANSWER_INFERENCE) |
| `version1/phase2_pipeline.py` | 624줄 | 노드 함수 6개 + 그래프 조립 + run_phase2() 진입점 |

---

## 3. 에이전트 상세

### 3.1 expand_node (기존 포팅)
- **역할**: 원본 쿼리를 행정 용어로 정밀화 + 검색 키워드 추출
- **LLM 호출**: 4~8회 (Group A→B 루프 + Group C→D 루프, 최대 재시도 2회)
- **입력**: `{original_query}`
- **출력**: `{dense_query, sparse_query}`

### 3.2 build_cot_node (신규)
- **역할**: 정밀화된 쿼리를 1~3개 검색 sub-step으로 분해
- **LLM 호출**: 1회
- **입력**: `{dense_query, original_query}`
- **출력**: `{cot_steps, current_step_index: 0}`

### 3.3 prepare_step_node (신규)
- **역할**: 현재 step 텍스트 → step별 dense/sparse 쿼리 생성
- **LLM 호출**: 2회 (Group A + Group C, 검증 루프 없음)
- **입력**: `{cot_steps, current_step_index}`
- **출력**: `{step_dense_query, step_sparse_query}`

### 3.4 search_and_rerank_node (기존 개선)
- **역할**: 4채널 검색 + RRF 리랭킹 → 상위 5개 문서 반환
- **LLM 호출**: 0회 (순수 DB 검색 + 알고리즘)
- **입력**: `{step_dense_query, step_sparse_query}`
- **출력**: `{accumulated_context: [top5], hierarchy_id}`

### 3.5 step_router_node (신규)
- **역할**: step 인덱스 증가 + 루프/종료 라우팅
- **LLM 호출**: 0회
- **라우팅**: `current_step_index < len(cot_steps)` → continue / done

### 3.6 infer_answer_node (신규)
- **역할**: 누적된 컨텍스트 기반 최종 답변 생성
- **LLM 호출**: 1회
- **입력**: `{original_query, accumulated_context}`
- **출력**: `{final_answer}`

---

## 4. 버그 수정 3건

명세서에서 지적한 기존 코드(minimum.ipynb)의 버그 3건을 모두 수정했다.

### Bug Fix #1: state.items() 순회 문제

| 항목 | 내용 |
|------|------|
| **기존** | `rerank_node`에서 `state.items()` 순회 → 비-리스트 필드(str, int 등)도 순회하여 오류 |
| **수정** | 명시적 4채널 리스트 `[("filtered_dense", ch1), ("filtered_sparse", ch2), ("global_dense", ch3), ("global_sparse", ch4)]` 순회 |
| **위치** | `phase2_pipeline.py` 430~435행 |

### Bug Fix #2: final_score 필드 누락

| 항목 | 내용 |
|------|------|
| **기존** | 출력 문서에 `final_score` 필드 없음 → 출력 셀에서 `KeyError: 'final_score'` |
| **수정** | RRF 결과에 `final_score`(RRF 합산), `source_channels`(채널 목록), `rank`(순위) 필드 포함 |
| **위치** | `phase2_pipeline.py` 464~473행 |

### Bug Fix #3: sparse_search 필터링 해킹

| 항목 | 내용 |
|------|------|
| **기존** | `sparse_search(f"{h_id} {query}")` — h_id를 쿼리 앞에 접두사로 붙이는 해킹 |
| **수정** | `sparse_search(query, l1=f'%{h_id}%')` — l1 파라미터 정식 사용 (SQL LIKE 패턴) |
| **위치** | `phase2_pipeline.py` 414행 |

---

## 5. 추가 개선사항

### Rate Limiting
모든 LLM 호출에 속도 제한 래퍼(`call_with_rate_limit`)를 적용했다.

| 설정 | 값 | 설명 |
|------|-----|------|
| `RATE_LIMIT_DELAY` | 1.0초 | API 호출 간 최소 대기 시간 |
| `RATE_LIMIT_MAX_RETRIES` | 3회 | 429 에러 시 최대 재시도 |
| `RATE_LIMIT_BACKOFF` | 2.0배 | 재시도 시 지수 백오프 배수 |

### merge_context_dedup Reducer
- `chunk_id` 기준 중복 제거하며 step 간 컨텍스트 자동 누적
- 동일 `chunk_id`가 여러 step에서 검색되면 `final_score`가 더 높은 쪽 유지

---

## 6. 리뷰 결과

### 버그 수정 검증

| # | 항목 | 결과 |
|---|------|------|
| 1 | 명시적 4채널 리스트 순회 | **PASS** |
| 2 | final_score/source_channels/rank 출력 | **PASS** |
| 3 | sparse_search l1 파라미터 사용 | **PASS** |

### 체크리스트 전수 검사

| # | 항목 | 결과 |
|---|------|------|
| 1 | Phase2State 10개 필드 명세 일치 | **PASS** |
| 2 | merge_context_dedup chunk_id 중복 제거 | **PASS** |
| 3 | 프롬프트 6개 정의 완료 | **PASS** |
| 4 | 템플릿 변수 단일 중괄호 `{var}` 사용 | **PASS** |
| 5 | 노드 함수 6개 존재 | **PASS** |
| 6 | 그래프 아키텍처 명세 일치 | **PASS** |
| 7 | 모든 LLM 호출 rate limit 적용 | **PASS** |
| 8 | prepare_step Group A+C만 사용 (경량) | **PASS** |
| 9 | run_phase2() 진입점 + 출력 포맷 | **PASS** |

---

## 7. 실행 방법

```bash
cd /home/codeitDev/project/part3_nlp/AI_7-team
python version1/phase2_pipeline.py
```

### 테스트 쿼리

| 쿼리 | 예상 CoT Steps | 확인 포인트 |
|------|---------------|------------|
| "철도 ISP 수립용역 마감 언제야?" | 1개 | 단순 질문 → 1-step 처리 |
| "예산이 3억 5천만원 이상인 ISP 사업의 기술 요구사항은?" | 2~3개 | 복합 조건 분해, 누적 컨텍스트 중복 제거 |

---

## 8. 향후 과제

- [ ] Stage 3~6 (CSV 분석, 답변 검수 등) 미구현 — 명세 확장 필요
- [ ] recursion_limit=25 설정 및 안전 가드 추가
- [ ] 실제 테스트 쿼리 실행 및 답변 품질 평가
- [ ] Langfuse 옵저빌리티 연동
