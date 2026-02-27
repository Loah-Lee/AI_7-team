# 발표용 실험 순서 재정리 (DB Handoff ~ 현재)

## 기준
- 근거 문서:
  - `eval_resources/ab_integrated_experiment_log_db_handoff_to_now.md`
  - `origin/dev:eval_resources/SESSION_TIMELINE_DB_HANDOFF_TO_NOW_2026-02-26.md`
- 정렬 원칙:
  - 타임라인 순서 우선
  - 레이턴시 실험은 `CSV 숏서킷 -> 2트랙 구축 -> 2트랙 개선`으로 묶어 배치

## 최종 발표 순서
1. 실험 1: 평가 정합화 기준선 확립
2. 실험 2: CSV short-circuit 저지연 경로 구축
3. 실험 3: 2트랙 생성 경로 구축(근거추출 + 생성 재진입)
4. 실험 4: 2트랙 개선(extractive 우선, 생성 스킵)
5. 실험 5: DB handoff 검증으로 데이터 영향 분리
6. 실험 6: chunk recall 개선(측정 정합 + 개선 시도 분리)
7. 실험 7: #017 목적형 개선(표/이미지 수치 추출)
8. 실험 8: evidence-bounded generation 확정

---

## 1) 실험 1: 평가 정합화 기준선 확립
핵심: "먼저 측정이 맞아야 개선이 맞다."

| 지표 | A (before_dev) | B (current_patch) | 변화율 |
|---|---:|---:|---:|
| Correctness | 1.80 | 3.75 | +108.33% |
| Answer Coverage | 1.60 | 3.35 | +109.38% |
| Faithfulness | 3.95 | 4.35 | +10.13% |
| Context Relevance | 3.75 | 4.65 | +24.00% |
| Recall@5 (source) | 0.75 | 0.90 | +20.00% |
| MRR (source) | 0.75 | 0.90 | +20.00% |
| 매크로(C/AC/F/CR) | 2.775 | 4.025 | +45.05% |

전환: "지표 정합화가 끝났으니, 성능/속도 병목을 줄이는 실험으로 이동."

---

## 2) 실험 2: CSV short-circuit 저지연 경로 구축
핵심: "CSV 질의는 무거운 경로를 타지 않게 분기."

비교 기준: `eval_results_current_full20_evidence_strict.json` 내 CSV vs Non-CSV 평균

| 단계 레이턴시 | CSV | Non-CSV | 변화율(CSV 기준) |
|---|---:|---:|---:|
| analyze_query | 1.7196s | 11.2681s | -84.74% |
| retrieve | 0.0000s | 0.5941s | -100.00% |
| extract_evidence | 0.0000s | 0.0371s | -100.00% |
| generate | 0.0000s | 25.2148s | -100.00% |

전환: "CSV는 분기됐지만, 일반 질의는 2트랙 생성으로 여전히 느림."

---

## 3) 실험 3: 2트랙 생성 경로 구축(근거추출 + 생성 재진입)
핵심: "근거 추출 후 생성 재진입 2트랙을 도입했더니, 생성 단계 지연이 커짐."

비교 기준: `current_patch -> dev_dataset_latest` (타임라인 기준)

| 지표 | A (current_patch) | B (dev_dataset_latest) | 변화율 |
|---|---:|---:|---:|
| Correctness | 3.75 | 3.60 | -4.00% |
| Answer Coverage | 3.35 | 3.45 | +2.99% |
| Recall@5 (source) | 0.90 | 1.00 | +11.11% |
| MRR (source) | 0.90 | 0.95 | +5.56% |
| Faithfulness | - | 4.25 | - |
| Context Relevance | - | 4.80 | - |

추가 관측(구축 후 baseline): 총 latency `20.314s`, 평균 generate `17.28s`.

전환: "2트랙 과개입을 줄이기 위해 extractive 우선 정책으로 개선."

---

## 4) 실험 4: 2트랙 개선(extractive 우선, 생성 스킵)
핵심: "extractive_draft가 있으면 생성을 스킵해 지연을 절반 수준으로 축소."

비교 기준: `dev_dataset_latest -> extractive_only_20260226`

