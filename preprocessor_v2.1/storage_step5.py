#!/usr/bin/env python3
"""
Storage & Indexing Step 5: Hybrid RAG DB (Korean-optimized)
- Korean embedding model: jhgan/ko-sroberta-multitask (768d)
- FTS5 tokenization: kiwipiepy morphological noun extraction
- Upsert pattern: doc_id-level DELETE→INSERT (deterministic SHA-256 hash)
- UID format: {doc_id}_{local_chunk_index}
- Hierarchy table: includes page ranges from chunk metadata
"""
import os
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, List, Dict, Tuple, cast

# 필수 라이브러리 로드
try:
    from langchain_community.vectorstores import SQLiteVec
    from langchain_community.embeddings import SentenceTransformerEmbeddings
    from kiwipiepy import Kiwi
except ImportError:
    print("❌ Error: Libraries not found. Run: pip install langchain-community sentence-transformers sqlite-vec kiwipiepy")
    exit(1)

DB_PATH = "DB/document.db"
CHUNK_DIR = "output/chunks"
EMBEDDING_MODEL = 'jhgan/ko-sroberta-multitask'  # 768d Korean model

os.makedirs('DB', exist_ok=True)

# Module-level Kiwi singleton
_kiwi = Kiwi()

# --- [수정된 함수] 명사 추출 (kiwipiepy) ---
def extract_nouns(text: str) -> str:
    """
    kiwipiepy를 사용하여 텍스트에서 명사만 추출합니다.
    예: "벤처확인종합관리시스템 기능 고도화" -> "벤처 확인 종합 관리 시스템 기능 고도"
    """
    if not text:
        return ""
    tokens: List[Any] = cast(List[Any], _kiwi.tokenize(text))
    nouns = [t.form for t in tokens if t.tag in ('NNG', 'NNP', 'NNB')]
    return " ".join(nouns)

