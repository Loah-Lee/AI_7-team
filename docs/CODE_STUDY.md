# 입찰메이트 v17+ 코드 스터디 (라인 단위 해설)

> 목적: 내 프로젝트 코드를 실제 줄 번호 기준으로 이해하고, "왜 이 함수가 필요한지"와 "왜 이 값으로 잡았는지"를 학습하는 문서

## 0. 읽는 법

- 기준 코드: 현재 워크트리 (`2026-02-23` 확인)
- 표기 규칙:
  - `파일:줄번호` 형태로 참조
  - import/주석/타입힌트 반복 라인은 묶어서 설명
  - 실행 경로에 영향이 큰 로직은 줄 단위로 상세 설명
- 먼저 볼 실행 경로:
  1. `app/main.py` -> 2) `src/graph/workflow.py` -> 3) `src/retrievers/vectorstore.py` -> 4) `src/parsers/*`

### 0.1 2026-02-23 최신 패치(정확도 보호)

| 줄 | 코드/값 | 왜 중요한가 |
|---|---|---|
| `src/graph/workflow.py:696-705` | 단일 기관 질의 + 미등록 기관 즉시 반환 | 다른 기관 문서가 섞여 오답으로 답하는 경로를 차단. |
| `src/graph/workflow.py:771-776` | 전역 검색 후 기관 필터 재적용 | fallback 검색에서도 기관 경계가 깨지지 않게 보정. |
| `src/graph/workflow.py:1512-1803` | `_extract_direct_fact_from_results(..., target_org)` | 사업비 질의를 별도 처리해 `60분` 같은 무관 수치 과매칭을 억제. |
| `src/graph/workflow.py:1768-1793` | 사업비 전용 정규식/근거 라인 선택 | `금 xxx천원`, `xxx원` 패턴과 `사업비/예산` 키워드가 있는 라인 우선. |
| `src/graph/workflow.py:2045-2046` | 질의 확장에 `사업비 예산 금액` 추가 | 검색 단계에서 사업비 근거를 더 안정적으로 회수. |
| `src/graph/workflow.py:2163-2170` | 사업비 근거 없으면 조기 종료 금지 | 충분한 금액 근거가 나올 때까지 검색을 이어감. |
| `src/graph/workflow.py:2489-2506` | 재랭크에 사업비 가중치/시간값 패널티 | 금액 라인을 상위로 끌어올리고, 시간 단위 숫자 라인을 하향. |
| `src/graph/workflow.py:2588-2608` | `_is_budget_query`, `_has_budget_evidence` | 사업비 질의 판별과 검색 품질 가드를 함수화. |
| `src/graph/workflow.py:2779-2804` | `_filter_results_by_org`, `_build_org_not_found_payload` | 단일 기관 질의의 결과 격리 + 실패 응답 표준화. |

### 0.2 2026-02-23 최신 패치 2차(CSV fast-path + 하이브리드 전환)

| 줄 | 코드/값 | 왜 중요한가 |
|---|---|---|
| `src/graph/workflow.py:233` | `_is_csv_shortcircuit_eligible()` | 비교/다문서/요구사항 코드 질의는 단축 금지, 구조화 필드만 즉답하도록 엄격 제어. |
| `src/graph/workflow.py:365` | `_build_csv_shortcircuit_payload()` | 사업비/공고번호/입찰일정/발주기관/사업명/요약 응답을 표준 payload로 빠르게 생성. |
| `src/graph/workflow.py:417` | `_try_csv_short_circuit()` | CSV 인메모리 인덱스에서 상수시간 조회 후 조기 반환. |
| `src/graph/workflow.py:965` | `answer()` CSV fast-path 연결 | 의도 파악 직후 단축 경로를 먼저 시도해 DB 검색 호출을 줄임. |
| `src/graph/workflow.py:889` | `csv_short_circuit_hit` perf 카운터 | 단축 경로 실제 적중률을 운영 로그에서 추적 가능. |
| `src/retrievers/vectorstore.py:295` | `search_hybrid()` 재구성 | semantic+keyword 단순 병합에서 lexical prefilter -> vector rerank 구조로 전환. |
| `src/retrievers/vectorstore.py:215` | `search_keyword(..., scan_limit)` | 렉시컬 후보군 크기를 제어해 prefilter 비용을 제한. |
| `src/retrievers/vectorstore.py:458` | `_rerank_lexical_candidates()` | 후보 ID 기반 임베딩 재조회 후 코사인 점수로 의미 재정렬 수행. |
| `src/utils/config.py:92-95` | 신규 ENV 4종 | `CSV_SHORTCIRCUIT_ENABLED`, `HYBRID_LEXICAL_*`로 운영 튜닝 가능. |
| `tests/test_workflow_csv_shortcircuit.py:117` | CSV 즉답 회귀 테스트 | 구조화 질의 단축 성공/비교 질의 단축 금지 동작을 고정. |
| `tests/test_vectorstore_hybrid_pipeline.py:21` | 하이브리드 파이프라인 테스트 | 렉시컬 충분/부족/precision 질의 3개 시나리오를 검증. |

### 0.3 2026-02-23 최신 패치 3차(정확도 우선 모드 + 정밀 사실 강화)

| 줄 | 코드/값 | 왜 중요한가 |
|---|---|---|
| `src/utils/config.py:92` | `ANSWER_QUALITY_MODE` | 운영 모드를 `balanced/accurate`로 분리해 정확도 우선 튜닝을 런타임에서 제어. |
| `src/graph/workflow.py:3361-3367` | `_is_accuracy_mode_enabled()` | 정확도 우선 모드일 때만 검색/후처리 보강 로직을 활성화. |
| `src/graph/workflow.py:3367-3431` | `_is_precision_fact_query`, `_has_precision_anchor_evidence` | 숫자/단위/문자셋/요구사항 코드 질의에서 앵커 근거 없는 임의 응답을 방지. |
| `src/graph/workflow.py:2006-2683` | `_extract_direct_fact_from_results()` | 용량/단위수량/복구기한/문자셋/요구사항 코드/가이드/핵심투입인력 분기 추출 정밀화. |
| `src/graph/workflow.py:3710-3803` | 프로젝트 힌트 + 기관 커버리지 보강 | 비교 질의에서 기관 복원 실패를 줄이고 기관별 최소 근거를 강제 확보. |
| `tests/test_workflow_fact_and_org.py:1` | 사실형/기관 복원 회귀 테스트 | 정밀 사실 추출과 비교 기관 복원 회귀를 자동 검증. |

---

## 1. 설정값이 시스템 행동을 결정하는 방식

### 1.1 `src/utils/config.py` 라인 해설

