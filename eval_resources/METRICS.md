# BiddingMate RAG 평가 지표 정의서

## 개요

LLM-as-Judge 기반 End-to-End 평가 체계.
전체 RAG 파이프라인(`build_graph().invoke()`)을 실행한 뒤, LLM Judge가 4가지 기준으로 채점하고 Retrieval 보조 지표를 병행 계산한다.

---

## LLM Judge 지표 (0~5점)

### 1. Correctness | 정확성

> 생성된 답변이 기대 답변과 **의미적으로 일치**하는가?

- **관점**: 답변의 정확성 (맞는 정보인가)
- **판단 기준**: 기대 답변의 핵심 사실과 생성 답변의 사실이 일치하는 정도
- **Coverage와의 차이**: Correctness는 "틀린 정보가 있는가"에 초점, Coverage는 "빠진 정보가 있는가"에 초점

| 점수 | 기준 |
|------|------|
| 5 | 기대 답변의 핵심 정보를 모두 **정확히** 포함 |
| 4 | 대부분 정확하나 사소한 부정확 있음 |
| 3 | 핵심의 절반 정도가 정확 |
| 2 | 일부만 맞고 오류 포함 |
| 1 | 거의 관련 없는 답변 |
| 0 | 완전히 틀리거나 답변 거부 |

---

### 2. Answer Coverage | 답변 커버리지

> 기대 답변의 핵심 정보가 생성 답변에 **얼마나 누락 없이** 포함되었는가?

- **관점**: 답변의 완전성/커버리지 (빠진 정보가 없는가)
- **판단 기준**: 기대 답변의 핵심 포인트 목록 대비 생성 답변이 커버한 비율
- **Correctness와의 차이**: Correctness=5이지만 Coverage=3일 수 있음 (포함된 부분은 정확하나 절반이 누락)
- **Retrieval Recall@K와의 차이**: Recall@K는 검색 단계의 문서 매칭, Answer Coverage는 최종 답변의 정보 커버리지

| 점수 | 기준 |
|------|------|
| 5 | 기대 답변의 모든 핵심 포인트를 빠짐없이 포함 |
| 4 | 대부분 포함하나 사소한 항목 1~2개 누락 |
| 3 | 핵심 포인트의 절반 정도만 커버 |
| 2 | 주요 정보 대부분 누락, 일부만 언급 |
| 1 | 핵심 정보가 거의 없음 |
| 0 | 관련 정보 전혀 없음 또는 답변 거부 |

---

### 3. Faithfulness | 충실성

> 생성된 답변이 검색된 context에 **근거하고 있는가**? (환각 없는가)

- **관점**: 답변의 근거 충실도
- **판단 기준**: 답변의 각 주장이 검색된 context에서 확인 가능한 정도

| 점수 | 기준 |
|------|------|
| 5 | 모든 내용이 context에서 직접 확인 가능 |
| 4 | 대부분 근거 있으나 사소한 추론 포함 |
| 3 | 핵심은 있으나 상당한 추론/일반화 포함 |
| 2 | 부분적으로만 관련, 환각 포함 |
| 1 | 대부분 환각이거나 context와 무관 |
| 0 | 완전한 환각 또는 context 무시 |

---

### 4. Context Relevance | 검색 관련성

> 검색된 context가 질문에 **실제로 관련 있는가**?

- **관점**: 검색 품질
- **판단 기준**: 검색된 문서가 질문에 답하는 데 필요한 정보를 포함하는 정도

| 점수 | 기준 |
|------|------|
| 5 | context가 질문에 완벽히 관련, 충분한 정보 포함 |
| 4 | 대부분 관련, 일부 불필요한 내용 |
| 3 | 부분적 관련, 핵심 정보 일부 부족 |
| 2 | 관련성 낮고 대부분 무관 |
| 1 | 거의 관련 없는 문서 |
| 0 | 완전히 무관 |

---

## Retrieval 보조 지표

### Recall@K (Source) | 검색 재현율 — 문서 단위

> top-K 검색 결과에 정답 문서(**source 기준**)가 **포함된** 질문의 비율

- 범위: 0.0 ~ 1.0
- 계산: `(per-query Recall@K > 0인 질문 수) / 전체 질문 수`
- 매칭: 파일명(source)만 일치하면 hit
- **single_doc**: top-K에 해당 source가 있으면 1.0
- **multi_doc/comparison (Strict Match)**: `ground_truth.sources`의 **모든** source가 top-K 안에 있어야 1.0. 하나라도 누락이면 0.0

### MRR (Source) | 평균 역순위 — 문서 단위

> 정답 문서(source 기준)가 검색 결과에서 **몇 번째**에 위치하는지의 역수 평균

- 범위: 0.0 ~ 1.0
- 계산: `mean(1/rank)` (정답 없으면 0)
- **multi_doc/comparison**: rank = 마지막으로 발견된 source의 위치 (모든 source를 포함하기 위한 최소 rank). 하나라도 미발견이면 0

---

---

## 단계별 지연시간 지표 | Pipeline Latency

> 각 LangGraph 노드의 처리 시간. `state["latencies"]`에 누적되어 `per_query` 결과에 포함된다.

| 단계 (Node) | 한글명 | 설명 |
|---|---|---|
| `analyze_query` | 질의 분석 | LLM이 query_type, institution, keywords 등 메타데이터 추출 |
| `retrieve` | 문서 검색 | ChromaDB MMR 검색 + 메타데이터 필터 적용 |
| `extract_evidence` | 근거 추출 | 검색 결과에서 LLM이 핵심 근거 문장 압축 |
| `generate` | 답변 생성 | 최종 RAG 답변 생성 |

- 단위: 초(s)
- `retrieve`는 DB I/O 위주라 수백ms 내외가 정상
- `analyze_query` / `extract_evidence` / `generate`는 LLM 호출로 수 초 소요
- 전체 소요 = `elapsed_seconds` (meta 필드)

---

## 지표 간 관계

```
                    ┌──────────────────────────────────┐
  Retrieval 품질 ──→│  Context Relevance (검색 관련성)  │
                    │  Recall@K, MRR                    │
                    └───────────────┬──────────────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────────┐
  답변 품질 ───────→│  Correctness (정확성)             │
                    │  Answer Coverage (커버리지)        │
                    │  Faithfulness (충실성)             │
                    └──────────────────────────────────┘
```

- **Context Relevance 낮음** → Correctness/Coverage 모두 낮아질 가능성 (쓰레기 input → 쓰레기 output)
- **Context Relevance 높음 + Correctness 낮음** → LLM 생성 품질 문제
- **Correctness 높음 + Coverage 낮음** → 맞는 말만 하되 빠진 정보 많음 (부분 답변)
- **Faithfulness 낮음** → 환각 문제 (context 무시하고 지어냄)

---

## 평가 실행

```bash
# E2E 평가 실행
uv run python scripts/eval_retrieval.py --label current --top_k 5

# HTML 리포트 생성
uv run python scripts/build_eval_report.py

# 결과 확인
open eval_resources/eval_report.html
```

## 평가셋

- 위치: `eval_resources/eval_dataset.yaml`
- 구성: 20개 질문 (single_doc 12, multi_doc 4, comparison 4)
- 각 항목: question, expected_answer, ground_truth(sources: list), query_type, metadata_filter
