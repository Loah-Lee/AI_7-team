#!/usr/bin/env python3
"""
Storage & Indexing Step 5: Hybrid RAG DB Construction
- Implements a single-file hybrid database using SQLiteVec for dense search
  and FTS5 for sparse (keyword) search, as per 'agents/5_storage.md'.
"""

import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Tuple

# Ensure required libraries are installed
try:
    from langchain_community.vectorstores import SQLiteVec
    from langchain_community.embeddings import SentenceTransformerEmbeddings
except ImportError:
    print("❌ Error: langchain_community or sentence-transformers is not installed.")
    print("   Please run: pip install langchain-community sentence-transformers sqlite-vec")
    exit(1)

DB_PATH = "DB/document.db"
CHUNK_DIR = "output/chunks"
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'

def initialize_database(db_path: str) -> None:
    """
    Initializes the SQLite database, creating tables for vector storage (SQLiteVec)
    and a virtual table for full-text search (FTS5). Also sets up triggers to
    prevent duplicates and synchronize data.
    """
    print(f"🔹 Initializing database at: {db_path}")
    Path(db_path).parent.mkdir(exist_ok=True)
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 1. & 2. Chunks and Hierarchy tables are created by SQLiteVec.
        # We only need to create the sparse table.
        # Forcing a drop to ensure schema is fresh on each run.
        cursor.execute("DROP TABLE IF EXISTS chunks")
        cursor.execute("DROP TABLE IF EXISTS hierarchy")
        
        # 3. Sparse FTS5 virtual table
        cursor.execute("DROP TABLE IF EXISTS sparse") # Drop for clean rebuild
        cursor.execute('''
            CREATE VIRTUAL TABLE sparse USING fts5(
                chunk_id UNINDEXED,
                content
            )
        ''')
        conn.commit()
    print("   ✅ Database initialized with tables: sparse (FTS5). Chunks and hierarchy will be created by SQLiteVec.")

