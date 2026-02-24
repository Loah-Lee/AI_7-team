# 평가 해석 보고서 (2026-02-14)

## 1) 분석 대상
- Run A: `https://smith.langchain.com/public/bdeb0728-721e-4d2e-b2b2-6407ba901653/r`
- Run B: `https://smith.langchain.com/public/e6617e25-742f-463c-985d-766663b40e55/r`
- 공통 런 이름: `eval_retrieval_run`
- 비교 기준: Retrieval 지표, LLM Judge 지표, 응답 시간, 문항별 변화

## 2) 실행 조건 차이
- Run A 입력: `use_judge=False`, `top_k=10`
- Run B 입력: `use_judge=True`, `top_k=10`

핵심: 두 런의 가장 큰 설정 차이는 LLM Judge 사용 여부이다.

## 3) 요약 결론
- Retrieval 성능은 두 런에서 동일하다.
- Judge 지표는 Run B에서만 계산되며, Run A와 직접 수치 비교는 불가능하다.
- Run B 결과상 "근거 기반성은 높고(충실성/관련성), 정답 적합성은 낮은(정확성/커버리지)" 패턴이 확인된다.

## 4) 메트릭 비교

### 공통/비교 가능한 지표
- `total_questions`: A=20, B=20
- `recall_at_k_source`: A=0.55, B=0.55
- `mrr_source`: A=0.55, B=0.55
- `recall_at_k_page`: A=0.00, B=0.00
- `mrr_page`: A=0.00, B=0.00
- `avg_response_time`: A=18.34s, B=17.82s

### Run B에서만 계산된 Judge 평균
- `avg_correctness`: 1.85 / 5
- `avg_coverage`: 1.40 / 5
- `avg_faithfulness`: 4.35 / 5
- `avg_context_relevance`: 4.35 / 5

## 5) 해석

### 5.1 Retrieval 관점
- 소스 기준 retrieval(`recall_at_k_source`, `mrr_source`)은 일정 수준(0.55) 확보됨.
- 페이지 기준 retrieval는 0.00으로 전 문항 실패.
- 해석: 문서 자체는 맞게 찾지만, 정답 페이지 정렬/매칭이 전혀 맞지 않거나 페이지 메타 정규화가 불완전할 가능성이 높다.

### 5.2 Generation 관점
- `faithfulness`/`context_relevance`는 높음(각 4.35).
- `correctness`/`coverage`는 낮음(1.85/1.40).
- 해석: 모델이 검색 문맥을 벗어나 환각하지는 않지만, 질문의 핵심 요구를 충분히 충족하지 못하는 답변을 자주 생성한다.
- 실제로 다수 문항에서 "문서에 명시되어 있지 않음" 형태의 보수적 답변이 반복되어 커버리지 점수를 깎는 패턴이 관찰된다.

### 5.3 두 런 간 변동성
- 문항 20/20에서 `generated_answer` 텍스트가 달라졌음.
- 그러나 `retrieved_docs` 순서는 20/20 동일.
- 해석: 검색 결과가 같아도 생성 단계에서 비결정성(LLM 출력 편차)이 존재한다.

## 6) 리스크
- 현재 지표 구조에서는 Retrieval 개선 없이도 Generation 단계에서 점수 편차가 크게 발생할 수 있다.
- Page-level 평가가 0.00이면, 문서 근거의 정밀 추적/감사 가능성이 낮다.
- Judge OFF 런과 ON 런을 같은 리포트 축에서 단순 비교하면 해석 오류가 생길 수 있다.

## 7) 개선 권고 (우선순위)

1. 페이지 메타 정합성 점검
- `ground_truth.page`와 인덱싱 `metadata.page`의 타입/오프셋(1-base vs 0-base) 일치 여부 확인.
- 파일명 정규화(공백/특수문자/확장자 표기 차이) 룰 통일.

2. 답변 정책 개선
- "명시되어 있지 않음" 반환 조건을 강화하여 조기 포기 응답을 줄이고, 근거 문장 인용 후 제한적 추론을 허용.
- 질문 유형별 템플릿(사실 질의 vs 비교 질의 vs 절차 질의) 분기 강화.

3. 평가 일관성 확보
- 실험 비교 시 `use_judge`를 고정(항상 ON 또는 항상 OFF)하여 동일 조건에서만 비교.
- `judge_model`, `top_k`, 데이터셋 버전 태깅을 런 메타데이터에 고정 기록.

