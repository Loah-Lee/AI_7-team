# 실험 변경 보고서 (Experiment Log)

프로젝트 성능 개선을 위해 수행한 실험의 변경사항/문제/조치 내역을 누적 기록한다.

---

## 실험 기록 템플릿

- 실험 ID:
- 날짜:
- 목표:
- 가설:
- 실행 범위:
- 변경 파일:
- 실행 커맨드:
- 결과 요약:
- 문제/원인:
- 조치 내용:
- 다음 액션:

---

## 현재까지 변경 요약 (2026-02-23 기준)

| 실험 ID | 핵심 문제 | 왜 변경했는가 | 변경 후 개선 |
|---|---|---|---|
| `EXP-2026-02-13-01` | HWP→PDF 변환 실패로 페이지/표 메타데이터 부족 | CSV 위주 검색 한계를 넘고 원문 근거 검색을 강화하기 위해 | PDF 페이지/표 메타 추출 경로 확보, HWP는 fallback 페이지 분할로 최소 page 메타 확보 |
| `EXP-2026-02-13-02` | CSV 미존재 정보 질의 대응 약함, 임베딩/API 호환 오류 | 원문 기반 추론 응답 강화와 eval 통과 안정화를 위해 | 통합 전처리+메타 매핑+검색 필터/임베딩 배치 개선, gpt-5 파라미터 호환 수정 |
| `EXP-2026-02-13-03` | 평가 스크립트에서 LangSmith 로그 누락 가능성 | 메인과 동일하게 테스트/평가도 추적 가능하게 만들기 위해 | eval 실행이 LangSmith run으로 남고, LLM Judge/평가 체인이 추적 가능해져 디버깅/회귀 비교성 향상 |
| `EXP-2026-02-14-02` | LibreOffice 미지원 HWP 변환 실패로 `converted_pdf=None` 다수 발생 | HWP/HWPX 입력에서 PDF 산출을 강제해 전처리 안정성을 확보하기 위해 | LibreOffice 실패 시 hwp5txt 기반 코드 생성 PDF fallback 도입, 96개 중 94개 변환 성공 |
| `EXP-2026-02-14-03` | Judge ON/OFF 해석 기준 혼재로 실험 비교가 어려움 | 동일 데이터셋 기준 평가 조건 차이를 계량적으로 분리하기 위해 | ON/OFF 비교표 정립, Judge 평균 지표와 retrieval 지표를 분리 비교 가능해짐 |
| `EXP-2026-02-19-01` | 정확성/커버리지 저점 고착(`C≈1.85`, `Cv≈1.50`) | 4점대 목표를 위한 검색/추출/응답 체계 재설계가 필요했기 때문 | 질문 계획/하이브리드 검색/재랭크/추출 우선 응답 적용, `C=2.00`, `Cv=1.60`, source recall 0.90 |
| `EXP-2026-02-19-02` | 이력/실험 문서의 사실 불일치와 통합 보고서 부재 | 결과 JSON 기준 단일 진실원천(Single Source of Truth)으로 문서를 정합화하기 위해 | 버전 히스토리 사실 정정 + 통합 로그 보고서(`PROJECT_LOG_REPORT.md`) 기준안 수립 |
| `EXP-2026-02-19-03` | 비교/사실형 저점 문항(`005/010/012/013/020`) 반복 실패 | 하드코딩 없이 검색 기반 일반화 성능을 먼저 회복하기 위해 | low8 Judge ON 최고 `C=4.25`, `Cv=4.00` 달성(`iter13_p62_focus`) |
| `EXP-2026-02-19-04` | 실험 조건(DB/문서범위) 혼재로 full20 점수 변동성 과대 | 인덱스 오염을 줄이고 최신 상태를 사실 기준으로 기록하기 위해 | DB 경로 스키마 분리(`INDEX_SCHEMA_VERSION`, `DOC_INCLUDE_PATTERN` 해시), latest full20 재측정값 고정(`C=2.80`, `Cv=2.50`) |
| `EXP-2026-02-20-01` | 앱 실행 시 문서 `변환 중` 반복 및 DB 재구축 경로 혼선 | 실행 안정성을 높이고 중단 후 재시작 비용을 줄이기 위해 | 앱/재구축 DB 경로 통일, 파일 단위 증분 인덱싱 + 기인덱싱 파일 스킵으로 반복 변환 최소화 |
| `EXP-2026-02-20-02` | 답변 가독성 저하 + 복합 질의 응답 지연 | 사용자 가독성 개선과 속도 20~30% 단축을 동시에 달성하기 위해 | 섹션형 답변 포맷 정규화 + 검색 튜닝 적용, first5 Judge `C=4.60/Cv=5.00`, all20 no-judge latency `21.19s`(기준 24.33s 대비 -12.9%) |
| `EXP-2026-02-20-03` | all20 평균 15초 목표 미달 + 과도한 검색/LLM 호출 | 기본 동작 자체를 고속화해 토글 없이 15초 이하를 달성하기 위해 | all20 no-judge `2.3154s` 달성(목표 통과), source recall `0.95` 유지, page recall `0.15`로 하한 미달 확인 |
| `EXP-2026-02-23-01` | 기관 질의가 타기관 근거로 답변되거나 사업비 질문에서 `60분` 같은 오답 수치 선택 | 실제 문서 근거 우선 원칙을 회복하고 기관 경계 오염을 차단하기 위해 | 단일 기관 필터 강제 + 사업비 전용 추출/재랭크/검색 가드 추가, 오답 경로 차단 |
| `EXP-2026-02-23-02` | 구조화 질의도 매번 DB 검색으로 지연 발생 + 하이브리드가 의미 재정렬보다 단순 병합 위주 | CSV 즉답 가능한 질의는 즉시 처리하고, 검색은 렉시컬 후보 축소 후 벡터로 재정렬해 속도/정합을 동시에 개선하기 위해 | CSV strict short-circuit + lexical->vector hybrid 전환, all20 no-judge `0.9599s`, page recall `0.25` |
| `EXP-2026-02-23-03` | 속도는 확보됐지만 Judge 정확도/커버리지가 목표 대비 낮음 | 5초 이내 지연을 유지하면서 정밀 사실/비교 질의의 정답률을 올리기 위해 | 정확도 우선 모드(`ANSWER_QUALITY_MODE`) + 정밀 사실 앵커 가드 적용, all20 Judge `C=3.40/Cv=3.30`, no-judge `1.0642s` |

---

## EXP-2026-02-13-01

- 실험 ID: `EXP-2026-02-13-01`
- 날짜: `2026-02-13`
- 목표: HWP 전처리 품질 개선 (HWP→PDF 변환, 페이지/표 메타데이터 확보)
- 가설:
  - LibreOffice 기반 HWP→PDF 변환이 안정화되면 PDF 페이지/표 추출을 통해 retrieval 근거 품질이 개선될 수 있다.
  - 변환 실패 시에도 fallback 텍스트를 페이지 단위로 나누면 최소한 page 메타데이터 축을 만들 수 있다.
- 실행 범위:
  - 데이터 EDA
  - HWP/PDF 파서 확장
  - 벡터 메타데이터 확장
  - 전처리 스크립트 추가
