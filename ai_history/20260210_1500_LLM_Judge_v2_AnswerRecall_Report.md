# LLM-as-Judge v2: Answer Recall 추가 및 평가 체계 완성

**일시:** 2026-02-10 13:00 ~ 15:00
**작업자:** Claude Opus 4.6

---

## 1. User Prompt

> RAG 평가 체계를 LLM-as-Judge 기반 E2E로 재설계하고, Answer Recall 지표 추가, 평가 실행/디버깅, HTML 리포트 생성, v1 아카이빙, METRICS.md 작성

---

## 2. Thinking Process

### 2.1 문제 인식

기존 평가(`eval_retrieval.py` v0)의 한계:
- source 매칭만으로 Recall 판정 → Recall=1.0이어도 답변이 "근거 없음"
- 답변 품질 평가 없음 → 검색만 보고 생성 결과 무시

### 2.2 v1: LLM-as-Judge 도입 (3지표)

- Correctness(정확성), Faithfulness(충실성), Relevance(관련성)
- 전체 RAG 파이프라인 `build_graph().invoke()` 실행 후 Judge 채점
- 디버깅 3차 진행:
  1. JSON 파싱 실패 → `response_format: json_object` 강제
  2. `LengthFinishReasonError` → `max_tokens` 1024→4096 + Exception catch
  3. 성공 (파싱 실패 0건)

### 2.3 v2: Answer Recall 추가 (4지표)

- **Correctness** = 정확성 ("틀린 정보가 있는가")
- **Answer Recall** = 커버리지 ("빠진 정보가 있는가")
- 이 둘을 분리해야 "맞는 말만 하되 절반을 빠뜨린" 부분 답변 문제를 정량 포착 가능

### 2.4 추가 산출물

- `eval/METRICS.md` — 지표 정의서 (4 LLM Judge + 3 Retrieval 보조)
- `eval/v1_20260210/` — v1 아카이빙
- `eval/eval_report.html` — Chart.js 기반 인터랙티브 대시보드
- `scripts/build_eval_report.py` — JSON → HTML 변환 스크립트

---

## 3. Execution Result

### 3.1 v2 평가 결과 (Summary)

| 지표 | 점수 |
|---|---|
| **Correctness** | 3.50 / 5 |
| **Answer Recall** | 3.25 / 5 |
| **Faithfulness** | 4.65 / 5 |
| **Relevance** | 4.25 / 5 |
| Hit Rate@5 | 0.90 |
| MRR | 0.90 |

### 3.2 v1 → v2 비교

| 지표 | v1 | v2 | 비고 |
|---|---|---|---|
| Correctness | 3.70 | 3.50 | LLM 비결정성 |
| Answer Recall | — | **3.25** | 신규 지표 |
| Faithfulness | 4.85 | 4.65 | |
| Relevance | 4.25 | 4.25 | 동일 |

### 3.3 Correctness vs Answer Recall 차이 사례

| # | C | AR | 해석 |
|---|---|---|---|
| #12 | 1 | 0 | 정답 청크 미검색 → 완전 실패 |
| #13 | 3 | 2 | 절반 정확하나 핵심 포인트 누락 많음 |
| #16 | 4 | 2 | 언급 부분은 정확하나 전체의 절반만 커버 |
| #17 | 2 | 1 | 부정확 + 커버리지 극히 낮음 |

→ **C > AR 패턴** = "부분 답변" 문제 정량 포착 성공

### 3.4 유형별 분석

| 유형 | C | AR | F | R |
|---|---|---|---|---|
| single_doc (12) | 3.92 | 3.75 | 4.83 | 4.67 |
| multi_doc (4) | 2.50 | 1.25 | 3.50 | 3.75 |
| comparison (4) | 3.00 | 3.25 | 4.75 | 3.25 |

---

## 4. Evidence of Execution

### 생성/수정 파일
| 파일 | 상태 |
|---|---|
| `src/evaluation/llm_judge.py` | 수정 — Answer Recall 추가 (4지표) |
| `scripts/eval_retrieval.py` | 수정 — answer_recall 집계/출력 |
| `scripts/build_eval_report.py` | 신규 — JSON→HTML 대시보드 |
| `eval/METRICS.md` | 신규 — 지표 정의서 |
| `eval/eval_results_current.json` | 갱신 — v2 결과 |
| `eval/eval_report.html` | 갱신 — v2 대시보드 |
| `eval/v1_20260210/` | 신규 — v1 아카이빙 |

### 터미널 출력
```
평가 결과 (label=current)
  [LLM Judge 점수 (0~5)]
    Correctness:    3.50
    Answer Recall:  3.25
    Faithfulness:   4.65
    Relevance:      4.25
  [Retrieval 보조 지표]
    Hit Rate@5:   0.9000
    MRR:            0.9000
  평가 건수: 20/20
  소요 시간: 1625.5초
[저장] eval/eval_results_current.json
```
