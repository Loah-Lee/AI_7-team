# ChromaDB 하이브리드 저장소 사용 가이드

**저장소**: `chroma_db/` (프로젝트 루트 기준)  
**엔진**: ChromaDB PersistentClient (로컬)  
**벡터 타입**: Dense (SRoBERTa, 768차원) + Sparse (BM25 로컬)  
**버전**: v3.1

---

## 목차

1. [개요 및 아키텍처](#1-개요-및-아키텍처)
2. [컬렉션 구조](#2-컬렉션-구조)
3. [chunks 컬렉션 (하이브리드)](#3-chunks-컬렉션-하이브리드)
4. [hierarchy 컬렉션 (Dense 전용)](#4-hierarchy-컬렉션-dense-전용)
5. [데이터 흐름](#5-데이터-흐름)
6. [Python 검색 예시](#6-python-검색-예시)
7. [메타데이터 참조](#7-메타데이터-참조)
8. [주의 사항](#8-주의-사항)

---

## 1. 개요 및 아키텍처

### 저장 구조

```
chroma_db/
├── collections/
│   ├── chunks/              # Dense 벡터 (768d) + Sparse 벡터 (JSON)
│   └── hierarchy/           # Dense 벡터 (768d) + 섹션 메타데이터
└── index/
```

### 특징

- **Cloud API 불필요**: BM25 Sparse 벡터를 로컬에서 생성 (ChromaBm25EmbeddingFunction)
- **Hybrid 검색**: Dense 유사도 검색 + Sparse 키워드 검색 동시 지원
- **Hierarchical Navigation**: 섹션 범위 정보로 scope 기반 검색 가능
- **멱등성**: SHA-256 기반 `doc_id` + upsert로 재실행 안전

### 초기화 코드

```python
import chromadb
from src.retrievers.build_db import client
from src.utils.config import CHROMA_PATH

# 또는 새로 초기화:
client = chromadb.PersistentClient(path=CHROMA_PATH)

chunks_coll = client.get_collection("chunks")
hierarchy_coll = client.get_collection("hierarchy")
```

---

## 2. 컬렉션 구조

| 컬렉션 | 용도 | ID 키 | 벡터 타입 | 행 수 |
|--------|------|-------|----------|-------|
| `chunks` | 청크 원문 + 메타 | `uid` (e.g., `abc123_0`) | Dense + Sparse | ~500~1000 (문서당) |
| `hierarchy` | 섹션 요약 + 범위 | `uid` (e.g., `abc123_h_1`) | Dense only | ~10~50 (문서당) |

---

## 3. chunks 컬렉션 (하이브리드)

### 저장 데이터 구조

```python
{
    "id": "abc123_0",  # uid from chunk metadata
    "document": "사업 개요\n본 사업은...",  # page_content
    "metadata": {
        # === Chunk 정보 ===
        "type": "chunk",
        "uid": "abc123_0",
        "doc_id": "abc123...",  # SHA-256 첫 16자
        "document_title": "고려대학교 제안요청서",
        "chunk_order": 0,       # doc 내 순차 번호 (0-based)
        
        # === 계층 정보 ===
        "section_level1": "I. 사업 개요",
        "section_level2": "1.1 사업 배경",
        "section_uid": "abc123_h_1",  # 소속 hierarchy UID
        
        # === 원본 위치 ===
        "source_file": "고려대학교_...pdf",
        "page_start": 1,
        "page_end": 3,
        "chunk_size": 1423,  # 문자 수
        
        # === 타임스탬프 ===
        "created_at": "2026-02-24T12:34:56.789012",
        
        # === Sparse 벡터 (JSON 문자열) ===
        "sparse_embedding": "{\"0\": 0.45, \"234\": 0.67, ...}"
    },
    "embedding": [0.123, -0.456, ..., 0.789]  # Dense 벡터 (768차원)
}
```

### 메타데이터 필드 설명

| 필드 | 타입 | 설명 | 예시 |
|------|------|------|------|
| `type` | string | 항상 `"chunk"` | `"chunk"` |
| `uid` | string | 청크 고유 ID (`{doc_id}_{chunk_order}`) | `"abc123_5"` |
| `doc_id` | string | 문서 식별자 (SHA-256 앞 16자) | `"abc123def456789"` |
| `document_title` | string | 문서 제목 | `"고려대학교 제안요청서"` |
| `chunk_order` | int | 문서 내 청크 순서 (0-based) | `0`, `1`, ... |
| `section_uid` | string | 소속 섹션 UID (hierarchy FK) | `"abc123_h_1"` |
| `section_level1` | string | L1 섹션명 또는 "N/A" | `"I. 사업 개요"` |
| `section_level2` | string | L2 섹션명 또는 "N/A" | `"1. 사업 배경"` |
| `source_file` | string | 원본 PDF 파일명 | `"고려대학교_차세대...pdf"` |
| `page_start` | int | 시작 페이지 | `1` |
| `page_end` | int | 종료 페이지 | `3` |
| `chunk_size` | int | 문자 수 | `1423` |
| `created_at` | string | ISO 8601 타임스탐프 | `"2026-02-24T12:34:56.789012"` |
| `sparse_embedding` | string (JSON) | BM25 벡터 (키워드 인덱스) | `"{\"0\": 0.45, ...}"` |

### Dense 벡터 정보

- **모델**: `jhgan/ko-sroberta-multitask`
- **차원**: 768
- **크기**: 768 float32 = 3,072 bytes
- **거리 메트릭**: Cosine 유사도 (hnsw:space = "cosine")

### Sparse 벡터 정보

- **생성 방식**: ChromaBm25EmbeddingFunction (로컬 계산)
- **토큰화**: kiwipiepy 명사 추출
- **저장**: JSON 문자열 (메타데이터의 `sparse_embedding` 필드)
- **형식**: `{token_index: score, ...}`

---

## 4. hierarchy 컬렉션 (Dense 전용)

### 저장 데이터 구조

```python
{
    "id": "abc123_h_1",  # uid from hierarchy metadata
    "document": "[Level 1] I. 사업 개요\n본 사업은 고려대학교의...",  # text_with_summary
    "metadata": {
        # === Hierarchy 정보 ===
        "type": "hierarchy",
        "uid": "abc123_h_1",      # hierarchy 고유 ID
        "level": 1,               # 1 (L1) 또는 2 (L2)
        "title": "I. 사업 개요",   # 섹션명
        
        # === 상위 섹션 (L2만) ===
        "parent_uid": "abc123_h_1",  # L1 부모 UID (L2인 경우에만)
        
        # === 문서 정보 ===
        "doc_id": "abc123...",
        "document_title": "고려대학교 제안요청서",
        
        # === 범위 정보 ===
        "start_order": 0,         # 첫 청크 order
        "end_order": 5,           # 마지막 청크 order
    },
    "embedding": [0.123, -0.456, ..., 0.789]  # Dense 벡터 (768차원)
}
```

### 메타데이터 필드 설명

| 필드 | 타입 | 설명 | 예시 |
|------|------|------|------|
| `type` | string | 항상 `"hierarchy"` | `"hierarchy"` |
| `uid` | string | 섹션 고유 ID (`{doc_id}_h_{counter}`) | `"abc123_h_1"` |
| `level` | int | 계층 레벨 (1 또는 2) | `1`, `2` |
| `title` | string | 섹션명 | `"I. 사업 개요"` |
| `parent_uid` | string | 부모 섹션 UID (L2만) | `"abc123_h_1"` |
| `doc_id` | string | 문서 ID (chunks와 동일) | `"abc123..."` |
| `document_title` | string | 문서 제목 | `"고려대학교 제안요청서"` |
| `start_order` | int | 첫 청크의 `chunk_order` | `0` |
| `end_order` | int | 마지막 청크의 `chunk_order` | `5` |

### Document 필드

```
[Level 1] I. 사업 개요
본 사업은 고려대학교의 차세대 포털 시스템 구축 사업이다. 
사업 예산은 11,270,000,000원(VAT 포함)이며, ...
```

**형식**: `_generate_section_summary()` 함수로 생성  
**내용**: `[Level N] {title}\n{snippet1} {snippet2} ...`  
**목적**: 섹션 요약 벡터 검색

---

## 5. 데이터 흐름

```
청크 JSON (output/chunks/)
         |
         v
[preprocessor.py]
  compute_doc_id() → SHA-256
  assign_uids()   → uid = "{doc_id}_{chunk_order}"
  build_hierarchy() → L1/L2 섹션 생성 + section_uid 매핑
  apply_section_uids() → chunks에 section_uid 주입
         |
         v
[build_db.py - upsert_hybrid_chunks]
  extract_nouns() → kiwipiepy 명사 추출
  bm25_ef() → Sparse 벡터 생성
  dense_ef → SRoBERTa Dense 벡터 생성
  normalize_metadata() → JSON 정규화
  collection.upsert() → ChromaDB 저장
         |
         v
chroma_db/
  ├── chunks/    (Dense + Sparse)
  └── hierarchy/ (Dense)
```

---

## 6. Python 검색 예시

### 초기화

```python
import chromadb
from src.retrievers.build_db import client, dense_ef
from src.utils.config import CHROMA_PATH
import json

client = chromadb.PersistentClient(path=CHROMA_PATH)

chunks_coll = client.get_collection("chunks", embedding_function=dense_ef)
hierarchy_coll = client.get_collection("hierarchy", embedding_function=dense_ef)
```

### 1. Dense 유사도 검색 (의미 검색)

```python
# 쿼리 벡터 생성 (SRoBERTa)
query_text = "사업 목적과 범위"
results = chunks_coll.query(
    query_texts=[query_text],
    n_results=5,  # 상위 5개
)

# 결과 구조
# results = {
#   'ids': [['abc123_0', 'abc123_1', ...]],
#   'documents': [['사업 개요...', '사업 배경...', ...]],
#   'metadatas': [[{...}, {...}, ...]],
#   'distances': [[0.15, 0.23, ...]]  # 낮을수록 유사
# }

for i, (uid, text, meta) in enumerate(zip(
    results['ids'][0], 
    results['documents'][0], 
    results['metadatas'][0]
)):
    print(f"{i+1}. {meta['document_title']} - {meta['section_level1']}")
    print(f"   유사도: {1 - results['distances'][0][i]:.3f}")
    print(f"   {text[:100]}...\n")
```

### 2. Where 필터 (메타데이터 기반)

```python
# 특정 문서의 청크만 검색
results = chunks_coll.query(
    query_texts=["사업 예산"],
    where={"doc_id": "abc123..."},
    n_results=3
)

# 특정 섹션만 검색
results = chunks_coll.query(
    query_texts=["예산"],
    where={"section_level1": "I. 사업 개요"},
    n_results=5
)

# 특정 페이지 범위만 검색
results = chunks_coll.query(
    query_texts=["기술 요구사항"],
    where={"$and": [
        {"page_start": {"$lte": 50}},
        {"page_end": {"$gte": 30}}
    ]},
    n_results=10
)
```

### 3. Hierarchy 네비게이션

```python
# L1 섹션 조회
l1_results = hierarchy_coll.query(
    query_texts=["사업 개요"],
    where={"level": 1},
    n_results=5
)

# L2 섹션 조회 (특정 L1의 자식)
l1_uid = "abc123_h_1"
l2_results = hierarchy_coll.query(
    query_texts=["배경"],
    where={"parent_uid": l1_uid},
    n_results=10
)

# L1의 모든 청크 조회
l1_meta = l1_results['metadatas'][0][0]
start_order = l1_meta['start_order']
end_order = l1_meta['end_order']

section_chunks = chunks_coll.get(
    where={"$and": [
        {"doc_id": l1_meta['doc_id']},
        {"chunk_order": {"$gte": start_order}},
        {"chunk_order": {"$lte": end_order}}
    ]}
)
```

### 4. Sparse 벡터 활용 (고급)

```python
# sparse_embedding 메타데이터 파싱
chunk = chunks_coll.get(ids=["abc123_0"])
sparse_embedding = json.loads(chunk['metadatas'][0][0]['sparse_embedding'])
print(f"인덱싱된 명사: {sparse_embedding}")
# 출력: {"234": 0.45, "567": 0.67, ...}
```

---

## 7. 메타데이터 참조

### Where 필터 연산자

```python
# 정확한 일치
where={"doc_id": "abc123"}

# 범위 비교
where={"chunk_order": {"$gte": 0, "$lte": 10}}
where={"page_start": {"$lte": 50}}

# 논리 연산
where={"$and": [
    {"doc_id": "abc123"},
    {"section_level1": "I. 사업 개요"}
]}
where={"$or": [
    {"section_level1": "I. 사업 개요"},
    {"section_level1": "II. 현황"}
]}

# NOT 연산
where={"section_level2": {"$ne": "N/A"}}
```

### 메타데이터 타입

| 필드 | 타입 | Queryable |
|------|------|-----------|
| `type` | string | ✅ |
| `uid` | string | ✅ |
| `doc_id` | string | ✅ |
| `chunk_order` | int | ✅ |
| `page_start` | int | ✅ |
| `page_end` | int | ✅ |
| `level` | int | ✅ |
| `section_level1` | string | ✅ |
| `section_level2` | string | ✅ |
| `sparse_embedding` | string (JSON) | ⚠️ (전체 검색만 가능) |
| `created_at` | string | ✅ (문자열 비교) |

---

## 8. 주의 사항

### 재실행 안전성

- **upsert 사용**: `collection.delete(where={"doc_id": did})` → `collection.upsert()`
- **멱등성 보장**: 같은 파일을 여러 번 실행해도 결과는 동일

### 벡터 모델 호환성

- **Dense**: `jhgan/ko-sroberta-multitask` (768d)
- **Sparse**: ChromaBm25EmbeddingFunction (로컬)
- ⚠️ 모델 변경 시 기존 벡터와 호환 불가 — 재인덱싱 필요

### 메타데이터 제약

- ChromaDB 로컬 버전은 리스트/딕셔너리를 메타데이터에 직접 저장 불가
- → JSON 문자열로 직렬화 (`_normalize_metadata()` 함수)
- → 파싱 후 사용: `json.loads(meta['sparse_embedding'])`

### 성능 최적화

- **많은 문서 질의**: `where` 필터로 문서별로 사전 필터링
- **범위 검색**: `start_order`/`end_order` 활용으로 섹션 스코프 제한
- **배치 처리**: `get(ids=[...])` 또는 `where={...}` 한 번에 여러 레코드 조회

### 백업 및 유지보수

```bash
# ChromaDB 데이터 백업
cp -r chroma_db/ chroma_db.backup/
# 저장소 상태 확인
ls -lh chroma_db/
```