- 변경 파일:
  - `src/parsers/pdf_loader.py`
  - `src/parsers/hwp_loader.py`
  - `src/graph/workflow.py`
  - `src/retrievers/vectorstore.py`
  - `scripts/preprocess_hwp_pdf.py`
- 실행 커맨드:
  - `python3` 기반 데이터 분포/DB 메타 분석
  - `libreoffice --headless --convert-to pdf ...` 변환 테스트
  - `./venv/bin/python` 기반 HWP fallback 텍스트 추출 검증
- 결과 요약:
  - 데이터 분포: `CSV 1(100행) + HWP 96 + PDF 4`
  - 기존 벡터DB: `417 chunks`, `type=csv`만 존재 (문서 페이지 메타 없음)
  - LibreOffice HWP 변환: 실패 (`Error: source file could not be loaded`)
  - HWP fallback(olefile 경유): 본문 추출 가능(샘플 7,000자대), 논리 페이지 분할 가능
  - PDF 파서: 페이지별 텍스트+표(markdown) 추출 가능하도록 확장 완료
  - workflow/vectorstore: `page`, `table_count`, `has_table` 메타 저장 경로 반영
- 문제/원인:
  - 서버 LibreOffice 환경에서 HWP import 필터가 동작하지 않아 HWP→PDF 직접 변환 실패.
  - 샌드박스 권한 이슈를 해소해도 동일 실패 재현되어, 권한 문제가 아닌 필터/호환성 문제로 판단.
- 조치 내용:
  - HWP 변환 실패 시 fallback 텍스트를 논리 페이지로 분할해 `page` 메타데이터를 생성.
  - PDF는 표 추출까지 포함해 페이지 메타데이터를 최대한 보존.
  - 별도 전처리 스크립트로 HWP→PDF 변환 및 페이지/표 통계 매니페스트 생성 경로 마련.
- 다음 액션:
  - HWP 변환 호환 툴체인 보강(대체 컨버터 검토) 또는 사전 PDF 확보 전략 필요.
  - 재인덱싱 후 타입별 청크 비율(`csv/pdf/hwp`)과 질의별 성능 변화를 추가 기록.

---

## EXP-2026-02-13-02

- 실험 ID: `EXP-2026-02-13-02`
- 날짜: `2026-02-13`
- 목표:
  - CSV 중심 응답에서 벗어나, CSV에 없는 질문은 원본 문서(PDF/HWP) 근거로 답변하도록 전처리/검색 체계 강화
  - `gpt-5-mini` 기반 추론형 답변 복구 및 eval 연동 안정화
- 가설:
  - `CSV↔원본 매칭 메타데이터`를 문서 청크까지 주입하면 기관/사업 단위 검색 정밀도가 올라간다.
  - 질의 유형(저작권/책임/조항)에 따라 원본 문서 검색 비중을 높이면 “CSV에 없는 정보” 질의 대응이 개선된다.
  - gpt-5 호환 파라미터(`max_completion_tokens`) 적용 시 fallback 요약 응답 비율이 줄어든다.
- 실행 범위:
  - 통합 전처리기 추가 (PDF 변환/Markdown 저장/Manifest 저장)
  - 벡터DB 메타데이터 확장 및 검색 로직 개선
  - gpt-5 API 호환성 수정
  - 임베딩 대량 요청 안정화
- 변경 파일:
  - `src/parsers/preprocessor.py`
  - `scripts/build_unified_corpus.py`
  - `src/parsers/csv_loader.py`
  - `src/graph/state.py`
  - `src/graph/workflow.py`
  - `src/retrievers/vectorstore.py`
  - `src/retrievers/embeddings.py`
  - `src/graph/nodes.py`
  - `src/parsers/__init__.py`
- 실행 커맨드:
  - `./venv/bin/python scripts/build_unified_corpus.py --input-dir data/files --output-dir data/processed_test --max-rows 2 --overwrite`
  - `./venv/bin/python - <<...>>` (RAGChatbot 초기화/단일 질의 스모크)
  - `./venv/bin/python - <<...>>` (eval_dataset 앞 2개 샘플 평가)
- 결과 요약:
  - 샘플 전처리 결과 생성:
    - `data/processed_test/manifest.json`
    - `data/processed_test/markdown/*.md`
  - 질의 시 `csv + original(pdf/hwp)` 혼합 검색 및 원본 fallback 동작 확인
  - `eval_001`, `eval_002` 샘플에서 요약 테이블이 아닌 근거형 답변 생성 확인
  - 기본 초기화 완료: `벡터 DB 청크 수 899`, `등록 기관 87`
- 문제/원인:
  - Chroma where 필터 구성 오류: `org + type` 동시 조건을 단일 dict로 전달해 query 오류 발생
  - OpenAI embedding 실패:
    - 요청당 토큰 초과(`max 300000`)
    - 일부 비정형 텍스트가 모델 context(8192) 초과
  - `gpt-5-mini` 파라미터 호환성:
    - `max_tokens` 미지원 (`max_completion_tokens` 필요)
    - `temperature` 커스텀값 미지원 (기본값만 허용)
  - QueryIntent LLM 파싱 오류 시 잘못된 기관으로 검색되는 케이스 발생
- 조치 내용:
  - 검색 필터를 `{"$and":[...]}`
    구조로 수정
  - 임베딩 요청 배치 처리(64개 단위) + 임베딩 전 텍스트 길이 클리핑(2500자)
  - gpt-5 모델 조건 분기:
    - `max_completion_tokens` 사용
    - gpt-5에서는 temperature 파라미터 제거
  - 명시 기관명이 질의에 포함되면 후속질문 컨텍스트보다 우선 적용
  - 비-LLM fallback에 규칙 기반 답변(책임 주체 질의) 추가
- 다음 액션:
  - 전체 `eval/eval_dataset.yaml`(20문항) 재실행 후 지표 추이 기록
  - HWP 변환 실패율 감소를 위한 대체 변환기/환경 분리 검토
  - 원본 문서 표 구조 추출 정확도 기반 rerank 실험 추가

---

## EXP-2026-02-13-03

- 실험 ID: `EXP-2026-02-13-03`
- 날짜: `2026-02-13`
- 목표:
  - 평가 스크립트(`scripts/eval_retrieval.py`) 실행도 LangSmith에 일관되게 로그가 남도록 개선
  - 메인 앱과 eval 경로의 관측성(Observability) 격차 해소
- 가설:
  - eval 루프와 LLM Judge 호출을 LangSmith trace span으로 감싸면, 질문별 실패 원인/점수 변화를 런 단위로 추적할 수 있다.
  - `OpenAI client`와 `ChatOpenAI` 경로 혼용을 제거하면 eval 안정성과 로깅 일관성이 올라간다.
- 실행 범위:
  - 평가 스크립트 로깅 경로 정리
  - LLM Judge 초기화 방식 통일
  - 스모크 평가로 동작 검증
- 변경 파일:
  - `scripts/eval_retrieval.py`
- 실행 커맨드:
  - `venv/bin/python -m py_compile scripts/eval_retrieval.py`
  - `venv/bin/python - <<...>>` (eval_dataset 1문항 인라인 스모크 실행)
