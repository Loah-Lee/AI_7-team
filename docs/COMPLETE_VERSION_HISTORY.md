# 입찰메이트 RFP 챗봇 - 전체 버전 히스토리 (사실 기준 정정본)

- 프로젝트명: 입찰메이트 RFP 챗봇
- 팀: 7팀
- 개발/개편 범위: 2026-02-04 ~ 2026-02-24
- 버전 범위: v1 ~ v17 + 운영 안정화/평가 개선
- 정정 기준일: 2026-02-24

---

## 1. 타임라인 개요

- 2026-02-04: v1~v5 기반 구축, OpenAI 연동
- 2026-02-05 ~ 2026-02-09: v6~v15 검색/질문처리/비교 기능 확장
- 2026-02-10: v16 하이브리드 검색 구조 강화
- 2026-02-11: v17 대화 컨텍스트 + LLM 질문 파싱
- 2026-02-13 ~ 2026-02-19: 전처리/평가/재랭크/추출우선 응답/실험로그 체계화
- 2026-02-20: 운영 안정화(증분 인덱싱/실패 스킵) + 답변 포맷 가독성 패치 + speed15 기본 성능 개편
- 2026-02-23: 기관 질의 경계 강화 + 사업비 추출 정확도 보호 패치
- 2026-02-23: CSV strict short-circuit + 렉시컬 prefilter->벡터 재정렬 하이브리드 전환
- 2026-02-23: 정확도 우선 모드 + 정밀 사실 질의 앵커 근거 검증 강화
- 2026-02-24: generated evalset + issue target셋 생성, judge/no-judge 회귀 기준선 추가

---

## 2. 버전별 핵심 내역

### v1-v3: 기반 구축 (2026-02-04)

- 기본 RAG 파이프라인 및 PDF 중심 처리
- 초기 검색/응답 흐름 구성

### v4-v5: OpenAI API 연동 (2026-02-04 ~ 2026-02-05)

- `text-embedding-3-small` 기반 임베딩 경로 도입
- OpenAI 모델 연동 및 파일 포맷 확장(HWP/HWPX 포함)

### v6-v9: 검색 개선 및 UI 강화 (2026-02-05 ~ 2026-02-06)

- 검색 로직 반복 개선, UI 사용성 개선
- 운영 중 발견된 품질 이슈 대응

### v10-v12: 최적화 및 안정화 (2026-02-07)

- 코드 단순화 및 안정성 보강
- 질의 처리 실패 케이스 보정

### v13-v14: 랭킹 및 비교 기능 (2026-02-08 ~ 2026-02-09)

- 랭킹/비교 질의 기능 추가
- 다기관 비교 시나리오 지원 기반 확보

### v15: Sequential Thinking 도입 시도 (2026-02-09)

- 복합 질의 대응을 위한 추론 흐름 실험
- 일부 호환/일관성 이슈 확인

### v16: 하이브리드 검색 강화 (2026-02-10)

- CSV + 원문(PDF/HWP) 병행 검색 구조 정비
- 내부 기능 테스트 고점 관찰은 있었으나, 공개 eval 기준 절대 고정 수치로 확정하지 않음

### v17: LLM 질문 파싱 + 대화 컨텍스트 (2026-02-11)

- `QueryIntentParser`, `ConversationContext` 도입
- 후속 질문(문맥 유지) 대응

### v17+ (평가/정확도 개편, 2026-02-13 ~ 2026-02-19)

- HWP 강제 PDF fallback 및 원문 메타 강화
- 평가 스크립트에 Judge/추적 일관화
- 질문 계획(`QuestionPlan`) + 근거 스팬(`EvidenceSpan`) + 답변 초안(`AnswerDraft`) 도입
- 검색 2단계(벡터+키워드 하이브리드 -> 규칙 기반 재랭크)
- 사실형 질의 추출 우선 응답 + 비교 질의 형식 강제
- 통합 로그 보고서 수동 최신화 체계 도입

### v17+ 운영 안정화/가독성/속도 패치 (2026-02-20)