| 줄 | 코드/값 | 왜 이렇게 했는가 |
|---|---|---|
| `src/utils/config.py:15` | `OPENAI_API_KEY` | 키가 있으면 원격 LLM/임베딩, 없으면 로컬 fallback 흐름으로 자연 전환하기 위해 nullable 처리. |
| `src/utils/config.py:16` | `EMBEDDING_MODEL=text-embedding-3-small` | 1536차원/비용 균형. 현재 코드의 `EmbeddingConfig.dimension=1536`과 일치. |
| `src/utils/config.py:17` | `DEFAULT_MODEL=gpt-5-mini` | 평가/Judge 기본 모델이 모델 변수 하나로 통일되게 하기 위해. |
| `src/utils/config.py:18` | `REASONING_MODEL=gpt-5-mini` | 실서비스 답변 모델을 분리 가능하게 하되 기본은 동일 모델로 운영 복잡도를 낮춤. |
| `src/utils/config.py:21-27` | `EmbeddingConfig` | 임베딩 설정을 단일 객체로 모아 OpenAI/로컬 모델 전환 시 코드 분기 최소화. |
| `src/utils/config.py:44-53` | `_get_env_int()` | env 오입력(문자열/음수)에도 기본값+하한 보장으로 런타임 장애 예방. |
| `src/utils/config.py:56-65` | `_get_env_float()` | float 파라미터도 동일 방어 로직 적용. 튜닝 실험에서 오타 내도 안전. |
| `src/utils/config.py:71` | `MAX_TEXT_LENGTH=20000` | CSV 원문 텍스트가 너무 길 때 마크다운 폭주 방지. |
| `src/utils/config.py:72` | `MIN_SECTION_LENGTH=50` | 너무 짧은 노이즈 문장(헤더/꼬리말) 인덱싱 억제 기준. |
| `src/utils/config.py:74` | `MAX_PAGES` 기본 `120` | PDF/HWP 전부 읽는 비용을 제한하면서도 대부분 문서를 포함하는 상한. `<=0`이면 전체 허용. |
| `src/utils/config.py:81` | `RETRIEVAL_EXPANSION_CAP=3` | 질의 확장은 효과가 있지만 호출이 늘어나므로 기본 3으로 시작하는 타협값. |
| `src/utils/config.py:82` | `RETRIEVAL_SEARCH_PASSES=1` | 기본 패스를 최소화해 latency 절감. 필요 시 env로 확장 가능. |
| `src/utils/config.py:83-85` | `RETRIEVAL_HIGH_RECALL_K_MULTIPLIER=0.8` | 정밀 질의에서 검색 폭을 늘리되 `top_k` 대비 과도 확장을 막기 위한 비율 파라미터. |
| `src/utils/config.py:86` | `CONTEXT_TOP_RESULTS=6` | LLM 컨텍스트 길이와 근거 다양성의 균형점. |
| `src/utils/config.py:87` | `CONTEXT_MAX_CHARS=700` | 컨텍스트 토큰 비용 억제를 위한 기본 컷. |
| `src/utils/config.py:88` | `RETRIEVAL_MAX_HYBRID_CALLS=6` | 하이브리드 검색 과호출 방지 예산. `workflow`에서 직접 소진 관리. |
| `src/utils/config.py:89` | `KEYWORD_SCAN_LIMIT=1200` | 키워드 검색 시 전수 스캔 비용 상한. |
| `src/utils/config.py:90` | `INTENT_REGEX_FIRST=true` | 단순 질의에서 LLM 호출을 줄여 속도/비용 개선하기 위한 기본 전략. |
| `src/utils/config.py:92` | `ANSWER_QUALITY_MODE=balanced` | 기본은 균형 모드, 필요 시 정확도 우선 모드로 전환 가능. |
| `src/utils/config.py:103-107` | `ORG_ALIASES` | 약칭 질의("고려대")를 정식 기관명으로 통일해 검색/필터 누락 방지. |
| `src/utils/config.py:113-115` | 랭킹 키워드 세트 | 의도 파서 regex에서 랭킹 상/하위 방향성 추론을 위해 분리. |
| `src/utils/config.py:126-135` | `get_default_db_path()` | DB 경로를 `schema + page_scope + include_pattern_hash`로 구성해 실험 조건 충돌을 방지. |

핵심 요약:
- 이 파일의 숫자는 단순 상수가 아니라 "속도/비용/정확도" 트레이드오프 핸들이다.
- `workflow`는 이 값을 그대로 신뢰하고 행동하므로, 여기 변경은 시스템 동작 변경과 동일하다.

---

## 2. 데이터 계약: 답변 품질 메타를 왜 따로 관리하나

### 2.1 `src/graph/state.py` 라인 해설

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/graph/state.py:15-25` | `OrgInfo` | 기관 단위로 정렬/랭킹/필터를 하기 위한 최소 모델. `amount`(표시용)와 `amount_numeric`(연산용) 분리. |
| `src/graph/state.py:29-39` | `MarkdownData` | 파서 결과를 공통 형태로 맞춰 CSV/PDF/HWP를 동일 파이프라인에 태우기 위함. |
| `src/graph/state.py:43-53` | `QueryIntent` | 의도 파싱 결과를 구조화해 검색/응답 분기 로직의 입력 계약으로 사용. |
| `src/graph/state.py:57-63` | `QuestionPlan` | 질문 유형별 필수 슬롯 관리(`value`, `unit`, `owner`, `comparison`)를 위해 추가된 계층. |
| `src/graph/state.py:66-73` | `EvidenceSpan` | "답변이 어떤 근거에서 나왔는지"를 소스/페이지/스니펫 단위로 추적하기 위해 필요. |
| `src/graph/state.py:76-83` | `AnswerDraft` | answer_mode/신뢰도/슬롯 충족률을 응답 payload로 표준화하기 위한 컨테이너. |
| `src/graph/state.py:92` | `max_history=5` | 대화 품질은 유지하면서 토큰 폭증을 막기 위한 메모리 길이. |
| `src/graph/state.py:114-124` | `get_context_summary()` 최근 3개 | 전체 대화를 넣지 않고 최근 문맥만 요약해 프롬프트 비용 절감. |
| `src/graph/state.py:135-139` | 후속질문 키워드 | 한국어 대화형 질의("그거", "얼마", "더")를 규칙 기반으로 가볍게 식별. |

---

## 3. 의도 파싱과 질문 플래닝

### 3.1 `src/graph/nodes.py` 라인 해설

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/graph/nodes.py:35-59` | `parse()` | `LLM only`가 아니라 `regex-first`/`LLM-first`를 config로 전환 가능하게 설계. |
| `src/graph/nodes.py:43` | regex 신뢰도 임계 `0.75` | 규칙 결과가 충분히 확실하면 LLM 호출을 생략하기 위한 컷오프. |
| `src/graph/nodes.py:54` | LLM fallback 임계 `0.7` | LLM 신뢰가 낮을 때 regex 재판단. 실수형 confidence를 실제 분기에 사용. |
| `src/graph/nodes.py:66` | "JSON만 반환" 시스템 지시 | LLM 출력 파싱 안정성 확보(자유 텍스트 섞임 방지). |
| `src/graph/nodes.py:73-83` | `QueryIntent(...)` 생성 | 누락 필드가 있어도 안전 기본값으로 payload 안정화. |
| `src/graph/nodes.py:92` | regex 기본 confidence `0.6` | 분류 근거가 약한 기본 상태를 숫자로 표현해 후속 비교에 사용. |
| `src/graph/nodes.py:94-101` | 랭킹 우선 검사 | "가장/최소/TOP" 질의는 검색보다 계산형 처리라 먼저 분기. |
| `src/graph/nodes.py:112-115` | 금액 범위 정규식 | "5억~10억"/"5억에서 10억" 한국어 표현을 직접 커버. |
| `src/graph/nodes.py:129-132` | 카테고리 키워드 사전 | 카테고리 질의를 저비용으로 빠르게 분류하는 휴리스틱. |
| `src/graph/nodes.py:178-223` | `QuestionPlanner.build()` | 의도와 별개로 "답변 완성 조건(required_slots)"을 정의해 품질 측정/후처리에 사용. |
| `src/graph/nodes.py:182-189` | 비교 질의 슬롯 3개 | `docA_claim`, `docB_claim`, `comparison_point`를 강제해 비교 답변 붕괴를 막음. |
| `src/graph/nodes.py:236-267` | `RFPAnswerGenerator.generate()` | LLM 호출/프롬프트 조합/예외 처리 역할만 담당해 workflow와 책임 분리. |
| `src/graph/nodes.py:270-275` | `_token_limit_arg()` | GPT-5는 `max_completion_tokens`, 타 모델은 `max_tokens`를 쓰는 API 차이 대응. |

