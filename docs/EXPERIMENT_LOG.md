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

## 현재까지 변경 요약 (2026-02-13 기준)

| 실험 ID | 핵심 문제 | 왜 변경했는가 | 변경 후 개선 |
|---|---|---|---|
| `EXP-2026-02-13-01` | HWP→PDF 변환 실패로 페이지/표 메타데이터 부족 | CSV 위주 검색 한계를 넘고 원문 근거 검색을 강화하기 위해 | PDF 페이지/표 메타 추출 경로 확보, HWP는 fallback 페이지 분할로 최소 page 메타 확보 |
| `EXP-2026-02-13-02` | CSV 미존재 정보 질의 대응 약함, 임베딩/API 호환 오류 | 원문 기반 추론 응답 강화와 eval 통과 안정화를 위해 | 통합 전처리+메타 매핑+검색 필터/임베딩 배치 개선, gpt-5 파라미터 호환 수정 |
| `EXP-2026-02-13-03` | 평가 스크립트에서 LangSmith 로그 누락 가능성 | 메인과 동일하게 테스트/평가도 추적 가능하게 만들기 위해 | eval 실행이 LangSmith run으로 남고, LLM Judge/평가 체인이 추적 가능해져 디버깅/회귀 비교성 향상 |

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
