import os
import json
import sqlite3
import sqlite_vec
from pathlib import Path
from langchain_community.vectorstores import SQLiteVec
from langchain_community.embeddings import SentenceTransformerEmbeddings

DB_PATH = "DB/document.db"
CHUNK_DIR = "output/chunks"
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'

embeddings = SentenceTransformerEmbeddings(model_name=EMBEDDING_MODEL)

os.makedirs('DB', exist_ok=True)

# DB 재생성을 위해 기존 테이블을 모두 삭제한다.
def initiate_db_file(db_path = DB_PATH):
    with sqlite3.connect(DB_PATH) as conn:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS chunks")
        cursor.execute("DROP TABLE IF EXISTS chunks_vec")
        cursor.execute("DROP TABLE IF EXISTS chunks_vec_info")
        cursor.execute("DROP TABLE IF EXISTS chunks_vec_chunks")
        cursor.execute("DROP TABLE IF EXISTS chunks_vec_rowids")
        cursor.execute("DROP TABLE IF EXISTS chunks_vec_vector_chunks00")
        cursor.execute("DROP TABLE IF EXISTS sparse")
        cursor.execute("DROP TABLE IF EXISTS sparse_data")
        cursor.execute("DROP TABLE IF EXISTS sparse_idx")
        cursor.execute("DROP TABLE IF EXISTS sparse_content")
        cursor.execute("DROP TABLE IF EXISTS sparse_docsize")
        cursor.execute("DROP TABLE IF EXISTS sparse_config")
        cursor.execute("DROP TABLE IF EXISTS hierarchy")
        cursor.execute("DROP TABLE IF EXISTS hierarchy_vec")
        cursor.execute("DROP TABLE IF EXISTS hierarchy_vec_info")
        cursor.execute("DROP TABLE IF EXISTS hierarchy_vec_chunks")
        cursor.execute("DROP TABLE IF EXISTS hierarchy_vec_rowids")
        cursor.execute("DROP TABLE IF EXISTS hierarchy_vec_vector_chunks00")

# DB 생성을 위해 chunk 파일들로부터 chunk들을 모은다.
def gather_chunks(chunk_dir = CHUNK_DIR):
    chunks = []
    chunk_path = Path(CHUNK_DIR)
    for chunk_file in sorted(chunk_path.glob('chunk_*.json')):
        with open(chunk_file, 'r', encoding='utf-8') as f:
            chunks.append(json.load(f))
    return chunks


# SQLiteVec을 활용하여 chunk들로부터 벡터 DB를 만든다.
def generate_vector_db_table(chunks, table = 'chunks', db_path = DB_PATH):
    SQLiteVec.from_texts(
        texts=[c['content'] for c in chunks],
        embedding=embeddings,
        table=table,
        db_file=db_path,
        metadatas=[c['metadata'] for c in chunks]
    )

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

def make_query_bigrams(text: str) -> str:
    """
    [Search용] 공백으로 구분된 키워드 리스트를 받아 FTS5 쿼리용 바이그램 문자열로 변환합니다.
    
    [Layer 3 수정 사항]
    1. Intra-token Logic (단어 내부): AND 연산. '서울시'는 '서울'과 '울시'가 모두 붙어있어야 함.
    2. Inter-token Logic (단어 간): OR 연산. 여러 키워드 중 하나라도 걸리면 검색되게 하여 'Zero Recall' 방지.
       -> 이후 BM25 알고리즘이 '더 많이 매칭된 문서'에 높은 점수를 주어 정렬함.
    
    예: "서울시 제안" 
      -> (서울 AND 울시) OR (제안)
    """
    if not text: return ""
    
    # 1. 키워드별로 분리
    tokens = text.split()
    if not tokens: return ""

    final_bigrams = []

    for token in tokens:
        # 2글자 미만인 토큰 처리 (무시하거나 그대로 둠)
        if len(token) < 2:
            continue
        
        # 2. 각 토큰별로 바이그램 생성
        token_bigrams = [token[i:i+2] for i in range(len(token) - 1)]
        
        # 3. [Intra-token] 단어 내부는 AND로 묶음 (순서와 구성 보장)
        if token_bigrams:
            # 예: "서울시" -> "서울" AND "울시"
            # FTS5에서 구문 검색을 위해 따옴표로 묶음
            token_query = " AND ".join(f'"{bg}"' for bg in token_bigrams)
            final_bigrams.append(f"({token_query})")
    
    # 4. [Inter-token] 단어 간은 OR로 연결 (Recall 확보)
    if not final_bigrams:
        return ""
        
    return " OR ".join(final_bigrams)

# 벡터 DB를 참조하는 FTS5 테이블을 생성한다.
def generate_sparse_db_table(chunks, db_path = DB_PATH):
    with sqlite3.connect(db_path) as conn:
        # DB 커서 생성
        cursor = conn.cursor()
        # vec_0 확장을 적용
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        # FTS 테이블 생성 (토크나이저는 기본 unicode61 사용)
        cursor.execute('''
            CREATE VIRTUAL TABLE sparse USING fts5(
                bigrams,               -- 검색용 (2글자씩 잘린 텍스트)
                text UNINDEXED, -- 결과 표시용 (원본 텍스트)
                tokenize='unicode61'
            )
        ''')

        # FTS용 데이터 리스트 생성 (토크나이저는 기본 unicode61 사용)
        data_to_insert = []

        for chunk in chunks:
            raw = chunk['content']
            bigram_text = make_bigrams(raw)
            data_to_insert.append((chunk['chunk_id'], bigram_text, raw))
        
        # FTS 데이터 삽입 (rowid는 보이지 않는 column으로, 실제로는 존재함)
        cursor.executemany("INSERT INTO sparse(rowid, bigrams, text) VALUES (?, ?, ?)", data_to_insert)
        conn.commit()

# FTS 데이터 검색 예시
# query: 검색할 대상
# k 값 (검색할 수)를 지정 - SQL 문에서는 LIMIT으로 구현
def sparse_search(query, k=10, db_path = DB_PATH):
    """
    수정 사항: make_query_bigrams가 반환한 쿼리가 비어있을 경우 예외 처리 추가
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        # 쿼리 변환
        fts_query = make_query_bigrams(query)
        
        # 검색어가 너무 짧거나 유효한 바이그램이 없는 경우 처리
        if not fts_query:
            print("[]") # 빈 결과 반환
            return []

        try:
            cursor.execute('''
                SELECT 
                    json_extract(c.metadata, '$.section_level1'),
                    c.metadata,
                    bm25(sparse) as score
                FROM chunks c
                JOIN sparse s ON c.rowid = s.rowid
                WHERE s.bigrams MATCH ?
                ORDER BY score
                LIMIT ?;
            ''', (fts_query, k,))
            results = cursor.fetchall()
            # print(results) # 디버깅용 출력 (필요시 주석 해제)
            return results # 결과를 반환하도록 수정 (Agent가 사용해야 하므로)
        except Exception as e:
            print(f"Sparse Search Error: {e}")
            return []


# 벡터 DB 객체와 연결하기
def vector_search(query, db_file=DB_PATH, table='chunks', filter=None, k=3):
    vector_store = SQLiteVec(
        table=table, connection=None, db_file=db_file, embedding=embeddings
    )

    # 벡터 DB로 검색하기
    # filter에 metadata 항목을 dictionary 형태로 인자로 주면 metadata를 통한 검색을 할 수 있다.
    if filter:
        res = vector_store.similarity_search(query, filter=filter, k=k)
    else:
        res = vector_store.similarity_search(query, k=k)
    # print(res)
    return res