---

## 4. 핵심 오케스트레이터: `workflow.py` 완전 해설

## 4.1 초기화/로딩 파이프라인

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/graph/workflow.py:56-70` | `data_dir` 정규화 | 상대경로/절대경로/`data/files` 구조 차이를 자동 흡수해 실행 환경 의존성을 줄임. |
| `src/graph/workflow.py:73-78` | LLM `temperature=0.0` | 문서 QA는 창의성보다 일관성이 우선이라 결정적 출력을 선호. |
| `src/graph/workflow.py:86-87` | `get_default_db_path()` 사용 | 앱/CLI/재구축 스크립트 DB 경로 불일치 문제를 근본 해결. |
| `src/graph/workflow.py:94-99` | runtime 폴더 + 실패 레지스트리 경로 | 인덱싱 산출물과 실패 상태를 로컬 파일로 영속화해 재시작 복구 가능. |
| `src/graph/workflow.py:103-127` | `_load_documents()` | "CSV 먼저 -> 문서 원본 -> 기존 DB 재사용 시 레지스트리 보강" 순서 고정. |
| `src/graph/workflow.py:111-114` | CSV 청크 미존재 시 재인덱싱 | 부분 손상 DB에서도 자동 자가복구. |
| `src/graph/workflow.py:129-161` | `_load_csv_files()` | CSV는 메타데이터의 단일 진실원천이라 항상 먼저 읽고 인덱싱 여부는 옵션으로 분리. |
| `src/graph/workflow.py:163-187` | 파일명/스템/기관명 인덱스 3종 | 원본 문서와 CSV 매칭 성공률을 높이기 위한 다중 키 조회 구조. |
| `src/graph/workflow.py:224` | `max_chars=1600`, `overlap=180` | 긴 원문 섹션을 검색 가능한 길이로 분할하되 경계 손실을 overlap으로 완화. |

## 4.2 실패 레지스트리/증분 인덱싱

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/graph/workflow.py:388-431` | `_load_failed_sources_registry()` | JSON 스키마 변형(`entries` 있거나 없음)까지 허용해 호환성 확보. |
| `src/graph/workflow.py:433-447` | 저장 시 `version`, `updated_at` 기록 | 운영 중 실패 히스토리 추적 가능하게 하려는 의도. |
| `src/graph/workflow.py:449-465` | 파일 시그니처 비교 후 자동 해제 | 파일이 수정되면 실패 상태를 해제해 자동 재시도되도록 설계. |
| `src/graph/workflow.py:467-478` | 실패 reason 300자 제한 | 레지스트리 파일 비대화 방지 + 로그 가독성 유지. |
| `src/graph/workflow.py:486-498` | `_has_unindexed_document_files()` | 이미 인덱싱되었거나 실패 레지스트리면 skip; 진짜 신규만 처리. |
| `src/graph/workflow.py:543-558` | 인덱싱/영구실패 스킵 분기 | 반복 실행 시 "변환 중" 루프를 줄여 운영 시간을 절감. |
| `src/graph/workflow.py:601-602` | `MIN_SECTION_LENGTH` 이하 페이지 제외 | 빈 페이지/헤더 노이즈 청크를 제거해 검색 오염 감소. |
| `src/graph/workflow.py:614-617` | `source_origin`, `original_ext` 메타 | 후속 분석에서 CSV/원문 출처를 분리 추적하기 위해 필요. |

## 4.3 질의응답 메인 루프

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/graph/workflow.py:645` | `top_k` 기본 `24` | 일반 질의 대비 다문서/비교 질의를 함께 커버하는 기본 탐색 폭. |
| `src/graph/workflow.py:648-656` | `perf_stats` | 호출수/시간/예산 소진을 답변 단위로 계측해 튜닝 근거를 남김. |
| `src/graph/workflow.py:669-674` | ranking 즉시 분기 | 랭킹은 벡터검색 불필요. 정렬 계산으로 즉시 응답하는 것이 정확/빠름. |
| `src/graph/workflow.py:685-693` | 후속질문 기관 복원 | 명시 기관이 없으면 이전 기관을 유지해 대화 자연성 확보. |
| `src/graph/workflow.py:700-703` | 비교/사실형은 `top_k` 확대 | 비교 질의 근거 다양성 확보와 수치 질의의 근거 회수율 확보 목적. |
| `src/graph/workflow.py:712-754` | original fallback | CSV 치우침 결과를 원문(PDF/HWP)으로 보정해 근거 품질 강화. |
| `src/graph/workflow.py:764-771` | 검색 실패 payload 표준화 | 상위 레이어(UI/eval)가 항상 동일 필드를 받게 보장. |

## 4.4 답변 생성/후처리 품질 장치

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/graph/workflow.py:801` | `max_items=3` evidence | 증거를 너무 많이 노출하면 잡음 증가. 핵심 3개로 압축. |
| `src/graph/workflow.py:818-833` | 추출 우선(extractive-first) | 수치/기한/책임 질의는 LLM 자유생성보다 직접 추출이 오류가 적음. |
| `src/graph/workflow.py:877-882` | uncertain 답변시 hybrid fallback | LLM이 "명시없음"으로 과보수 응답할 때 규칙기반 근거로 보완. |
| `src/graph/workflow.py:929-936` | 책임/보안 질의 특화 조건 | 도메인 고빈도 실패 케이스를 별도 분기해 정밀도 보강. |
| `src/graph/workflow.py:949` | 보안 질의 `evidence_limit=6` | 보안 요구사항은 단일 문장보다 복수 근거가 필요해 상한 확대. |
| `src/graph/workflow.py:1011-1043` | EvidenceSpan 생성 | 소스/페이지/스코어/슬롯을 구조화해 eval 및 UI 재활용 가능. |
| `src/graph/workflow.py:1171-1207` | `_build_answer_payload()` | 응답 스키마를 중앙화해 누락/형식 편차 방지. |
| `src/graph/workflow.py:1216-1223` | 섹션 라벨 치환 | 모델이 `[근거]`/`[근거 요약]` 등 다르게 출력해도 UI 표준 유지. |
| `src/graph/workflow.py:1235-1237` | 출처 bullet 자동 보정 | 출처 섹션에서 bullet 누락되면 렌더 가독성 저하 -> 자동 수정. |
| `src/graph/workflow.py:1244-1290` | 슬롯충족률 계산 | "답이 그럴듯한가"가 아니라 "필수 슬롯이 채워졌는가"를 정량화. |
| `src/graph/workflow.py:1298-1305` | confidence 휴리스틱 | 슬롯충족률 + 근거수 + answer_mode를 조합한 경량 신뢰 점수. |

