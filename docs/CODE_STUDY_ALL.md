# 입찰메이트 전체 코드 스터디 (프로젝트 전체 인덱스)

## 문서 목적
- 이 문서는 프로젝트에서 사용한 코드 파일을 **전체 범위**로 빠르게 파악하기 위한 인덱스입니다.
- "이 파일이 왜 필요한지"를 한 줄로 정리하고, 핵심 파일은 **주석처럼 읽는 설명**을 붙였습니다.

## 1) 실행 코드 전체 맵

| 경로 | 역할 | 핵심 진입점 |
|---|---|---|
| `app/main.py` | Streamlit UI/입출력 | `main()`(`app/main.py:300`) |
| `src/graph/workflow.py` | 전체 오케스트레이션 핵심 | `RAGChatbotV17.answer()`(`src/graph/workflow.py:900`) |
| `src/graph/nodes.py` | 의도 파싱/질문 계획/생성기 | `QueryIntentParser.parse()`(`src/graph/nodes.py:35`) |
| `src/graph/state.py` | 데이터 계약(dataclass)/대화 상태 | `ConversationContext`(`src/graph/state.py:89`) |
| `src/retrievers/vectorstore.py` | Chroma 저장/검색/하이브리드 재정렬 | `search_hybrid()`(`src/retrievers/vectorstore.py:348`) |
| `src/retrievers/embeddings.py` | 임베딩 생성(OpenAI/로컬) | `embed_texts()`(`src/retrievers/embeddings.py:43`) |
| `src/retrievers/metadata_filter.py` | 메타/금액 필터 보조 유틸 | `MetadataFilter.filter_results()`(`src/retrievers/metadata_filter.py:34`) |
| `src/parsers/csv_loader.py` | CSV -> MarkdownData 변환 | `convert_file()`(`src/parsers/csv_loader.py:99`) |
| `src/parsers/pdf_loader.py` | PDF 페이지/표 추출 -> 마크다운 | `extract_pages()`(`src/parsers/pdf_loader.py:74`) |
| `src/parsers/hwp_loader.py` | HWP/HWPX 변환/추출/fallback | `convert_to_pdf()`(`src/parsers/hwp_loader.py:308`) |
| `src/parsers/preprocessor.py` | 통합 코퍼스 생성 배치 | `UnifiedCorpusPreprocessor.build()`(`src/parsers/preprocessor.py:30`) |
| `src/parsers/chunker.py` | 청크 생성 규칙(섹션/길이) | `MarkdownChunker.chunk_markdown()`(`src/parsers/chunker.py:75`) |
| `src/parsers/text_cleaner.py` | 텍스트 정리/키워드 보조 | `TextCleaner.clean()`(`src/parsers/text_cleaner.py:43`) |
| `src/prompts/templates.py` | 시스템/의도/응답 프롬프트 | `RFP_SYSTEM_PROMPT`(`src/prompts/templates.py:37`) |
| `src/utils/config.py` | 환경변수/튜닝 파라미터 | `get_default_db_path()`(`src/utils/config.py:131`) |
| `src/utils/helpers.py` | 공통 유틸(금액/텍스트 정규화) | `parse_amount()`(`src/utils/helpers.py:38`) |
| `src/evaluation/metrics.py` | retrieval 지표 계산 | `calculate_recall_at_k()`(`src/evaluation/metrics.py:129`) |
| `src/evaluation/llm_judge.py` | LLM Judge 채점 | `judge_rag_response()`(`src/evaluation/llm_judge.py:120`) |
| `src/evaluation/langsmith_tracer.py` | LangSmith 트레이싱 설정 | `setup_langsmith_tracing()`(`src/evaluation/langsmith_tracer.py:10`) |
| `src/evaluation/langfuse_tracer.py` | Langfuse 로깅 보조 | `log_score()`(`src/evaluation/langfuse_tracer.py:52`) |

## 2) 운영/배치 스크립트 전체 맵

| 경로 | 역할 | 핵심 진입점 |
|---|---|---|
| `scripts/rebuild_db.py` | DB 재구축 | `main()`(`scripts/rebuild_db.py:21`) |
| `scripts/eval_retrieval.py` | 평가 실행(JSON 생성) | `run_evaluation()`(`scripts/eval_retrieval.py:236`) |
| `scripts/build_eval_report.py` | 평가 HTML 보고서 생성 | `build_html_report()`(`scripts/build_eval_report.py:625`) |
| `scripts/preprocess_hwp_pdf.py` | HWP 전처리/변환 유틸 | `main()`(`scripts/preprocess_hwp_pdf.py:24`) |
| `scripts/build_unified_corpus.py` | 통합 코퍼스 생성 실행기 | `main()`(`scripts/build_unified_corpus.py:16`) |

## 3) 테스트 코드 전체 맵

