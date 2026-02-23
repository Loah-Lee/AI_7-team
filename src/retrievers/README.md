# src/retrievers — 벡터 검색 + 메타데이터 필터링

## 파일 구성

| 파일 | 역할 | 핵심 함수/클래스 |
|------|------|-----------------|
| `embeddings.py` | 임베딩 모델 팩토리 | `get_embeddings()` — OpenAI text-embedding-3-small |
| `vectorstore.py` | Chroma 벡터스토어 관리 | `get_vectorstore()`, `build_vectorstore()`, `get_unique_institutions()` |
| `metadata_filter.py` | MMR 검색 + 메타데이터 필터 | `search_with_metadata()` (메인 검색 진입점) |
| `hybrid.py` | BM25 + Dense 하이브리드 | `HybridRetriever` |

## 검색 흐름 (메인 파이프라인)

`graph/nodes.py:retrieve()` → `metadata_filter.py:search_with_metadata()` 호출.

```
1. search_with_metadata(query, metadata_filter, top_k, search_type)
2. _enrich_query(): institution/project_name/keywords를 query에 추가
3. _build_where_filter(): institution/year → Chroma $eq 필터
4. 검색 수행 (search_type에 따라):
   ├─ "mmr" → _mmr_search()
   └─ 기타  → _similarity_search()
5. 단계적 폴백: where 필터 결과 없으면 → 필터 없이 재검색
```

## 검색 전략 상세

### MMR 검색 (`_mmr_search`)
1. `vectorstore._embedding_function.embed_query()` — 쿼리 임베딩 생성
2. `vectorstore._collection.query()` — fetch_k(50)개 후보 조회 (거리 + 임베딩 포함)
3. **TOC/표지/서식 필터링** — MMR 전에 노이즈 청크 제거
   - `is_toc` 메타데이터 태그 또는 런타임 탐지 (`_is_toc_text`)
   - `is_form` 메타데이터 태그
4. `maximal_marginal_relevance()` — 유효 후보에서 top_k개 re-ranking
5. L2 거리 → 유사도 변환: `score = 1 / (1 + distance)` (0~1 범위)

### 유사도 검색 (`_similarity_search`)
- 폴백용 기본 검색
- `similarity_search_with_relevance_scores()` + TOC/서식 필터링
- top_k + 10개를 가져와서 필터링 후 top_k개 반환

### 쿼리 보강 (`_enrich_query`)
- institution → 쿼리에 추가 (임베딩 유사도에 기관명 반영)
- project_name → 쿼리에 추가 (Chroma `$contains` 미지원이므로)
- keywords → 중복 제거 후 최대 3개만 추가 (쿼리 희석 방지)

### 하이브리드 검색 (`hybrid.py`)
- BM25 + Dense 벡터 결합 (가중치: BM25 30%, Dense 70%)
- `kiwipiepy` 형태소 분석 기반 토큰화 (NNG, NNP, VV 등 내용어만)
- 점수 정규화 후 합산 → 상위 top_k개 반환
- **현재 메인 파이프라인에서 미사용** (metadata_filter.py의 MMR이 기본)

## Chroma DB 스키마

```yaml
collection: rfp_docs
persist_directory: ./chroma_db_eval_yc
embedding: text-embedding-3-small (1536 dim)

document metadata:
  source: str        # 파일명 (NFC 정규화)
  file_type: str     # "pdf" | "hwp"
  page: int          # 페이지 번호 (1-indexed)
  institution: str   # 발주 기관명
  project_name: str  # 사업명
  section: str       # 섹션 제목 (있으면)
  is_toc: bool       # 목차/표지 여부
  is_form: bool      # 서식/양식 여부
```

## 설정값 (configs/default.yaml)

```yaml
retriever:
  search_type: "mmr"
  top_k: 8
  fetch_k: 50
  lambda_mult: 0.7
  score_threshold: 0.3
```

## dev-yc 브랜치와의 차이

| 항목 | integration-eval-yc | dev-yc |
|------|---------------------|--------|
| 벡터스토어 래퍼 | `langchain_chroma.Chroma` | `chromadb.PersistentClient` 직접 |
| 메인 검색 | `search_with_metadata()` (MMR) | `balanced_search()` (MMR + 데이터타입 밸런싱) |
| TOC 필터링 | MMR 전 사전 제거 + is_toc 태그 | 런타임 탐지 |
| 쿼리 보강 | institution/project_name/keywords → 쿼리 추가 | 없음 (where 필터만) |
| 폴백 전략 | where 필터 → 필터 없음 (2단계) | 기관+유형 → 기관만 → 전체 (3단계) |
| collection | `rfp_docs` (config 기반) | `rfp_docs_v17` (하드코딩 → config 이관) |