## 4.5 검색 확장/예산/재랭크

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/graph/workflow.py:1948-1998` | `_expand_query_terms()` | 질의 표현이 짧거나 모호할 때 도메인 키워드를 붙여 recall 개선. |
| `src/graph/workflow.py:2009-2013` | 확장 cap 상향(보안/비교) | 어려운 질의 유형에만 확장 폭을 동적으로 늘려 효율 유지. |
| `src/graph/workflow.py:2060-2087` | 조기종료 조건 | 충분한 다양성/커버리지 확보 시 반복 검색 중단해 latency 절감. |
| `src/graph/workflow.py:2106-2115` | 하이브리드 예산 소진 | 무한 호출 방지. 예산 소진 시 fallback/종료 분기 근거 제공. |
| `src/graph/workflow.py:2166` | 기본 `primary_types=[pdf,hwp]` | 원문 근거 우선 정책. CSV는 필요 시 보강 패스로만 사용. |
| `src/graph/workflow.py:2168` | `per_call_k=max(8, top_k*0.8)` | 호출당 결과가 너무 적으면 병합 효과가 없고, 너무 크면 느려지므로 중간값. |
| `src/graph/workflow.py:2207-2229` | CSV 보강 패스 조건부 실행 | 이미 충분한 결과가 있으면 CSV 검색을 생략해 시간 절약. |
| `src/graph/workflow.py:2234-2261` | 통합 fallback 패스 | precision/high-recall 질의에서 마지막으로 all-type 검색을 한번 더 수행. |
| `src/graph/workflow.py:2323-2340` | 재랭크 + stable sort | 점수 동률시 입력 순서(인덱스) 기준 안정정렬로 결과 흔들림 완화. |
| `src/graph/workflow.py:2363-2368` | 원문 우선 + 기관 일치 가중치 | 정확한 기관 질의에서 오탐 줄이는 핵심 가중치. |
| `src/graph/workflow.py:2394-2410` | 수치/단위/문자셋 가중치 | 도메인 질문 타입에 맞춰 근거성 높은 라인 우선 노출. |
| `src/graph/workflow.py:2429-2433` | 협상/배점/85% 가중치 | 반복 실패 문항 패턴을 반영한 도메인 특화 재랭크 룰. |

## 4.6 컨텍스트 구성/랭킹 응답

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/graph/workflow.py:2505-2506` | 비교질의 컨텍스트 보정(+2, +200자) | 비교 질문은 양쪽 근거가 필요해 단일 질문보다 더 넓은 컨텍스트를 허용. |
| `src/graph/workflow.py:2517` | `_extract_relevant_excerpt()` 사용 | 원문을 그대로 넣지 않고 질문 관련 부분만 추출해 토큰 절약 + 정확도 개선. |
| `src/graph/workflow.py:2574-2635` | `_handle_ranking_query()` | 랭킹은 구조화된 표 출력으로 사용자 해석 비용을 낮춤. |
| `src/graph/workflow.py:2580` | N 추출 regex | "3곳/TOP5/TOP 5" 변형 표현을 모두 허용하려는 UX 배려. |

---

## 5. 검색 엔진 구현 디테일