- 앱 기본 DB 경로를 `get_default_db_path()` 절대경로로 통일해 실행/재구축 경로 불일치 제거
- 문서 인덱싱을 파일 단위 upsert로 전환해 중간 종료 후 재실행 시 이어서 처리 가능하도록 개선
- 이미 인덱싱된 문서는 `source` 기준으로 자동 스킵해 불필요한 `변환 중` 반복 최소화
- 반복 실패 문서를 영구 실패 레지스트리(`data/processed_runtime/indexing_failed_sources.json`)에 기록해 다음 실행부터 즉시 스킵
- 답변 표시 포맷을 섹션형(`핵심 답변/근거 요약/출처`)으로 정규화하고, UI에서 소스 배지를 본문과 분리 렌더링
- 검색 호출 상한(`RETRIEVAL_MAX_HYBRID_CALLS=6`) + 검색 패스 축소(`RETRIEVAL_SEARCH_PASSES=1`) + 확장 캡(`RETRIEVAL_EXPANSION_CAP=3`) 적용
- 키워드 스캔 상한(`KEYWORD_SCAN_LIMIT=1200`)과 precision 질의 조건부 키워드 검색으로 불필요 검색 반복 축소
- 의도분석 regex-first(`INTENT_REGEX_FIRST=true`)로 LLM 호출 최소화
- 컨텍스트 기본값 하향(`CONTEXT_TOP_RESULTS=6`, `CONTEXT_MAX_CHARS=700`) 및 비교 질의 예외폭 최소화
- 평가 지표 확장(`p50_response_time`, `p90_response_time`, `answer_mode_distribution`) 반영

### v17+ 정확도 보호 패치 (2026-02-23)

- 단일 기관 질의에 대해 전역 fallback 이후에도 기관 필터를 강제 적용
- 미등록 기관 질의는 추정 응답 대신 명시적 `not found` payload로 종료
- 사업비 질의 전용 판별/근거 함수(`_is_budget_query`, `_has_budget_evidence`) 추가
- 사업비 추출 로직에서 금액/예산 키워드 + 통화 패턴 우선, 시간 수치 라인 감점 적용
- 검색 조기 종료/통합 fallback 조건에 사업비 근거 존재 여부를 반영해 오탐 경로 차단

### v17+ CSV 우선 + 하이브리드 전환 패치 (2026-02-23)

- 모든 질의에서 CSV 우선 확인 경로 추가, 단 구조화 필드 질의만 엄격 단축
- `answer()`에 CSV fast-path 연결 및 `csv_short_circuit_hit` 성능 카운터 추가
- CSV 메타 인덱스 확장:
  - 기관 정규화 키 인덱스
  - 공고번호 인덱스
  - 질의 키워드-필드 매핑
- 하이브리드 검색 구조 변경:
  - `search_hybrid`: lexical prefilter -> vector rerank -> semantic fallback
  - precision 질의(요구사항 코드/문자셋/평가 기준)에서 렉시컬 가중 강화
- 신규 설정값 추가:
  - `CSV_SHORTCIRCUIT_ENABLED=true`
  - `HYBRID_LEXICAL_PREFILTER_K=120`
  - `HYBRID_LEXICAL_MIN_HITS=1`
  - `HYBRID_RERANK_TOP_MULTIPLIER=4`
- 회귀 테스트 추가:
  - `tests/test_workflow_csv_shortcircuit.py`
  - `tests/test_vectorstore_hybrid_pipeline.py`

### v17+ 정확도 우선 모드/정밀 사실 강화 패치 (2026-02-23)

- 정확도 우선 모드 토글(`ANSWER_QUALITY_MODE`) 추가로 검색/후처리 강도를 운영 모드별로 분리
- 정밀 사실 질의 판별(`_is_precision_fact_query`) 및 앵커 근거 검증(`_has_precision_anchor_evidence`) 강화
- 사실형 추출 분기 보강:
  - 문자셋(UTF), 용량(MB/GB), 단위/수량, 복구기한, 요구사항 코드, 가이드, 핵심투입인력