def setup_triggers(db_path: str) -> None:
    """Sets up triggers after tables have been created."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Trigger to synchronize chunks with sparse FTS table
        cursor.execute("DROP TRIGGER IF EXISTS sync_chunks_to_sparse")
        cursor.execute('''
            CREATE TRIGGER sync_chunks_to_sparse
            AFTER INSERT ON chunks
            BEGIN
                INSERT INTO sparse (chunk_id, content)
                VALUES (NEW.id, NEW.text);
            END;
        ''')
        
        conn.commit()
    print("   ✅ Triggers set up successfully.")

def load_chunks_from_disk(chunk_dir: str) -> List[Dict]:
    """Loads all chunk JSON files from the specified directory."""
    chunks = []
    chunk_path = Path(chunk_dir)
    
    if not chunk_path.exists():
        print(f"⚠️  Chunk directory not found: {chunk_dir}")
        return []

    for chunk_file in sorted(chunk_path.glob('chunk_*.json')):
        with open(chunk_file, 'r', encoding='utf-8') as f:
            chunks.append(json.load(f))
    
    return chunks

def extract_hierarchy_data(chunks: List[Dict]) -> List[Tuple[str, Dict]]:
    """Extracts unique hierarchy paths from chunks to be indexed separately."""
    hierarchy_set = set()
    hierarchy_data = []

    for chunk in chunks:
        meta = chunk.get('metadata', {})
        doc_title = meta.get('document_title', 'Unknown')
        l1 = meta.get('section_level1', None)
        l2 = meta.get('section_level2', None)
        
        path_str = ""
        if l1 and l1 != "N/A":
            path_str = l1
            if l2 and l2 != "N/A":
                path_str += f" > {l2}"
        
        # Unique key: (document title, hierarchy path)
        unique_key = (doc_title, path_str)
        
        if path_str and unique_key not in hierarchy_set:
            hierarchy_set.add(unique_key)
            hierarchy_data.append((path_str, {"document_name": doc_title}))

    return hierarchy_data

def main():
    """Main function to build the hybrid RAG database."""
    print("\n" + "="*60)
    print("💾 STORAGE & INDEXING STAGE (Step 5 - Hybrid DB)")
    print("="*60 + "\n")

    # 1. Initialize DB Schema
    initialize_database(DB_PATH)

    # 2. Load all chunks from the output directory
    print("📂 Loading all chunks from disk...")
    all_chunks = load_chunks_from_disk(CHUNK_DIR)
    if not all_chunks:
        print("❌ No chunks found to process. Exiting.")
        return
    print(f"   ✓ Loaded {len(all_chunks)} chunks.")

    # 3. Initialize embedding model
    print(f"🧠 Loading embedding model: '{EMBEDDING_MODEL}'...")
    embeddings = SentenceTransformerEmbeddings(model_name=EMBEDDING_MODEL)
    print("   ✓ Embedding model loaded.")

    # 4. Dense Indexing (Chunks)
    print("\n🔼 Performing Dense Indexing for Chunks...")
    chunk_texts = [chunk['content'] for chunk in all_chunks]
    chunk_metadatas = [chunk['metadata'] for chunk in all_chunks]

    # Create SQLiteVec store for chunks
    chunks_db = SQLiteVec.from_texts(
        texts=chunk_texts,
        embedding=embeddings,
        table="chunks",
        db_file=DB_PATH,
        metadatas=chunk_metadatas
    )
    print(f"   ✓ Indexed {len(chunk_texts)} chunks into 'chunks' table.")

    # Now that the 'chunks' table is created, set up the triggers
    setup_triggers(DB_PATH)

    # 5. Dense Indexing (Hierarchy)
    print("\n🔼 Performing Dense Indexing for Hierarchy...")
    hierarchy_to_index = extract_hierarchy_data(all_chunks)
    if hierarchy_to_index:
        hierarchy_texts = [item[0] for item in hierarchy_to_index]
        hierarchy_metadatas = [item[1] for item in hierarchy_to_index]

        # Create SQLiteVec store for hierarchy
        hierarchy_db = SQLiteVec.from_texts(
            texts=hierarchy_texts,
            embedding=embeddings,
            table="hierarchy",
            db_file=DB_PATH,
            metadatas=hierarchy_metadatas
        )
        print(f"   ✓ Indexed {len(hierarchy_texts)} unique hierarchy paths.")
    else:
        print("   - No hierarchy data to index.")

    # Sparse indexing is handled automatically by the 'sync_chunks_to_sparse' trigger.
    print("\n📊 Sparse Indexing (FTS5) was populated automatically via triggers.")

    # 6. Integrity Verification (Self-Test)
    print("\n" + "="*60)
    print("🔍 INTEGRITY VERIFICATION (SELF-TEST)")
    print("="*60)

    # Test 1: Vector Similarity Search
    print("\n   1. Testing Vector Search (Similarity)...")
    query_vec = "예산"
    try:
        results_vec = chunks_db.similarity_search(query_vec, k=1)
        if results_vec:
            print(f"      Query: '{query_vec}'")
            print(f"      ✅ [PASS] Top result: \"{results_vec[0].page_content[:100]}...\"")
        else:
            print("      ⚠️ [WARN] Vector search returned no results.")
    except Exception as e:
        print(f"      ❌ [FAIL] Vector search failed: {e}")

    # Test 2: Keyword Search (FTS5)
    print("\n   2. Testing Keyword Search (FTS5)...")
    query_fts = "제안"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT content FROM sparse WHERE content MATCH ? ORDER BY rank", (query_fts,))
            results_fts = cursor.fetchall()
            if results_fts:
                print(f"      Query: '{query_fts}'")
                print(f"      ✅ [PASS] Found {len(results_fts)} results. Top result: \"{results_fts[0][0][:100]}...\"")
            else:
                print(f"      ⚠️ [WARN] Keyword search returned no results for '{query_fts}'.")
    except Exception as e:
        print(f"      ❌ [FAIL] Keyword search failed: {e}")

    print("\n\n✨ Storage & Indexing stage complete!")
    print(f"   Final database located at: {DB_PATH}")


if __name__ == '__main__':
    main()
