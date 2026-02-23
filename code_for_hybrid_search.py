import os
import hashlib
import json
import chromadb
from chromadb.utils import embedding_functions
from chromadb.utils.embedding_functions import ChromaBm25EmbeddingFunction
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional, cast

# 필수 라이브러리 체크
try:
    from kiwipiepy import Kiwi
except ImportError:
    print("❌ Error: kiwipiepy not found. Run: pip install kiwipiepy")
    exit(1)



bm25_ef = ChromaBm25EmbeddingFunction(
    k=1.2, b=0.75, avg_doc_length=256.0, token_max_length=40
)
_kiwi = Kiwi()


def _sparse_to_dict(sparse_vec) -> Dict:
    """SparseVector를 JSON-serializable dict로 변환."""
    return {str(idx): float(val) for idx, val in zip(sparse_vec.indices, sparse_vec.values)}


def extract_nouns(text: str) -> str:
    """BM25용 명사 추출 (한국어 검색 품질 최적화)."""
    if not text: return ""
    tokens = _kiwi.tokenize(text)
    return " ".join([t.form for t in tokens if t.tag in ('NNG', 'NNP', 'NNB')])


def hybrid_query(collection, query_text: str, n_results: int = 10):
    # 1. Dense retrieval
    dense_results = collection.query(query_texts=[query_text], n_results=n_results * 2)
    
    # 2. Compute BM25 scores from stored sparse vectors
    query_sparse = _sparse_to_dict(bm25_ef([extract_nouns(query_text)])[0])
    
    scored = []
    for i, meta in enumerate(dense_results['metadatas'][0]):
        doc_sparse = json.loads(meta.get('sparse_embedding', '{}'))

        # Dot product
        sparse_score = sum(
            query_sparse.get(k, 0) * v for k, v in doc_sparse.items()
        )
        dense_score = 1 - dense_results['distances'][0][i]  # cosine similarity
        
        # RRF-style fusion
        combined = (1 / (60 + i + 1)) + sparse_score * 0.5
        scored.append((i, combined))
    
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:n_results]