4. 재현성 강화
- Generation 파라미터(temperature, max tokens) 고정.
- 동일 입력에서 n회 반복 평가 후 평균/분산 병행 기록.

## 8) 다음 실험 제안
- E1: 페이지 메타 정규화 패치 후 `recall_at_k_page`, `mrr_page` 재측정
- E2: 답변 정책 패치 후 `avg_correctness`, `avg_coverage` 개선 확인
- E3: 동일 설정 3회 반복으로 점수 분산(안정성) 측정

## 9) 2026-02-14 재실행 업데이트 (코드 개선 반영)

### 9.1 반영한 개선
- `src/evaluation/metrics.py`
  - source 문자열 정규화 매칭(`NFKC`, 공백 정리, 포함 매칭)
  - page 매칭 시 ±1 오프셋 허용
- `src/graph/workflow.py`
  - LLM이 과도하게 "명시 없음"으로 답할 때 규칙 기반 fallback 보완
  - 근거 라인 추출 실패 시 의무/요구 표현 기반 2차 추출
- `src/prompts/templates.py`
  - "명시 없음" 단정 전 관련 조항 우선 제시하도록 지시 완화

### 9.2 재실행 결과 파일
- 전체 20문항, Judge OFF: `eval/eval_results_rerun_2026-02-14_improve_full.json`
- 샘플 5문항, Judge OFF: `eval/eval_results_rerun_2026-02-14_improve_first5.json`
- 샘플 5문항, Judge ON: `eval/eval_results_rerun_2026-02-14_improve_first5_judge.json`

### 9.3 지표 변화 요약
- 전체 20문항 (Judge OFF):
  - `recall_at_k_source=0.55` (변화 없음)
  - `mrr_source=0.55` (변화 없음)
  - `recall_at_k_page=0.00` (변화 없음)
  - `mrr_page=0.00` (변화 없음)
  - `avg_response_time=21.53s` (증가)
- 샘플 5문항 (Judge OFF):
  - `recall_at_k_source=0.80`, `mrr_source=0.80`
  - `recall_at_k_page=0.00`, `mrr_page=0.00`
- 샘플 5문항 (Judge ON) vs 기존 judgefix 첫 5문항:
  - `correctness`: `0.4 -> 1.2` (상승)
  - `coverage`: `0.2 -> 1.0` (상승)
  - `faithfulness`: `4.2 -> 3.2` (하락)
  - `context_relevance`: `4.0 -> 3.8` (소폭 하락)

### 9.4 해석 업데이트
- 개선 패치는 "보수적 미응답 감소"에는 효과가 있었고, 샘플 기준 정확성/커버리지를 끌어올렸다.
- 하지만 page-level retrieval는 여전히 `0.00`으로, 핵심 구조적 병목(페이지 정합성)은 해소되지 않았다.
- 정확성/커버리지를 올리는 과정에서 faithfulness가 일부 낮아져, 근거 엄밀성과 답변 완결성의 trade-off가 발생했다.
- 다음 우선순위는 page 메타데이터 정합성(인덱싱/GT 기준 통일) 복구다.

## 10) 2026-02-14 최신화 (HWP 강제 PDF 변환 반영)

### 10.1 실행 내용
- HWP/HWPX를 강제 PDF 변환(fallback renderer 포함)한 상태로 평가 재실행
- 실행 명령: `scripts/eval_retrieval.py --label force_pdf_2026-02-14 --dataset eval_resources/eval_dataset.yaml --output eval/eval_results.json --no-judge`
- 결과 리포트 재생성: `scripts/build_eval_report.py --input eval/eval_results.json --output eval/eval_report.html`

### 10.2 최신 지표
- `total_questions=20`
- `recall_at_k_source=0.55`
- `mrr_source=0.55`
- `recall_at_k_page=0.00`
- `mrr_page=0.00`
- `avg_response_time=23.34s`

### 10.3 해석
- 소스 기준 retrieval는 기존과 동일(0.55)하며, 강제 PDF 변환만으로 소스 검색 성능의 즉각적 상승은 관찰되지 않음.
- 페이지 지표는 여전히 0.00으로, page-level 정합성 이슈가 주요 병목으로 유지됨.
- 이번 최신화의 핵심 효과는 "HWP 변환 실패로 평가가 중단되지 않음"이라는 안정성 확보에 있음.

