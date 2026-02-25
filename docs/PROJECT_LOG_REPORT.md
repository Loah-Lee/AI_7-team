# 프로젝트 로그 통합 보고서 (수동 최신화, as-of 2026-02-24)

## 1) Executive Summary
- 본 문서는 자동생성이 아닌 수동 업데이트 기준으로 최신 실험 결과를 반영한다.
- baseline(20문항 Judge ON): `eval/eval_results_force_pdf_judge_2026-02-14.json`
  - `avg_correctness=1.8500`, `avg_coverage=1.5000`
- 최신 정확도 프로파일(20문항 Judge ON): `eval/eval_results_improved2_all20_judge_2026-02-23.json`
  - `avg_correctness=3.4000`, `avg_coverage=3.3000`, `avg_response_time=1.1402s`
  - 직전 full20 Judge 기준(`2.8000/2.5000`) 대비 `+0.6000/+0.8000`
- 최신 no-judge 동일 코드 프로파일: `eval/eval_results_improved2_all20_nojudge_2026-02-23.json`
  - `avg_response_time=1.0642s`, `p90=1.4414s`
  - `recall_at_k_source=0.7500`, `recall_at_k_page=0.2000`
- 최고 속도 프로파일(20문항 No-Judge): `eval/eval_results_rework_2026-02-23_all20_nojudge_impl_sources20_v2.json`
  - `avg_response_time=0.9599s`, `p90=1.2837s`
  - `recall_at_k_source=0.9500`, `recall_at_k_page=0.2500`
- 생성 evalset 프로파일(20문항 No-Judge): `eval/eval_results_generated_evalset_2026-02-24_all20_nojudge.json`
  - `avg_response_time=2.6997s`
  - `recall_at_k_source=0.6500`, `recall_at_k_page=0.6000`
- 생성 evalset 프로파일(20문항 Judge ON): `eval/eval_results_generated_evalset_2026-02-24_all20_judge.json`
  - `avg_correctness=1.6500`, `avg_coverage=1.3500`
  - `avg_faithfulness=2.5500`, `avg_context_relevance=4.1500`
  - `avg_response_time=2.8884s`
- 2026-02-23 핵심 패치:
  - 기관 경계 강화 + 사업비 오탐 방지
  - CSV strict short-circuit + lexical prefilter -> vector rerank
  - 정확도 우선 모드(`ANSWER_QUALITY_MODE`) + 정밀 사실 앵커 근거 검증

## 2) Version History 핵심 진화 요약
- `v1~v5`: 기본 RAG + OpenAI 연동
- `v6~v12`: 검색/안정화 반복
- `v13~v17`: 랭킹/비교/질문 파싱/대화 컨텍스트 확장
- `2026-02-13~02-19`: 추출 우선 응답, 하이브리드 검색, 실험 로그 체계화, 인덱스 경로 정책 개편
- `2026-02-20`: 운영 안정화(증분 인덱싱/실패 스킵/가독성/속도 개편)
- `2026-02-23`: 정확도 보호 패치(기관 경계 + 사업비 전용 추출)
- `2026-02-23`: CSV 단축 경로 + 렉시컬->벡터 하이브리드 전환
- `2026-02-23`: 정확도 우선 모드 + 정밀 사실 질의 추출 강화
- `2026-02-24`: generated evalset/issue-target 셋 구축 + judge/no-judge 회귀 기준선 추가

## 3) Experiment Ledger (ID 순)
- `EXP-2026-02-13-01`
- `EXP-2026-02-13-02`
- `EXP-2026-02-13-03`
- `EXP-2026-02-14-01`
- `EXP-2026-02-14-02`
- `EXP-2026-02-14-03`
- `EXP-2026-02-19-01`
- `EXP-2026-02-19-02`
- `EXP-2026-02-19-03`
- `EXP-2026-02-19-04`
- `EXP-2026-02-20-01`
- `EXP-2026-02-20-02`
- `EXP-2026-02-20-03`
- `EXP-2026-02-23-01`
- `EXP-2026-02-23-02`
- `EXP-2026-02-23-03`
- `EXP-2026-02-24-01`

