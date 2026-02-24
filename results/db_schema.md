# DB 스키마 문서 (`DB/document.db`)

**파이프라인 버전**: v2.1.3
**DB 엔진**: SQLite + sqlite-vec 0.1.6 (벡터 검색) + FTS5 (전문 검색)
**총 행 수**: 8,185

---

## 테이블 구조 요약

| 테이블 | 유형 | 역할 | 행 수 |
|--------|------|------|-------|
| `chunks` | 일반 테이블 | Dense 벡터 + 텍스트 + 메타데이터 | 8,185 |
| `chunks_vec` | 가상 테이블 (vec0) | 벡터 유사도 검색 인덱스 | 8,185 |
| `sparse` | 가상 테이블 (FTS5) | 키워드 검색 (명사 기반) | 8,185 |
| `hierarchy` | — | **미생성** (현재 DB에 없음) | — |

---

## 1. `chunks` 테이블 (Dense Index)

### DDL

```sql
CREATE TABLE chunks (
    rowid          INTEGER PRIMARY KEY AUTOINCREMENT,
    text           TEXT,
    metadata       BLOB,       -- JSON 문자열
    text_embedding BLOB        -- float32 × 768 = 3,072 bytes
);
```

### 컬럼 설명

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `rowid` | INTEGER | 자동 증가 PK |
| `text` | TEXT | chunk 원문 텍스트 |
| `metadata` | BLOB | JSON 문자열로 저장된 메타데이터 (아래 참조) |
| `text_embedding` | BLOB | ko-sroberta-multitask 768차원 벡터 (float32, 3,072 bytes) |

### `metadata` JSON 구조

```json
{
  "document_title": "제안요청서",
  "source_file": "sample1.pdf",
  "section_level1": "N/A",
  "section_level2": "N/A",
  "page_start": 1,
  "page_end": 3,
  "chunk_size": 1423,
  "created_at": "2026-02-13T01:09:08.595978",
  "uid": "eb69a3dfeb69208c_0",
  "doc_id": "eb69a3dfeb69208c"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `document_title` | string | 표지에서 추출한 문서 제목 |
| `source_file` | string | 원본 PDF 파일명 |
| `section_level1` | string | H1 섹션명 (`"N/A"` = 해당 없음) |
| `section_level2` | string | H2 섹션명 (`"N/A"` = 해당 없음) |
| `page_start` | int | chunk가 시작되는 페이지 번호 |
| `page_end` | int | chunk가 끝나는 페이지 번호 |
| `chunk_size` | int | chunk 텍스트 길이 (문자 수) |
| `created_at` | string | chunk 생성 시각 (ISO 8601) |
| `uid` | string | 고유 식별자 (`{doc_id}_{chunk_index}`) |
| `doc_id` | string | 문서 식별자 (parser 출력의 SHA-256 앞 16자리) |

### metadata 접근 예시

```sql
-- doc_id로 특정 문서의 chunk 조회
SELECT rowid, text, json_extract(metadata, '$.doc_id') AS doc_id
FROM chunks
WHERE json_extract(metadata, '$.source_file') = 'sample1.pdf';

