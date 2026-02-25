#!/usr/bin/env python3
"""입찰메이트 v17 - 벡터 저장소."""

from __future__ import annotations

import sys, json, math, unicodedata
from pathlib import Path
from typing import Any

import chromadb
from openai import OpenAI

from src.retrievers.build_db import bm25_ef, _kiwi, dense_ef

# 설정
sys.path.insert(0, 'src')
from src.utils.config import OPENAI_API_KEY, EMBEDDING_MODEL, CHUNK_HASH_MOD, ORG_ALIASES

# 파서는 import 방식을 사용
from src.parsers.csv_loader import CSVMarkdownConverter
from src.graph.state import OrgInfo


from sentence_transformers import SentenceTransformer


class VectorStore:
    """마크다운 문서를 저장하고 검색하는 벡터 저장소 클래스."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from src.utils.config import get_default_db_path
            db_path = get_default_db_path()

        self.db_path = db_path
        self.client = chromadb.PersistentClient(path="./chroma_db")
        self.collection = self.client.get_collection(name="chunks")
        self.count = self.collection.count()
        self.org_registry: dict[str, OrgInfo] = {}
        self.last_search_results: list[dict[str, Any]] = []

        # 변환기 초기화
        self.csv_converter = CSVMarkdownConverter()


    def add_documents(self, chunks: list[dict[str, str]]) -> None:
        """문서 청크를 추가합니다."""
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        ids = [f"chunk_{i}_{hash(c['text']) % CHUNK_HASH_MOD}" for i, c in enumerate(chunks)]
        metadatas = [
            {"source": c.get("source", ""), "org": c.get("org", ""), "type": c.get("type", "unknown")}
            for c in chunks
        ]

        vectors = self._create_embeddings(texts)
        self.collection.add(documents=texts, embeddings=vectors, ids=ids, metadatas=metadatas)
        self.count = self.collection.count()

    def _create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """텍스트 임베딩을 생성합니다."""
        model = SentenceTransformer(EMBEDDING_MODEL)
        return model.encode(texts).tolist()

    def register_org(self, org_info: OrgInfo, preserve_existing: bool = True) -> None:
        """기관 정보를 등록합니다."""
        if not org_info.name:
            return

        existing = self.org_registry.get(org_info.name)
        if existing and preserve_existing:
            self._update_org_fields(existing, org_info)
        else:
            self.org_registry[org_info.name] = org_info

    def _update_org_fields(self, existing: OrgInfo, new: OrgInfo) -> None:
        """기존 기관 정보의 누락된 필드를 업데이트합니다."""
        if new.amount_numeric > 0:
            if existing.amount_numeric == 0:
                existing.amount = new.amount
                existing.amount_numeric = new.amount_numeric
            elif new.amount_numeric > existing.amount_numeric:
                existing.amount = new.amount
                existing.amount_numeric = new.amount_numeric

        if new.project_name:
            if not existing.project_name or new.amount_numeric > existing.amount_numeric:
                existing.project_name = new.project_name
        if new.summary:
            if not existing.summary or new.amount_numeric > existing.amount_numeric:
                existing.summary = new.summary

        if not existing.open_date and new.open_date:
            existing.open_date = new.open_date
        if not existing.file_format and new.file_format:
            existing.file_format = new.file_format
        if new.has_pdf:
            existing.has_pdf = True
        if new.has_hwp:
            existing.has_hwp = True

    def _normalize_metadata(self, metadata: dict) -> dict:
        """메타데이터의 문자열을 NFC normalize한다."""
        normalized = {}
        for k, v in metadata.items():
            if isinstance(v, str):
                normalized[k] = unicodedata.normalize('NFC', v)
            else:
                normalized[k] = v
        return normalized
    
    def extract_nouns(self, text: str) -> str:
        """명사 추출 (한국어 최적화)"""
        if not text:
            return ""
        tokens = _kiwi.tokenize(text)
        return " ".join([t.form for t in tokens if t.tag in ('NNG', 'NNP', 'NNB')])
    

    def _sparse_to_dict(self, sparse_vec) -> dict:
        """SparseVector를 dict로 변환"""
        return {str(idx): float(val) for idx, val in zip(sparse_vec.indices, sparse_vec.values)}
    

    def hybrid_query(self, collection, query_text: str, n_results: int = 10,
                    alpha: float = 0.5,
                    candidate_multiplier: int = 3,
                    rrf_k: int = 60):
        """
        Manual Hybrid Fusion: Dense + Sparse 수동 결합
        
        Args:
            collection: ChromaDB 컬렉션 객체
            query_text: 쿼리 텍스트
            n_results: 최종 반환 결과 수
            alpha: Sparse 가중치 (0.3~0.7 권장)
            candidate_multiplier: Dense 후보 확대 배수
            rrf_k: RRF 민감도 상수
        
        Returns:
            결합 점수 순으로 정렬된 결과 리스트
        """
        
        # 1️⃣ Candidate Expansion: Dense에서 더 많은 후보 가져오기
        dense_results = collection.query(
            query_texts=[query_text],
            n_results=n_results * candidate_multiplier  # 보통 n_results * 3
        )
        
        # 2️⃣ Query용 Sparse Vector 생성
        query_nouns = self.extract_nouns(query_text)
        query_sparse = self._sparse_to_dict(bm25_ef([query_nouns])[0])
        
        scored_results = []
        
        # 3️⃣ Dense 결과 각각에 대해 Sparse 점수 계산 및 결합
        for i, (uid, doc, meta) in enumerate(zip(
            dense_results['ids'][0],
            dense_results['documents'][0],
            dense_results['metadatas'][0]
        )):
            # Sparse 점수: 저장된 sparse_embedding과 dot-product
            doc_sparse = json.loads(meta.get('sparse_embedding', '{}'))
            raw_sparse = sum(
                query_sparse.get(k, 0.0) * v
                for k, v in doc_sparse.items()
            )
            
            # 음수 방지
            raw_sparse = max(raw_sparse, 0.0)
            
            # 결합 점수 계산
            dense_rank = i + 1  # 1-based rank
            rrf_dense = 1 / (rrf_k + dense_rank)
            sparse_score = math.log1p(raw_sparse)  # log(1 + x) 안정화
            
            combined = rrf_dense + (alpha * sparse_score)
            
            scored_results.append({
                "id": uid,
                "document": doc,
                "metadata": self._normalize_metadata(meta),
                "dense_rank": dense_rank,
                "raw_sparse_score": raw_sparse,
                "sparse_score": sparse_score,
                "rrf_dense": rrf_dense,
                "combined_score": combined
            })
        
        # 4️⃣ 결합 점수 기준으로 재정렬
        scored_results.sort(key=lambda x: x["combined_score"], reverse=True)
        
        # 5️⃣ Top-K 반환
        return scored_results[:n_results]


    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """문서를 검색합니다."""

        try:
            results = self.hybrid_query(self.collection, query, n_results=top_k, alpha=0.5)
            # response = self.collection.query(query_embeddings=[query_embedding], n_results=top_k)
            # results = self._parse_search_results(response)

            self.last_search_results = results  # 검색 결과 저장
            return results
        except Exception as e:
            print(f"검색 오류: {e}")
            return []

    def _create_query_embedding(self, query: str) -> list[float]:
        """쿼리 임베딩을 생성합니다."""
        model = SentenceTransformer(EMBEDDING_MODEL)
        return model.encode([query]).tolist()[0]

    def _parse_search_results(self, response: dict) -> list[dict[str, Any]]:
        """검색 응답을 파싱합니다."""
        results = []
        if response['documents'] and response['documents'][0]:
            for i, doc in enumerate(response['documents'][0]):
                results.append({
                    'text': doc,
                    'metadata': response['metadatas'][0][i] if response.get('metadatas') else {}
                })
        return results

    def get_ranking(
        self, field: str = "amount", top_n: int = 5, reverse: bool = True
    ) -> list[OrgInfo]:
        """랭킹을 조회합니다."""
        orgs = list(self.org_registry.values())
        if field == "amount":
            orgs = [o for o in orgs if o.amount_numeric > 0]
            return sorted(orgs, key=lambda x: x.amount_numeric, reverse=reverse)[:top_n]
        return orgs[:top_n]

    def normalize_org_name(self, org_name: str) -> str:
        """기관명을 정규화합니다."""
        for alias, standard in ORG_ALIASES.items():
            if alias in org_name:
                return standard
        return org_name