## 4) Metric Trend Table (핵심 런)
| file | label | questions | correctness | coverage | faithfulness | context | recall(src) | recall(page) | latency(s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| eval_results_force_pdf_judge_2026-02-14.json | force_pdf_2026-02-14_judge | 20 | 1.8500 | 1.5000 | 4.0000 | 4.2500 | 0.5500 | 0.0000 | 20.8699 |
| eval_results_rework_2026-02-19_full20_judge_iter14_p60.json | rework_2026-02-19_full20_judge_iter14_p60 | 20 | 2.8000 | 2.5000 | 3.4000 | 4.2000 | 0.8500 | 0.1500 | 22.3921 |
| eval_results_improved2_all20_judge_2026-02-23.json | improved2_all20_judge_2026-02-23 | 20 | 3.4000 | 3.3000 | 3.2000 | 4.4000 | 0.7500 | 0.2000 | 1.1402 |
| eval_results_speed15_all20_nojudge_v7.json | speed15_all20_nojudge_v7 | 20 | - | - | - | - | 0.9500 | 0.1500 | 2.3154 |
| eval_results_rework_2026-02-23_all20_nojudge_impl_sources20_v2.json | rework_2026-02-23_all20_nojudge_impl_sources20_v2 | 20 | - | - | - | - | 0.9500 | 0.2500 | 0.9599 |
| eval_results_improved2_all20_nojudge_2026-02-23.json | improved2_all20_nojudge_2026-02-23 | 20 | - | - | - | - | 0.7500 | 0.2000 | 1.0642 |
| eval_results_generated_evalset_2026-02-24_all20_nojudge.json | generated_evalset_2026-02-24_all20_nojudge | 20 | - | - | - | - | 0.6500 | 0.6000 | 2.6997 |
| eval_results_generated_evalset_2026-02-24_all20_judge.json | generated_evalset_2026-02-24_all20_judge | 20 | 1.6500 | 1.3500 | 2.5500 | 4.1500 | 0.6500 | 0.6000 | 2.8884 |

## 5) 실패/회귀 사례 Top N (latest all20 no-judge 기준)
- 대상 파일: `eval/eval_results_improved2_all20_nojudge_2026-02-23.json`
- source/page miss는 결과 JSON의 `source_hit/page_hit` 필드가 없어서 `ground_truth` 대비 `retrieved_docs(top-k)`로 재계산
- source miss: 없음 (`0건`)
- page miss: `eval_002,003,004,006,007,008,011,012,013,014,015,016,017,019,020` (`15건`)
- 장시간 문항 Top:
  - `eval_003` 1.9705s
  - `eval_005` 1.6410s
  - `eval_016` 1.4193s
  - `eval_002` 1.4165s
  - `eval_017` 1.4026s
  - `eval_015` 1.3665s

## 6) 아키텍처 변경 영향 맵
- 검색 계층
  - CSV strict short-circuit(`사업비/공고번호/입찰일정/발주기관/사업명/요약`) 즉답 경로
  - 하이브리드 재구성: lexical prefilter -> vector rerank -> semantic fallback
  - 비교/다문서 질의 기관별 커버리지 강제(`_ensure_org_coverage`)
  - 정밀 사실 질의 앵커 근거 검증(`_has_precision_anchor_evidence`)
- 답변 계층
  - 사실형 추출 분기 강화(사업비/문자셋/용량/단위수량/복구기한/요구사항 코드/가이드/핵심투입인력)
  - 근거 부족 비교 응답 차단(`_has_comparison_coverage` 미달 시 부족 명시)
  - 정확도 우선 모드(`ANSWER_QUALITY_MODE`)에서 검색 패스/후처리 보강
- 인덱싱/관측 계층
  - 파일 단위 증분 인덱싱 + 실패 문서 레지스트리 스킵
  - `DEBUG_RETRIEVAL_TIMING`에서 `csv_short_circuit_hit` 포함 성능 로그 확인 가능

## 7) 현재 상태 및 다음 실험 백로그
- 목표(20문항 Judge ON): `avg_correctness >= 4.0`, `avg_coverage >= 3.8`
- 목표(20문항 No-Judge 속도): `avg_response_time <= 5.0s`
- 현재 상태:
  - Judge 기준 최신치 `C=3.40`, `Cv=3.30`까지 상승
  - No-Judge 평균응답 `0.9599s`(최고속도) / `1.0642s`(정확도 우선 코드 기준)
  - 속도 목표는 안정적으로 충족, 정확도 목표는 추가 개선 필요
- 다음 액션:
  1. page miss 15문항 대상 페이지 정합 보강(페이지 힌트/표 라인 스코어 상향)
  2. 정밀 사실 질의에서 recall 하락 구간을 대상으로 기관 스코프 재탐색 상한 조정
  3. 정확도 우선 preset과 속도 우선 preset을 ENV 템플릿으로 분리 문서화

## 8) 증빙 링크 모음(JSON/문서)
- `docs/COMPLETE_VERSION_HISTORY.md`
- `docs/EXPERIMENT_LOG.md`
- `eval/eval_results_force_pdf_judge_2026-02-14.json`
- `eval/eval_results_rework_2026-02-19_full20_judge_iter14_p60.json`
- `eval/eval_results_rework_2026-02-23_all20_nojudge_impl_sources20_v2.json`
- `eval/eval_results_improved2_all20_nojudge_2026-02-23.json`
- `eval/eval_results_improved2_all20_judge_2026-02-23.json`
- `eval/eval_results_generated_evalset_2026-02-24_all20_nojudge.json`
- `eval/eval_results_generated_evalset_2026-02-24_all20_judge.json`
- `eval/eval_report_generated_evalset_2026-02-24_all20_judge.html`
- `eval/eval_report_latest_all20_nojudge.html`
- `eval/eval_report_latest_all20_judge.html`
- `docs/EXPERIMENT_LOG.md` (`EXP-2026-02-23-01`, `EXP-2026-02-23-02`, `EXP-2026-02-23-03`, `EXP-2026-02-24-01`)
- `src/graph/workflow.py`
- `src/retrievers/vectorstore.py`
- `src/utils/config.py`
