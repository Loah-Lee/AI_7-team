"""검색 그래프 (Hybrid Search)

Dense + Sparse 2채널 검색 후 RRF로 결합하는 LangGraph 검색 파이프라인.
"""

import json
import sqlite3
from typing import Any, Dict, List, TypedDict, cast

import numpy as np
import sqlite_vec
from kiwipiepy import Kiwi
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langgraph.graph import END, StateGraph


# ============================================================
# 상수
# ============================================================

DB_PATH = "/home/codeitDev/project/AI_7-team/DB/document.db"
MODEL_NAME = "jhgan/ko-sroberta-multitask"
RRF_K = 20


# ============================================================
# 모듈 초기화 (임베딩 모델, 형태소 분석기)
# ============================================================

embeddings = SentenceTransformerEmbeddings(model_name=MODEL_NAME)
kiwi = Kiwi()


# ============================================================
# State 정의
# ============================================================

class SearchState(TypedDict):
    # 검색용 쿼리
    query: str

    # 계층 정보 (필터링 용도)
    # 추후, 전처리 단계 개선을 수행한 뒤에 적용 예정
    # scopes: List[Dict]

    # 검색 결과
    dense_result: List[Dict]
    sparse_result: List[Dict]

    # 최종 결과
    search_result: List[Dict]


# ============================================================
# 유틸리티
# ============================================================

def extract_nouns(query: str) -> str:
    if not query:
        return ""
    tokens: List[Any] = cast(List[Any], kiwi.tokenize(query))
    nouns = [f'"{t.form}"' for t in tokens if t.tag in ('NNG', 'NNP', 'NNB')]
    if len(nouns) == 0:
        return ""
    return " OR ".join(nouns)


# ============================================================
# 검색 노드
# ============================================================

def dense_search(state: SearchState):
    query = state['query']
    query_vec = np.array(embeddings.embed_query(query)).astype('float32')

    with sqlite3.connect(DB_PATH) as conn:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                json_extract(c.metadata, '$.uid'),
                c.text,
                c.metadata
            FROM chunks c
            JOIN chunks_vec v ON c.rowid = v.rowid
            WHERE v.text_embedding MATCH ? AND k = 30
        """, (query_vec,))
        results = cursor.fetchall()

        # 'uid': ('text', 'metadata') 형식이다.
        search_results = []
        for result in results:
            search_results.append({result[0]: (result[1], json.loads(result[2]))})

    return {'dense_result': search_results}


def sparse_search(state: SearchState):
    query = extract_nouns(state['query'].strip())
    # 단어 단위의 OR를 사용한다.
    # 추후 bigram 변경 계획이 있다.
    if len(query) == 0:
        return {'sparse_result': []}

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                uid,
                snippet(sparse, 1, '[', ']', '...', 20),
                bm25(sparse) as score
                FROM sparse
                WHERE nouns MATCH ?
                ORDER BY score
                LIMIT 30
        """, (query,))

        sparse_result = cursor.fetchall()
        uids = [r[0] for r in sparse_result]
        
        if len(uids) > 0:
            cursor.execute(f"""
                SELECT 
                    json_extract(metadata, '$.uid'), 
                    text,
                    metadata
                FROM chunks
                WHERE json_extract(metadata, '$.uid') IN (SELECT value FROM json_each(?))
            """, (json.dumps(list(uids)),))

            final_results = cursor.fetchall()

            final_results = {a: (b, json.loads(c)) for a, b, c in final_results}

            final_results = [{uid: final_results[uid]} for uid in uids]
        else:
            final_results = []
    return {'sparse_result': final_results}


def rrf(state: SearchState):
    def compute_scores(result_list):
        scores = {}
        for i, d in enumerate(result_list):
            doc_id = next(iter(d.keys()))
            scores[doc_id] = 1 / (i + RRF_K + 1)
        return scores

    # RRF 계산
    dense_scores = compute_scores(state['dense_result'])
    sparse_scores = compute_scores(state['sparse_result'])

    # 검색된 전체 데이터에 대해, doc_id: value 매핑을 수행
    total_docs = {}
    for result_list in [
        state['dense_result'],
        state['sparse_result']
    ]:
        for d in result_list:
            total_docs.update(d)

    # doc_id: score 매핑을 수행 - 동일 문서가 여러 번 나오면 합을 계산
    total_scores = {}

    for score_dict in [
        dense_scores,
        sparse_scores
    ]:
        for doc_id, score in score_dict.items():
            total_scores[doc_id] = total_scores.get(doc_id, 0) + score

    score_list = sorted(total_scores.items(), key=lambda x: -x[1])

    result = [total_docs[k] for k, v in score_list[:10]]
    return {'search_result': result}


def empty(state: SearchState):
    return


# ============================================================
# 그래프 빌드
# ============================================================

def build_search_graph():
    """검색 그래프를 빌드하고 컴파일한다."""
    search_workflow = StateGraph(SearchState)

    search_workflow.add_node("empty", empty)

    search_workflow.add_node("dense", dense_search)
    search_workflow.add_node("sparse", sparse_search)

    search_workflow.add_node("rrf", rrf)

    search_workflow.set_entry_point("empty")

    search_workflow.add_edge("empty", "dense")
    search_workflow.add_edge("empty", "sparse")

    search_workflow.add_edge("dense", "rrf")
    search_workflow.add_edge("sparse", "rrf")
    search_workflow.add_edge("rrf", END)

    return search_workflow.compile()


hybrid_app = build_search_graph()
