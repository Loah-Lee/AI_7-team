# KPI Definition

RFP RAG 시스템의 성능을 정량적으로 측정하기 위한 KPI 정의서입니다.
LangSmith / Langfuse를 통해 자동 수집하며, Streamlit 대시보드에서 시각화합니다.

---

## 정답 품질 KPI

| KPI | 설명 | 측정 방법 |
|-----|------|----------|
| **Answer-in-Context Rate (AICR)** | 생성된 답변이 검색된 문맥(context) 내 정보만으로 구성되었는지 비율 | 답변 문장별로 context에 근거가 있는지 확인 |
| **Top-k Hit Position** | 정답이 포함된 chunk가 Top-k 검색 결과 중 몇 번째에 위치하는지 | 정답 chunk의 rank 위치 기록 (1위일수록 좋음) |
| **Empty Retrieval Rate** | 검색 결과가 비어있거나 관련 chunk를 찾지 못한 비율 | 검색 결과 0건인 질의 수 / 전체 질의 수 |
| **Hallucination Rate** | 답변에 context에 없는 정보가 포함된 비율 | context 대비 답변의 비근거 문장 비율 |
| **'없는 정보' Precision** | "해당 정보가 없습니다"라고 답변했을 때 실제로 정보가 없는 비율 | 거절 답변 중 실제로 데이터에 없는 경우 / 전체 거절 답변 |
| **Failure Attribution Rate** | 오답 발생 시 원인을 파이프라인 단계별로 귀인할 수 있는 비율 | 오답을 Retrieval 실패 / Generation 실패 / Parsing 실패로 분류 |
| **Determinism Stability** | 동일 질의에 대해 동일 답변이 반복 생성되는 안정성 | 동일 질의 N회 반복 → 답변 일치율 측정 |

---

## Latency KPI

| KPI | 설명 | 담당 |
|-----|------|------|
| **End-to-End Latency** | 사용자 질의 입력 → 최종 답변 출력까지의 전체 소요 시간 | PM / 전체 |
| **Retrieval Latency** | 질의 임베딩 생성 → 벡터DB 검색 완료까지 소요 시간 | Retriever |
| **Evidence Extraction Latency** | 검색된 chunk에서 근거 문장을 추출하는 데 걸리는 시간 | LangGraph |
| **Answer Generation Latency** | 프롬프트 전달 → LLM 답변 생성 완료까지 소요 시간 | Prompt / LLM |
| **P95 Latency** | 전체 질의의 95번째 백분위 응답 시간 (최악 케이스 관리) | PM |
| **Latency Variance** | 응답 시간의 분산 (안정성 지표) | PM |

---

## 측정 인프라

| 도구 | 역할 |
|------|------|
| **LangSmith** | LangGraph 노드별 실행 트레이스, 프롬프트 버전 관리, 단계별 latency 자동 수집 |
| **Langfuse** | 평가 메트릭 대시보드, 비용 추적, 세션별 품질 점수 기록 |
| **Streamlit** | KPI 시각화 대시보드, 실험 결과 비교 UI |

---

## 목표 기준 (Target)

> 프로젝트 초기에 baseline 측정 후, 개선 목표를 아래 표에 채워 넣습니다.

| KPI | Baseline | Target |
|-----|----------|--------|
| AICR | - | - |
| Top-k Hit Position | - | - |
| Empty Retrieval Rate | - | - |
| Hallucination Rate | - | - |
| '없는 정보' Precision | - | - |
| End-to-End Latency | - | - |
| P95 Latency | - | - |