| 지표 | A (dev_dataset_latest) | B (extractive_only) | 변화율 |
|---|---:|---:|---:|
| Correctness | 3.60 | 3.70 | +2.78% |
| Answer Coverage | 3.45 | 3.60 | +4.35% |
| Faithfulness | 4.25 | 4.10 | -3.53% |
| Context Relevance | 4.80 | 4.75 | -1.04% |
| Recall@5 (source) | 1.00 | 1.00 | +0.00% |
| MRR (source) | 0.95 | 0.95 | +0.00% |
| 총 latency | 20.314s | 10.886s | -46.41% |
| 평균 generate | 17.28s | 8.31s | -51.91% |
| answer_mode generative 개수 | 6 | 1 | -83.33% |

전환: "속도 구조가 안정화됐으니, 데이터 영향(DB)을 분리 검증."

---

## 5) 실험 5: DB handoff 검증으로 데이터 영향 분리
핵심: "코드보다 DB 품질이 결과를 크게 좌우."

| 지표 | A (testdb_20260226) | B (backupdb_20260226) | 변화율 |
|---|---:|---:|---:|
| Correctness | 1.20 | 3.75 | +212.50% |
| Answer Coverage | 1.00 | 3.50 | +250.00% |
| Recall@5 (source) | 0.20 | 0.90 | +350.00% |
| MRR (source) | 0.20 | 0.90 | +350.00% |

전환: "source hit 이후에는 chunk hit 개선이 다음 과제."

---

## 6) 실험 6: chunk recall 개선(측정/개선 분리 보고)
핵심: "chunk recall은 별도 지표로 관리하고, 품질 트레이드오프를 함께 본다."

### 6-1) 측정 정합(라벨 보정)

| 지표 | A (chunk_labeled_fix) | B (chunk_manual_gt) | 변화율 |
|---|---:|---:|---:|
| Recall@5 (chunk) | 0.0000 | 0.4286 | +0.4286p (절대) |
| Correctness | 3.80 | 3.95 | +3.95% |
| Answer Coverage | 3.55 | 3.65 | +2.82% |
| Faithfulness | 4.50 | 4.45 | -1.11% |
| Context Relevance | 4.65 | 4.70 | +1.08% |
| 매크로(C/AC/F/CR) | 4.1250 | 4.1875 | +1.52% |

### 6-2) 개선 시도(subset 재정렬)

| 지표 | A (p1_dedupe_subset) | B (p4_clean_subset) | 변화율 |
|---|---:|---:|---:|
| Recall@5 (chunk) | 0.00 | 0.25 | +0.25p (절대) |
| Correctness | 3.12 | 2.88 | -7.69% |
| Answer Coverage | 2.75 | 2.62 | -4.73% |
| Faithfulness | 4.62 | 4.12 | -10.82% |
| Context Relevance | 4.75 | 4.75 | +0.00% |

전환: "평균 점수 외에 목적형 단건 개선을 별도로 검증."

---

## 7) 실험 7: #017 목적형 개선(표/이미지 수치 추출)
핵심: "평균이 아니라 목적형 KPI 단건 성공을 증명."

| 지표 (#017) | A (focus6_after_patch) | B (full20_after_patch_v2) | 변화율 |
|---|---:|---:|---:|
| Correctness | 4 | 5 | +25.00% |
| Answer Coverage | 4 | 5 | +25.00% |
| Faithfulness | 4 | 5 | +25.00% |
| Context Relevance | 5 | 5 | +0.00% |

전환: "마지막 단계는 생성 후단 신뢰성 고정."

---

## 8) 실험 8: evidence-bounded generation 확정
핵심: "근거 밖 문장 생성 억제로 신뢰성 향상."

| 지표 | A (full20_after_patch_v2) | B (full20_evidence_strict) | 변화율 |
|---|---:|---:|---:|
| Correctness | 3.95 | 3.95 | +0.00% |
| Answer Coverage | 3.85 | 3.85 | +0.00% |
| Faithfulness | 4.05 | 4.30 | +6.17% |
| Context Relevance | 4.70 | 4.80 | +2.13% |
| 매크로(C/AC/F/CR) | 4.1375 | 4.2250 | +2.11% |

마무리: "측정 정합 -> 레이턴시 구조 개선 -> 데이터 영향 분리 -> chunk recall 관리 -> 목적형 개선 -> 생성 신뢰성 고정 순으로 체계를 완성."
