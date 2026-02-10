# BiddingMate Architecture

## 파이프라인 흐름

```
┌──────────────┐    ┌──────────┐    ┌──────────────────┐    ┌──────────┐
│ analyze_query│───→│ retrieve  │───→│ extract_evidence │───→│ generate │───→ END
└──────────────┘    └──────────┘    └──────────────────┘    └──────────┘
```

- **analyze_query**: 질의 유형 분류 (single_doc / multi_doc / comparison / out_of_scope), 메타데이터 필터 추출
- **retrieve**: Chroma 벡터스토어 검색 (MMR 기본, 3단계 fallback: filter → no-filter → empty)
- **extract_evidence**: 검색 결과에서 근거 문장 추출
- **generate**: LLM 답변 생성

## RFPState 핵심 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `query` | `str` | 사용자 원본 질의 |
| `query_type` | `str` | 질의 유형 (single_doc, multi_doc, comparison, out_of_scope) |
| `metadata_filter` | `MetadataFilter` | institution, project_name, year, keywords |
| `retrieved_docs` | `list[RetrievedDoc]` | 검색된 문서 청크 (content, source, page, score) |
| `evidence` | `str` | 추출된 근거 텍스트 |
| `answer` | `str` | 최종 생성 답변 |
| `latencies` | `dict` | 노드별 소요시간 |

정의: `src/graph/state.py` (TypedDict, total=False)

## 모듈 의존관계

```
graph/           → retrievers/, prompts/, evaluation/
  workflow.py    : StateGraph 조립 (build_graph)
  nodes.py       : 4개 노드 함수 + latency 추적
  state.py       : RFPState TypedDict

retrievers/      → embeddings, vectorstore, metadata_filter
  embeddings.py  : OpenAI text-embedding-3-small
  vectorstore.py : Chroma persistent store
  hybrid.py      : BM25 + dense 하이브리드
  metadata_filter.py : 질의→필터 변환

parsers/         → pdf_loader, hwp_loader, chunker, text_cleaner
  pdf_loader.py  : pypdf 기반 PDF 파싱
  hwp_loader.py  : pyhwpx (Windows-only)
  chunker.py     : RecursiveCharacterTextSplitter
  text_cleaner.py: 테이블 플래트닝, 폼 태깅, 중복 제거

prompts/
  templates.py   : ChatPromptTemplate 정의

evaluation/      → LLM-as-Judge + Retrieval 메트릭
  → eval/METRICS.md 참조
```

## 검색 전략

- **기본**: MMR (lambda_mult=0.7, fetch_k=50, top_k=8)
- **3단계 fallback**:
  1. 메타데이터 필터 적용 검색
  2. 필터 없이 전체 검색
  3. 빈 결과 반환 (out_of_scope 처리)
- **score_threshold**: 0.3

## 평가 체계

- **LLM-as-Judge 4지표** (0~5점): Correctness, Answer Coverage, Faithfulness, Context Relevance
- **Retrieval 보조 3지표**: Recall@K (Source/Page), MRR (Source/Page)
- 상세 정의: `eval/METRICS.md`
- 평가셋: `eval/eval_dataset.yaml` (20개 질문: single_doc 12, multi_doc 4, comparison 4)

## 설정

`configs/default.yaml` 주요 값:

| 항목 | 값 |
|------|---|
| LLM | gpt-5-mini, temp=0.0 |
| Embedding | text-embedding-3-small (1536d) |
| Vectorstore | Chroma (persistent) |
| Retriever | MMR, top_k=8, fetch_k=50 |
| Chunking | recursive, 1000/200 |

## 알려진 약점

- **multi_doc**: Answer Coverage 평균 1.25 → 다중 문서 커버리지 부족
- **comparison**: Context Relevance 평균 3.25 → 비교 대상 문서 동시 검색 어려움
