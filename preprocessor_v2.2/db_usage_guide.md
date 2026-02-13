# DB 테이블별 사용 가이드 (`DB/document.db`)

**파이프라인 버전**: v2.2 (Document Anchor + Hierarchy Scope)  
**DB 엔진**: SQLite + sqlite-vec 0.1.6 + FTS5  
**임베딩 모델**: `jhgan/ko-sroberta-multitask` (768d, float32)

---

## 목차

1. [테이블 전체 구조](#1-테이블-전체-구조)
2. [chunks — Dense 벡터 검색](#2-chunks--dense-벡터-검색)
3. [chunks_vec — 벡터 유사도 인덱스](#3-chunks_vec--벡터-유사도-인덱스)
4. [sparse — FTS5 키워드 검색](#4-sparse--fts5-키워드-검색)
5. [hierarchy — 섹션 범위 메타 인덱스](#5-hierarchy--섹션-범위-메타-인덱스)
6. [테이블 간 JOIN 패턴](#6-테이블-간-join-패턴)
7. [Scope 필터링 (Document Anchor / Hierarchy Scope)](#7-scope-필터링)
8. [Python 코드 예시](#8-python-코드-예시)
9. [인덱스 목록](#9-인덱스-목록)
10. [주의 사항](#10-주의-사항)

---

## 1. 테이블 전체 구조

| 테이블 | 유형 | 역할 | 조인 키 |
|--------|------|------|---------|
| `chunks` | 일반 테이블 | Dense 벡터 + 텍스트 + 메타데이터 (Single Source of Truth) | `rowid`, `metadata.uid` |
| `chunks_vec` | vec0 가상 테이블 | 벡터 유사도 검색 | `rowid` (chunks와 동일) |
| `sparse` | FTS5 가상 테이블 | kiwipiepy 명사 기반 키워드 검색 | `uid` ↔ `chunks.metadata.uid` |
| `hierarchy` | 일반 테이블 | L1/L2 섹션 범위 정의 (검색 대상 아님, Scope 가이드) | `metadata.doc_id`, `start_order`/`end_order` |

**핵심 원칙**: 모든 Scope 필터는 `chunks.metadata` 기준으로 수행한다.

---

## 2. chunks — Dense 벡터 검색

### DDL

```sql
CREATE TABLE chunks (
    rowid          INTEGER PRIMARY KEY AUTOINCREMENT,
    text           TEXT,            -- chunk 원문 텍스트
    metadata       BLOB,            -- JSON 문자열
    text_embedding BLOB             -- float32 × 768 = 3,072 bytes
);
```

### metadata JSON 구조

```json
{
  "type": "chunk",
  "doc_id": "eb69a3dfeb69208c",
  "document_title": "제안요청서",
  "uid": "eb69a3dfeb69208c_0",
  "chunk_order": 0,
  "section_uid": "eb69a3dfeb69208c_h_1",
  "section_level1": "사업 개요",
  "section_level2": "추진 배경",
  "source_file": "sample1.pdf",
  "page_start": 1,
  "page_end": 3,
  "chunk_size": 1423,
  "created_at": "2026-02-13T01:09:08.595978"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 항상 `"chunk"` (hierarchy와 구분) |
| `doc_id` | string | 문서 식별자 (SHA-256 앞 16자리) |
| `document_title` | string | 문서 제목 (lower + trim 정규화) |
| `uid` | string | chunk 고유 ID (`{doc_id}_{index}`) |
| `chunk_order` | int | doc_id 단위 0-based 순서 번호 |
| `section_uid` | string \| null | 소속 hierarchy 엔트리 UID (L2 우선, L1 fallback) |
| `section_level1` | string | H1 섹션명 (`"N/A"` = 해당 없음) |
| `section_level2` | string | H2 섹션명 (`"N/A"` = 해당 없음) |
| `source_file` | string | 원본 PDF 파일명 |
| `page_start` | int | chunk 시작 페이지 |
| `page_end` | int | chunk 종료 페이지 |
| `chunk_size` | int | chunk 텍스트 길이 (문자 수) |
| `created_at` | string | 생성 시각 (ISO 8601) |

### 기본 조회

```sql
-- 전체 chunk 수
SELECT COUNT(*) FROM chunks;

-- 특정 문서의 모든 chunk (순서대로)
SELECT rowid, text, metadata
FROM chunks
WHERE json_extract(metadata, '$.doc_id') = 'eb69a3dfeb69208c'
ORDER BY json_extract(metadata, '$.chunk_order');

-- 특정 파일의 chunk
SELECT rowid, text
FROM chunks
WHERE json_extract(metadata, '$.source_file') = 'sample1.pdf';

-- 특정 섹션의 chunk
SELECT text
FROM chunks
WHERE json_extract(metadata, '$.section_level1') = '사업 개요';

-- 특정 페이지 범위의 chunk
SELECT text, json_extract(metadata, '$.page_start') AS p_start
FROM chunks
WHERE json_extract(metadata, '$.page_start') >= 5
  AND json_extract(metadata, '$.page_end') <= 10
  AND json_extract(metadata, '$.doc_id') = 'eb69a3dfeb69208c';
```

### 문서 단위 통계

```sql
-- 문서별 chunk 수
SELECT json_extract(metadata, '$.source_file') AS file,
       json_extract(metadata, '$.doc_id') AS doc_id,
       COUNT(*) AS chunk_count
FROM chunks
GROUP BY doc_id
ORDER BY chunk_count DESC;

-- 섹션별 chunk 분포
SELECT json_extract(metadata, '$.section_level1') AS section,
       COUNT(*) AS cnt
FROM chunks
WHERE json_extract(metadata, '$.section_level1') != 'N/A'
GROUP BY section
ORDER BY cnt DESC;

-- 전체 페이지 범위
SELECT json_extract(metadata, '$.doc_id') AS doc_id,
       json_extract(metadata, '$.source_file') AS file,
       MIN(json_extract(metadata, '$.page_start')) AS first_page,
       MAX(json_extract(metadata, '$.page_end')) AS last_page
FROM chunks
GROUP BY doc_id;
```

---

## 3. chunks_vec — 벡터 유사도 인덱스

### DDL

```sql
CREATE VIRTUAL TABLE chunks_vec USING vec0(
    rowid          INTEGER PRIMARY KEY,
    text_embedding float[768]
);
```

`chunks_vec`은 `chunks.text_embedding`의 벡터 인덱스이다. `rowid`가 `chunks.rowid`와 1:1 대응한다.

### 벡터 유사도 검색

```sql
-- 쿼리 벡터와 가장 유사한 k개 chunk 조회
-- ? 에는 768d float32 벡터 바인딩
SELECT c.rowid, c.text, c.metadata, v.distance
FROM chunks c
JOIN chunks_vec v ON c.rowid = v.rowid
WHERE v.text_embedding MATCH ?
ORDER BY v.distance
LIMIT 10;
```

> **참고**: `distance`는 L2 거리(유클리디안)이다. 값이 작을수록 유사하다.

### Document Anchor 필터 결합

```sql
-- 특정 문서 범위 내에서만 벡터 검색
SELECT c.rowid, c.text, v.distance
FROM chunks c
JOIN chunks_vec v ON c.rowid = v.rowid
WHERE v.text_embedding MATCH ?
  AND json_extract(c.metadata, '$.document_title') IN ('제안요청서')
ORDER BY v.distance
LIMIT 10;
```

### 내부 보조 테이블

| 테이블 | 역할 |
|--------|------|
| `chunks_vec_chunks` | 벡터 chunk 저장소 |
| `chunks_vec_info` | 인덱스 메타정보 |
| `chunks_vec_rowids` | rowid 매핑 |
| `chunks_vec_vector_chunks00` | 실제 벡터 바이너리 |

> 이 보조 테이블들은 sqlite-vec가 내부적으로 관리한다. **직접 조작하지 않는다.**

---

## 4. sparse — FTS5 키워드 검색

### DDL

```sql
CREATE VIRTUAL TABLE sparse USING fts5(
    uid,                        -- chunk UID (검색 가능)
    doc_id    UNINDEXED,        -- 문서 ID (검색 제외, 필터용)
    nouns,                      -- kiwipiepy 명사 추출 결과 (검색 대상)
    text      UNINDEXED,        -- 원문 텍스트 (검색 제외, 반환용)
    tokenize='unicode61'
);
```

| 컬럼 | 인덱싱 | 설명 |
|------|--------|------|
| `uid` | O | chunk 고유 ID — `chunks.metadata.uid`와 동일 |
| `doc_id` | X (UNINDEXED) | 문서 ID — DELETE 기준 |
| `nouns` | O | kiwipiepy로 추출한 명사들 (공백 구분) |
| `text` | X (UNINDEXED) | chunk 원문 — 결과 반환용 |

### 기본 키워드 검색

```sql
-- 단일 키워드 검색 (BM25 랭킹)
SELECT uid, doc_id, text, bm25(sparse) AS score
FROM sparse
WHERE nouns MATCH '시스템'
ORDER BY bm25(sparse)
LIMIT 10;
```

> **참고**: `bm25()` 값은 음수이다. 값이 작을수록(절대값이 클수록) 관련도가 높다.

### 복합 키워드 검색

```sql
-- AND 검색: 두 키워드 모두 포함
SELECT uid, text, bm25(sparse) AS score
FROM sparse
WHERE nouns MATCH '"시스템" AND "구축"'
ORDER BY bm25(sparse)
LIMIT 10;

-- OR 검색: 두 키워드 중 하나 이상 포함
SELECT uid, text, bm25(sparse) AS score
FROM sparse
WHERE nouns MATCH '"시스템" OR "구축"'
ORDER BY bm25(sparse)
LIMIT 10;

-- 구문 검색: 연속된 명사 시퀀스
SELECT uid, text, bm25(sparse) AS score
FROM sparse
WHERE nouns MATCH '"시스템 구축"'
ORDER BY bm25(sparse)
LIMIT 10;
```

### snippet (하이라이트)

```sql
-- 검색 결과에서 매칭 부분 하이라이트
SELECT uid,
       snippet(sparse, 2, '[', ']', '...', 20) AS highlighted_nouns,
       bm25(sparse) AS score
FROM sparse
WHERE nouns MATCH '시스템'
ORDER BY bm25(sparse)
LIMIT 5;
```

`snippet()` 인자: `(테이블, 컬럼인덱스, 시작태그, 종료태그, 생략부호, 최대토큰수)`
- 컬럼 인덱스: `uid=0, doc_id=1, nouns=2, text=3`

### 특정 문서 내 검색

```sql
-- doc_id로 필터링 후 키워드 검색
SELECT uid, nouns, text
FROM sparse
WHERE doc_id = 'eb69a3dfeb69208c'
  AND nouns MATCH '시스템';
```

### FTS5 내부 보조 테이블

| 테이블 | 역할 |
|--------|------|
| `sparse_content` | 원본 데이터 (c0=uid, c1=doc_id, c2=nouns, c3=text) |
| `sparse_data` | 역인덱스 데이터 |
| `sparse_idx` | 세그먼트/토큰 인덱스 |
| `sparse_docsize` | 문서 길이 통계 (BM25 계산용) |
| `sparse_config` | FTS5 설정 |

> 이 보조 테이블들은 FTS5가 내부적으로 관리한다. **직접 조작하지 않는다.**

---

## 5. hierarchy — 섹션 범위 메타 인덱스

### DDL

```sql
CREATE TABLE hierarchy (
    rowid          INTEGER PRIMARY KEY AUTOINCREMENT,
    text           TEXT,            -- 임베딩용 텍스트 (L1: "섹션명", L2: "L1 > L2")
    metadata       BLOB,            -- JSON 문자열
    text_embedding BLOB             -- float32 × 768 = 3,072 bytes
);
```

### metadata JSON 구조

```json
{
  "type": "hierarchy",
  "doc_id": "eb69a3dfeb69208c",
  "document_title": "제안요청서",
  "uid": "eb69a3dfeb69208c_h_1",
  "level": 1,
  "title": "사업 개요",
  "parent_uid": null,
  "start_order": 0,
  "end_order": 15
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 항상 `"hierarchy"` |
| `doc_id` | string | 문서 식별자 |
| `document_title` | string | 문서 제목 |
| `uid` | string | hierarchy 엔트리 UID (`{doc_id}_h_{N}`) |
| `level` | int | 1 = H1 섹션, 2 = H2 섹션 |
| `title` | string | 섹션 제목 |
| `parent_uid` | string \| null | L2의 경우 상위 L1의 uid, L1은 null |
| `start_order` | int | 해당 섹션의 첫 번째 chunk_order |
| `end_order` | int | 해당 섹션의 마지막 chunk_order |

### 섹션 목록 조회

```sql
-- 특정 문서의 전체 섹션 구조 (계층순)
SELECT json_extract(metadata, '$.level') AS level,
       json_extract(metadata, '$.title') AS title,
       json_extract(metadata, '$.uid') AS uid,
       json_extract(metadata, '$.parent_uid') AS parent_uid,
       json_extract(metadata, '$.start_order') AS start_order,
       json_extract(metadata, '$.end_order') AS end_order
FROM hierarchy
WHERE json_extract(metadata, '$.doc_id') = 'eb69a3dfeb69208c'
ORDER BY json_extract(metadata, '$.start_order');

-- L1 섹션만 조회
SELECT json_extract(metadata, '$.title') AS title,
       json_extract(metadata, '$.start_order') AS start_order,
       json_extract(metadata, '$.end_order') AS end_order
FROM hierarchy
WHERE json_extract(metadata, '$.doc_id') = 'eb69a3dfeb69208c'
  AND json_extract(metadata, '$.level') = 1;

-- L2 하위 섹션 조회 (특정 L1 아래)
SELECT json_extract(metadata, '$.title') AS title,
       json_extract(metadata, '$.start_order') AS start_order,
       json_extract(metadata, '$.end_order') AS end_order
FROM hierarchy
WHERE json_extract(metadata, '$.parent_uid') = 'eb69a3dfeb69208c_h_1';
```

### 섹션에 속한 chunk 조회 (Hierarchy Scope)

```sql
-- 특정 섹션의 chunk_order 범위로 chunk 조회
-- 예: hierarchy에서 start_order=5, end_order=15인 섹션
SELECT c.rowid, c.text,
       json_extract(c.metadata, '$.chunk_order') AS chunk_order
FROM chunks c
WHERE json_extract(c.metadata, '$.doc_id') = 'eb69a3dfeb69208c'
  AND json_extract(c.metadata, '$.chunk_order') BETWEEN 5 AND 15
ORDER BY json_extract(c.metadata, '$.chunk_order');
```

### 섹션 제목으로 벡터 검색 (hierarchy 자체 검색)

```sql
-- hierarchy 텍스트와 유사한 섹션 찾기
-- (hierarchy도 임베딩이 있으므로 벡터 검색 가능)
SELECT h.rowid, h.text, json_extract(h.metadata, '$.doc_id') AS doc_id,
       json_extract(h.metadata, '$.start_order') AS s,
       json_extract(h.metadata, '$.end_order') AS e
FROM hierarchy h
JOIN hierarchy_vec v ON h.rowid = v.rowid
WHERE v.text_embedding MATCH ?
ORDER BY v.distance
LIMIT 5;
```

---

## 6. 테이블 간 JOIN 패턴

> **⚠️ 성능 주의**: FTS5 가상 테이블(`sparse`)과 일반 테이블(`chunks`)의 단일 JOIN 쿼리는 SQLite 옵티마이저 한계로 인해 **매우 느림** (120초 이상 소요, 실용 불가). 반드시 아래의 **2단계 쿼리 패턴**을 사용해야 한다.

### 6.1 Sparse → Chunks (2단계 쿼리, 필수 패턴)

Sparse 단독으로는 metadata 필터를 걸 수 없으므로, 2단계로 처리한다.

```sql
-- Step 1: FTS5 단독 검색 (빠름, doc_id 필터 가능)
SELECT uid, bm25(sparse) AS score
FROM sparse
WHERE doc_id = 'eb69a3dfeb69208c'
  AND nouns MATCH '"시스템" AND "구축"'
ORDER BY bm25(sparse)
LIMIT 30;

-- Step 2: uid로 chunks 메타데이터 조회 (인덱스 활용, 빠름)
SELECT rowid, text, metadata
FROM chunks
WHERE json_extract(metadata, '$.uid') = ?;
-- 결과를 Python에서 추가 필터링 (Scope 등)
```

실측 성능 (99개 문서, 8,185 chunks 기준):

| 단계 | 소요 시간 |
|------|----------|
| Step 1: FTS5 (doc_id 내 30건) | ~1.5s |
| Step 2: uid별 chunks 조회 (30건) | ~0.06s |
| **합계** | **~1.6s** |

### 6.2 Dense (chunks_vec) → Chunks JOIN

Dense 검색은 rowid 기반 JOIN이므로 성능 문제 없음.

```sql
-- 벡터 검색 + 전체 메타데이터
SELECT c.rowid, c.text, c.metadata, v.distance
FROM chunks c
JOIN chunks_vec v ON c.rowid = v.rowid
WHERE v.text_embedding MATCH ?
ORDER BY v.distance
LIMIT 10;
```

### 6.3 Hybrid 검색 (Dense + Sparse 결합)

Dense와 Sparse 결과를 각각 가져온 뒤 RRF(Reciprocal Rank Fusion)로 합산한다.

```sql
-- Step 1: Dense top-k (단일 쿼리)
SELECT c.rowid, v.distance AS dense_dist
FROM chunks c
JOIN chunks_vec v ON c.rowid = v.rowid
WHERE v.text_embedding MATCH ?
ORDER BY v.distance
LIMIT 20;

-- Step 2: Sparse top-k (2단계 — FTS5 먼저, 그 다음 chunks)
--   2a: FTS5 검색
SELECT uid, bm25(sparse) AS score FROM sparse
WHERE nouns MATCH ? ORDER BY bm25(sparse) LIMIT 20;
--   2b: uid별 chunks.rowid 조회
SELECT rowid FROM chunks WHERE json_extract(metadata, '$.uid') = ?;

-- Step 3: (Python에서) RRF 합산 → 최종 top-k
```

### 6.4 Hierarchy → Chunks (섹션 범위 조회)

hierarchy에서 범위를 먼저 조회한 뒤, chunks를 범위 필터한다.

```sql
-- Step 1: hierarchy에서 범위 조회
SELECT json_extract(metadata, '$.start_order') AS s,
       json_extract(metadata, '$.end_order') AS e
FROM hierarchy
WHERE json_extract(metadata, '$.doc_id') = 'eb69a3dfeb69208c'
  AND json_extract(metadata, '$.title') = '제안요청내용';

-- Step 2: 범위로 chunks 조회 (인덱스 활용)
SELECT c.rowid, c.text,
       json_extract(c.metadata, '$.chunk_order') AS chunk_order
FROM chunks c
WHERE json_extract(c.metadata, '$.doc_id') = 'eb69a3dfeb69208c'
  AND json_extract(c.metadata, '$.chunk_order') BETWEEN 27 AND 85
ORDER BY json_extract(c.metadata, '$.chunk_order');
```

---

## 7. Scope 필터링

### 7.1 Document Anchor (문서 필터)

특정 문서(들)로 검색 범위를 제한한다.

```sql
-- Dense + Document Anchor (단일 쿼리, 성능 양호)
SELECT c.rowid, c.text, v.distance
FROM chunks c
JOIN chunks_vec v ON c.rowid = v.rowid
WHERE v.text_embedding MATCH ?
  AND json_extract(c.metadata, '$.document_title') IN ('제안요청서')
ORDER BY v.distance
LIMIT 10;
```

```sql
-- Sparse + Document Anchor (2단계)
-- Step 1: FTS5 검색
SELECT uid, bm25(sparse) AS score FROM sparse
WHERE nouns MATCH '시스템' ORDER BY bm25(sparse) LIMIT 30;

-- Step 2: Python에서 uid별 chunks 조회 후 document_title 필터
SELECT json_extract(metadata, '$.document_title'), text
FROM chunks WHERE json_extract(metadata, '$.uid') = ?;
```

### 7.2 Hierarchy Scope (섹션 범위 필터)

특정 섹션의 chunk_order 범위로 검색을 제한한다. 반드시 동일 문서 조건과 결합해야 한다.

```sql
-- Dense + Hierarchy Scope (단일 쿼리, 성능 양호)
SELECT c.rowid, c.text, v.distance
FROM chunks c
JOIN chunks_vec v ON c.rowid = v.rowid
WHERE v.text_embedding MATCH ?
  AND json_extract(c.metadata, '$.doc_id') = 'eb69a3dfeb69208c'
  AND json_extract(c.metadata, '$.chunk_order') BETWEEN 5 AND 15
ORDER BY v.distance
LIMIT 10;
```

```sql
-- Sparse + Hierarchy Scope (2단계)
-- Step 1: FTS5 (doc_id로 사전 필터)
SELECT uid, bm25(sparse) AS score FROM sparse
WHERE doc_id = 'eb69a3dfeb69208c' AND nouns MATCH '시스템'
ORDER BY bm25(sparse) LIMIT 30;

-- Step 2: uid별 chunks 조회 후 chunk_order 범위 필터 (Python)
SELECT json_extract(metadata, '$.chunk_order'), text
FROM chunks WHERE json_extract(metadata, '$.uid') = ?;
-- Python: chunk_order BETWEEN 5 AND 15 인 것만 필터
```

### 7.3 Document Anchor + Hierarchy Scope 결합

```sql
-- Sparse + 문서 필터 + 섹션 범위 필터 (2단계)
-- Step 1: FTS5 검색 (doc_id로 사전 필터 가능 시)
SELECT uid, bm25(sparse) AS score FROM sparse
WHERE doc_id = 'eb69a3dfeb69208c'
  AND nouns MATCH '"사업" AND "개요"'
ORDER BY bm25(sparse) LIMIT 30;

-- Step 2: uid별 chunks 조회 후 Python에서 복합 필터
--   document_title IN (...) AND chunk_order BETWEEN start AND end
SELECT metadata, text FROM chunks
WHERE json_extract(metadata, '$.uid') = ?;
```

---

## 8. Python 코드 예시

### 8.1 DB 연결 (sqlite-vec 확장 로드)

```python
import sqlite3
import json
import sqlite_vec
import numpy as np
from sentence_transformers import SentenceTransformer

DB_PATH = "DB/document.db"
MODEL_NAME = "jhgan/ko-sroberta-multitask"

# sqlite-vec 확장 로드 (벡터 검색 시 필수)
conn = sqlite3.connect(DB_PATH)
conn.enable_load_extension(True)
sqlite_vec.load(conn)
```

### 8.2 Dense 벡터 검색

```python
model = SentenceTransformer(MODEL_NAME)
query = "시스템 구축 사업 개요"
query_vec = model.encode(query).astype(np.float32).tobytes()

cursor = conn.cursor()
cursor.execute("""
    SELECT c.rowid, c.text, c.metadata, v.distance
    FROM chunks c
    JOIN chunks_vec v ON c.rowid = v.rowid
    WHERE v.text_embedding MATCH ?
    ORDER BY v.distance
    LIMIT 5
""", (query_vec,))

for rowid, text, metadata_blob, distance in cursor.fetchall():
    meta = json.loads(metadata_blob)
    print(f"[{distance:.4f}] {meta['source_file']} p.{meta['page_start']}")
    print(f"  {text[:100]}...")
```

### 8.3 Sparse 키워드 검색 (2단계 패턴)

```python
from kiwipiepy import Kiwi

kiwi = Kiwi()

def extract_nouns(text: str) -> str:
    tokens = kiwi.tokenize(text)
    nouns = [t.form for t in tokens if t.tag in ('NNG', 'NNP', 'NNB')]
    return " ".join(nouns)

query = "통합 관리 시스템 구축"
query_nouns = extract_nouns(query)
# → "통합 관리 시스템 구축"

# FTS5 쿼리 생성 (AND 검색)
fts_query = " AND ".join([f'"{n}"' for n in query_nouns.split()])
# → '"통합" AND "관리" AND "시스템" AND "구축"'

cursor = conn.cursor()

# Step 1: FTS5 단독 검색 (빠름)
cursor.execute("""
    SELECT uid, bm25(sparse) AS score
    FROM sparse
    WHERE nouns MATCH ?
    ORDER BY bm25(sparse)
    LIMIT 20
""", (fts_query,))
sparse_hits = cursor.fetchall()  # [(uid, score), ...]

# Step 2: uid별 chunks 메타데이터 조회 (인덱스 활용, 빠름)
results = []
for uid, score in sparse_hits:
    cursor.execute("""
        SELECT rowid, text, metadata
        FROM chunks
        WHERE json_extract(metadata, '$.uid') = ?
    """, (uid,))
    row = cursor.fetchone()
    if row:
        results.append((row[0], row[1], row[2], score))

for rowid, text, metadata_blob, score in results:
    meta = json.loads(metadata_blob)
    print(f"[BM25={score:.4f}] {meta['source_file']} p.{meta['page_start']}")
    print(f"  {text[:100]}...")
```

### 8.4 Hybrid 검색 (RRF)

```python
def rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)

# Dense top-20 (단일 쿼리)
cursor.execute("""
    SELECT c.rowid, v.distance
    FROM chunks c
    JOIN chunks_vec v ON c.rowid = v.rowid
    WHERE v.text_embedding MATCH ?
    ORDER BY v.distance
    LIMIT 20
""", (query_vec,))
dense_results = cursor.fetchall()

# Sparse top-20 (2단계)
cursor.execute("""
    SELECT uid, bm25(sparse) AS score
    FROM sparse
    WHERE nouns MATCH ?
    ORDER BY bm25(sparse)
    LIMIT 20
""", (fts_query,))
sparse_hits = cursor.fetchall()

# uid → rowid 변환
sparse_results = []
for uid, score in sparse_hits:
    cursor.execute("""
        SELECT rowid FROM chunks
        WHERE json_extract(metadata, '$.uid') = ?
    """, (uid,))
    row = cursor.fetchone()
    if row:
        sparse_results.append((row[0], score))

# RRF 합산
scores = {}
for rank, (rowid, _) in enumerate(dense_results):
    scores[rowid] = scores.get(rowid, 0) + rrf_score(rank + 1)
for rank, (rowid, _) in enumerate(sparse_results):
    scores[rowid] = scores.get(rowid, 0) + rrf_score(rank + 1)

# 최종 top-k
top_k = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
for rowid, score in top_k:
    cursor.execute("SELECT text, metadata FROM chunks WHERE rowid = ?", (rowid,))
    text, meta_blob = cursor.fetchone()
    meta = json.loads(meta_blob)
    print(f"[RRF={score:.4f}] {meta['source_file']} ({meta['section_level1']})")
    print(f"  {text[:100]}...")
```

### 8.5 Hierarchy Scope 적용 검색

Hierarchy 테이블의 **설계 목적**은 사용자 질의에서 관련 문서/섹션을 먼저 발견(anchor)한 뒤,
해당 범위 내에서 chunk를 검색하는 **2단계 스코핑 패턴**이다.

> **핵심 흐름**: 질의 → `hierarchy_vec` 벡터 검색 → `(doc_id, start_order, end_order)` 발견 → 해당 범위 내 chunk 검색

#### vec0 kNN 제약 사항 (중요)

`chunks_vec`의 kNN 검색(`MATCH ? AND k = N`)은 **전역 최근접 이웃**을 반환한다.
`doc_id`나 `chunk_order` 조건으로 필터링할 수 없으므로, `k=4096`(최대값)으로 검색해도
특정 섹션의 11개 chunk 중 5개만 포함되는 등 **누락이 발생**한다.

따라서 스코핑된 Dense 검색은 **Python-side 유사도 계산** 방식을 사용한다:
1. SQL로 scope 내 chunk + embedding을 일괄 fetch
2. Python에서 cosine similarity 계산 후 정렬

이 방식은 scope 크기가 보통 5~60개 chunk이므로 **~0.06초** 내 완료된다.

#### Step 1: Hierarchy 벡터 검색 (문서/섹션 발견)

```python
import struct
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("jhgan/ko-sroberta-multitask")

query = "사업 추진 내용"
q_emb = model.encode(query)
q_bytes = struct.pack(f"{len(q_emb)}f", *q_emb.tolist())

# hierarchy_vec에서 관련 섹션 검색 (k=10)
cursor.execute("""
    SELECT rowid, distance
    FROM hierarchy_vec
    WHERE text_embedding MATCH ? AND k = 10
""", (q_bytes,))
h_results = cursor.fetchall()

# 각 결과의 메타데이터 확인
scopes = []
for rowid, distance in h_results:
    cursor.execute("SELECT text, metadata FROM hierarchy WHERE rowid = ?", (rowid,))
    text, meta_blob = cursor.fetchone()
    meta = json.loads(meta_blob)
    scopes.append({
        "doc_id": meta["doc_id"],
        "level": meta["level"],
        "title": meta["title"],
        "start_order": meta["start_order"],
        "end_order": meta["end_order"],
        "distance": distance,
    })
    print(f"[{distance:.2f}] L{meta['level']} \"{meta['title']}\" "
          f"doc={meta['doc_id'][:8]}.. scope=[{meta['start_order']},{meta['end_order']}]")

# 예시 출력:
# [7.21] L2 "사업추진내용"  doc=a12e8707.. scope=[14,24]
# [7.40] L2 "사업개요"      doc=376ea776.. scope=[3,5]
# [7.53] L2 "사업추진계획"  doc=376ea776.. scope=[7,10]
```

#### Step 2a: Scoped Dense 검색 (Python-side 유사도)

```python
# Step 1에서 발견한 최상위 scope 사용
best = scopes[0]
doc_id = best["doc_id"]
start_order = best["start_order"]
end_order = best["end_order"]

# scope 내 chunk + embedding 일괄 fetch
cursor.execute("""
    SELECT rowid, text, text_embedding
    FROM chunks
    WHERE json_extract(metadata, '$.doc_id') = ?
      AND json_extract(metadata, '$.chunk_order') BETWEEN ? AND ?
""", (doc_id, start_order, end_order))
scoped_chunks = cursor.fetchall()

# Python-side cosine similarity 계산
q_vec = q_emb / np.linalg.norm(q_emb)
scored = []
for rowid, text, emb_blob in scoped_chunks:
    chunk_vec = np.array(struct.unpack(f"{768}f", emb_blob))
    norm = np.linalg.norm(chunk_vec)
    if norm > 0:
        chunk_vec /= norm
    sim = float(np.dot(q_vec, chunk_vec))
    scored.append((rowid, text, sim))

scored.sort(key=lambda x: x[2], reverse=True)
for rowid, text, sim in scored[:5]:
    print(f"[cos={sim:.4f}] rowid={rowid}: {text[:100]}...")

# 예시 출력 (scope=[14,24], 11 chunks):
# [cos=0.4906] rowid=15: ## 사업추진내용 ...
# [cos=0.3761] rowid=25: | ※ (중요) 기재된화면은참고자료이며 ...
# [cos=0.3537] rowid=17: - 스톡옵션배정및처리현황통계기능구축 ...
```

#### Step 2b: Scoped Sparse 검색 (FTS5 + doc_id 필터)

```python
from kiwipiepy import Kiwi

kiwi = Kiwi()
nouns = [t.form for t in kiwi.tokenize(query) if t.tag.startswith("NN")]
fts_query = " ".join(nouns)  # "사업 추진 내용"

# sparse 테이블에서 doc_id 필터 적용 검색
cursor.execute("""
    SELECT uid, bm25(sparse) AS score
    FROM sparse
    WHERE nouns MATCH ? AND doc_id = ?
    ORDER BY bm25(sparse)
    LIMIT 30
""", (fts_query, doc_id))
sparse_hits = cursor.fetchall()

# chunk_order 범위로 섹션 scope 필터링
results = []
for uid, score in sparse_hits:
    cursor.execute("""
        SELECT json_extract(metadata, '$.chunk_order')
        FROM chunks
        WHERE json_extract(metadata, '$.uid') = ?
    """, (uid,))
    row = cursor.fetchone()
    if row and start_order <= row[0] <= end_order:
        results.append((uid, score))

# 결과 출력
for uid, score in results[:5]:
    cursor.execute("""
        SELECT text FROM chunks
        WHERE json_extract(metadata, '$.uid') = ?
    """, (uid,))
    text = cursor.fetchone()[0]
    print(f"[BM25={score:.4f}] uid={uid}: {text[:100]}...")
```

#### 성능 참고 (E2E 벤치마크)

| 단계 | 소요시간 |
|------|----------|
| hierarchy_vec 검색 (k=10) | ~0.24초 |
| metadata fetch | <0.01초 |
| scope 내 chunk fetch (11~59개) | ~0.03~0.06초 |
| Python-side similarity | <0.01초 |
| **E2E 합계** | **~0.28초** |

### 8.6 문서 목록 조회

```python
# 전체 문서 목록
cursor.execute("""
    SELECT json_extract(metadata, '$.doc_id') AS doc_id,
           json_extract(metadata, '$.source_file') AS file,
           json_extract(metadata, '$.document_title') AS title,
           COUNT(*) AS chunk_count
    FROM chunks
    GROUP BY doc_id
    ORDER BY file
""")
for doc_id, file, title, count in cursor.fetchall():
    print(f"{file}: {title} ({count} chunks, doc_id={doc_id})")
```

---

## 9. 인덱스 목록

`storage_step5.py`의 `ensure_indexes()`가 자동 생성하는 JSON-expression 인덱스 5종:

| 인덱스 | 대상 | 용도 |
|--------|------|------|
| `idx_chunks_doc_title` | `json_extract(metadata, '$.document_title')` | Document Anchor 필터 가속 |
| `idx_chunks_order` | `json_extract(metadata, '$.chunk_order')` | Hierarchy Scope 범위 검색 가속 |
| `idx_chunks_doc_order` | `(document_title, chunk_order)` | Anchor + Scope 복합 필터 가속 |
| `idx_chunks_uid` | `json_extract(metadata, '$.uid')` | Sparse→Chunks 2단계 쿼리 Step2 가속 |
| `idx_chunks_doc_id` | `json_extract(metadata, '$.doc_id')` | doc_id 기반 조회/upsert 가속 |

```sql
-- 인덱스 확인
SELECT name, sql FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%';
```

---

## 10. 주의 사항

### 10.1 sqlite-vec 확장 필수

벡터 검색(`chunks_vec MATCH`)을 사용하려면 **반드시** sqlite-vec 확장을 로드해야 한다. 순수 `sqlite3` 모듈만으로는 `vec0` 가상 테이블에 접근할 수 없다.

```python
import sqlite_vec
conn.enable_load_extension(True)
sqlite_vec.load(conn)
```

확장 없이 접근하면 `sqlite3.OperationalError: no such module: vec0` 오류가 발생한다.

### 10.2 임베딩 모델 일치

인덱싱과 검색에서 **반드시 동일한 임베딩 모델**을 사용해야 한다.

| 용도 | 모델 | 차원 |
|------|------|------|
| 인덱싱 (storage_step5.py) | `jhgan/ko-sroberta-multitask` | 768 |
| 검색 (쿼리 벡터 생성) | `jhgan/ko-sroberta-multitask` | 768 |

다른 모델(예: `all-MiniLM-L6-v2`, 384d)로 생성한 벡터를 사용하면 차원 불일치로 오류가 발생한다.

### 10.3 BM25 점수 해석

FTS5의 `bm25()` 함수는 **음수** 값을 반환한다. `ORDER BY bm25(sparse)` (오름차순)이 가장 관련도 높은 순서이다.

```
bm25 = -0.0000  →  관련도 낮음
bm25 = -5.1234  →  관련도 높음
```

### 10.4 kiwipiepy 명사 추출

Sparse 검색 시 쿼리도 반드시 kiwipiepy로 명사를 추출해서 검색해야 한다. 원문 그대로 FTS5에 넣으면 조사·어미 때문에 매칭이 안 된다.

```python
# ❌ 잘못된 사용
cursor.execute("SELECT * FROM sparse WHERE nouns MATCH '시스템을 구축합니다'")

# ✅ 올바른 사용
nouns = extract_nouns("시스템을 구축합니다")  # → "시스템 구축"
cursor.execute("SELECT * FROM sparse WHERE nouns MATCH ?", (nouns,))
```

### 10.5 Upsert (재처리)

동일 문서를 다시 처리하면 doc_id 기반 DELETE→INSERT가 작동한다. 중복 데이터가 쌓이지 않는다. 단, DB 전체를 처음부터 다시 만들려면 `DB/document.db`를 삭제 후 실행해야 한다.

### 10.6 FTS5 + chunks 단일 JOIN 금지

FTS5 가상 테이블(`sparse`)과 일반 테이블(`chunks`)의 **단일 JOIN 쿼리는 실용 불가**하다 (120초 이상 타임아웃). SQLite 옵티마이저가 FTS5와 일반 테이블 간 인덱스를 효과적으로 활용하지 못하는 구조적 한계이다.

```python
# ❌ 절대 사용 금지 (120초+ 타임아웃)
cursor.execute("""
    SELECT c.rowid, c.text, bm25(sparse) AS score
    FROM sparse
    JOIN chunks c ON sparse.uid = json_extract(c.metadata, '$.uid')
    WHERE sparse.nouns MATCH '시스템'
    ORDER BY bm25(sparse) LIMIT 10
""")

# ✅ 2단계 패턴 사용 (~1.6초)
# Step 1: FTS5 단독
cursor.execute("SELECT uid, bm25(sparse) FROM sparse WHERE nouns MATCH '시스템' ORDER BY bm25(sparse) LIMIT 20")
# Step 2: uid별 chunks 조회
cursor.execute("SELECT text, metadata FROM chunks WHERE json_extract(metadata, '$.uid') = ?", (uid,))
```

### 10.7 hierarchy 테이블 부재 시

v2.1.3 이하 DB에는 `hierarchy` 테이블이 존재하지 않는다. hierarchy 관련 쿼리 전에 테이블 존재 여부를 확인하는 것이 안전하다.

```sql
SELECT name FROM sqlite_master WHERE type='table' AND name='hierarchy';
```