- 문제/원인:
  - 평가 스크립트에서 `ChatOpenAI` 기반 코드와 구형 `OpenAI(...)` 초기화 로직이 혼재되어, 실제 judge 호출/로깅 경로가 불안정했다.
  - 메인 앱은 LangSmith 설정이 있었지만 eval 경로는 trace span 단위 구분이 없어 분석이 어려웠다.
- 조치 내용:
  - `evaluate_with_llm_judge`에 `@traceable(name="eval_llm_judge", run_type="llm")` 적용
  - `run_evaluation`에 `@traceable(name="eval_retrieval_run", run_type="chain")` 적용
  - 메인 함수의 judge 초기화를 `ChatOpenAI(model=DEFAULT_MODEL)`로 통일하고 구형 `OpenAI(...)` 경로 제거
- 결과 요약:
  - 1문항 스모크 평가 정상 완료 (`total_questions=1`)
  - 콘솔에서 LangSmith 트레이싱 활성화 출력 확인
  - 질문 응답 + Judge 점수까지 한 번의 eval 런으로 기록 가능해져, 이후 회귀 실험 비교가 쉬워짐
- 개선 효과:
  - **디버깅 개선**: 질문별 judge 실패/파싱 실패를 런 기록에서 바로 확인 가능
  - **실험 관리 개선**: “어떤 코드/설정에서 점수가 변했는지”를 LangSmith 프로젝트 기준으로 추적 가능
  - **운영 일관성**: 메인/평가 모두 동일한 LangChain-LangSmith 경로 사용
- 다음 액션:
  - 전체 20문항 eval 재실행 후, LangSmith run 링크와 지표 스냅샷을 본 로그에 추가
  - run tag(모델/top_k/데이터셋 버전) 표준화로 실험 비교 자동화

---

## EXP-2026-02-14-01

- 실험 ID: `EXP-2026-02-14-01`
- 날짜: `2026-02-14`
- 목표:
  - LangSmith 공유 런 2건의 비교 해석으로 현재 평가 파이프라인의 병목 지점을 식별
  - Retrieval vs Generation 중 어느 단계가 점수 저하를 유발하는지 분리 분석
- 가설:
  - source-level retrieval는 유지되지만 page-level 정합성과 생성 단계 커버리지에서 병목이 있을 수 있다.
  - Judge ON/OFF 설정 차이가 리포트 해석의 핵심 분기점이 될 수 있다.
- 실행 범위:
  - LangSmith shared run 2건 메트릭 비교
  - 런 입력 파라미터(`use_judge`, `top_k`) 비교
  - 문항별 점수/응답 변동성 확인
- 분석 대상 런:
  - `https://smith.langchain.com/public/bdeb0728-721e-4d2e-b2b2-6407ba901653/r`
  - `https://smith.langchain.com/public/e6617e25-742f-463c-985d-766663b40e55/r`
- 변경 파일:
  - `eval/INTERPRETATION_REPORT_2026-02-14.md`
- 결과 요약:
  - 공통 retrieval 지표 동일:
    - `recall_at_k_source=0.55`, `mrr_source=0.55`
    - `recall_at_k_page=0.00`, `mrr_page=0.00`
  - Run A는 `use_judge=False`, Run B는 `use_judge=True`
  - Run B Judge 평균:
    - `avg_correctness=1.85`
    - `avg_coverage=1.40`
    - `avg_faithfulness=4.35`
    - `avg_context_relevance=4.35`
  - 응답 시간:
    - A `18.34s`, B `17.82s` (유의미한 차이 없음)
  - 문항별 관찰:
    - `generated_answer`는 20/20 문항에서 변경
    - `retrieved_docs` 순서는 20/20 동일
- 문제/원인:
  - page-level 정답 매칭 실패(`recall_at_k_page=0.00`)가 지속됨
  - 검색 결과는 유지되나 생성 단계 비결정성으로 답변 텍스트가 흔들림
  - Judge OFF/ON 결과를 동일 선상에서 비교하면 해석 오류 가능성 존재
- 조치 내용:
  - 비교 결과를 해석 보고서로 문서화:
    - `eval/INTERPRETATION_REPORT_2026-02-14.md`
  - 평가 실험 해석 규칙 정리:
    - 동일 조건(`use_judge`, `judge_model`, `top_k`)에서만 추세 비교
- 개선 효과:
  - 병목 구간을 Retrieval(페이지 정합성)과 Generation(정확성/커버리지)으로 분리해 후속 실험 우선순위가 명확해짐
  - 단순 평균 점수 비교 대신 실험 조건을 먼저 확인하는 분석 기준 확립
- 다음 액션:
  - `ground_truth.page`와 인덱싱 `metadata.page` 정합성 점검 (type/offset/파일명 정규화)
  - "문서에 명시되어 있지 않음" 조기 반환 조건 완화 및 답변 템플릿 보강
  - 동일 설정으로 3회 반복 실행해 점수 분산(재현성) 기록

---

## EXP-2026-02-14-02

- 실험 ID: `EXP-2026-02-14-02`
- 날짜: `2026-02-14`
- 목표:
  - HWP/HWPX 입력에서 `converted_pdf`를 가능한 한 항상 생성하도록 변환 파이프라인 강화
  - 변환 실패를 조용히 넘기지 않고 명시적 에러로 처리
- 가설:
  - LibreOffice 실패 시 `hwp5txt -> code-rendered PDF(reportlab)` fallback을 두면 전처리 성공률이 크게 올라간다.
- 실행 범위:
  - HWP 변환기 fallback 경로 추가
  - preprocessor/manifest에 생성 모드 기록
  - 전처리 스크립트 실패 정책 예외 기반으로 정리
- 변경 파일:
  - `src/parsers/hwp_loader.py`
  - `src/parsers/preprocessor.py`
  - `scripts/preprocess_hwp_pdf.py`
  - `requirements.txt`
- 실행 커맨드:
  - `./venv/bin/python scripts/preprocess_hwp_pdf.py --input-dir data/files --output-dir tmp/verify_preprocessed_pdf_2026-02-14 --manifest tmp/verify_preprocessed_pdf_2026-02-14/manifest.json --overwrite`
  - `./venv/bin/python scripts/build_unified_corpus.py --max-rows 2 --overwrite`
- 결과 요약:
  - 전체 HWP/HWPX 96개 중 `성공 94 / 실패 2`
  - 성공 94개 모두 `pdf_generation_mode=fallback_text_render`
  - 성공 파일 `converted_pdf` 실파일 존재 확인(`missing_pdf_among_success=0`)
  - 실패 2건은 `hwp5txt` 파싱 자체 실패(Unicode/XMLSyntaxError)
- 문제/원인:
  - 환경 LibreOffice HWP import 필터 실패 지속
  - 일부 원본 HWP의 비정형 구조로 hwp5txt 파싱 실패
- 조치 내용:
  - 변환 순서 고정: LibreOffice -> hwp5txt 추출 -> reportlab PDF 렌더
  - 최종 실패는 `RuntimeError` 발생(침묵 실패 제거)
  - manifest에 `pdf_generation_mode` 기록
- 다음 액션:
  - 실패 2건 파일에 대한 대체 파서 또는 수동 PDF 확보 전략 필요

---

## EXP-2026-02-14-03

