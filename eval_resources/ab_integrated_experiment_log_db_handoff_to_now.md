# 통합 실험 로그 (DB Handoff 이후 ~ 현재)

## 선택 기준
- 유효한 변화가 도출되기까지의 유효 실험만 포함
- AI 직무 포트폴리오에 넣을 수 있는 재현성/측정가능성/트레이드오프 관리가 확인된 실험만 포함
- 정리 형식: 문제 / 수정내용 / 결과(변화율)

## 근거 문서
- `origin/dev:eval_resources/SESSION_TIMELINE_DB_HANDOFF_TO_NOW_2026-02-26.md`
- `eval_resources/ab_success_experiments_post_newdb_sync.md`
- `eval_resources/eval_results_*.json` (로컬 평가 산출물)

---

## 실험 1 (2026-02-25 15:23 ~ 21:19) - 멀티소스 평가 정합화
- 문제:
  멀티소스 질의에서 source 확장자/표기 차이로 hit/recall/mrr가 왜곡됨.
- 수정내용:
  `c86f826`, `6fd2f39`, `127bcb5`, `233341a`
  (multi-source Recall@K/MRR 지원, strict hit_position, source 동치 비교)
- 결과(변화율):
  `before_dev -> current_patch` 기준
  C `1.80 -> 3.75` (**+108.33%**), AC `1.60 -> 3.35` (**+109.38%**),
  F `3.95 -> 4.35` (**+10.13%**), CR `3.75 -> 4.65` (**+24.00%**),
  Recall `0.75 -> 0.90` (**+20.00%**), MRR `0.75 -> 0.90` (**+20.00%**),
  매크로(C/AC/F/CR) `2.775 -> 4.025` (**+45.05%**).
- 포트폴리오 포인트:
  "평가 지표 신뢰도(정합성) 확보"를 먼저 해결한 실험으로, 이후 개선 실험의 해석 가능성을 만든 단계.

## 실험 2 (2026-02-25 15:23 ~ 2026-02-26 14:50) - 멀티독 #019~#020 Hit 개선(필수)
- 문제:
  멀티독(정답 source 2개)에서 하나만 맞아도 miss 처리되거나 반대로 과대평가되는 불일치가 존재.
- 수정내용:
  `c86f826`, `127bcb5`, `233341a`, `07013fc`
  (strict multi-source hit_position + source 동치 비교 + robust 매칭)
- 결과(변화율):
  `eval_results_p2_full20_recheck.json -> eval_results_current_019_020_r1.json`
  #019: `hit None -> 2`, `recall 0.0 -> 1.0` (절대 +1.0)
  #020: `hit None -> 2`, `recall 0.0 -> 1.0` (절대 +1.0)
  2문항 평균 MRR: `0.0 -> 0.5` (절대 +0.5).
- 포트폴리오 포인트:
  "복수 정답 조건"을 지표 로직에 맞게 엄밀하게 반영한 케이스.

## 실험 3 (2026-02-25 22:07 ~ 2026-02-26 14:50) - CSV short-circuit 저지연 경로 확립(필수)
- 문제:
  CSV 질의도 일반 검색/생성 경로를 타며 지연시간이 불필요하게 커지고, CSV 경로의 평가 반영도 불완전.
- 수정내용:
  `f0ab7f3`, `7db206a`, `0278d9b`, `07013fc`
  (csv_short_circuit 집계, CSV 동적 응답 강화, latencies 전달, CSV retrieved_docs 합성)
- 결과(변화율):
  `eval_results_current_reval_dev_latest.json` 기준
  CSV vs Non-CSV 평균 latency
  analyze `0.0166s vs 0.1030s` (**-83.88%**),
  retrieve `0.0000s vs 0.4782s` (**-100%**),
  extract `0.0000s vs 0.0581s` (**-100%**).
  `eval_results_current_full20_evidence_strict.json` 기준
  analyze `1.7196s vs 11.2681s` (**-84.74%**),
  retrieve `0.0000s vs 0.5941s` (**-100%**),
  generate `0.0000s vs 25.2148s` (**-100%**).
- 포트폴리오 포인트:
  규칙 기반 fast-path로 비용/시간을 절감하면서도 평가 지표와 정합을 유지한 실전형 최적화.

## 실험 4 (2026-02-26 09:39 ~ 14:12) - DB handoff 검증 및 리트리버 안정화
- 문제:
  DB 버전 변경 시 점수가 급락하여, 코드 변경 효과와 DB 품질 효과가 섞여 해석 불가.
- 수정내용:
  `048d68a`, `d6ca724`, `f5cc477`, `e5a18a4`
  (single-doc ranking/fallback 정밀화, anchor chunk 강화, source metadata 정규화, source-based fallback)
- 결과(변화율):
  `testdb_20260226 -> backupdb_20260226`
  C `1.20 -> 3.75` (**+212.50%**),
  AC `1.00 -> 3.50` (**+250.00%**),
  Recall `0.20 -> 0.90` (**+350.00%**),
  MRR `0.20 -> 0.90` (**+350.00%**).
- 포트폴리오 포인트:
  "모델/알고리즘 이전에 데이터/인덱스 품질 검증"의 중요성을 수치로 분리해 보여준 실험.

## 실험 5 (2026-02-26 15:17 ~ 19:17) - 유효 패치 묶음(15~19시)
- 문제:
  단건 패치 효과가 약해 보이고, 근거 품질/중복 제거/출력 안정성이 분산되어 있음.
- 수정내용:
  `f5ebb82`, `685d36b`, `f5f3d31`
  (리포트 구조 보존, extractive_draft 우선, evidence rerank + chunk-aware dedupe)