## 11) Judge ON/OFF 비교표 (2026-02-14 최신)

### 11.1 비교 대상
- Judge OFF: `eval/eval_results.json` (`label=force_pdf_2026-02-14`)
- Judge ON: `eval/eval_results_force_pdf_judge_2026-02-14.json` (`label=force_pdf_2026-02-14_judge`)

### 11.2 메트릭 비교
| metric | Judge OFF | Judge ON |
|---|---:|---:|
| total_questions | 20 | 20 |
| avg_response_time (s) | 23.34 | 20.87 |
| recall_at_k_source | 0.55 | 0.55 |
| recall_at_k_page | 0.00 | 0.00 |
| mrr_source | 0.55 | 0.55 |
| mrr_page | 0.00 | 0.00 |
| avg_correctness | - | 1.85 |
| avg_coverage | - | 1.50 |
| avg_faithfulness | - | 4.00 |
| avg_context_relevance | - | 4.25 |

### 11.3 해석
- Retrieval 지표는 Judge ON/OFF에서 동일하다. 즉, Judge는 "평가 계산"에만 영향을 주고 검색 결과 자체를 바꾸지 않는다.
- Judge ON에서 추가 확인된 품질 패턴은 기존과 동일하게 `정확성/커버리지 낮음`, `충실성/문맥관련성 높음`이다.
- 이번 기준에서는 Judge ON 평균 응답 시간이 OFF보다 짧게 나왔지만(20.87s vs 23.34s), 실행 시점/외부 API 지연 변동 영향이 있어 성능 우열의 근거로 단정하지 않는다.

## 12) 성능 개선 개편(v2) 적용 결과

### 12.1 코드 개편 요약
- `src/graph/workflow.py`
  - 기관명 매칭 강화: 공백/특수문자/정규화(NFKC) 기반 매칭 추가
  - 검색 전략 개편: 원본 문서(PDF/HWP) 우선 검색 + 키워드 확장 강화
  - 결과 재랭킹 추가: 질문 키워드/기관 일치도/원본 문서 가중치 기반 정렬
  - 컨텍스트 압축 개선: 질문 관련 문장 우선 추출 후 LLM 입력
  - fallback 답변 개선: 수치/기한/주기/용량/가이드 직접 추출 로직 추가
- `src/prompts/templates.py`
  - 사실형 질의(수치/기한/단위)에서 값 우선 답변하도록 규칙 강화
  - 메타성 답변(“관련 문서를 찾았다”) 금지 지시 추가

### 12.2 Judge ON 기준 v1 -> v2 비교
- v1: `eval/eval_results_force_pdf_judge_2026-02-14.json`
- v2: `eval/eval_results_force_pdf_judge_2026-02-14_v2.json`

| metric | v1 | v2 | delta |
|---|---:|---:|---:|
| recall_at_k_source | 0.55 | 0.90 | +0.35 |
| recall_at_k_page | 0.00 | 0.05 | +0.05 |
| mrr_source | 0.55 | 0.90 | +0.35 |
| mrr_page | 0.00 | 0.0083 | +0.0083 |
| avg_correctness | 1.85 | 2.00 | +0.15 |
| avg_coverage | 1.50 | 1.60 | +0.10 |
| avg_faithfulness | 4.00 | 3.90 | -0.10 |
| avg_context_relevance | 4.25 | 4.70 | +0.45 |
| avg_response_time (s) | 20.87 | 35.73 | +14.86 |

### 12.3 해석
- 정확성/커버리지는 소폭 개선되었고(`+0.15`, `+0.10`), 검색 지표는 크게 개선되었다.
- 반면 응답 시간이 증가했고, 충실성은 소폭 하락했다.
- 즉, 현재 v2는 “정답 근접도↑ / 속도↓” 트레이드오프 상태다.
- 다음 최적화 포인트는 확장 질의 수와 컨텍스트 길이 축소를 통한 지연 시간 회수다.

---
작성일: 2026-02-14  
최종 업데이트: 2026-02-14  
기준 런: `bdeb0728-721e-4d2e-b2b2-6407ba901653`, `e6617e25-742f-463c-985d-766663b40e55`
최신 로컬 결과: `eval/eval_results.json` (label=`force_pdf_2026-02-14`)