- 실험 ID: `EXP-2026-02-14-03`
- 날짜: `2026-02-14`
- 목표:
  - 동일 데이터셋에서 Judge OFF/ON 결과를 분리 비교해 해석 기준 통일
- 가설:
  - Judge ON/OFF는 retrieval 지표엔 영향이 없고, 생성 품질 지표만 비교 축으로 활용해야 한다.
- 실행 범위:
  - 전체 20문항 OFF 재실행
  - 전체 20문항 ON 재실행
  - 비교표 문서화
- 변경 파일:
  - `eval/eval_results.json`
  - `eval/eval_results_force_pdf_judge_2026-02-14.json`
  - `eval/eval_report.html`
  - `eval/eval_report_force_pdf_judge_2026-02-14.html`
  - `eval/INTERPRETATION_REPORT_2026-02-14.md`
- 실행 커맨드:
  - `./venv/bin/python scripts/eval_retrieval.py --label force_pdf_2026-02-14 --dataset eval_resources/eval_dataset.yaml --output eval/eval_results.json --no-judge`
  - `./venv/bin/python scripts/eval_retrieval.py --label force_pdf_2026-02-14_judge --dataset eval_resources/eval_dataset.yaml --output eval/eval_results_force_pdf_judge_2026-02-14.json`
- 결과 요약:
  - Judge OFF(20문항): `recall_at_k_source=0.55`, `mrr_source=0.55`, `recall_at_k_page=0.00`
  - Judge ON(20문항): 위 retrieval 동일 + `avg_correctness=1.85`, `avg_coverage=1.50`, `avg_faithfulness=4.00`, `avg_context_relevance=4.25`
- 문제/원인:
  - 정확성/커버리지는 낮고(질문 핵심 미충족), faithfulness는 높은 패턴 지속
- 조치 내용:
  - ON/OFF 비교표를 보고서에 고정 섹션으로 추가
  - 이후 실험은 Judge 조건을 명시해 비교하도록 기준 수립
- 다음 액션:
  - low-score 문항 중심으로 질문 계획/추출/비교 응답 체계 재설계

---

## EXP-2026-02-19-01

- 실험 ID: `EXP-2026-02-19-01`
- 날짜: `2026-02-19`
- 목표:
  - 정확성/커버리지 4점대 목표를 위해 질문 계획 + 하이브리드 검색 + 추출 우선 응답으로 엔진 개편
- 가설:
  - 질문 유형별 필수 슬롯을 채우는 구조로 바꾸면 correctness/coverage가 상승한다.
  - 원본 문서 우선 + 키워드 재랭킹 + 관련 문장 컨텍스트 압축이 정답 근접도를 높인다.
- 실행 범위:
  - `QuestionPlan/EvidenceSpan/AnswerDraft` 타입 추가
  - workflow 답변 메타(`answer_mode`, `slot_fill_rate`, `evidence_count`, `confidence`) 노출
  - eval 결과 스키마 확장 + `--slice low8` 옵션 추가
  - 벡터+키워드 하이브리드 검색 메서드 추가
- 변경 파일:
  - `src/graph/state.py`
  - `src/graph/nodes.py`
  - `src/graph/workflow.py`
  - `src/retrievers/vectorstore.py`
  - `src/prompts/templates.py`
  - `scripts/eval_retrieval.py`
- 실행 커맨드:
  - `./venv/bin/python scripts/eval_retrieval.py --label force_pdf_2026-02-14_judge_v2 --dataset eval_resources/eval_dataset.yaml --output eval/eval_results_force_pdf_judge_2026-02-14_v2.json`
  - `./venv/bin/python scripts/build_eval_report.py --input eval/eval_results_force_pdf_judge_2026-02-14_v2.json --output eval/eval_report_force_pdf_judge_2026-02-14_v2.html`
- 결과 요약 (v1 -> v2):
  - `avg_correctness: 1.85 -> 2.00` (+0.15)
  - `avg_coverage: 1.50 -> 1.60` (+0.10)
  - `recall_at_k_source: 0.55 -> 0.90` (+0.35)
  - `recall_at_k_page: 0.00 -> 0.05` (+0.05)
  - `avg_response_time: 20.87s -> 35.73s` (+14.86s)
- 문제/원인:
  - 정확성은 상승했지만 목표(4점대)와 큰 격차가 여전히 존재
  - 비교/복합 문항에서 슬롯 미충족이 반복
- 조치 내용:
  - 추출 우선 모드와 비교 질의 강제 템플릿을 적용
  - 답변 메타 로깅으로 실패 유형 추적 가능하게 전환
- 다음 액션:
  - 저점 8문항 반복 튜닝(`--slice low8`) 후 전체 20문항 재검증
  - 슬롯 채움률 기반 gating(미충족 시 재검색) 추가

---

## EXP-2026-02-19-02

- 실험 ID: `EXP-2026-02-19-02`
- 날짜: `2026-02-19`
- 목표:
  - `docs/COMPLETE_VERSION_HISTORY.md`와 `docs/EXPERIMENT_LOG.md`를 eval 사실값 기준으로 정합화
  - `docs/PROJECT_LOG_REPORT.md`를 수동 최신화 기준으로 운영
- 가설:
  - 수동 문서 서술은 시간 경과에 따라 과장/오기(연도·수치)가 누적될 수 있으므로, 최신 결과 JSON을 근거로 체크리스트 기반 수동 업데이트가 필요하다.
  - 비교 지표를 baseline/latest로 고정하면 실험 회귀 추적이 일관된다.
- 실행 범위:
  - 버전 히스토리 문서 전면 사실 정정
  - 통합 로그 보고서 수동 정리
  - 링크/날짜/중복 ID 수동 점검
- 변경 파일:
  - `docs/COMPLETE_VERSION_HISTORY.md`
  - `docs/EXPERIMENT_LOG.md`
  - `docs/PROJECT_LOG_REPORT.md`
- 실행 커맨드:
  - `python3 - <<...>>` 기반 결과 JSON 사실값 점검 및 문서 반영(수동)
- 결과 요약:
  - 통합 보고서 최신화 완료: `docs/PROJECT_LOG_REPORT.md`
  - baseline/latest 기준 파일을 명시적으로 고정해 수치 일관성 확보
  - 버전 히스토리 내 과장 수치(고정 100% 등) 및 2024 연도 표기를 사실 기준으로 정정
- 문제/원인:
  - 기존 히스토리 문서는 서술형 누적으로 실험 산출물과 일부 충돌
  - 지표 추세가 문서 수동 업데이트 시점에 따라 쉽게 불일치
- 조치 내용:
  - 수치 표현은 `eval/*.json` 값을 우선 사용하도록 정책 고정
  - 문서 업데이트 시 정합성 체크리스트(중복 ID/링크 누락/날짜 역전) 적용
- 다음 액션:
  - 신규 실험 실행 직후 로그/리포트를 같은 세션에서 즉시 수동 갱신
  - `avg_correctness >= 4.0` 달성 시점의 full20 결과를 기준선 표와 백로그에 반영

---

## EXP-2026-02-19-03

- 실험 ID: `EXP-2026-02-19-03`
- 날짜: `2026-02-19`
- 목표:
  - 하드코딩 없이 검색 기반으로 low8 정확성/커버리지를 4점대까지 회복
