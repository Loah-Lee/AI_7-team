# src/evaluation — 평가 + 관측성(Observability)

## 파일 구성

| 파일 | 역할 | 핵심 함수/클래스 |
|------|------|-----------------|
| `llm_judge.py` | LLM-as-Judge 4지표 채점 | `judge_rag_response()` |
| `metrics.py` | KPI 계산 함수 | Retrieval 지표 + AICR |
| `langfuse_tracer.py` | Langfuse 메트릭 수집 | `log_score()`, `log_retrieval_metrics()` |
| `langsmith_tracer.py` | LangSmith 트레이싱 설정 | `setup_langsmith_tracing()` |

## LLM-as-Judge (llm_judge.py)

단일 LLM 호출로 4가지 기준을 0~5점 채점 + 1줄 근거 반환.

| 지표 | 초점 | 설명 |
|------|------|------|
| **Correctness** | 정확성 | 생성 답변이 기대 답변과 의미적으로 일치하는 정도 |
| **Answer Coverage** | 누락 | 기대 답변의 핵심 포인트가 빠짐없이 포함되었는가 |
| **Faithfulness** | 환각 | 답변이 검색된 context에 근거하고 있는 정도 |
| **Context Relevance** | 검색 품질 | 검색된 context가 질문에 실제로 관련 있는 정도 |

- `response_format: json_object` 강제
- 컨텍스트 길이 제한: 6000자 (초과 시 트리밍)
- 파싱 실패 시 최대 2회 재시도
- 호출처: `scripts/eval_retrieval.py`

## Retrieval 메트릭 (metrics.py)

### 활성 함수 (eval_retrieval.py에서 사용)

| 함수 | 설명 | 반환 |
|------|------|------|
| `calculate_hit_position()` | 정답 문서의 검색 순위 (1-based) | `int \| None` |
| `calculate_recall_at_k()` | top-K 내 정답 존재 여부 | `1.0 \| 0.0` |
| `calculate_recall_at_k_summary()` | per-query Recall@K 평균 (=Hit Rate) | `float` |
| `calculate_mrr()` | Mean Reciprocal Rank | `float` |

### 기타 함수 (런타임 파이프라인에서 사용)

| 함수 | 호출처 | 설명 |
|------|--------|------|
| `calculate_aicr()` | `nodes.py:generate()` | 답변 문장이 context에 근거하는 비율 |
| `calculate_hallucination_rate()` | - | `1 - AICR` (미사용) |
| `calculate_empty_retrieval_rate()` | - | 빈 검색 비율 (미사용) |
| `calculate_avg_score()` | - | 정답 청크 평균 점수 (미사용) |

## 관측성 (Observability)

### Langfuse (langfuse_tracer.py)
- `nodes.py:generate()`에서 자동 호출
- 기록 항목: AICR 점수, 검색 청크 수, 평균/최고 유사도 점수
- 환경변수 없으면 무시 (graceful skip)

### LangSmith (langsmith_tracer.py)
- `setup_langsmith_tracing()`: LangChain 환경변수 설정으로 자동 트레이싱 활성화
- `LANGSMITH_API_KEY` 필요, 없으면 비활성화
- 프로젝트명: .env `LANGSMITH_PROJECT` → config `tracing.langsmith_project` (폴백)

## 평가 실행 흐름

```
scripts/eval_retrieval.py
  → eval_dataset.yaml 로드 (20개 질의)
  → 각 질의: build_graph().invoke() 실행
  → 검색 결과에서 Recall@K, MRR, Hit Position 계산 (metrics.py)
  → LLM Judge 채점 (llm_judge.py)
  → eval_results_{label}.json 저장

scripts/build_eval_report.py
  → eval_results_*.json 로드
  → HTML 인터랙티브 리포트 생성
```

## dev-yc 브랜치와의 차이

| 항목 | integration-eval-yc | dev-yc |
|------|---------------------|--------|
| LLM Judge | 동일 (`llm_judge.py`) | 동일 |
| metrics.py | 8개 함수 (4개 미사용) | 4개 함수 (정리 완료) |
| AICR 사용 | `nodes.py`에서 Langfuse 기록 | 미사용 |
| Langfuse | `langfuse_tracer.py` 연동 | 없음 |
| LangSmith | `langsmith_tracer.py` 연동 | 없음 |
| 평가 실행 | `graph.invoke()` 직접 | `eval_adapter.py` 래핑 |