-- 특정 섹션의 chunk 조회
SELECT text FROM chunks
WHERE json_extract(metadata, '$.section_level1') = '사업 개요';
```

---

## 2. `chunks_vec` 가상 테이블 (벡터 검색 인덱스)

### DDL

```sql
CREATE VIRTUAL TABLE chunks_vec USING vec0(
    rowid          INTEGER PRIMARY KEY,
    text_embedding float[768]
);
```

SQLiteVec가 `chunks` 테이블과 연동하여 자동 관리하는 인덱스. 직접 INSERT/DELETE하지 않음.

### 내부 보조 테이블

| 테이블 | 역할 |
|--------|------|
| `chunks_vec_chunks` | 벡터 chunk 저장소 |
| `chunks_vec_info` | 인덱스 메타정보 |
| `chunks_vec_rowids` | rowid 매핑 |
| `chunks_vec_vector_chunks00` | 실제 벡터 바이너리 |

### 벡터 검색 예시

```sql
-- 쿼리 벡터와 가장 유사한 5개 chunk 조회
SELECT c.rowid, c.text, c.metadata, v.distance
FROM chunks c
JOIN chunks_vec v ON c.rowid = v.rowid
WHERE v.text_embedding MATCH ?  -- 바인딩: 768d float32 벡터
ORDER BY v.distance
LIMIT 5;
```

---

## 3. `sparse` 가상 테이블 (FTS5 키워드 검색)

### DDL

```sql
CREATE VIRTUAL TABLE sparse USING fts5(
    uid,                        -- chunk UID (검색 대상)
    doc_id    UNINDEXED,        -- 문서 ID (검색 제외, 필터용)
    nouns,                      -- kiwipiepy 명사 추출 결과 (검색 대상)
    text      UNINDEXED,        -- 원문 텍스트 (검색 제외, 반환용)
    tokenize='unicode61'
);
```

### 컬럼 설명

| 컬럼 | 인덱싱 | 설명 |
|------|--------|------|
| `uid` | O | chunk 고유 식별자 (`{doc_id}_{index}`) |
| `doc_id` | X (UNINDEXED) | 문서 식별자 (upsert DELETE 기준) |
| `nouns` | O | kiwipiepy NNG/NNP/NNB 명사 추출 결과 (공백 구분) |
| `text` | X (UNINDEXED) | chunk 원문 텍스트 (검색 결과 반환용) |

### 내부 보조 테이블

| 테이블 | 역할 |
|--------|------|
| `sparse_content` | 원본 데이터 (c0=uid, c1=doc_id, c2=nouns, c3=text) |
| `sparse_data` | 역인덱스 데이터 |
| `sparse_idx` | 세그먼트/토큰 인덱스 |
| `sparse_docsize` | 문서 길이 통계 (BM25 계산용) |
| `sparse_config` | FTS5 설정 |

### 키워드 검색 예시

```sql
-- 명사 기반 키워드 검색 (BM25 랭킹)
SELECT uid, doc_id, snippet(sparse, 2, '[', ']', '...', 20), bm25(sparse)
FROM sparse
WHERE nouns MATCH '"시스템" AND "구축"'
ORDER BY bm25(sparse)
LIMIT 10;

-- 특정 문서의 모든 chunk 조회
SELECT uid, nouns, text FROM sparse
WHERE doc_id = 'eb69a3dfeb69208c';
```

---

## 4. `hierarchy` 테이블

현재 DB에 **미생성** 상태.

`run_full_pipeline.py`에서 hierarchy 인덱싱을 호출하지 않았기 때문.
`storage_step5.py`의 `main()` 함수에는 hierarchy 생성 로직이 존재하나,
`preprocessor.py`의 `process_single_pdf()`에서는 호출하지 않음.

생성 시 예상 스키마:

```sql
CREATE TABLE hierarchy (
    rowid          INTEGER PRIMARY KEY AUTOINCREMENT,
    text           TEXT,           -- 섹션 경로 (예: "사업 개요 > 추진 배경")
    metadata       BLOB,           -- JSON: {"document_name": "...", "page_start": N, "page_end": M}
    text_embedding BLOB            -- 768d 벡터
);
```

---

## 5. 임베딩 모델 정보

| 항목 | 값 |
|------|-----|
| 모델 | `jhgan/ko-sroberta-multitask` |
| 차원 | 768 |
| 바이너리 크기 | 3,072 bytes/vector (float32) |
| 언어 | 한국어 최적화 |

---

## 6. 데이터 무결성 계약

| 계약 | 보장 주체 | 검증 방법 |
|------|----------|----------|
| 모든 chunk에 `doc_id` 존재 | `assign_uids()` (Fail-Fast) | `json_extract(metadata, '$.doc_id') IS NOT NULL` |
| `doc_id != 'unknown'` | `assign_uids()` (Fail-Fast) | `SELECT COUNT(*) FROM sparse WHERE doc_id = 'unknown'` → 0 |
| `metadata.doc_id == chunk.doc_id` | `assign_uids()` | — |
| Dense 행 수 == Sparse 행 수 | `preprocessor.py` 검증 | `SELECT COUNT(*) FROM chunks` == `SELECT COUNT(*) FROM sparse` |
| UID 형식 = `{doc_id}_{index}` | `assign_uids()` | — |
| 동일 doc_id 재처리 시 중복 없음 | `upsert_dense_vectors()` + `initialize_sparse_db()` | DELETE→INSERT |