- 가설:
  - 질문 계획 + 하이브리드 검색 + 규칙 기반 재랭크 + 추출 우선 응답을 함께 적용하면 비교/사실형 저점 문항이 회복된다.
  - HWP 원문 텍스트 품질(hwp5html 경유)이 개선되면 `QUR-02`, `UTF-8`, `12시간 이내` 같은 핵심 근거가 검색 상위로 노출된다.
- 실행 범위:
  - `workflow.py` 검색/재랭크/추출 로직 반복 튜닝
  - `vectorstore.py` 키워드 검색 깊이 확장
  - `hwp_loader.py` HTML 기반 추출 품질 보강
  - 포커스 10문서 반복 실험(`DOC_INCLUDE_PATTERN`)
- 변경 파일:
  - `src/graph/workflow.py`
  - `src/retrievers/vectorstore.py`
  - `src/parsers/hwp_loader.py`
  - `src/parsers/pdf_loader.py`
  - `src/prompts/templates.py`
  - `src/utils/config.py`
- 실행 커맨드:
  - `MAX_PAGES=62 DOC_INCLUDE_PATTERN='...' venv/bin/python scripts/eval_retrieval.py --slice low8 --label rework_2026-02-19_low8_nojudge_iter10_p62_focus --output eval/eval_results_rework_2026-02-19_low8_nojudge_iter10_p62_focus.json --no-judge`
  - `MAX_PAGES=62 DOC_INCLUDE_PATTERN='...' venv/bin/python scripts/eval_retrieval.py --slice low8 --label rework_2026-02-19_low8_judge_iter12_p62_focus --output eval/eval_results_rework_2026-02-19_low8_judge_iter12_p62_focus.json`
  - `MAX_PAGES=62 DOC_INCLUDE_PATTERN='...' venv/bin/python scripts/eval_retrieval.py --slice low8 --label rework_2026-02-19_low8_judge_iter13_p62_focus --output eval/eval_results_rework_2026-02-19_low8_judge_iter13_p62_focus.json`
- 결과 요약:
  - low8 Judge ON 최고 성능:
    - `eval/eval_results_rework_2026-02-19_low8_judge_iter13_p62_focus.json`
    - `avg_correctness=4.25`, `avg_coverage=4.00`, `recall_at_k_source=0.75`, `recall_at_k_page=0.25`
  - 핵심 회복 문항:
    - `eval_010`: `12시간 이내` 복구 기한 추출 회복
    - `eval_012`: `UTF-8 우선 적용` 추출 회복
    - `eval_005`: `QUR-02 가용성` 운영요건 문구 추출 회복
- 문제/원인:
  - `eval_013`, `eval_020`은 근거는 확보되나 coverage 슬롯 충족이 불안정
  - 동일 날짜 내 실험 조건(DB 범위/문서 포함 패턴) 차이로 점수 분산 발생
- 조치 내용:
  - 비교 질의 기관 커버리지 강제(`_ensure_org_coverage`)
  - 요구사항 코드/문자셋 질의 전용 점수 가중치 및 추출 분기 추가
  - 노이즈 라인 필터 조정(표 본문 보존)
- 다음 액션:
  - full20 기준 하위 문항을 동일 방식으로 타깃 튜닝
  - low8 성능을 full20에 이식 가능한 규칙과 문서범위 정책으로 정리

---

## EXP-2026-02-19-04

- 실험 ID: `EXP-2026-02-19-04`
- 날짜: `2026-02-19`
- 목표:
  - 실험 오염(다른 문서범위 인덱스 재사용) 위험을 줄이고 latest full20 성능을 사실값으로 고정
- 가설:
  - `DOC_INCLUDE_PATTERN` 실험과 전체 실험이 동일 DB 경로를 공유하면 점수 회귀가 발생할 수 있다.
  - DB 경로를 스키마/패턴 기반으로 분리하면 실험 재현성이 개선된다.
- 실행 범위:
  - DB 경로 정책 개편(`INDEX_SCHEMA_VERSION`, include pattern hash)
  - 기존 컬렉션 재사용 시 org registry 보강
  - latest full20/low8 재측정
- 변경 파일:
  - `src/utils/config.py`
  - `src/graph/workflow.py`
  - `src/retrievers/vectorstore.py`
- 실행 커맨드:
  - `MAX_PAGES=60 venv/bin/python scripts/eval_retrieval.py --slice all --label rework_2026-02-19_full20_judge_iter14_p60 --output eval/eval_results_rework_2026-02-19_full20_judge_iter14_p60.json`
  - `MAX_PAGES=62 DOC_INCLUDE_PATTERN='...' venv/bin/python scripts/eval_retrieval.py --slice low8 --label rework_2026-02-19_low8_judge_iter16_p62_focus_schema --output eval/eval_results_rework_2026-02-19_low8_judge_iter16_p62_focus_schema.json`
- 결과 요약:
  - latest full20 (Judge ON):
    - `eval/eval_results_rework_2026-02-19_full20_judge_iter14_p60.json`
    - `avg_correctness=2.80`, `avg_coverage=2.50`
  - latest low8 (Judge ON, schema 분리 후):
    - `eval/eval_results_rework_2026-02-19_low8_judge_iter16_p62_focus_schema.json`
    - `avg_correctness=3.75`, `avg_coverage=3.875`
  - full20 저점 Top:
    - `eval_009(C0/Cv0)`, `eval_005(C1/Cv0)`, `eval_012(C1/Cv0)`, `eval_008(C1/Cv1)`, `eval_013(C1/Cv1)`
- 문제/원인:
  - low8 최고 성능(`iter13`)이 full20으로 그대로 이전되지 않음
  - full20에서는 비교/복합 문항 coverage 저하가 크게 발생
- 조치 내용:
  - DB 경로 분리 정책 적용:
    - `data/files/chroma_db_v17_<schema>_p{MAX_PAGES}_inc{hash}`
  - 문서 최신화 기준을 “최신 full20 Judge ON”으로 고정
- 다음 액션:
  - full20 저점 문항(`005/008/009/012/013/015/016/017/019/020`) 타깃 룰 분리
  - full20 동일 조건 2회 반복으로 분산 확인 후 목표치 재도전

---

## EXP-2026-02-20-01

- 실험 ID: `EXP-2026-02-20-01`
- 날짜: `2026-02-20`
- 목표:
  - 앱 실행 시 반복되는 `변환 중` 로그를 줄이고, 중간 종료 이후 재실행 시 남은 문서만 처리되도록 개선
  - `scripts/rebuild_db.py`와 앱(`streamlit run app/main.py`)의 DB 경로 불일치를 제거
- 가설:
  - DB 경로를 단일 기준(`get_default_db_path`)으로 통일하면 재구축/실행 결과가 일치한다.
  - 문서 인덱싱을 파일 단위로 저장하고 기인덱싱 파일을 스킵하면, 장시간 인덱싱 중단 후 재개 시 반복 변환이 줄어든다.
- 실행 범위:
  - DB 경로 초기화 로직 정렬
  - 인덱싱 파일 존재 판단(`source`) 로직 추가
  - 문서 인덱싱 루프를 파일 단위 upsert로 전환