| 경로 | 검증 대상 | 핵심 테스트 |
|---|---|---|
| `tests/test_conversation.py` | 대화/의도 기본동작 | `test_conversation_context()`(`tests/test_conversation.py:38`) |
| `tests/test_vectorstore_hybrid_pipeline.py` | 하이브리드 검색 파이프라인 | `test_hybrid_lexical_prefilter_then_vector_rerank_order()`(`tests/test_vectorstore_hybrid_pipeline.py:21`) |
| `tests/test_workflow_csv_shortcircuit.py` | CSV 즉답 경로 | `test_answer_amount_shortcircuits_to_csv_without_db_retrieval()`(`tests/test_workflow_csv_shortcircuit.py:117`) |
| `tests/test_workflow_fact_and_org.py` | 사실형 추출/기관 복원 | `test_extract_fact_charset_utf8()`(`tests/test_workflow_fact_and_org.py:61`) |

## 4) 핵심 코드 "주석처럼" 읽기

### 4.1 `csv_loader.py` 핵심 흐름
```python
def convert_row(self, row, row_num=0):
    # 1) CSV 컬럼을 꺼내서 의미 있는 필드로 매핑
    project_name = row.get('사업명', '')
    amount = row.get('사업 금액', '')
    org_name = remove_josa(row.get('발주 기관', ''))

    # 2) 화면/검색 친화적으로 포맷 정리
    amount_str = self._format_amount_value(amount)
    original_text = self._truncate_text(row.get('텍스트', ''))

    # 3) 템플릿으로 일관된 문서 형태 생성
    markdown = MARKDOWN_TEMPLATE.format(...)

    # 4) workflow/vectorstore가 바로 쓰는 표준 구조로 반환
    return MarkdownData(markdown=markdown, metadata={...})
```
- 왜 중요함: CSV 한 줄이 검색 가능한 "문서 단위"로 변환되는 시작점입니다.

### 4.2 `pdf_loader.py` 핵심 흐름
```python
def extract_pages(self, pdf_path, max_pages=None, include_tables=True):
    # 1) pdfplumber로 페이지 순회
    for page_num, page in enumerate(source_pages, 1):
        page_text = normalize_newlines(page.extract_text() or "").strip()

        # 2) 표를 markdown 테이블로 변환해 텍스트와 합침
        if include_tables:
            raw_tables = page.extract_tables() or []
            md_table = self._table_to_markdown(table)

        # 3) page 번호/표 개수까지 메타 포함
        pages.append({"page": page_num, "content": content, "table_count": ...})
```
- 왜 중요함: 페이지 번호가 평가 지표(page hit)와 직접 연결됩니다.

### 4.3 `hwp_loader.py` 핵심 흐름
```python
def convert_to_pdf(self, hwp_path, output_dir, overwrite=False):
    # 1) LibreOffice 변환 시도
    converted = self._convert_with_libreoffice(...)

    # 2) 변환은 됐지만 품질이 낮으면 fallback으로 교체
    if not self._is_pdf_quality_acceptable(...):
        converted = self._build_pdf_from_hwp_text(...)

    # 3) 최종적으로 검색 가능한 PDF를 보장
    return converted
```
- 왜 중요함: HWP 환경 차이로 실패가 잦아서 "성공 여부"보다 "검색 품질"을 보장하도록 설계됐습니다.

### 4.4 `chunker.py` 핵심 흐름
```python
def _chunk_by_size(self, markdown, source, org, chunk_type):
    # 1) max_chunk_length 단위로 자르되
    end = start + self.max_chunk_length

    # 2) 가능하면 문장 경계에서 끊어서 문맥 손실 완화
    sentence_end = re.search(...)

    # 3) overlap으로 다음 청크에 일부 문맥 유지
    start = end - self.overlap
```
- 왜 중요함: 청킹 품질이 검색 정밀도와 응답 일관성에 큰 영향을 줍니다.

## 5) 전체 실행 흐름 (실전 관점)
1. `app/main.py`에서 질문 입력
2. `workflow.answer()`가 의도/플랜/검색/응답을 총괄
3. CSV 즉답 가능하면 바로 반환
4. 아니면 `vectorstore.search_hybrid()`로 검색
5. 근거 검증 후 extractive 우선 응답
6. 필요할 때만 `RFPAnswerGenerator` 생성 보완
7. 평가는 `scripts/eval_retrieval.py`와 `scripts/build_eval_report.py`로 수행

## 6) 처음 읽는 순서 (추천)
1. `app/main.py`
2. `src/graph/workflow.py`
3. `src/retrievers/vectorstore.py`
4. `src/parsers/csv_loader.py`, `src/parsers/pdf_loader.py`, `src/parsers/hwp_loader.py`
5. `src/prompts/templates.py`
6. `scripts/eval_retrieval.py`

## 7) 같이 보면 좋은 기존 문서
- `docs/CODE_STUDY.md`
- `docs/CODE_STUDY_DEEP.md`
- `docs/ARCHITECTURE.md`
- `docs/ARCHITECTURE_PRESENTATION.md`
