#!/usr/bin/env python3
"""
Storage & Indexing Step 5: Hybrid RAG DB (Python Bigram Solution)
- 해결: 띄어쓰기 없는 한국어('서울시청년')와 2글자 키워드('제안') 검색 동시 지원
- 방법: Python에서 텍스트를 2글자씩(Bigram) 잘라서 FTS에 저장
"""
import os
import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Tuple

# 필수 라이브러리 로드
try:
    from langchain_community.vectorstores import SQLiteVec
    from langchain_community.embeddings import SentenceTransformerEmbeddings
except ImportError:
    print("❌ Error: Libraries not found. Run: pip install langchain-community sentence-transformers sqlite-vec")
    exit(1)

DB_PATH = "DB/document.db"
CHUNK_DIR = "output/chunks"
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'

os.makedirs('DB', exist_ok=True)

# --- [추가된 함수] Bigram 생성기 ---
def make_bigrams(text: str) -> str:
    """
    텍스트를 2글자 단위로 쪼개서 반환합니다.
    예: "서울시 제안" -> "서울 울시 시제 제안"
    """
    if not text: return ""
    # 띄어쓰기를 없애고 순수 텍스트만 추출 (띄어쓰기 없는 검색 지원을 위해)
    clean_text = text.replace(" ", "")
    if len(clean_text) < 2: return clean_text
    
    # 2글자씩 슬라이딩 윈도우
    bigrams = [clean_text[i:i+2] for i in range(len(clean_text) - 1)]
    return " ".join(bigrams)

# --- [수정된 함수] Sparse DB 초기화 ---
def initialize_database(db_path: str, chunks: List[Dict]) -> None:
    """
    FTS 테이블을 생성하고 Bigram 데이터를 직접 삽입합니다.
    (content='chunks' 옵션을 쓰지 않고, 별도로 데이터를 밀어넣습니다)
    """
    print(f"🔹 Initializing database at: {db_path}")
    Path(db_path).parent.mkdir(exist_ok=True)
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 1. FTS 테이블 생성 (토크나이저는 기본 unicode61 사용)
        cursor.execute("DROP TABLE IF EXISTS sparse")
        cursor.execute('''
            CREATE VIRTUAL TABLE sparse USING fts5(
                bigrams,               -- 검색용 (2글자씩 잘린 텍스트)
                text UNINDEXED, -- 결과 표시용 (원본 텍스트)
                tokenize='unicode61'
            )
        ''')
        
        # 2. 데이터 변환 및 삽입 (Batch Insert)
        print(f"   Generating Bigram index for {len(chunks)} chunks...")
        data_to_insert = []
        for chunk in chunks:
            raw = chunk['content']
            bigram_text = make_bigrams(raw)
            data_to_insert.append((chunk['chunk_id'], bigram_text, raw))
        
        cursor.executemany("INSERT INTO sparse(rowid, bigrams, text) VALUES (?, ?, ?)", data_to_insert)
        conn.commit()

    print("   ✅ Database initialized with Python Bigram Indexing.")

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
    hierarchy_set = set()
    hierarchy_data = []
    for chunk in chunks:
        meta = chunk.get('metadata', {})
        doc_title = meta.get('document_title', 'Unknown')
        l1 = meta.get('section_level1', None)
        l2 = meta.get('section_level2', None)
        path_str = l1 if l1 and l1 != "N/A" else ""
        if path_str and l2 and l2 != "N/A": path_str += f" > {l2}"
        unique_key = (doc_title, path_str)
        if path_str and unique_key not in hierarchy_set:
            hierarchy_set.add(unique_key)
            hierarchy_data.append((path_str, {"document_name": doc_title}))
    return hierarchy_data

def main():
    print("\n" + "="*60)
    print("💾 STORAGE & INDEXING STAGE (Bigram Fix)")
    print("="*60 + "\n")

    # 1. Load chunks
    all_chunks = load_chunks_from_disk(CHUNK_DIR)
    if not all_chunks:
        print("❌ No chunks found.")
        return
    print(f"   ✓ Loaded {len(all_chunks)} chunks.")

    # 2. Embedding Model
    print(f"🧠 Loading embedding model...")
    embeddings = SentenceTransformerEmbeddings(model_name=EMBEDDING_MODEL)

    # 3. Dense Indexing (SQLiteVec) - 기존 유지
    print("\n🔼 Performing Dense Indexing...")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS chunks")
        conn.execute("DROP TABLE IF EXISTS hierarchy")
    
    SQLiteVec.from_texts(
        texts=[c['content'] for c in all_chunks],
        embedding=embeddings,
        table="chunks",
        db_file=DB_PATH,
        metadatas=[c['metadata'] for c in all_chunks]
    )
    print("   ✓ Dense indexing complete.")

    # 4. Sparse Indexing (Bigram FTS) - [수정됨]
    # initialize_database 함수에 all_chunks를 인자로 전달합니다.
    initialize_database(DB_PATH, all_chunks)

    # 5. Hierarchy Indexing - 기존 유지
    h_data = extract_hierarchy_data(all_chunks)
    if h_data:
        SQLiteVec.from_texts(
            texts=[h[0] for h in h_data],
            embedding=embeddings,
            table="hierarchy",
            db_file=DB_PATH,
            metadatas=[h[1] for h in h_data]
        )

    # 6. Verification - [수정됨] Bigram 검색 로직 적용
    print("\n🔍 INTEGRITY VERIFICATION")
    
    query_keyword = "제안"
    
    # [중요] 쿼리 전처리: 쿼리도 Bigram으로 변환해야 매칭됨
    if len(query_keyword) >= 2:
        query_bigram_str = make_bigrams(query_keyword)
        # 공백으로 분리된 토큰들을 AND 조건으로 연결 (예: "서울" AND "울시")
        fts_query = ' AND '.join([f'"{token}"' for token in query_bigram_str.split()])
    else:
        fts_query = query_keyword

    print(f"\n   Testing Keyword Search: '{query_keyword}'")
    print(f"   -> Bigram Query: '{fts_query}'")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # 검색은 bigrams 컬럼에서, 결과는 original_text에서 가져옴
            cursor.execute("""
                SELECT rowid, snippet(sparse, 1, '[', ']', '...', 20), bm25(sparse) as score
                FROM sparse
                WHERE bigrams MATCH ?
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

    print("\n\n✨ Storage & Indexing complete!")

if __name__ == '__main__':
    main()