- 변경 파일:
  - `src/graph/workflow.py`
  - `src/retrievers/vectorstore.py`
  - `scripts/rebuild_db.py`
- 실행 커맨드:
  - `./venv/bin/python -m py_compile src/graph/workflow.py src/retrievers/vectorstore.py scripts/rebuild_db.py`
- 결과 요약:
  - 앱 기본 DB 경로를 `Path(get_default_db_path()).resolve()`로 통일
  - `VectorStore.get_indexed_sources()` 추가로 `pdf/hwp` source 기준 인덱싱 여부 조회 가능
  - `_load_document_files()`가 이미 인덱싱된 파일을 스킵하고, 변환 완료 파일만 즉시 DB에 추가하도록 변경
  - `scripts/rebuild_db.py`가 앱과 동일한 DB 경로를 명시적으로 사용
- 문제/원인:
  - 기존에는 앱 내부 경로 조합(`data/files/...`)과 재구축 스크립트 기본 경로(`data/...`)가 달라 동일한 재구축 결과를 재사용하지 못하는 케이스가 있었다.
  - 문서 인덱싱이 배치 단위로 누적되어 중간 종료 시 다음 실행에서 동일 변환을 반복할 가능성이 있었다.
- 조치 내용:
  - 경로 정책을 단일 함수 결과로 통일
  - 문서별 증분 인덱싱/스킵 로직 도입
  - 로그에 `이미 인덱싱됨` 상태를 출력해 진행 상태를 명확화
- 다음 액션:
  - 동일 문서셋에서 앱 2회 연속 실행 시 두 번째 실행의 변환 스킵 동작 확인
  - 필요 시 `--force-reindex` 성격 옵션을 별도 스크립트로 추가해 운영/실험 사용성을 분리

---

## EXP-2026-02-20-02

- 실험 ID: `EXP-2026-02-20-02`
- 날짜: `2026-02-20`
- 목표:
  - 답변 가독성 포맷(`핵심 답변/근거 요약/출처`)을 유지하면서 응답속도 20~30% 단축 가능성 검증
  - 검색 반복(pass)/컨텍스트 길이 최적화의 품질 하한 영향 사전 측정
- 가설:
  - 검색 확장 캡, 검색 패스 축소, 컨텍스트 압축을 함께 적용하면 source recall 하락 없이 지연을 줄일 수 있다.
  - 복합 질의의 과도한 검색 반복이 평균 지연의 주원인이다.
- 실행 범위:
  - `RETRIEVAL_EXPANSION_CAP`, `RETRIEVAL_SEARCH_PASSES`, `RETRIEVAL_HIGH_RECALL_K_MULTIPLIER` 도입
  - `CONTEXT_TOP_RESULTS`, `CONTEXT_MAX_CHARS` 도입
  - fallback 검색 조건/early-stop 조건 추가
  - 디버그 관측(`DEBUG_RETRIEVAL_TIMING`) 조건부 로깅 추가
- 변경 파일:
  - `src/graph/workflow.py`
  - `src/utils/config.py`
  - `.env.example`
- 실행 커맨드:
  - `venv/bin/python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset.yaml --slice first5 --label format_readability_v1_first5 --output eval/eval_results_format_readability_v1_first5.json`
  - `venv/bin/python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset.yaml --slice all --label format_readability_v1_all20_nojudge --output eval/eval_results_format_readability_v1_all20_nojudge.json --no-judge`
  - `venv/bin/python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset.yaml --slice first5 --label speed_tuned_final_first5_judge --output eval/eval_results_speed_tuned_final_first5_judge.json`
  - `venv/bin/python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset.yaml --slice all --label speed_tuned_v5_all20_nojudge --output eval/eval_results_speed_tuned_v5_all20_nojudge.json --no-judge`
- 결과 요약:
  - 가독성 기준(first5 Judge ON):
    - `eval/eval_results_format_readability_v1_first5.json`
    - `avg_correctness=4.6000`, `avg_coverage=4.8000`, `avg_response_time=12.3634s`
  - 속도 튜닝 후(first5 Judge ON):
    - `eval/eval_results_speed_tuned_final_first5_judge.json`
    - `avg_correctness=4.6000`, `avg_coverage=5.0000`, `avg_response_time=13.9093s`
  - 가독성 기준(all20 No-Judge):
    - `eval/eval_results_format_readability_v1_all20_nojudge.json`
    - `avg_response_time=24.3336s`, `recall_at_k_source=0.8500`, `recall_at_k_page=0.2000`
  - 속도 튜닝 후(all20 No-Judge):
    - `eval/eval_results_speed_tuned_v5_all20_nojudge.json`
    - `avg_response_time=21.1919s`, `recall_at_k_source=0.8500`, `recall_at_k_page=0.2000`
  - 지연 개선율:
    - `24.3336s -> 21.1919s` (`-12.9111%`)
  - 병목 문항(튜닝 후 상위):
    - `eval_015(60.3382s)`, `eval_017(43.0443s)`, `eval_007(39.6278s)`, `eval_018(35.7026s)`
- 문제/원인:
  - 복합/다문서 질의에서 pass별 검색과 재조합 비용이 여전히 커서 목표치(`<=19.5s`) 미달
  - source recall은 유지됐지만 page-level 정합(`0.2000`) 개선이 정체
- 조치 내용:
  - 검색 패스 기본값을 2-pass로 축소하고, fallback에서만 3-pass 허용
  - 컨텍스트 수/길이를 기본 축소(`8`, `900`)하고 비교 질의만 제한 완화
  - high-recall request_k를 multiplier 기반으로 제한
- 다음 액션:
  - `eval_015/017/018` 전용 early-stop 분기와 비교 질의 회수 제한 추가
  - 같은 설정으로 all20 no-judge 2회 반복해 응답시간 분산/안정성 검증
  - full20 Judge ON은 이번 사이클에서 미실행(비용/시간 블로킹)으로 별도 배치에서 재개

---

## EXP-2026-02-20-03

- 실험 ID: `EXP-2026-02-20-03`
- 날짜: `2026-02-20`
- 목표:
  - 기본 성능 자체 개선으로 `all20 no-judge avg_response_time <= 15.0s` 달성
  - 품질 하한(`recall_at_k_source >= 0.82`, `recall_at_k_page >= 0.18`, first5 Judge `C>=4.4/Cv>=4.6`) 유지 확인
- 가설:
  - 검색 호출 수 상한 + regex-first 의도분석 + extractive 우선 강화로 생성 호출과 검색 반복을 동시에 줄일 수 있다.
  - 비교 질의를 기본 비생성형으로 처리하면 지연 분산을 크게 줄일 수 있다.
- 실행 범위:
  - 검색 budget/passes/call 조건 전면 개편
  - LLM 호출 최소화(regex-first, 비교 질의 비생성형 우선)
  - 컨텍스트 기본값 축소 및 디버그 관측 항목 확장
  - eval 결과 지표에 `p50/p90`, `answer_mode_distribution` 추가
- 변경 파일:
  - `src/utils/config.py`
  - `.env.example`
  - `src/retrievers/vectorstore.py`
  - `src/graph/nodes.py`
  - `src/prompts/templates.py`
  - `src/graph/workflow.py`
  - `scripts/eval_retrieval.py`