- 비교/다문서 질의 기관 커버리지 보정 로직 강화(`_extract_project_hints_from_query`, `_ensure_org_coverage`)
- 회귀 테스트 추가:
  - `tests/test_workflow_fact_and_org.py`

### v17+ evalset 생성/회귀셋 구축 (2026-02-24)

- eval 리소스에서 생성형 데이터셋 20문항 생성:
  - `eval_resources/eval_dataset_generated_2026-02-24.yaml`
  - 분포: `single_doc=12`, `multi_doc=4`, `comparison=4`
- 이슈 재현용 타깃셋 12문항 구성:
  - `eval_resources/eval_dataset_issue_target_2026-02-24.yaml`
  - 분포: `single_doc=4`, `multi_doc=4`, `comparison=4`
- generated evalset 평가 산출물:
  - `eval/eval_results_generated_evalset_2026-02-24_all20_nojudge.json`
  - `eval/eval_results_generated_evalset_2026-02-24_all20_judge.json`
  - `eval/eval_report_generated_evalset_2026-02-24_all20_judge.html`

---

## 3. 공개 평가 지표 스냅샷 (eval JSON 기준)

| 구분 | 파일 | 문항수 | correctness | coverage | faithfulness | context relevance | recall@k(source) | recall@k(page) | mrr(source) | mrr(page) | latency(s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline (Judge ON) | `eval/eval_results_force_pdf_judge_2026-02-14.json` | 20 | 1.8500 | 1.5000 | 4.0000 | 4.2500 | 0.5500 | 0.0000 | 0.5500 | 0.0000 | 20.8699 |
| 기존 latest full20 (Judge ON) | `eval/eval_results_rework_2026-02-19_full20_judge_iter14_p60.json` | 20 | 2.8000 | 2.5000 | 3.4000 | 4.2000 | 0.8500 | 0.1500 | 0.8538 | 0.0763 | 22.3921 |
| 최신 정확도 지표 (all20 Judge ON) | `eval/eval_results_improved2_all20_judge_2026-02-23.json` | 20 | 3.4000 | 3.3000 | 3.2000 | 4.4000 | 0.7500 | 0.2000 | 0.7219 | 0.0888 | 1.1402 |
| 보조 지표 (first5 Judge ON) | `eval/eval_results_format_readability_v1_first5.json` | 5 | 4.6000 | 4.8000 | 3.8000 | 4.6000 | 1.0000 | 0.4000 | 1.0000 | 0.2333 | 12.3634 |
| 보조 지표 (all20 No-Judge) | `eval/eval_results_format_readability_v1_all20_nojudge.json` | 20 | - | - | - | - | 0.8500 | 0.2000 | 0.8552 | 0.0902 | 24.3336 |
| 보조 지표 (first5 Judge ON, speed tuned) | `eval/eval_results_speed_tuned_final_first5_judge.json` | 5 | 4.6000 | 5.0000 | 3.4000 | 5.0000 | 1.0000 | 0.4000 | 1.0000 | 0.2333 | 13.9093 |
| 보조 지표 (all20 No-Judge, speed tuned) | `eval/eval_results_speed_tuned_v5_all20_nojudge.json` | 20 | - | - | - | - | 0.8500 | 0.2000 | 0.8574 | 0.0858 | 21.1919 |
| 최신 지표 (first5 Judge ON, speed15) | `eval/eval_results_speed15_first5_judge_v3.json` | 5 | 4.6000 | 4.6000 | 3.4000 | 4.8000 | 1.0000 | 0.4000 | 1.0000 | 0.2400 | 0.9469 |
| 최신 지표 (all20 No-Judge, speed15 주설정) | `eval/eval_results_speed15_all20_nojudge_v7.json` | 20 | - | - | - | - | 0.9500 | 0.1500 | 0.8633 | 0.0726 | 2.3154 |
| 비교 지표 (all20 No-Judge, speed15 2차 파라미터) | `eval/eval_results_speed15_all20_nojudge_v7_stage2.json` | 20 | - | - | - | - | 0.9500 | 0.1500 | 0.8633 | 0.0726 | 3.1899 |
| 최신 지표 (all20 No-Judge, impl sources20 v2) | `eval/eval_results_rework_2026-02-23_all20_nojudge_impl_sources20_v2.json` | 20 | - | - | - | - | 0.9500 | 0.2500 | 0.9500 | 0.1134 | 0.9599 |
| 최신 동일코드 지표 (all20 No-Judge, improved2) | `eval/eval_results_improved2_all20_nojudge_2026-02-23.json` | 20 | - | - | - | - | 0.7500 | 0.2000 | 0.7219 | 0.0888 | 1.0642 |
| generated evalset (all20 No-Judge) | `eval/eval_results_generated_evalset_2026-02-24_all20_nojudge.json` | 20 | - | - | - | - | 0.6500 | 0.6000 | 0.6199 | 0.4129 | 2.6997 |
| generated evalset (all20 Judge ON) | `eval/eval_results_generated_evalset_2026-02-24_all20_judge.json` | 20 | 1.6500 | 1.3500 | 2.5500 | 4.1500 | 0.6500 | 0.6000 | 0.6199 | 0.4129 | 2.8884 |

- 사실 기준 결론: 2026-02-24 현재 공개 20문항 Judge ON 기준 `avg_correctness >= 4.0`에는 도달하지 못함
- 속도 튜닝 결론(all20 No-Judge):
  - `21.1919s(speed_tuned_v5) -> 2.3154s(speed15_v7)`로 `89.0740%` 단축, 목표 `<=15.0s` 달성
  - 최신 추가 개선: `2.3154s(speed15_v7) -> 0.9599s(impl_sources20_v2)`로 `58.5415%` 추가 단축
  - 정확도 우선 동일코드 지표는 `1.0642s`로 여전히 속도 목표(`<=5s`)를 충족
- 상태 표기:
  - **운영 기준선(기존 eval_dataset): 2026-02-23 all20 Judge ON 재실행 완료(`improved2_all20_judge_2026-02-23`)**
  - **생성 evalset 기준선: 2026-02-24 all20 Judge/No-Judge 실행 완료(`generated_evalset_2026-02-24_*`)**

---

## 4. 정합성 정정 내역

- 과거 문서의 `정확도 100% 고정 달성`, `MCP 100% 호환 고정`, `2024년 날짜 타임라인` 표현은 현재 저장소 실험 로그 및 eval 산출물과 충돌하여 제거/정정
- 본 문서는 정량 수치가 필요한 경우 반드시 `eval/*.json`의 `metrics` 값을 사용
- 과장 가능성이 있는 서술(예: "완전", "항상", "100%")은 증빙 없는 경우 배제

---

## 5. 현재 상태 및 다음 단계

- 현재 상태(2026-02-24): 정확도 개선 중간 단계 + 생성 evalset 회귀 기준선 반영
  - 달성: retrieval 계열 지표 개선, 추출 우선/비교 강제 구조 반영
  - 달성: DB 경로 일관성 확보, 부분 인덱싱 후 재시작 시 누적 진행 가능
  - 달성: 답변 포맷 가독성 정규화 및 no-judge 평균 지연 목표(`<=5s`) 통과
  - 달성: CSV strict short-circuit + 렉시컬->벡터 하이브리드 재구성 반영
  - 달성: Judge ON all20 `avg_correctness=3.40`, `avg_coverage=3.30`로 상승
  - 달성: generated evalset/issue-target 셋 생성 및 judge/no-judge 평가 파이프라인 검증
  - 미달성: Judge ON 20문항 `avg_correctness >= 4.0`, `avg_coverage >= 3.8`
  - 관찰: generated evalset에서는 recall(source/page) `0.65/0.60`, judge `avg_correctness=1.65`로 난도/채점 편차가 큼
- 다음 단계:
  1. page miss 다발 문항(`eval_002/003/004/006/007/008/011/012/013/014/015/016/017/019/020`) 정합 스코어 보정
  2. 정확도 우선 모드의 recall 하락 구간에 대해 기관 스코프 재탐색 상한 조정
  3. 운영 preset 분리(정확도 우선/속도 우선) 문서화 및 배포

---

## 6. 증빙 및 참조

- 버전/실험 로그: `docs/EXPERIMENT_LOG.md`
- 통합 보고서: `docs/PROJECT_LOG_REPORT.md`
- baseline: `eval/eval_results_force_pdf_judge_2026-02-14.json`
- latest judge: `eval/eval_results_improved2_all20_judge_2026-02-23.json`
- prior full20 judge baseline: `eval/eval_results_rework_2026-02-19_full20_judge_iter14_p60.json`
- readability 보조 지표:
  - `eval/eval_results_format_readability_v1_first5.json`
  - `eval/eval_results_format_readability_v1_all20_nojudge.json`
- speed tuned 보조 지표:
  - `eval/eval_results_speed_tuned_final_first5_judge.json`
  - `eval/eval_results_speed_tuned_v5_all20_nojudge.json`
- speed15 최신 지표:
  - `eval/eval_results_speed15_first5_judge_v3.json`
  - `eval/eval_results_speed15_all20_nojudge_v7.json`
  - `eval/eval_results_speed15_all20_nojudge_v7_stage2.json`
- latest no-judge 구현 반영 지표:
  - `eval/eval_results_rework_2026-02-23_all20_nojudge_impl_sources20_v2.json`
  - `eval/eval_results_improved2_all20_nojudge_2026-02-23.json`
- 2026-02-24 generated evalset 지표:
  - `eval/eval_results_generated_evalset_2026-02-24_all20_nojudge.json`
  - `eval/eval_results_generated_evalset_2026-02-24_all20_judge.json`
  - `eval/eval_report_generated_evalset_2026-02-24_all20_judge.html`
- 2026-02-24 데이터셋 산출물:
  - `eval_resources/eval_dataset_generated_2026-02-24.yaml`
  - `eval_resources/eval_dataset_issue_target_2026-02-24.yaml`
- 운영/속도 패치 근거:
  - `src/graph/workflow.py`
  - `src/utils/config.py`
  - `src/retrievers/vectorstore.py`
  - `scripts/rebuild_db.py`
- 2026-02-23 정확도 보호 패치 근거:
  - `src/graph/workflow.py` (`answer`, `_extract_direct_fact_from_results`, `_score_result`)
  - `docs/EXPERIMENT_LOG.md` (`EXP-2026-02-23-01`)
- 2026-02-23 CSV/하이브리드 전환 패치 근거:
  - `src/graph/workflow.py` (`_try_csv_short_circuit`, `_is_csv_shortcircuit_eligible`, `answer`)
  - `src/retrievers/vectorstore.py` (`search_hybrid`, `_rerank_lexical_candidates`)
  - `docs/EXPERIMENT_LOG.md` (`EXP-2026-02-23-02`)
- 2026-02-23 정확도 우선/정밀 사실 강화 패치 근거:
  - `src/utils/config.py` (`ANSWER_QUALITY_MODE`)
  - `src/graph/workflow.py` (`_is_precision_fact_query`, `_has_precision_anchor_evidence`, `_extract_project_hints_from_query`)
  - `tests/test_workflow_fact_and_org.py`
  - `docs/EXPERIMENT_LOG.md` (`EXP-2026-02-23-03`)
- 2026-02-24 evalset 생성/평가 근거:
  - `eval_resources/generate_eval_set.py`
  - `eval_resources/eval_dataset_generated_2026-02-24.yaml`
  - `eval_resources/eval_dataset_issue_target_2026-02-24.yaml`
  - `eval/eval_results_generated_evalset_2026-02-24_all20_nojudge.json`
  - `eval/eval_results_generated_evalset_2026-02-24_all20_judge.json`
  - `docs/EXPERIMENT_LOG.md` (`EXP-2026-02-24-01`)

---

- 문서 버전: v2.6
- 최종 업데이트: 2026-02-24
- 작성자: 7팀