def initialize_sparse_db(db_path: str, chunks: List[Dict]) -> int:
    """doc_id 단위 DELETE→INSERT upsert. Returns number of inserted rows."""
    print(f"🔹 Sparse indexing at: {db_path}")
    Path(db_path).parent.mkdir(exist_ok=True)
    inserted = 0

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS sparse USING fts5(
                uid,
                doc_id UNINDEXED,
                nouns,
                text UNINDEXED,
                tokenize='unicode61'
            )
        ''')

        doc_ids = {c['doc_id'] for c in chunks}
        for doc_id in doc_ids:
            cursor.execute("DELETE FROM sparse WHERE doc_id = ?", (doc_id,))

        print(f"   Extracting nouns for {len(chunks)} chunks...")
        data = []
        for chunk in chunks:
            uid = chunk['uid']
            doc_id = chunk['doc_id']
            noun_text = extract_nouns(chunk['content'])
            data.append((uid, doc_id, noun_text, chunk['content']))

        if data:
            cursor.executemany(
                "INSERT INTO sparse(uid, doc_id, nouns, text) VALUES (?, ?, ?, ?)",
                data,
            )
            conn.commit()
            inserted = len(data)
            print(f"   ✓ Inserted {inserted} chunks into sparse index.")

    return inserted

def upsert_dense_vectors(db_path: str, chunks: List[Dict], model_name: str) -> int:
    """
    Doc_ID 기반 Dense Upsert 수행.
    - 기존 동일 doc_id 벡터 삭제
    - 새 벡터 삽입
    Returns: inserted vector count
    """
    if not chunks:
        return 0

    print(f"🔼 Dense upsert at: {db_path}")
    Path(db_path).parent.mkdir(exist_ok=True)

    embeddings = SentenceTransformerEmbeddings(model_name=model_name)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'")
        table_exists = cursor.fetchone() is not None

    if not table_exists:
        # 테이블이 없으면 신규 생성
        print("   Creating new chunks table...")
        SQLiteVec.from_texts(
            texts=[c['content'] for c in chunks],
            embedding=embeddings,
            table="chunks",
            db_file=db_path,
            metadatas=[c['metadata'] for c in chunks],
        )
        print(f"   ✓ Created chunks table with {len(chunks)} vectors.")
        return len(chunks)

    # 테이블 존재 → doc_id 기반 DELETE → INSERT
    doc_ids = {c['doc_id'] for c in chunks}
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        for did in doc_ids:
            cursor.execute(
                "DELETE FROM chunks WHERE json_extract(metadata, '$.doc_id') = ?",
                (did,),
            )
            deleted = cursor.rowcount
            if deleted > 0:
                print(f"   Deleted {deleted} existing vectors for doc_id={did}")
        conn.commit()

    # 새 벡터 삽입
    SQLiteVec.from_texts(
        texts=[c['content'] for c in chunks],
        embedding=embeddings,
        table="chunks",
        db_file=db_path,
        metadatas=[c['metadata'] for c in chunks],
    )
    print(f"   ✓ Inserted {len(chunks)} vectors.")
    return len(chunks)


def compute_doc_id(parser_raw_path: Path) -> str:
    """SHA-256 of parser raw output (before auditor) → deterministic doc_id."""
    h = hashlib.sha256(parser_raw_path.read_bytes()).hexdigest()[:16]
    return h


def assign_uids(chunks: List[Dict]) -> None:
    """Assign UIDs and enforce Upsert contract (Fail-Fast architecture)."""

    if not chunks:
        raise RuntimeError(
            "Critical: empty chunk list detected before UID assignment"
        )

    doc_counters: Dict[str, int] = {}

    for i, chunk in enumerate(chunks):

        if 'doc_id' not in chunk:
            raise RuntimeError(
                f"Critical: chunk index {i} missing 'doc_id' before UID assignment"
            )

        doc_id = chunk['doc_id']

        if not isinstance(doc_id, str) or not doc_id.strip():
            raise RuntimeError(
                f"Critical: invalid doc_id detected at chunk index {i}"
            )

        if doc_id == "unknown":
            raise RuntimeError(
                f"Critical: forbidden fallback doc_id 'unknown' "
                f"at chunk index {i}"
            )

        idx = doc_counters.get(doc_id, 0)
        uid = f"{doc_id}_{idx}"
        chunk['uid'] = uid

        if 'metadata' not in chunk or chunk['metadata'] is None:
            chunk['metadata'] = {}

        if not isinstance(chunk['metadata'], dict):
            raise RuntimeError(
                f"Critical: metadata must be dict (chunk index {i})"
            )

        chunk['metadata']['uid'] = uid
        chunk['metadata']['doc_id'] = doc_id

        doc_counters[doc_id] = idx + 1


def load_chunks_from_disk(chunk_dir: str) -> List[Dict]:
    chunks = []
    chunk_path = Path(chunk_dir)
    if not chunk_path.exists():
        return []
    for chunk_file in sorted(chunk_path.glob('chunk_*.json')):
        with open(chunk_file, 'r', encoding='utf-8') as f:
            c = json.load(f)
            c['metadata']['chunk_id'] = c['chunk_id']
            chunks.append(c)
    return chunks

def extract_hierarchy_data(chunks: List[Dict]) -> List[Tuple[str, Dict]]:
    """
    계층 구조 데이터를 추출하고 페이지 범위를 메타데이터에 포함합니다.
    """
    hierarchy_map = {}  # (doc_title, path_str) → {pages: [page_start, page_end, ...]}
    
    for chunk in chunks:
        meta = chunk.get('metadata', {})
        doc_title = meta.get('document_title', 'Unknown')
        l1 = meta.get('section_level1', 'N/A')
        l2 = meta.get('section_level2', 'N/A')
        
        # Build path string
        path_str = l1 if l1 and l1 != "N/A" else ""
        if path_str and l2 and l2 != "N/A":
            path_str += f" > {l2}"
        
        if not path_str:
            continue
        
        key = (doc_title, path_str)
        if key not in hierarchy_map:
            hierarchy_map[key] = {"pages": []}
        
        # Collect page ranges
        ps = meta.get('page_start')
        pe = meta.get('page_end')
        if ps is not None:
            hierarchy_map[key]["pages"].append(ps)
        if pe is not None:
            hierarchy_map[key]["pages"].append(pe)
    
    # Convert to list with page range metadata
    result = []
    for (doc_title, path_str), info in hierarchy_map.items():
        pages = info["pages"]
        metadata = {"document_name": doc_title}
        if pages:
            metadata["page_start"] = min(pages)
            metadata["page_end"] = max(pages)
        result.append((path_str, metadata))
    
    return result

def main():
    print("\n" + "="*60)
    print("💾 STORAGE & INDEXING STAGE (Korean-optimized)")
    print("="*60 + "\n")

    all_chunks = load_chunks_from_disk(CHUNK_DIR)
    if not all_chunks:
        print("❌ No chunks found.")
        return
    print(f"   ✓ Loaded {len(all_chunks)} chunks.")

    parser_dir = Path('output')
    for chunk in all_chunks:
        src = chunk.get('metadata', {}).get('source_file', '')
        stem = Path(src).stem if src else 'unknown'
        raw_path = parser_dir / f'step1_parsed_{stem}.md'
        if raw_path.exists():
            chunk['doc_id'] = compute_doc_id(raw_path)
        else:
            chunk['doc_id'] = hashlib.sha256(src.encode()).hexdigest()[:16]

    assign_uids(all_chunks)

    dense_count = upsert_dense_vectors(DB_PATH, all_chunks, EMBEDDING_MODEL)
    sparse_count = initialize_sparse_db(DB_PATH, all_chunks)

    print(f"\n   Dense={dense_count}, Sparse={sparse_count}, Chunks={len(all_chunks)}")
    if dense_count != sparse_count:
        print(f"   ⚠️ Dense/Sparse mismatch!")

    # 5. Hierarchy Indexing - Upsert pattern with page ranges
    print("\n🌳 Performing Hierarchy Indexing...")
    h_data = extract_hierarchy_data(all_chunks)
    
    if h_data:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hierarchy'")
            hierarchy_table_exists = cursor.fetchone() is not None

        if not hierarchy_table_exists:
            h_embeddings = SentenceTransformerEmbeddings(model_name=EMBEDDING_MODEL)
            print(f"   Creating hierarchy table with {len(h_data)} entries...")
            SQLiteVec.from_texts(
                texts=[h[0] for h in h_data],
                embedding=h_embeddings,
                table="hierarchy",
                db_file=DB_PATH,
                metadatas=[h[1] for h in h_data],
            )
            print("   ✓ Hierarchy indexing complete.")
        else:
            print("   ✓ Hierarchy table already exists (skipping recreate).")

    # 6. Verification - kiwipiepy noun-based search
    print("\n🔍 INTEGRITY VERIFICATION")
    
    query_keyword = "제안"
    query_nouns = extract_nouns(query_keyword)
    
    print(f"\n   Testing Keyword Search: '{query_keyword}'")
    print(f"   -> Extracted Nouns: '{query_nouns}'")
    
    # Build FTS query from noun tokens
    if query_nouns.strip():
        noun_tokens = query_nouns.split()
        fts_query = ' AND '.join([f'"{token}"' for token in noun_tokens])
    else:
        fts_query = query_keyword

    print(f"   -> FTS Query: '{fts_query}'")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # Search in nouns column, return text snippets
            cursor.execute("""
                SELECT rowid, snippet(sparse, 1, '[', ']', '...', 20), bm25(sparse) as score
                FROM sparse
                WHERE nouns MATCH ?
                ORDER BY score
                LIMIT 5
            """, (fts_query,))
            
            results = cursor.fetchall()
            if results:
                for row in results:
                    print(f"      ✅ [PASS] Score={row[2]:.2f}, Text: {row[1]}")
            else:
                print(f"      ⚠️ No results found.")
    except Exception as e:
        print(f"      ❌ Search failed: {e}")

    # Additional verification: check hierarchy page ranges
    print("\n   Testing Hierarchy Page Ranges...")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT metadata FROM hierarchy LIMIT 3
            """)
            rows = cursor.fetchall()
            if rows:
                for row in rows:
                    meta = json.loads(row[0])
                    doc_name = meta.get('document_name', 'N/A')
                    page_start = meta.get('page_start', 'N/A')
                    page_end = meta.get('page_end', 'N/A')
                    print(f"      ✅ Doc: {doc_name}, Pages: {page_start}-{page_end}")
            else:
                print(f"      ⚠️ No hierarchy entries found.")
    except Exception as e:
        print(f"      ❌ Hierarchy verification failed: {e}")

    print("\n\n✨ Storage & Indexing complete!")

if __name__ == '__main__':
    main()