# LLM-as-Judge E2E 평가 체계 구축 및 실행 리포트

**일시:** 2026-02-10 13:00 ~ 13:30 (평가 실행: ~26분)
**작업자:** Claude Opus 4.6

---

## 1. User Prompt

> RAG 평가 체계를 LLM-as-Judge 기반 End-to-End로 재설계하고, 평가 실행 및 디버깅, ai_history 작성

---

## 2. Thinking Process

### 2.1 기존 문제 진단

기존 `eval_retrieval.py`의 치명적 한계:
- **source 매칭만으로 Recall 판정** → top-5에 정답 문서가 "포함"만 되면 Recall=1.0
- **유사도 점수 0.48~0.57로 균일** → 정답/오답 문서 구별 불가
- **답변 품질 미평가** → Recall 1.0이어도 "근거 없음" 답변 가능
- 즉, 검색 지표만으로는 RAG 시스템의 실제 성능을 측정할 수 없음

### 2.2 설계 결정

1. **LLM-as-Judge 도입**: 3가지 독립 지표(Correctness, Faithfulness, Relevance)로 채점
2. **E2E 파이프라인**: `build_graph().invoke()` 전체 실행 → 실제 답변 기반 평가
3. **기존 Retrieval 지표 보존**: Hit Rate@K, MRR은 보조 지표로 병행

### 2.3 디버깅 과정 (3차 실행만에 성공)

| 차수 | 문제 | 원인 | 수정 |
|---|---|---|---|
| 1차 | 파싱 실패 5/20건 (0점 처리) | Judge LLM이 JSON 대신 텍스트 응답 | `response_format: json_object` 추가 |
| 2차 | 3번째 질문에서 크래시 | `LengthFinishReasonError` (reasoning_tokens가 max_tokens=1024 초과) | `max_tokens` 1024→4096, Exception catch 추가 |
| 3차 | 성공 (파싱 실패 0건) | — | — |

**추가 개선:**
- context 길이를 6000자로 제한 (Judge 입력 안정성)
- 재시도 로직 2회 (파싱 실패 + LLM 호출 에러 모두 처리)

---

## 3. Execution Result

### 3.1 최종 평가 결과 (Summary)

| 지표 | 값 | 설명 |
|---|---|---|
| **Avg Correctness** | **3.70 / 5** | 답변 ↔ 기대답변 의미 일치 |
| **Avg Faithfulness** | **4.85 / 5** | context 근거 충실도 (환각 거의 없음) |
| **Avg Relevance** | **4.25 / 5** | 검색 문서의 질문 관련성 |
| Hit Rate@5 | 0.9000 | 정답 문서 포함률 |
| MRR | 0.9000 | 평균 역순위 |
| 소요 시간 | 1584.4초 (~26분) | 20개 질문 |

### 3.2 질의 유형별 분석

| 유형 | 건수 | Correctness | Faithfulness | Relevance |
|---|---|---|---|---|
| **single_doc** | 12 | 4.00 | 4.92 | 4.42 |
| **multi_doc** | 4 | 3.50 | 4.75 | 4.25 |
| **comparison** | 4 | 3.00 | 4.75 | 3.75 |

### 3.3 핵심 인사이트

1. **Faithfulness가 압도적으로 높음 (4.85)** → RAG가 환각 없이 context 기반 답변 생성
2. **Correctness가 상대적으로 낮음 (3.70)** → 정답 청크를 검색하지 못해 답변 자체가 불완전
3. **single_doc > multi_doc > comparison 순** → 복잡한 질문일수록 성능 하락
4. **저조 항목 공통 패턴**: 정답이 특정 페이지에만 있는데 해당 청크가 top-5에 미포함

### 3.4 저조 항목 (Correctness ≤ 2)

| ID | 유형 | C | 문제 |
|---|---|---|---|
| eval_002 | single_doc | 2 | "월 1회 교육" 정보가 검색된 청크에 없음 (page 45인데 page 8,10 검색) |
| eval_010 | single_doc | 1 | "12시간 이내 복구" 정보가 검색 결과에 미포함 |
| eval_012 | single_doc | 1 | "UTF-8" 정보가 검색 결과에 미포함 |
| eval_017 | comparison | 2 | 두 문서 비교 시 한쪽 문서 내용만 검색됨 |
| eval_020 | comparison | 2 | 구미 입찰서약서의 제재조항(담합·뇌물) 미검색 |

### 3.5 이전 평가 대비 개선

| 항목 | 이전 (source 매칭) | 현재 (LLM Judge) |
|---|---|---|
| 평가 방식 | Recall@K (source 포함 여부만) | Correctness + Faithfulness + Relevance |
| 답변 품질 평가 | 없음 | LLM Judge 0~5점 |
| 파이프라인 | 검색만 (`search_with_metadata`) | 전체 E2E (`build_graph().invoke()`) |
| 환각 탐지 | 불가 | Faithfulness 지표로 정량화 |
| 파싱 실패 | N/A | 0건 (JSON 모드 + 재시도) |

---

## 4. Evidence of Execution

### 생성된 파일
- `src/evaluation/llm_judge.py` — LLM-as-Judge 모듈 (신규)
- `scripts/eval_retrieval.py` — E2E 평가 스크립트 (전면 재작성)
- `eval/eval_results_current.json` — 평가 결과 (20개 질문, per_query 포함)

### 터미널 출력 (최종)
```
============================================================
평가 결과 (label=current)
------------------------------------------------------------
  [LLM Judge 점수 (0~5)]
    Correctness:   3.70
    Faithfulness:  4.85
    Relevance:     4.25
  [Retrieval 보조 지표]
    Hit Rate@5:   0.9000
    MRR:            0.9000
  평가 건수: 20/20
  소요 시간: 1584.4초
============================================================
[저장] eval/eval_results_current.json
```

---

## 5. 다음 단계 제안

1. **Correctness 개선** → 저조 항목의 정답 페이지가 검색되지 않는 문제 해결 (chunking 전략, metadata 필터 정확도)
2. **comparison 유형 강화** → multi-doc 질문 시 양쪽 문서를 모두 검색하도록 쿼리 분해 로직 추가
3. **평가셋 확장** → 현재 20개 → 50개+ (유형별 균등 분포)
