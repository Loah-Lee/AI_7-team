# 파일명: search.py
import sqlite3
# langchain_community와 sqlite-vec 등은 환경에 설치되어 있어야 합니다.
from langchain_community.vectorstores import SQLiteVec
from langchain_community.embeddings import SentenceTransformerEmbeddings

# --- 설정 ---
DB_PATH = "DB/document.db"
MODEL_NAME = "all-MiniLM-L6-v2"

def make_bigrams(text: str) -> str:
    """
    텍스트를 2글자 단위로 쪼개서 반환합니다.
    예: "서울시 제안" -> "서울" AND "울시" AND "시제" AND "제안"
    """
    if not text: return ""
    # 띄어쓰기를 없애고 순수 텍스트만 추출
    clean_text = text.replace(" ", "")
    
    # 1글자 이하인 경우 원본 반환 (빈 문자열 반환 시 SQL 에러 방지)
    if len(clean_text) < 2: 
        return clean_text
    
    # 2글자씩 슬라이딩 윈도우 & AND 연산자로 연결
    bigrams = [clean_text[i:i+2] for i in range(len(clean_text) - 1)]
    return " AND ".join(bigrams)

def sparse_search(query: str, k: int = 3, window_size: int = 24):
    query_sparse = make_bigrams(query)
    print(f"      (Debug) FTS Query: {query_sparse}")  # 디버깅용 출력

    results = []
    # with 문을 사용하면 블록이 끝날 때 conn이 자동으로 close 됩니다.
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        try:
            # 검색은 bigrams 컬럼에서, 결과는 original_text에서 가져옴
            cursor.execute("""
                SELECT rowid, snippet(sparse, 1, '[', ']', '...', ?), bm25(sparse) as score
                FROM sparse
                WHERE bigrams MATCH ?
                ORDER BY score
                LIMIT ?
            """, (window_size, query_sparse, k))
            
            results = cursor.fetchall()
        except sqlite3.OperationalError as e:
            print(f"      ⚠️ SQLite Error: {e}")
            
    return results

def hybrid_search(query):
    print(f"\n🔎 질문: '{query}'")
    print("-" * 50)
    
    # ---------------------------------------------------------
    # 1. Sparse Search (FTS5) - 키워드 매칭
    # ---------------------------------------------------------
    try:        
        sparse_results = sparse_search(query)
        
        print(f"📋 [Keyword Search] 결과: {len(sparse_results)}건")
        if sparse_results:
            for row in sparse_results:
                # 결과 미리보기 (줄바꿈 제거 후 80자 제한)
                preview = row[1].replace('\n', ' ')[:80]
                print(f"   - [Score: {row[2]:.2f}] ...{preview}...")
        else:
            print("   - 결과 없음")
            
    except Exception as e:
        print(f"⚠️ Keyword 검색 중 오류 발생: {e}")
    # finally 구문 삭제 (conn은 위에서 이미 닫힘)

    # ---------------------------------------------------------
    # 2. Dense Search (SQLiteVec) - 의미 기반 검색
    # ---------------------------------------------------------
    print(f"\n🧠 [Vector Search] 실행 중...")
    try:
        # 임베딩 모델 로드
        embedding_function = SentenceTransformerEmbeddings(model_name=MODEL_NAME)
        connection = SQLiteVec.create_connection(db_file=DB_PATH)
        
        db = SQLiteVec(
            table="chunks",
            connection=connection, 
            embedding=embedding_function
        )
        
        # 유사도 검색 수행
        docs = db.similarity_search(query, k=3)
        
        print(f"🧠 [Vector Search] 결과: {len(docs)}건")
        for doc in docs:
            # 메타데이터 추출 (document_title로 수정)
            title = doc.metadata.get('document_title', '무제')
            content_preview = doc.page_content.replace('\n', ' ')[:80]
            print(f"   - [{title}] {content_preview}...")
            
    except Exception as e:
        print(f"❌ Vector 검색 실패: {e}")

if __name__ == "__main__":
    print(f"🚀 하이브리드 검색기 시작 (DB: {DB_PATH})")
    while True:
        try:
            q = input("\n💬 검색어 입력 (종료: q) > ")
            if q.lower() in ['q', 'exit']:
                print("👋 종료합니다.")
                break
            if q.strip():
                hybrid_search(q)
        except KeyboardInterrupt:
            print("\n👋 종료합니다.")
            break