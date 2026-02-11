#!/usr/bin/env python3
"""입찰메이트 v17 - 벡터 저장소."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import chromadb
from openai import OpenAI

# 설정
sys.path.insert(0, 'src')
from src.utils.config import OPENAI_API_KEY, EMBEDDING_MODEL, CHUNK_HASH_MOD, ORG_ALIASES

# 파서는 import 방식을 사용
from src.parsers.csv_loader import CSVMarkdownConverter
from src.parsers.pdf_loader import PDFMarkdownConverter
from src.parsers.hwp_loader import HWPMarkdownConverter
from src.graph.state import OrgInfo


class VectorStore:
    """마크다운 문서를 저장하고 검색하는 벡터 저장소 클래스."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from src.utils.config import get_default_db_path
            db_path = get_default_db_path()

        self.db_path = db_path
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(
            name="rfp_docs_v17",
            metadata={"hnsw:space": "cosine"}
        )
        self.count = self.collection.count()
        self.org_registry: dict[str, OrgInfo] = {}

        # 변환기 초기화
        self.csv_converter = CSVMarkdownConverter()
        self.pdf_converter = PDFMarkdownConverter()
        self.hwp_converter = HWPMarkdownConverter()

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
        if OPENAI_API_KEY:
            client = OpenAI(api_key=OPENAI_API_KEY)
            embeddings = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            return [e.embedding for e in embeddings.data]
        else:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("BM-K/KoSimCSE-roberta-multitask")
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

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """문서를 검색합니다."""
        query_embedding = self._create_query_embedding(query)

        try:
            response = self.collection.query(query_embeddings=[query_embedding], n_results=top_k)
            return self._parse_search_results(response)
        except Exception:
            return []

    def _create_query_embedding(self, query: str) -> list[float]:
        """쿼리 임베딩을 생성합니다."""
        if OPENAI_API_KEY:
            client = OpenAI(api_key=OPENAI_API_KEY)
            return client.embeddings.create(
                model=EMBEDDING_MODEL, input=[query]
            ).data[0].embedding
        else:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("BM-K/KoSimCSE-roberta-multitask")
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