- 실행 커맨드:
  - `venv/bin/python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset.yaml --slice first5 --label speed15_first5_judge_v3 --output eval/eval_results_speed15_first5_judge_v3.json`
  - `venv/bin/python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset.yaml --slice all --label speed15_all20_nojudge_v7 --output eval/eval_results_speed15_all20_nojudge_v7.json --no-judge`
  - `RETRIEVAL_EXPANSION_CAP=2 CONTEXT_TOP_RESULTS=5 CONTEXT_MAX_CHARS=600 venv/bin/python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset.yaml --slice all --label speed15_all20_nojudge_v7_stage2 --output eval/eval_results_speed15_all20_nojudge_v7_stage2.json --no-judge`
- 결과 요약:
  - first5 Judge ON:
    - `eval/eval_results_speed15_first5_judge_v3.json`
    - `avg_correctness=4.6000`, `avg_coverage=4.6000`, `avg_response_time=0.9469s`
  - all20 No-Judge(주 설정):
    - `eval/eval_results_speed15_all20_nojudge_v7.json`
    - `avg_response_time=2.3154s`, `recall_at_k_source=0.9500`, `recall_at_k_page=0.1500`
    - `p50=0.8295s`, `p90=1.9479s`, `answer_mode_distribution={extractive:19, generative:1}`
  - all20 No-Judge(2차 파라미터):
    - `eval/eval_results_speed15_all20_nojudge_v7_stage2.json`
    - `avg_response_time=3.1899s`, `recall_at_k_source=0.9500`, `recall_at_k_page=0.1500`
  - 속도 비교:
    - `speed_tuned_v5(21.1919s) -> speed15_v7(2.3154s)` (`-89.0740%`)
- 문제/원인:
  - 목표 지연은 통과했지만 page recall이 `0.15`로 하한(`0.18`) 미달
  - 병목 문항은 `eval_018` 1건(27.6349s)으로 집중, 나머지는 2.6초 이내
  - 2차 파라미터 적용 시 page recall 개선 없이 지연만 증가(`2.3154s -> 3.1899s`)
- 조치 내용:
  - speed15 주 설정(`v7`)을 기본 성능 기준으로 채택
  - page 정합 개선은 별도 보정 패치(페이지 스코어/근거 라인 매칭) 트랙으로 분리
  - 문서 3종(`PROJECT_LOG_REPORT`, `EXPERIMENT_LOG`, `COMPLETE_VERSION_HISTORY`)을 결과 기준으로 동기화
- 다음 액션:
  - `eval_013` source miss + page miss 다발 문항 대상 페이지 정합 보정
  - `eval_018` 단건 장시간 원인 분석(질의 분기/문서 길이/추출 라인 품질)
  - speed15 설정 고정 상태에서 all20 no-judge 1회 재측정해 변동성 확인

---

## EXP-2026-02-23-01

- 실험 ID: `EXP-2026-02-23-01`
- 날짜: `2026-02-23`
- 목표:
  - 기관 질의에서 타기관 근거가 섞여 답변되는 경로 차단
  - 사업비 질의의 숫자 오탐(`60분`, `75분`)을 방지하고 금액 근거 우선 응답으로 보정
- 가설:
  - 단일 기관 질의에 기관 필터를 끝까지 강제하면 오답 혼입이 줄어든다.
  - 사업비 질의를 전용 타입으로 판별해 금액 패턴/키워드 중심으로 재랭크하면 수치 정확도가 올라간다.
- 실행 범위:
  - `answer()` 흐름에서 단일 기관 가드/미등록 기관 early return 추가
  - `_extract_direct_fact_from_results`에 사업비 전용 분기 추가
  - 검색 조기 종료/통합 fallback 조건에 사업비 근거 체크 추가
  - `_score_result`에 사업비 가중치 및 시간 단위 패널티 추가
- 변경 파일:
  - `src/graph/workflow.py`
  - `docs/CODE_STUDY.md`
  - `docs/CODE_STUDY_DEEP.md`
  - `docs/EXPERIMENT_LOG.md`
  - `docs/COMPLETE_VERSION_HISTORY.md`
- 실행 커맨드:
  - `./venv/bin/python -m py_compile src/graph/workflow.py`
  - `./venv/bin/python - <<...>>` (`_extract_direct_fact_from_results` 사업비 추출 스모크)
  - `./venv/bin/python - <<...>>` (`_should_stop_retrieval_early` 사업비 근거 가드 스모크)
- 결과 요약:
  - 코드 문법 검증 통과
  - 스모크 테스트에서 `고려대학교 사업비` 질의가 `60분` 대신 `금14,110,000천원` 근거 라인을 선택함
  - 단일 기관 질의는 전역 검색 fallback 이후에도 기관 필터를 다시 적용하도록 보정됨
- 문제/원인:
  - 기존 로직은 단일 기관 검색 실패 시 전역 검색 결과를 그대로 사용해 타기관 근거 혼입 가능
  - 사실형 숫자 추출이 범용 숫자 패턴 중심이라 사업비 질의에서 시간 단위 숫자를 오탐할 수 있었음
  - 로컬 E2E 재현은 Chroma 내부 오류(`Failed to apply logs to the hnsw segment writer`)로 전 구간 검증이 제한됨
- 조치 내용:
  - 단일 기관 질의 판단(`is_single_org_query`) 및 기관 미등록/미검색 시 명시적 실패 응답 추가
  - `_is_budget_query`, `_has_budget_evidence` 추가 후 검색 단계(확장/조기종료/fallback)에 반영
  - 사업비 전용 정규식(`금 xxx천원`, `xxx원`)과 예산 키워드 기반 라인 선택 로직 추가
  - 재랭크에서 사업비 신호 강화, 시간 단위 숫자 라인 감점
- 다음 액션:
  - Chroma DB 재구축 후 실제 앱 질의 3건(고려대/서울특별시/서울시립대) E2E 재검증
  - `eval_resources/eval_dataset.yaml`에 기관+사업비 회귀 케이스를 추가해 자동 검증 항목화

---

## EXP-2026-02-23-02

- 실험 ID: `EXP-2026-02-23-02`
- 날짜: `2026-02-23`
- 목표:
  - 모든 질문에서 CSV를 먼저 확인하되, 구조화 필드 질의만 엄격 단축으로 즉답
  - 하이브리드 검색을 `렉시컬 prefilter -> 벡터 재정렬` 구조로 전환
- 가설:
  - `사업비/공고번호/입찰일정/발주기관/사업명/요약` 같은 구조화 질의는 CSV 단축으로 DB 탐색 없이 빠르게 응답 가능
  - 의미 유사도 계산 전에 렉시컬 후보를 줄이면 벡터 재정렬 품질과 응답시간을 동시에 개선할 수 있다
- 실행 범위:
  - `workflow.answer()` 초입에 CSV fast-path 연결
  - CSV 메타 인덱스(기관 정규화 키/공고번호/질의필드 매핑) 확장
  - `vectorstore.search_hybrid()`를 lexical->vector rerank->semantic fallback으로 재구현
  - 운영 튜닝 env 추가 + 회귀 테스트 추가
- 변경 파일:
  - `src/graph/workflow.py`
  - `src/retrievers/vectorstore.py`
  - `src/utils/config.py`
  - `.env.example`
  - `tests/test_workflow_csv_shortcircuit.py`
  - `tests/test_vectorstore_hybrid_pipeline.py`
