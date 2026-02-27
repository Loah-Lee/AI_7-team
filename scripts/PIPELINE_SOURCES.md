# 평가 파이프라인 소스 파일 목록

> 브랜치: `feature/dev-yc` (dev 기반)
> 최종 업데이트: 2026-02-25

---

## 1. 평가 실행 스크립트

| 파일 | 역할 |
|---|---|
| `scripts/eval_retrieval.py` | E2E 평가 진입점. 평가셋 로드 → RAG 실행 → Retrieval 지표 계산 → LLM Judge 채점 → JSON 저장 |
| `scripts/build_eval_report.py` | 평가 결과 JSON → HTML 대시보드 생성 |

### 실행 명령 (버전 관리)

`--label` 로 버전을 지정하면 결과가 누적 저장됨. 두 스크립트에서 동일 label 사용.

```bash
# 평가 실행 → eval_resources/eval_results_{label}.json 저장
uv run python scripts/eval_retrieval.py --label v5-pdf-fix --top_k 5

# HTML 리포트 생성 → eval_resources/eval_report_{label}.html 저장
uv run python scripts/build_eval_report.py --label v5-pdf-fix
```

#### 누적 파일 예시
```
eval_resources/
  eval_results_v4-newdb.json      # DB 교체 전
  eval_results_v5-pdf-fix.json    # .hwp→.pdf 수정 후
  eval_report_v4-newdb.html
  eval_report_v5-pdf-fix.html
```

---

## 2. RAG 파이프라인 (워크플로우)

| 파일 | 역할 |
|---|---|
| `src/graph/workflow.py` | `RAGChatbotV17` 클래스. 검색 → 근거추출 → 답변생성 통합 |
| `src/retrievers/vectorstore.py` | Chroma 벡터스토어 래퍼. 검색 타입(dense/hybrid) 처리 |

> **dev 브랜치 주의**: `build_graph` 없음. `RAGChatbotV17` 클래스 사용.
> `eval_retrieval.py`는 `build_graph` import 실패 시 자동으로 `RAGChatbotV17` fallback.

---

## 3. 평가 모듈 (src/evaluation/)

### 3-1. LLM Judge 채점 (`llm_judge.py`)

**호출 위치**: `scripts/eval_retrieval.py` → `evaluate_e2e()` 내 각 질문마다 1회 호출

```
eval_retrieval.py
  └─ judge_rag_response(question, expected_answer, generated_answer, context)
        ├─ ChatOpenAI 호출 (단일 LLM call, JSON 응답 강제)
        ├─ 4개 지표 동시 채점
        └─ _parse_judge_response() → dict 반환
```

| 지표 | 채점 관점 | 비교 대상 |
|---|---|---|
| **Correctness** | 정확성 | generated_answer vs expected_answer |
| **Answer Coverage** | 누락 여부 | generated_answer가 expected_answer 항목을 빠짐없이 커버하는지 |
| **Faithfulness** | 환각 여부 | generated_answer가 context에 근거하는지 |
| **Context Relevance** | 검색 품질 | context가 question에 실제로 관련 있는지 |

- 모델: config `llm.model` (기본 `gpt-5-mini`) 또는 `--judge_model` 인자
- context 6000자 초과 시 트리밍
- JSON 파싱 실패 시 최대 2회 재시도, 최종 실패 시 전 지표 0점 처리

---

### 3-2. Retrieval 지표 (`metrics.py`)

**호출 위치**: `scripts/eval_retrieval.py` → `evaluate_e2e()` 내 각 질문마다 RAG 실행 직후 계산

```
eval_retrieval.py
  └─ run_rag_pipeline() → retrieved_docs 반환
       ├─ calculate_recall_at_k(retrieved_docs, gt_sources, k=top_k)
       │     → top-K 안에 정답 소스 있으면 1.0, 없으면 0.0
       ├─ calculate_hit_position(retrieved_docs, gt_sources)
       │     → 정답 소스가 몇 번째에 있는지 (1-based, 없으면 None)
       └─ [집계 시]
             calculate_recall_at_k_summary(recalls)  → Hit Rate@K (전체 평균)
             calculate_mrr(hit_positions)             → MRR
```

**멀티소스 처리 방식** (`str | list[str]` 지원):

| query_type | gt_sources | Recall 판정 기준 |
|---|---|---|
| `single_doc` | `["A.hwp"]` | top-K에 A.hwp 있으면 1.0 |
| `multi_doc` | `["A.hwp", "B.hwp"]` | top-K에 **둘 다** 있어야 1.0 (strict) |
| `comparison` | `["A.hwp"]` | single_doc과 동일 |
| `csv_match` | `["data_list.csv"]` | **항상 0.0** (CSV는 벡터스토어 미인덱싱) → LLM Judge 4지표만 참고 |

`calculate_hit_position` 멀티소스 strict: 모든 소스가 발견된 경우 마지막 발견 위치(max rank) 반환. 하나라도 누락이면 None.

---

### 3-3. 관측성 모듈 (평가 실행과 직접 무관)

| 파일 | 호출 위치 | 역할 |
|---|---|---|
| `langfuse_tracer.py` | `src/graph/nodes.py:generate()` | 런타임 답변 품질 로깅 (AICR 점수, 검색 청크 수 등) |
| `langsmith_tracer.py` | `src/graph/workflow.py` 초기화 시 | LangChain 자동 트레이싱 설정 |

> 이 두 모듈은 `eval_retrieval.py`가 직접 호출하지 않음. RAG 파이프라인 내부에서 자동 실행.

---

## 4. 평가셋 및 결과 파일

| 파일 | 역할 |
|---|---|
| `eval_resources/eval_dataset.yaml` | 평가 질문셋 (20문항) |
| `eval_resources/eval_results_{label}.json` | 평가 결과 JSON |
| `eval_resources/eval_report.html` | HTML 대시보드 |
| `eval_resources/METRICS.md` | 지표 상세 정의 문서 |

---

## 5. src/evaluation/ 코드 동기화 현황

> 비교 대상: `feature/integration-eval-yc` vs 현재 `feature/dev-yc`

| 파일 | 상태 | 비고 |
|---|---|---|
| `metrics.py` | ✅ 동기화 완료 | 2026-02-25 integration-eval-yc 버전 적용 (str\|list[str] 지원) |
| `llm_judge.py` | ✅ dev가 최신 | UTILS_AVAILABLE fallback 패턴 적용 — integration-eval-yc보다 앞선 버전 |
| `langfuse_tracer.py` | ✅ dev가 최신 | 동일 — ImportError graceful skip 추가됨 |
| `langsmith_tracer.py` | ✅ dev가 최신 | 동일 — ImportError graceful skip 추가됨 |
| `__init__.py` | ✅ 동일 | (비어있음) |
| `README.md` | ⚠️ integration-eval-yc에만 존재 | 이 문서(PIPELINE_SOURCES.md)로 대체 |

---

## 6. 환경 / 의존성

| 항목 | 값 |
|---|---|
| Python | 3.11 |
| 임베딩 | `sentence-transformers` (hybrid retriever, v5.2.3 설치됨) |
| LLM Judge | OpenAI API (OPENAI_API_KEY 필요) |
| 벡터스토어 | Chroma (`data_index/chroma_B/`) |
| 환경변수 | `.env` (OPENAI_API_KEY, LANGSMITH_API_KEY 등) |
