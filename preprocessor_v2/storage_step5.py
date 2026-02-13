#!/usr/bin/env python3
"""
Storage & Indexing Step 5: Hybrid RAG DB (Korean-optimized)
- Korean embedding model: jhgan/ko-sroberta-multitask (768d)
- FTS5 tokenization: kiwipiepy morphological noun extraction
- Upsert pattern: incremental inserts, no DROP TABLE
- Hierarchy table: includes page ranges from chunk metadata
"""
import os
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

# --- [수정된 함수] Sparse DB 초기화 (upsert pattern) ---
def initialize_database(db_path: str, chunks: List[Dict]) -> None:
    """
    FTS 테이블을 생성하고 명사 추출 데이터를 삽입합니다.
    기존 데이터는 유지하고 새로운 chunk만 추가합니다.
    """
    print(f"🔹 Initializing database at: {db_path}")
    Path(db_path).parent.mkdir(exist_ok=True)
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 1. FTS 테이블 생성 (CREATE IF NOT EXISTS)
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS sparse USING fts5(
                nouns,              -- kiwipiepy 명사 토큰
                text UNINDEXED,     -- 원본 텍스트
                tokenize='unicode61'
            )
        ''')
        
        # 2. 기존 rowid 조회 (중복 방지)
        cursor.execute("SELECT rowid FROM sparse")
        existing_rowids = set(row[0] for row in cursor.fetchall())
        
        # 3. 데이터 변환 및 삽입 (새로운 chunk만 추가)
        print(f"   Extracting nouns for {len(chunks)} chunks...")
        data_to_insert = []
        for chunk in chunks:
            chunk_id = chunk['chunk_id']
            if chunk_id not in existing_rowids:
                raw = chunk['content']
                noun_text = extract_nouns(raw)
                data_to_insert.append((chunk_id, noun_text, raw))
        
        if data_to_insert:
            cursor.executemany("INSERT INTO sparse(rowid, nouns, text) VALUES (?, ?, ?)", data_to_insert)
            conn.commit()
            print(f"   ✓ Inserted {len(data_to_insert)} new chunks into sparse index.")
        else:
            print(f"   ✓ All chunks already exist in sparse index.")

    print("   ✅ Database initialized with kiwipiepy noun extraction.")

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

    # 1. Load chunks
    all_chunks = load_chunks_from_disk(CHUNK_DIR)
    if not all_chunks:
        print("❌ No chunks found.")
        return
    print(f"   ✓ Loaded {len(all_chunks)} chunks.")

    # 2. Embedding Model
    print(f"🧠 Loading embedding model: {EMBEDDING_MODEL}...")
    embeddings = SentenceTransformerEmbeddings(model_name=EMBEDDING_MODEL)

    # 3. Dense Indexing (SQLiteVec) - Upsert pattern
    print("\n🔼 Performing Dense Indexing...")
    
    # Check if chunks table exists
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'")
        chunks_table_exists = cursor.fetchone() is not None
    
    if not chunks_table_exists:
        print("   Creating new chunks table...")
        SQLiteVec.from_texts(
            texts=[c['content'] for c in all_chunks],
            embedding=embeddings,
            table="chunks",
            db_file=DB_PATH,
            metadatas=[c['metadata'] for c in all_chunks]
        )
        print("   ✓ Dense indexing complete.")
    else:
        print("   ✓ Chunks table already exists (skipping recreate).")

    # 4. Sparse Indexing (Noun-based FTS)
    initialize_database(DB_PATH, all_chunks)

    # 5. Hierarchy Indexing - Upsert pattern with page ranges
    print("\n🌳 Performing Hierarchy Indexing...")
    h_data = extract_hierarchy_data(all_chunks)
    
    if h_data:
        # Check if hierarchy table exists
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hierarchy'")
            hierarchy_table_exists = cursor.fetchone() is not None
        
        if not hierarchy_table_exists:
            print(f"   Creating hierarchy table with {len(h_data)} entries...")
            SQLiteVec.from_texts(
                texts=[h[0] for h in h_data],
                embedding=embeddings,
                table="hierarchy",
                db_file=DB_PATH,
                metadatas=[h[1] for h in h_data]
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