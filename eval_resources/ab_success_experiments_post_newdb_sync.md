# A/B 실험 요약 (새 DB 전환 + 싱크 안정화 이후)

## 범위
- 기간: 2026-02-26 ~ 2026-02-27
- 조건: **새 DB 적용 후**, 평가가 **싱크 오류 없이 정상 시작된 구간** 기준
- 대상: LLM Judge 4지표(C/AC/F/CR)에서 **뚜렷한 개선이 확인된 패치만**
- 보고 원칙: 변화율(%) 중심, 원점수는 보조지표로만 표기

## 계산 기준
- 변화율(%) = `(B - A) / A * 100`
- 종합 변화율(매크로) = `((C+AC+F+CR)/4)`의 A/B 변화율

---

## 실험 1 (성공)
### 커밋(시간순)
1. `f5cc477` (2026-02-26 12:03) feat(retriever): normalize source metadata and default asset sidecar off  
2. `e5a18a4` (2026-02-26 14:12) feat(retriever): source-based fallback and eval alignment  
3. `d758ebe` (2026-02-26 14:42) refactor(retrieval): dynamic strategy routing for visual/fact queries  
4. `07013fc` (2026-02-26 14:50) fix(eval): preserve csv sources and robust multi-source hit position

### 실험 이유
- 새 DB 전환 직후 `source/metadata` 불일치와 라우팅 불안정으로 평가가 흔들려,  
  검색-평가 정렬(align)과 사실 질의 라우팅 안정화가 필요했음.

### A/B
- A: `eval_results_p2_full20_recheck.json`
- B: `eval_results_current_reval_dev_latest.json`

### 결과 (변화율 중심)
- Correctness: **+134.4%** (1.60 -> 3.75)
- Answer Coverage: **+157.1%** (1.40 -> 3.60)
- Faithfulness: **+1.2%** (4.30 -> 4.35)
- Context Relevance: **+203.3%** (1.50 -> 4.55)
- 매크로(4지표 평균): **+84.7%** (2.20 -> 4.06)

### 판단
- **성공**: C/AC/CR에서 대폭 개선, 평가 정상화 구간 진입.

---

## 실험 2 (성공)
### 커밋(시간순)
1. `685d36b` (2026-02-26 19:14) fix(graph): short-circuit to extractive draft before LLM generation  
2. `f5f3d31` (2026-02-26 19:17) retriever: keep effective evidence rerank and chunk-aware dedupe

### 실험 이유
- 생성 단계에서 불필요한 재서술/누락이 발생해,  
  **추출 초안 우선(extractive-first)** + **근거 재정렬/중복제거**로 답변 충실도를 끌어올리려 함.

### A/B
- A: `eval_results_current_reval_dev_latest.json`
- B: `eval_results_current_reval_full20_after_rebase.json`

### 결과 (변화율 중심)
- Correctness: **+2.7%** (3.75 -> 3.85)
- Answer Coverage: **+4.2%** (3.60 -> 3.75)
- Faithfulness: **+5.7%** (4.35 -> 4.60)
- Context Relevance: **-1.1%** (4.55 -> 4.50)
- 매크로(4지표 평균): **+2.8%** (4.06 -> 4.17)

### 판단
- **성공**: CR 소폭 하락은 있었지만 C/AC/F가 동시 상승했고 매크로가 양(+) 개선.

---

## 메모
- 본 문서는 **커밋 단위 패치**만 포함했으며, 미커밋(worktree) 실험은 제외함.
- 참조 리포트/결과:
  - `eval_resources/eval_results_p2_full20_recheck.json`
  - `eval_resources/eval_results_current_reval_dev_latest.json`
  - `eval_resources/eval_results_current_reval_full20_after_rebase.json`