### 5.1 `src/retrievers/vectorstore.py` 라인 해설

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/retrievers/vectorstore.py:54` | `last_hybrid_stats` 확장 | fallback 여부, prefilter 크기, rerank 개수까지 계측. |
| `src/retrievers/vectorstore.py:67-101` | `add_documents()` + `upsert` | 재실행/재인덱싱 시 덮어쓰기 가능하게 하여 idempotent 처리. |
| `src/retrievers/vectorstore.py:215-274` | `search_keyword()` | 렉시컬 prefilter 후보를 `id/lexical_score` 포함 형태로 반환. |
| `src/retrievers/vectorstore.py:295-372` | `search_hybrid()` | 렉시컬 선별 -> 벡터 재정렬 -> semantic fallback의 적응형 흐름. |
| `src/retrievers/vectorstore.py:320` | `_rerank_lexical_candidates()` 호출 | 후보군 내부 의미 유사도 재정렬로 precision/coverage 균형 보정. |
| `src/retrievers/vectorstore.py:374` | `_build_where_filter()` | `org_name/doc_types` 필터를 모든 검색 단계에 일관 적용. |
| `src/retrievers/vectorstore.py:401` | `_merge_dedup_results()` | `source/org/page/type/section` 기준 중복 제거 유지. |
| `src/retrievers/vectorstore.py:432` | `_fetch_candidates_by_ids()` | 후보 ID 기반 문서/메타/임베딩 재조회로 재랭크 품질 확보. |
| `src/retrievers/vectorstore.py:458` | `_rerank_lexical_candidates()` | precision 질의는 lexical 65%, 일반 질의는 vector 65% 가중. |
| `src/retrievers/vectorstore.py:361` | `last_hybrid_stats` 저장 | `keyword_reason`, `fallback_used`를 workflow 성능 로그로 집계. |
| `src/retrievers/vectorstore.py:535` | `get_indexed_sources()` | 증분 인덱싱에서 이미 처리된 source를 빠르게 판별하기 위한 핵심 API. |

---

## 6. 파서 계층: 입력 품질이 답변 품질을 결정

### 6.1 CSV 파서 `src/parsers/csv_loader.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/parsers/csv_loader.py:25-28` | 파일명 기반 기관 추출 | 원본 문서와 CSV 매칭 시 최소한의 공통 키를 만들기 위함. |
| `src/parsers/csv_loader.py:38` | `MIN_SECTION_LENGTH` 필터 | 빈 섹션/잡음 섹션 제거. |
| `src/parsers/csv_loader.py:58-71` | `MARKDOWN_TEMPLATE` 채움 | CSV를 문서형 텍스트로 바꿔 벡터검색 대상과 형식 통일. |
| `src/parsers/csv_loader.py:68` | 파일형식 기본 `HWP` | 데이터 누락 상황에서 보수적 기본값 제공. |
| `src/parsers/csv_loader.py:92-95` | metadata 저장 | 후속 검색/랭킹/출처 표시에 필요한 필드를 유지. |
| `src/parsers/csv_loader.py:104` | `utf-8-sig` | BOM 포함 CSV를 안전하게 파싱하기 위해. |
| `src/parsers/csv_loader.py:155` | 텍스트 2만자 컷 | 원문 컬럼 과대 길이로 인한 인덱싱 폭주 방지. |

### 6.2 PDF 파서 `src/parsers/pdf_loader.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/parsers/pdf_loader.py:46-72` | 표를 markdown table로 변환 | 표 정보가 텍스트로 유실되지 않도록 검색 가능한 포맷으로 보존. |
| `src/parsers/pdf_loader.py:83` | `limit = MAX_PAGES` | 페이지 수 상한을 중앙 config로 제어. |
| `src/parsers/pdf_loader.py:92-97` | `include_tables` 조건 처리 | 속도 중심/정확도 중심 모드 선택 가능. |
| `src/parsers/pdf_loader.py:105-115` | 페이지 단위 구조(`page`,`table_count`) | 근거 페이지 추적과 평가(page recall)에 필요. |
| `src/parsers/pdf_loader.py:138-151` | 추출 실패 시 명시적 마크다운 | 실패 상태도 downstream에서 식별 가능하게 텍스트로 남김. |

### 6.3 HWP 파서 `src/parsers/hwp_loader.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/parsers/hwp_loader.py:29-31` | `hwp5txt`, `hwp5html`, generation_mode | 변환 경로/품질 모드를 추적하기 위해 상태 보관. |
| `src/parsers/hwp_loader.py:75-85` | headless LibreOffice env | 서버/CI 환경에서 GUI 의존 없이 변환이 돌도록 환경 격리. |
| `src/parsers/hwp_loader.py:135-144` | LibreOffice 변환 예외시 `None` 반환 | 상위에서 fallback 경로로 자연 전환하기 위한 계약. |
| `src/parsers/hwp_loader.py:159-184` | 한글 폰트 선택 | fallback PDF 렌더에서 한글 깨짐 최소화. |
| `src/parsers/hwp_loader.py:289-307` | `_is_pdf_quality_acceptable()` | 변환 "성공" 여부가 아니라 추출 텍스트량 기준으로 품질 판단. |
| `src/parsers/hwp_loader.py:301-306` | 임계치 `2500`, `0.28`, `4페이지` | 너무 작은 변환 결과를 저품질로 판단하기 위한 경험적 안전선. |
| `src/parsers/hwp_loader.py:320-323` | 캐시 재사용 | 동일 파일 반복 변환 비용 절감. |
| `src/parsers/hwp_loader.py:324-339` | LibreOffice 실패 -> text render fallback | HWP 계열에서 "무응답" 대신 최소한의 검색 가능 텍스트를 확보. |
| `src/parsers/hwp_loader.py:443` | `max_chars=1800` logical page | HWP 텍스트 추출 시 페이지성 단위를 만들기 위한 분할값. |
| `src/parsers/hwp_loader.py:463-466` | 최종 fallback으로 PDF 추출 재사용 | PDF 파서 로직을 재사용해 코드 중복을 줄이고 결과 형식을 통일. |

### 6.4 통합 전처리기 `src/parsers/preprocessor.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/parsers/preprocessor.py:30` | `build(overwrite, max_rows)` | 대용량 전처리를 단계적으로 실행/검증할 수 있게 옵션화. |
| `src/parsers/preprocessor.py:58-64` | CSV 자동 탐색 | 파일명 변형(`data_list*`, `*data*`)을 허용해 운영 실수 대응. |
| `src/parsers/preprocessor.py:66-77` | source 파일 resolve | exact 매칭 실패 시 stem 기반 느슨한 매칭으로 연결 성공률 상승. |
| `src/parsers/preprocessor.py:97-103` | HWP는 PDF 변환 후 동일 파서 | 입력 포맷이 달라도 검색 대상 구조를 통일하기 위한 선택. |
| `src/parsers/preprocessor.py:113-129` | manifest record | 실험/디버깅 때 어떤 행이 어떤 원본과 매칭됐는지 증빙. |

---

## 7. 임베딩 계층

### 7.1 `src/retrievers/embeddings.py` 라인 해설

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/retrievers/embeddings.py:29` | `FORCE_LOCAL_EMBEDDINGS` | API 키가 있어도 로컬 강제 테스트를 가능하게 하는 운영 스위치. |
| `src/retrievers/embeddings.py:35-41` | 로컬 모델 초기화 예외 흡수 | 의존성 미설치 환경에서 즉시 크래시 대신 graceful fallback. |
| `src/retrievers/embeddings.py:85` | `batch_size=64` | OpenAI 임베딩 API 요청당 부하/안정성 균형을 위한 배치 크기. |
| `src/retrievers/embeddings.py:117-121` | dimension 반환 분기 | backend(openai/local)에 따라 차원이 달라질 수 있어 런타임 확인용 제공. |

---

## 8. 프롬프트 설계

