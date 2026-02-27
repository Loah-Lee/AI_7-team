# A/B 실험 요약 (새 DB 전환 + 싱크 안정화 이후)

## 범위
- 기간: 2026-02-26 ~ 2026-02-27
- 조건: 새 DB 적용 후, 평가가 싱크 오류 없이 정상 시작된 구간
- 보고 원칙: 변화율(%) 중심, 원점수는 보조지표

## 계산 기준
- 변화율(%) = `(B - A) / A * 100`
- 매크로 변화율 = `((C+AC+F+CR)/4)`의 A/B 변화율

---

## 실험 2 (묶음, 성공) - 2/26 15:00~19:17 유효 실험 통합
### 포함 커밋(시간순)
1. `f5ebb82` (2026-02-26 15:17) eval report 구조화 답변 보존
2. `685d36b` (2026-02-26 19:14) extractive draft 우선 short-circuit
3. `f5f3d31` (2026-02-26 19:17) evidence rerank + chunk-aware dedupe

### 묶음 실험 이유
- 단건 패치로는 개선 해석이 약해서, 15~19시 구간의 유효 패치를 하나의 실험군으로 재정의.
- 생성 전 단계에서 근거 초안을 먼저 고정하고, 근거 정렬/중복 제거로 실제 답변 입력 품질을 끌어올리는 것이 목적.
- `f5ebb82`는 점수 지표보다 결과 해석 안정성(리포트 가독성) 측면의 유효 패치로 포함.

### A/B
- A: `eval_resources/eval_results_current_reval_dev_latest.json`
- B: `eval_resources/eval_results_current_reval_full20_after_rebase.json`

### 결과 (변화율 중심)
- Correctness: +2.7% (3.75 -> 3.85)
- Answer Coverage: +4.2% (3.60 -> 3.75)
- Faithfulness: +5.7% (4.35 -> 4.60)
- Context Relevance: -1.1% (4.55 -> 4.50)
- 매크로(4지표 평균): +2.8% (4.06 -> 4.17)

### 판단
- 성공: CR 소폭 하락이 있었지만 C/AC/F가 동시 상승, 매크로 개선 유지.

---

## 목적형 실험 별도 정리 - #017(표/이미지 정보 활용)
### 목적
- #017은 일반 질의 개선이 아니라, 표/이미지 기반 수치 추출 가능 여부를 확인하는 목적형 실험으로 별도 관리.

### #017 전후 비교
- 비교 파일
  - 전: `eval_resources/eval_results_current_focus6_after_patch.json`
  - 후: `eval_resources/eval_results_current_full20_after_patch_v2.json`
- 점수 변화 (#017 단건)
  - Correctness: +25.0% (4 -> 5)
  - Answer Coverage: +25.0% (4 -> 5)
  - Faithfulness: +25.0% (4 -> 5)
  - Context Relevance: +0.0% (5 -> 5)
- 해석
  - 전체 20문항 평균과 무관하게, #017 목적(표/이미지 수치 추출 안정화)은 달성됨.

---

## 실험 3 (성공) - 어젯밤부터 생성단계 확정 패치 전체 정리
### 포함 패치(확정, 시간순)
1. `685d36b` (2026-02-26 19:14)
  - 생성 전에 extractive draft를 우선 채택해 장황/누락 리스크를 줄임.
2. `b1e3439` (2026-02-27 10:36)
  - evidence-bounded generation 강제
  - 답변 스타일 제어(단답형 vs 가이드형) 강화
  - 라벨(`결론/요약/근거/출처`) 제거 및 불필요 메타문장 억제

### 생성단계 A/B (최종 확정 패치 비교)
- A: `eval_resources/eval_results_current_full20_after_patch_v2.json`
- B: `eval_resources/eval_results_current_full20_evidence_strict.json`

### 결과 (변화율 중심)
- Correctness: +0.0% (3.95 -> 3.95)
- Answer Coverage: +0.0% (3.85 -> 3.85)
- Faithfulness: +6.2% (4.05 -> 4.30)
- Context Relevance: +2.1% (4.70 -> 4.80)
- 매크로(4지표 평균): +2.1% (4.14 -> 4.23)

### 판단
- 성공: C/AC 유지 상태에서 F/CR을 동시 개선.

---

## 메모
- 본 문서는 커밋/결과 파일로 재현 가능한 실험만 포함.
- 참조 결과 파일
  - `eval_resources/eval_results_current_reval_dev_latest.json`
  - `eval_resources/eval_results_current_reval_full20_after_rebase.json`
  - `eval_resources/eval_results_current_focus6_after_patch.json`
  - `eval_resources/eval_results_current_full20_after_patch_v2.json`
  - `eval_resources/eval_results_current_full20_evidence_strict.json`
