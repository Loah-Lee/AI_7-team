# KPI Definition

RFP RAG 시스템의 성능을 정량적으로 측정하기 위한 KPI 정의서입니다.
평가 체계: LLM-as-Judge 기반 E2E 평가 (상세: `eval_resources/METRICS.md`)

---

## 답변 품질 KPI (LLM-as-Judge, 0~5점)

| KPI | 설명 | Baseline (v2) | Target |
|-----|------|:---:|:---:|
| **Correctness** | 답변이 기대 답변과 의미적으로 일치하는 정도 | 3.50 | 4.0+ |
| **Answer Coverage** | 기대 답변의 핵심 포인트가 누락 없이 포함된 정도 | 3.25 | 4.0+ |
| **Faithfulness** | 답변이 검색된 context에 근거하는 정도 (환각 없음) | 4.65 | 4.5+ (유지) |
| **Context Relevance** | 검색된 context가 질문에 관련 있는 정도 | 4.25 | 4.5+ |

---

## Retrieval 보조 KPI

| KPI | 설명 | Baseline (v2) | Target |
|-----|------|:---:|:---:|
| **Recall@5** | top-5 검색 결과에 정답 문서가 포함된 질문 비율 | 0.90 | 0.95+ |
| **MRR** | 정답 문서의 검색 순위 역수 평균 | 0.90 | 0.92+ |

---

## Latency KPI

| KPI | 설명 | 담당 |
|-----|------|------|
| **End-to-End Latency** | 질의 입력 → 최종 답변 출력까지 전체 소요 시간 | PM / 전체 |
| **Retrieval Latency** | 질의 임베딩 생성 → 벡터DB 검색 완료까지 소요 시간 | Retriever |
| **Evidence Extraction Latency** | 검색된 chunk에서 근거 문장 추출 소요 시간 | LangGraph |
| **Answer Generation Latency** | 프롬프트 전달 → LLM 답변 생성 완료까지 소요 시간 | Prompt / LLM |
| **P95 Latency** | 전체 질의의 95번째 백분위 응답 시간 | PM |

---

## 측정 인프라

| 도구 | 역할 |
|------|------|
| **LangSmith** | LangGraph 노드별 실행 트레이스, 단계별 latency 자동 수집 |
| **Langfuse** | 평가 메트릭 대시보드, 비용 추적, 세션별 품질 점수 기록 |
| **Streamlit** | KPI 시각화 대시보드, 실험 결과 비교 UI |

---

## 유형별 약점 (개선 우선순위)

| 유형 | 약점 지표 | 현재 값 | 원인 분석 |
|------|----------|---------|----------|
| multi_doc | Answer Coverage | 1.25 | 다중 문서 커버리지 부족 |
| comparison | Context Relevance | 3.25 | 비교 대상 문서 동시 검색 어려움 |