### 8.1 `src/prompts/templates.py` 라인 해설

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/prompts/templates.py:10-31` | `MARKDOWN_TEMPLATE` | CSV를 질의 가능한 문서 스키마로 강제 변환. |
| `src/prompts/templates.py:40-49` | 절대 원칙 8개 | 환각/메타답변을 줄이고 문서 근거 중심 답변 강제. |
| `src/prompts/templates.py:55-58` | 사실형 우선 규칙 | 수치 질문에서 장황한 설명을 억제하고 값 먼저 출력하게 함. |
| `src/prompts/templates.py:81-110` | `ANSWER_GENERATION_PROMPT` 형식 강제 | `핵심 답변/근거 요약/출처` 구조를 모델 레벨에서 선행 유도. |
| `src/prompts/templates.py:116-155` | 의도분석 JSON 스키마 | 파서가 신뢰할 수 있는 구조 데이터를 얻기 위한 스키마 명시. |

---

## 9. 앱(UI) 계층

### 9.1 `app/main.py` 라인 해설

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `app/main.py:31-36` | LangSmith env 주입 | 앱에서 발생한 체인도 평가 스크립트와 같은 방식으로 추적 가능. |
| `app/main.py:43-48` | `layout=wide` | 문서형 답변(근거/출처)이 길어질 때 가독성 확보. |
| `app/main.py:126-132` | `@st.cache_resource` | 앱 rerun 시 챗봇/DB 재초기화 비용 방지. |
| `app/main.py:139-143` | source badge 매핑 | 답변 출처 타입을 사용자가 즉시 파악하도록 시각적 구분. |
| `app/main.py:189-227` | 빠른 질문 버튼 | 대표 사용 시나리오를 클릭형으로 제공해 데모/검증 속도 향상. |
| `app/main.py:252-268` | 메트릭 카드 | 현재 인덱스 상태(기관 수/문서 수/청크 수)를 화면에서 즉시 확인. |
| `app/main.py:271-293` | 질의 처리 + 응답시간 | 사용자 체감 성능 확인과 로그 없는 상황에서 디버깅 단서 제공. |
| `app/main.py:332-337` | 중복 전송 방지 조건 | session_state 기반 버튼/입력 중복 실행을 방지. |

---

## 10. 평가/운영 스크립트

### 10.1 `scripts/eval_retrieval.py` 라인 해설

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `scripts/eval_retrieval.py:46-55` | `LOW8_IDS` | 반복 저성능 문항만 빠르게 검증하는 집중 실험용 슬라이스. |
| `scripts/eval_retrieval.py:68-76` | `slice=all/low8/first5` | 속도 실험과 품질 실험을 분리해 비용을 줄이기 위한 인터페이스. |
| `scripts/eval_retrieval.py:118-126` | Judge context `max_docs=3`, 문서당 500자 | judge 비용 폭증 없이 핵심 근거만 전달. |
| `scripts/eval_retrieval.py:129-174` | retrieval metric 계산 | source/page recall, MRR를 질문별로 쌓아 전체 품질을 정량화. |
| `scripts/eval_retrieval.py:206` | judge context 2000자 컷 | Judge 안정성과 비용을 위한 상한. |
| `scripts/eval_retrieval.py:261-277` | answer 메타 추출 | `answer_mode`, `slot_fill_rate`, `confidence`를 실험 지표로 활용. |
| `scripts/eval_retrieval.py:350-353` | `p50`, `p90`, mode 분포 | 평균만으로 숨겨지는 tail latency/모드 편향을 파악하기 위함. |
| `scripts/eval_retrieval.py:380` | `top_k` 기본 10 | 평가 비교를 위한 표준 검색 폭. |
| `scripts/eval_retrieval.py:381` | `--no-judge` 옵션 | 비용 높은 Judge를 끄고 retrieval/latency만 빠르게 반복 측정 가능. |

### 10.2 `scripts/rebuild_db.py` 라인 해설

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `scripts/rebuild_db.py:23` | DB 경로를 `get_default_db_path()`로 계산 | 앱과 동일한 인덱스 경로를 보장해 "재구축했는데 앱에서 안 보이는" 문제 제거. |
| `scripts/rebuild_db.py:33-40` | 삭제 확인 프롬프트 | 실수로 기존 DB를 날리는 사고 방지. |
| `scripts/rebuild_db.py:44` | `RAGChatbotV17` 초기화로 재구축 | 별도 파이프라인 구현 없이 실제 운영 코드 그대로 재사용해 정합성 확보. |

---

## 11. 왜 이 숫자인가: 튜닝값 해석표

| 파라미터 | 기본값 | 영향 | 크게 늘리면 | 줄이면 |
|---|---:|---|---|---|
| `RETRIEVAL_EXPANSION_CAP` | 3 | 질의 확장 개수 | recall↑ latency↑ | latency↓ recall↓ |
| `RETRIEVAL_MAX_HYBRID_CALLS` | 6 | 검색 예산 | 더 느리지만 놓침↓ | 빠르지만 놓침↑ |
| `CONTEXT_TOP_RESULTS` | 6 | LLM 입력 문서 수 | 근거 다양성↑ 토큰↑ | 빠름↑ 문맥 손실↑ |
| `CONTEXT_MAX_CHARS` | 700 | 문서당 컨텍스트 길이 | 상세 근거↑ 비용↑ | 비용↓ 누락↑ |
| `KEYWORD_SCAN_LIMIT` | 1200 | 키워드 스캔 후보수 | 정밀키워드 hit↑ 느림↑ | 빠름↑ miss↑ |
| `MAX_PAGES` | 120 | 문서 페이지 수집 범위 | coverage↑ 인덱싱시간↑ | 인덱싱 빠름↑ 근거누락↑ |
| `_split_text_for_retrieval.max_chars` | 1600 | CSV 긴 문단 분할 | 덜 쪼개짐(문맥↑) | 더 쪼개짐(검색정밀↑) |
| `_split_text_for_retrieval.overlap` | 180 | 청크 경계 보정 | 중복↑ recall↑ | 중복↓ 경계손실↑ |

---

## 12. "이 함수 왜 있지?" 빠른 인덱스

- 의도/질문계획
  - `src/graph/nodes.py:35` `parse()`
  - `src/graph/nodes.py:178` `QuestionPlanner.build()`
- 인덱싱 안정화
  - `src/graph/workflow.py:388` `_load_failed_sources_registry()`
  - `src/graph/workflow.py:486` `_has_unindexed_document_files()`
  - `src/graph/workflow.py:500` `_load_document_files()`
- 검색 품질
  - `src/graph/workflow.py:1948` `_expand_query_terms()`
  - `src/graph/workflow.py:2153` `_retrieve_results()`
  - `src/graph/workflow.py:2323` `_rerank_results()`
- 답변 품질
  - `src/graph/workflow.py:912` `_build_non_llm_answer()`
  - `src/graph/workflow.py:1171` `_build_answer_payload()`
  - `src/graph/workflow.py:1244` `_estimate_slot_fill_rate()`
- 저장소/임베딩
  - `src/retrievers/vectorstore.py:67` `add_documents()`
  - `src/retrievers/vectorstore.py:282` `search_hybrid()`
  - `src/retrievers/embeddings.py:71` `_embed_with_openai()`

---

## 13. 실습 루트 (학습용)

1. `config` 파라미터 1개씩 바꿔 동작 차이를 확인

```bash
RETRIEVAL_MAX_HYBRID_CALLS=2 streamlit run app/main.py
```

2. 인덱싱 안정화 로직 검증

```bash
python3 scripts/rebuild_db.py
```

3. 평가 지표 확인

```bash
python3 scripts/eval_retrieval.py --slice first5 --label line_study --output eval/eval_results_line_study.json
```

4. 결과 JSON에서 아래 필드 비교

- `avg_response_time`
- `recall_at_k_source`
- `answer_mode_distribution`
- `avg_slot_fill_rate`

---

## 14. 한 줄 결론

이 프로젝트의 핵심은 "LLM 성능" 자체보다, **라인 단위로 설계된 운영 안전장치(증분 인덱싱/검색 예산/정규화 출력/근거 메타)**가 실제 품질과 속도를 만든다는 점이다.

---

## 15. 실행 유틸리티(`helpers.py`)까지 포함한 해설

### 15.1 `src/utils/helpers.py` 라인 해설

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/utils/helpers.py:13-18` | `remove_josa()` | 기관명 후처리("서울시는" -> "서울시")로 질의/파일명 매칭 성공률을 높임. |
| `src/utils/helpers.py:21-30` | `format_amount()` | UI/랭킹 출력에서 사람이 읽기 쉬운 단위(억/만)로 변환. |
| `src/utils/helpers.py:33-35` | `normalize_newlines()` | 파서 계층에서 줄바꿈 폭주를 공통 규칙으로 정리. |
| `src/utils/helpers.py:38-50` | `parse_amount()` | 문자열/쉼표/비정형 금액을 안전하게 정수화해 정렬/필터 연산 가능. |
| `src/utils/helpers.py:53-89` | `extract_amount_from_text()` | 원문 PDF/HWP에서 사업비를 재추출해 CSV 누락/오류를 보정. |
| `src/utils/helpers.py:58-66` | 정규식 패턴 다중 정의 | 문서마다 표기("사업비", "계약금액", "총사업비")가 달라 커버리지를 높이기 위한 다중 패턴. |
| `src/utils/helpers.py:79-88` | `억/만` 단위 파싱 | 숫자+단위 표현을 원 단위로 변환해 내부 계산 일관성 확보. |