- 결과(변화율):
  `eval_results_current_reval_dev_latest.json -> eval_results_current_reval_full20_after_rebase.json`
  C `3.75 -> 3.85` (**+2.67%**),
  AC `3.60 -> 3.75` (**+4.17%**),
  F `4.35 -> 4.60` (**+5.75%**),
  CR `4.55 -> 4.50` (**-1.10%**),
  매크로 `4.0625 -> 4.175` (**+2.77%**).
- 포트폴리오 포인트:
  성능/가독성/근거품질 패치를 묶어 배포했을 때의 실효 개선을 제시한 운영형 실험.

## 실험 6 (2026-02-26 18:26 ~ 18:50) - 생성 정책: extractive 우선(프롬프트/그래프)
- 문제:
  생성 과개입으로 장황화/누락이 발생하고 지연시간이 커짐.
- 수정내용:
  `685d36b` 중심 (extractive_draft 존재 시 생성 스킵)
- 결과(변화율):
  `dev_dataset_latest -> extractive_only_20260226`
  C `3.60 -> 3.70` (**+2.78%**),
  AC `3.45 -> 3.60` (**+4.35%**),
  F `4.25 -> 4.10` (**-3.53%**),
  CR `4.80 -> 4.75` (**-1.04%**),
  Recall/MRR 변화 없음,
  Total latency `20.314s -> 10.886s` (**-46.41%**).
- 포트폴리오 포인트:
  지연시간 절감과 품질지표(F/CR) 트레이드오프를 정량적으로 제시한 정책 실험.

## 실험 7 (목적형, 필수) - #017 표/이미지 정보 활용 개선
- 문제:
  #017은 일반 질의와 달리 표/이미지 기반 수치 추출 정확도가 핵심.
- 수정내용:
  #017 목적형 경로 점검 및 근거 추출 안정화 패치 반영 후 단건 비교.
- 결과(변화율):
  `eval_results_current_focus6_after_patch.json -> eval_results_current_full20_after_patch_v2.json` (#017 단건)
  C `4 -> 5` (**+25.00%**),
  AC `4 -> 5` (**+25.00%**),
  F `4 -> 5` (**+25.00%**),
  CR `5 -> 5` (**+0.00%**).
- 포트폴리오 포인트:
  전체 평균이 아니라 "목적형 KPI"로 성공 여부를 판정한 타겟 실험 사례.

## 실험 8 (2026-02-27 10:36) - 최종 생성단 evidence-bounded 확정
- 문제:
  생성 후단에서 문맥 밖 문장으로 Faithfulness 변동이 발생.
- 수정내용:
  `b1e3439`
  (evidence-bounded generation 강제, 생성 후단 제약)
- 결과(변화율):
  `eval_results_current_full20_after_patch_v2.json -> eval_results_current_full20_evidence_strict.json`
  C `3.95 -> 3.95` (**+0.00%**),
  AC `3.85 -> 3.85` (**+0.00%**),
  F `4.05 -> 4.30` (**+6.17%**),
  CR `4.70 -> 4.80` (**+2.13%**),
  매크로 `4.1375 -> 4.225` (**+2.11%**).
- 포트폴리오 포인트:
  정확도 손실 없이 신뢰성(F)과 맥락 적합성(CR)을 끌어올린 생성단 마감 실험.

## 실험 9 (통합) - Chunk Recall 개선(지표 정합 + 후보 재정렬)
- 문제:
  source-level 지표는 높은데 chunk-level 정답 일치율이 낮아, 리트리버 개선 포인트가 가려짐.
- 수정내용:
  1) `c74f099` + chunk 라벨 보정
  (chunk-level Recall 지표 추가, 라벨링/수동 GT 정합화)
  2) p1~p5 subset A/B
  (dedupe baseline -> neighbor 확장/boost -> clean/orgscan/source-evidence 재정렬)
- 결과(변화율):
  A. 지표/라벨 정합화
  `eval_results_current_reval_chunk_labeled_fix.json -> eval_results_current_reval_chunk_manual_gt.json`
  Recall@5_chunk `0.0000 -> 0.4286` (절대 +0.4286p, 라벨 문항 16 -> 14 재정의),
  C `3.80 -> 3.95` (**+3.95%**), AC `3.55 -> 3.65` (**+2.82%**),
  F `4.50 -> 4.45` (**-1.11%**), CR `4.65 -> 4.70` (**+1.08%**),
  매크로 `4.125 -> 4.1875` (**+1.52%**).
  B. 후보 재정렬(subset 실험)
  `eval_results_current_p1_dedupe_chunk_subset.json -> eval_results_current_p4_clean_subset.json` (8문항 subset)
  Recall@5_chunk `0.00 -> 0.25` (절대 +0.25p),
  C `3.12 -> 2.88` (**-7.69%**), AC `2.75 -> 2.62` (**-4.73%**),
  F `4.62 -> 4.12` (**-10.82%**), CR `4.75 -> 4.75` (**0.00%**).
  (참고: `p4 -> p4_orgscan`에서 C/AC 일부 회복, chunk recall은 0.25 유지)
- 포트폴리오 포인트:
  \"평가 정합(측정)\"과 \"리트리버 재정렬(개선)\"을 분리해 실험하고, chunk recall과 LLM 품질의 충돌을 정량적으로 보여준 사례.

---

## 최종 요약 (포트폴리오 관점)
- 실험 설계 역량:
  지표 정합 -> DB 검증 -> 경로 최적화 -> 생성 제약까지 단계형 실험 설계.
- 엔지니어링 역량:
  소스 동치 비교, strict multi-source 평가, CSV fast-path, latency 계측 표준화 구현.
- 운영 역량:
  "정확도/커버리지/신뢰성/지연"의 상충을 수치로 공개하고 정책을 선택.
- 재현성:
  각 실험은 커밋 해시와 평가 파일 쌍(A/B)으로 역추적 가능.