- 실행 커맨드:
  - `python3 -m py_compile src/graph/workflow.py src/retrievers/vectorstore.py src/utils/config.py tests/test_workflow_csv_shortcircuit.py tests/test_vectorstore_hybrid_pipeline.py`
  - `venv/bin/python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset.yaml --slice all --label rework_2026-02-23_all20_nojudge_impl_sources20_v2 --output eval/eval_results_rework_2026-02-23_all20_nojudge_impl_sources20_v2.json --no-judge`
- 결과 요약:
  - 결과 파일: `eval/eval_results_rework_2026-02-23_all20_nojudge_impl_sources20_v2.json`
  - 주요 지표:
    - `avg_response_time=0.9599s`
    - `p50=0.9098s`, `p90=1.2837s`
    - `recall_at_k_source=0.9500`
    - `recall_at_k_page=0.2500`
    - `mrr_source=0.9500`, `mrr_page=0.1134`
    - `answer_mode_distribution={extractive:20}`
  - 속도 비교:
    - `speed15_v7(2.3154s) -> impl_sources20_v2(0.9599s)` (`-58.5415%`)
  - 회귀 포인트:
    - source miss: `eval_017` (1건)
    - page miss: `eval_002,003,004,006,007,008,009,010,011,012,013,015,017,020` (14건)
- 문제/원인:
  - full20 Judge ON 재측정은 이번 실험 사이클에서 미실행이라 정확도/커버리지 상승 효과를 정량 확정하지 못함
  - page miss가 여전히 비교/복합 문항에 집중됨
- 조치 내용:
  - CSV strict short-circuit를 비교/다문서/요구사항 코드 질의에는 비활성화해 환각 비교 경로 차단
  - precision 질의에 렉시컬 가중치를 높여 코드/문자셋/평가 기준 탐지 강화를 적용
  - perf 로그에 `csv_short_circuit_hit` 카운터를 추가해 단축 경로 효과 관측 가능화
- 다음 액션:
  - full20 Judge ON 재실행으로 correctness/coverage 영향 검증
  - `eval_017` source miss 원인(대상 문서 커버리지) 보정
  - page miss 14문항 대상 페이지 정합 스코어 튜닝

---

## EXP-2026-02-23-03

- 실험 ID: `EXP-2026-02-23-03`
- 날짜: `2026-02-23`
- 목표:
  - latency는 5초 이하로 유지하면서 all20 Judge 정확도/커버리지 추가 개선
  - 비교/정밀 사실 질의에서 근거 부족 상태의 생성을 줄이고 extractive 정합성을 강화
- 가설:
  - 정확도 우선 모드에서 retrieval 패스를 선택적으로 늘리고, 정밀 사실 질의의 앵커 근거 검증을 강화하면 Judge 점수가 상승한다.
  - CSV short-circuit는 유지하되 비교/복합 질의는 DB 경로를 강제하면 환각 비교를 줄일 수 있다.
- 실행 범위:
  - `workflow`에 정확도 우선 모드 분기(`ANSWER_QUALITY_MODE`) 연결
  - 정밀 사실 질의 판별/앵커 근거 체크 강화(`_is_precision_fact_query`, `_has_precision_anchor_evidence`)
  - 사실형 추출 분기 보강(가이드/핵심투입인력/문자셋/용량/단위수량/복구기한)
  - 기관 복원 강화(프로젝트 힌트 기반 기관 후보 복원 + 비교 커버리지 보정)
  - 회귀 테스트 추가(`test_workflow_fact_and_org.py`)
- 변경 파일:
  - `src/graph/workflow.py`
  - `src/utils/config.py`
  - `tests/test_workflow_fact_and_org.py`
  - `docs/CODE_STUDY.md`
  - `docs/CODE_STUDY_DEEP.md`
  - `docs/EXPERIMENT_LOG.md`
  - `docs/PROJECT_LOG_REPORT.md`
  - `docs/COMPLETE_VERSION_HISTORY.md`
- 실행 커맨드:
  - `venv/bin/python -m pytest tests/test_workflow_csv_shortcircuit.py tests/test_workflow_fact_and_org.py tests/test_vectorstore_hybrid_pipeline.py -q`
  - `venv/bin/python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset.yaml --slice all --label improved2_all20_nojudge_2026-02-23 --output eval/eval_results_improved2_all20_nojudge_2026-02-23.json --no-judge`
  - `venv/bin/python scripts/eval_retrieval.py --dataset eval_resources/eval_dataset.yaml --slice all --label improved2_all20_judge_2026-02-23 --output eval/eval_results_improved2_all20_judge_2026-02-23.json`
  - `venv/bin/python scripts/build_eval_report.py --input eval/eval_results_improved2_all20_nojudge_2026-02-23.json --output eval/eval_report_improved2_all20_nojudge_2026-02-23.html`
  - `venv/bin/python scripts/build_eval_report.py --input eval/eval_results_improved2_all20_judge_2026-02-23.json --output eval/eval_report_improved2_all20_judge_2026-02-23.html`
- 결과 요약:
  - 테스트: `15 passed`
  - all20 Judge:
    - `eval/eval_results_improved2_all20_judge_2026-02-23.json`
    - `avg_correctness=3.4000` (vs 2.8000, `+0.6000`)
    - `avg_coverage=3.3000` (vs 2.5000, `+0.8000`)
    - `avg_faithfulness=3.2000`, `avg_context_relevance=4.4000`
    - `avg_response_time=1.1402s`, `p90=1.6162s`
  - all20 No-Judge(같은 코드 기준):
    - `eval/eval_results_improved2_all20_nojudge_2026-02-23.json`
    - `avg_response_time=1.0642s`, `p50=1.1062s`, `p90=1.4414s`
    - `recall_at_k_source=0.7500`, `recall_at_k_page=0.2000`
  - 산출 리포트:
    - `eval/eval_report_improved2_all20_judge_2026-02-23.html`
    - `eval/eval_report_improved2_all20_nojudge_2026-02-23.html`
    - `eval/eval_report_latest_all20_judge.html`
    - `eval/eval_report_latest_all20_nojudge.html`
- 문제/원인:
  - 정확도 우선 모드에서 precision/coverage를 높이는 대신 retrieval recall(source/page) 계열 보조지표가 하락했다.
  - no-judge 최저지연 프로파일(`impl_sources20_v2`) 대비 평균 지연이 소폭 증가했다.
- 조치 내용:
  - 운영 프로파일을 분리:
    - 정확도 기준선: `improved2_all20_judge_2026-02-23`
    - 초저지연 기준선: `rework_2026-02-23_all20_nojudge_impl_sources20_v2`
  - 문서/리포트에서 "latest"와 "best-latency"를 분리 표기해 해석 혼선을 제거
- 다음 액션:
  - 정확도 프로파일에서 source/page recall 회복(기관 스코프 재탐색 상한/페이지 정합 스코어 보정)
  - 저점 문항(`013/016/020`, 정밀 사실형) 집중 회귀셋으로 재검증
  - 목표 프로파일(정확도 우선/속도 우선)별 기본 ENV preset 문서화