---

## 16. 보조 모듈(필터/정규화/청킹)

### 16.1 `src/retrievers/metadata_filter.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/retrievers/metadata_filter.py:14-33` | `MetadataFilter` 생성자 | source/org/type 필터를 set으로 보관해 membership 체크 성능 향상. |
| `src/retrievers/metadata_filter.py:34-51` | `filter_results()` | 검색 결과 후처리 시 간단한 메타 필터가 필요할 때 재사용 가능하도록 분리. |
| `src/retrievers/metadata_filter.py:62-69` | `_matches_filters()` | 필터 미설정(`None`)일 때는 통과, 설정 시에만 엄격 필터링. |
| `src/retrievers/metadata_filter.py:114-188` | `AmountFilter.parse_amount_range()` | 자연어 금액 조건("5억~10억", "10억 이상")을 파싱해 구조화 필터로 변환. |
| `src/retrievers/metadata_filter.py:190-218` | `filter_by_amount()` | `OrgInfo.amount_numeric` 기준 필터링으로 랭킹/조건질의 계산 재사용. |

참고: 현재 핵심 워크플로우에서 직접 호출 비중은 낮지만, 금액형 질의 확장에 재사용 가능한 유틸리티다.

### 16.2 `src/parsers/text_cleaner.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/parsers/text_cleaner.py:23-41` | 클리너 옵션들 | 정규화 강도를 상황별로 조정 가능하도록 옵션화. |
| `src/parsers/text_cleaner.py:57-65` | 단계적 클린 파이프라인 | 줄바꿈/공백/특수문자 제거를 조합해 입력 품질을 안정화. |
| `src/parsers/text_cleaner.py:79` | `\n{3,} -> \n\n` | 문단 구조는 보존하면서 과도한 빈 줄만 제거. |
| `src/parsers/text_cleaner.py:90-94` | 공백/탭 정리 | OCR/복사 텍스트에서 발생하는 비정형 공백을 표준화. |
| `src/parsers/text_cleaner.py:105-109` | HTML 태그/특수문자 제거 옵션 | 파서 입력에 마크업/노이즈가 섞인 경우를 대비. |
| `src/parsers/text_cleaner.py:130-143` | `extract_sentences()` | 후속 문장 단위 처리(요약/키워드 추출)에 쓰기 쉬운 API. |
| `src/parsers/text_cleaner.py:154-161` | `extract_keywords()` | 간단한 키워드 통계를 뽑아 탐색/요약 보조에 활용 가능. |

### 16.3 `src/parsers/chunker.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/parsers/chunker.py:16-49` | `Chunk` 데이터클래스 | 텍스트+소스+기관+타입 메타를 묶어 저장소 입력 형식을 표준화. |
| `src/parsers/chunker.py:55-73` | `MarkdownChunker` 파라미터 | 섹션 기반/길이 기반 청킹을 전환 가능하게 설계. |
| `src/parsers/chunker.py:93-97` | 분기(`chunk_by_section`) | 구조화 문서에는 섹션 분할, 비구조 문서에는 길이 분할이 유리. |
| `src/parsers/chunker.py:116-134` | 섹션 청킹 | Markdown 헤더 구조를 유지해 검색 시 의미 단위 보존. |
| `src/parsers/chunker.py:157-178` | 크기 청킹 + overlap | 긴 문서 분할 시 문장 경계와 문맥 연속성을 동시에 고려. |
| `src/parsers/chunker.py:182-244` | CSV/문서 전용 청킹 메서드 | 소스 타입별 기본 메타를 자동 주입해 호출자 코드 단순화. |

---

## 17. 평가 모듈(실험/검증 필수)

### 17.1 `src/evaluation/metrics.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/evaluation/metrics.py:16-20` | source 정규화 | 파일명 공백/케이스 차이로 인한 오판을 줄이기 위함. |
| `src/evaluation/metrics.py:31-32` | 포함관계 매칭 허용 | 데이터셋 source 명칭이 축약/변형된 경우를 흡수. |
| `src/evaluation/metrics.py:35-46` | 페이지 ±1 허용 | 파서 오프셋/1-based/0-based 차이의 경미한 오차를 허용. |
| `src/evaluation/metrics.py:129-145` | `calculate_recall_at_k()` | 검색 상위 K 내 정답 포함 여부를 이진 지표로 산출. |
| `src/evaluation/metrics.py:157-168` | `calculate_mrr()` | 정답이 앞순위에 올수록 높은 점수를 주는 순위 품질 지표. |

### 17.2 `src/evaluation/llm_judge.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/evaluation/llm_judge.py:18-65` | Judge system prompt | Correctness/Coverage/Faithfulness/Context relevance 4축을 고정 스키마로 평가. |
| `src/evaluation/llm_judge.py:81-117` | `_parse_judge_response()` | 코드블록/키명 변형 대응으로 JSON 파싱 안정성 강화. |
| `src/evaluation/llm_judge.py:160-170` | GPT-5/비GPT-5 파라미터 분기 | 모델별 토큰 파라미터 차이를 안전하게 처리. |
| `src/evaluation/llm_judge.py:175-178` | context 6000자 컷 | 너무 긴 컨텍스트로 인한 judge 불안정/비용 증가를 억제. |
| `src/evaluation/llm_judge.py:192-218` | 재시도 2회 | 파싱 실패/일시적 API 에러 시 평가 파이프라인 중단 방지. |

### 17.3 트레이싱 유틸

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `src/evaluation/langsmith_tracer.py:20-36` | LangSmith env 주입 | 런타임 체인 자동 추적을 환경변수 방식으로 표준화. |
| `src/evaluation/langfuse_tracer.py:27-33` | 미설치 시 경고만 출력 | optional 의존성으로 유지해 기본 실행을 막지 않음. |
| `src/evaluation/langfuse_tracer.py:78-102` | retrieval 메트릭 기록 | trace 단위로 검색 품질 요약을 남겨 실험 비교 가능. |

---

## 18. 스크립트 계층(구동/운영 자동화)

### 18.1 `scripts/build_unified_corpus.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `scripts/build_unified_corpus.py:17-22` | CLI 인자 | 입력/출력/덮어쓰기/샘플링을 옵션화해 대규모 전처리 제어. |
| `scripts/build_unified_corpus.py:24-25` | `UnifiedCorpusPreprocessor` 호출 | 전처리 핵심 로직을 모듈에 두고 스크립트는 진입점 역할만 담당. |

### 18.2 `scripts/preprocess_hwp_pdf.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `scripts/preprocess_hwp_pdf.py:18-21` | HWP/HWPX 수집 | 확장자 기반 사전 스캔으로 변환 대상 확정. |
| `scripts/preprocess_hwp_pdf.py:60` | `convert_to_pdf()` 호출 | HWP 품질보정 로직을 재사용해 일관된 PDF 산출. |
| `scripts/preprocess_hwp_pdf.py:76-90` | 페이지/표/텍스트 길이 통계 | 변환 품질을 정량적으로 확인하기 위한 최소 지표. |
| `scripts/preprocess_hwp_pdf.py:95-101` | 매니페스트 저장 | 성공/실패 이력을 다음 실험에서 재활용 가능. |

### 18.3 `scripts/build_eval_report.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `scripts/build_eval_report.py:20` | `HTML_TEMPLATE` 상수화 | 리포트 스타일/구조를 코드에서 일관되게 재생성 가능. |
| `scripts/build_eval_report.py:527-528` | 결과 카드 반복 생성 | 문항별 상세 평가를 카드 구조로 시각화. |
| `scripts/build_eval_report.py:540-559` | 템플릿 포맷팅 주입 | 계산 지표를 HTML에 매핑해 정적 리포트로 출력. |
| `scripts/build_eval_report.py:564-597` | CLI 엔트리 | JSON -> HTML 리포트를 독립 실행 가능하게 제공. |

### 18.4 `scripts/rebuild_db.py`

| 줄 | 코드/값 | 이유 |
|---|---|---|
| `scripts/rebuild_db.py:23-24` | 기본 DB/데이터 경로 계산 | 운영 코드와 동일 경로 사용으로 경로 불일치 리스크 제거. |
| `scripts/rebuild_db.py:33-40` | 삭제 확인 | DB 삭제는 파괴적 작업이므로 명시적 사용자 확인 필요. |
| `scripts/rebuild_db.py:43-44` | 챗봇 초기화로 재구축 | 실제 런타임 로직을 그대로 재사용해 정합성 보장. |

---

## 19. 설치/환경 파일까지 포함한 구동 필수 해설

### 19.1 `requirements.txt`

| 줄 | 패키지 | 구동상 이유 |
|---|---|---|
| `requirements.txt:4-6` | `langchain`, `langchain-openai`, `langsmith` | LLM 호출 체인 + 트레이싱. |
| `requirements.txt:9` | `openai` | GPT/임베딩 API 필수. |
| `requirements.txt:12` | `chromadb` | 벡터 저장소 백엔드. |
| `requirements.txt:15-17` | `pdfplumber`, `reportlab`, `olefile` | PDF 추출 + HWP fallback 렌더/파싱 지원. |
| `requirements.txt:20` | `python-dotenv` | `.env` 로드로 설정 일원화. |
| `requirements.txt:23` | `streamlit` | 웹 앱 실행 엔트리. |
| `requirements.txt:26` | `sentence-transformers` | OpenAI 없는 환경의 임베딩 fallback. |
| `requirements.txt:29` | `pandas` | 데이터 처리/실험 보조. |

### 19.2 `.env.example`

| 줄 | 변수 | 이유 |
|---|---|---|
| `.env.example:4` | `OPENAI_API_KEY` | LLM/임베딩 활성화 핵심 키. |
| `.env.example:5-7` | 모델 변수 3종 | 임베딩/기본/추론 모델을 독립 조정 가능. |
| `.env.example:13-15` | LangSmith 설정 | 실행 트레이싱/실험 추적. |
| `.env.example:20-22` | Langfuse 설정 | 대체 모니터링 도구 옵션. |
| `.env.example:35-43` | 검색 튜닝 변수 | 속도/정확도/비용을 환경변수로 제어. |

---

## 20. 프로젝트 구동에 필요한 전체 흐름(End-to-End)

1. 설치

```bash
pip install -r requirements.txt
```

2. 환경 변수 설정

```bash
cp .env.example .env
# OPENAI_API_KEY, 필요시 LANGSMITH_* 수정
```

3. 웹 앱 실행(기본)

```bash
streamlit run app/main.py
```

4. 인덱스 재구축(데이터 갱신 시)

```bash
python3 scripts/rebuild_db.py
```

5. 통합 전처리(선행 검증/품질 확인)

```bash
python3 scripts/build_unified_corpus.py --input-dir data/files --output-dir data/processed
python3 scripts/preprocess_hwp_pdf.py --input-dir data/files --output-dir data/preprocessed_pdf
```

6. 평가/리포트

```bash
python3 scripts/eval_retrieval.py --slice all --output eval/eval_results.json
python3 scripts/build_eval_report.py --input eval/eval_results.json --output eval/eval_report.html
```

---

## 21. 최종 체크: "구동 필수" 파일 커버리지

- 앱 엔트리: `app/main.py`
- 핵심 런타임: `src/graph/workflow.py`, `src/graph/nodes.py`, `src/graph/state.py`
- 설정/헬퍼: `src/utils/config.py`, `src/utils/helpers.py`
- 검색/임베딩: `src/retrievers/vectorstore.py`, `src/retrievers/embeddings.py`
- 문서 파서: `src/parsers/csv_loader.py`, `src/parsers/pdf_loader.py`, `src/parsers/hwp_loader.py`, `src/parsers/preprocessor.py`
- 보조 모듈: `src/parsers/chunker.py`, `src/parsers/text_cleaner.py`, `src/retrievers/metadata_filter.py`
- 평가 모듈: `src/evaluation/metrics.py`, `src/evaluation/llm_judge.py`, `src/evaluation/langsmith_tracer.py`, `src/evaluation/langfuse_tracer.py`
- 운영 스크립트: `scripts/rebuild_db.py`, `scripts/build_unified_corpus.py`, `scripts/preprocess_hwp_pdf.py`, `scripts/eval_retrieval.py`, `scripts/build_eval_report.py`
- 환경/의존성: `.env.example`, `requirements.txt`

이 문서는 위 파일들을 기준으로 "왜 존재하는지"와 "왜 그 값인지"까지 포함해 학습 가능한 수준으로 확장 완료.
