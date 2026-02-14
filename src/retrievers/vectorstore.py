#!/usr/bin/env python3
"""입찰메이트 v17 - 벡터 저장소."""

from __future__ import annotations

import sys
import hashlib
from pathlib import Path
from typing import Any

import chromadb

# 설정
sys.path.insert(0, 'src')
from src.utils.config import OPENAI_API_KEY, ORG_ALIASES

# 파서는 import 방식을 사용
from src.parsers.csv_loader import CSVMarkdownConverter
from src.parsers.pdf_loader import PDFMarkdownConverter
from src.parsers.hwp_loader import HWPMarkdownConverter
from src.graph.state import OrgInfo
from src.retrievers.embeddings import EmbeddingGenerator


class VectorStore:
    """마크다운 문서를 저장하고 검색하는 벡터 저장소 클래스."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from src.utils.config import get_default_db_path
            db_path = get_default_db_path()

        self.db_path = db_path
        self.embedding_generator = EmbeddingGenerator(api_key=OPENAI_API_KEY)
        backend = "openai" if self.embedding_generator.use_openai else "local"
        collection_name = f"rfp_docs_v17_{backend}"
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        self.count = self.collection.count()
        self.org_registry: dict[str, OrgInfo] = {}
        self.last_search_results: list[dict[str, Any]] = []

        # 변환기 초기화
        self.csv_converter = CSVMarkdownConverter()
        self.pdf_converter = PDFMarkdownConverter()
        self.hwp_converter = HWPMarkdownConverter()

    @staticmethod
    def _normalize_metadata_value(value: Any) -> str | int | float | bool | None:
        """Chroma 메타데이터로 저장 가능한 타입으로 정규화합니다."""
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    def add_documents(self, chunks: list[dict[str, Any]]) -> None:
        """문서 청크를 추가합니다."""
        if not chunks:
            return

        texts = [self._clip_for_embedding(str(c.get("text", ""))) for c in chunks]
        ids = [self._build_chunk_id(c) for c in chunks]
        metadatas = []
        for chunk in chunks:
            metadata: dict[str, Any] = {
                "source": chunk.get("source", ""),
                "org": chunk.get("org", ""),
                "type": chunk.get("type", "unknown"),
            }

            for key in ("page", "table_count", "has_table", "section"):
                if key in chunk:
                    metadata[key] = chunk.get(key)

            extra = chunk.get("metadata")
            if isinstance(extra, dict):
                for key, value in extra.items():
                    metadata[key] = value

            normalized = {}
            for key, value in metadata.items():
                clean = self._normalize_metadata_value(value)
                if clean is not None:
                    normalized[key] = clean
            metadatas.append(normalized)

        vectors = self._create_embeddings(texts)
        # upsert를 사용해 재인덱싱 시 동일 ID 충돌 없이 갱신되게 처리
        self.collection.upsert(documents=texts, embeddings=vectors, ids=ids, metadatas=metadatas)
        self.count = self.collection.count()

    @staticmethod
    def _clip_for_embedding(text: str, max_chars: int = 2500) -> str:
        """임베딩 요청 한도를 초과하지 않도록 긴 텍스트를 자릅니다."""
        cleaned = text.strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars]

    @staticmethod
    def _build_chunk_id(chunk: dict[str, Any]) -> str:
        """청크 내용/출처 기반의 안정적인 ID를 생성합니다."""
        basis = "|".join(
            [
                str(chunk.get("source", "")),
                str(chunk.get("org", "")),
                str(chunk.get("type", "")),
                str(chunk.get("page", "")),
                str(chunk.get("section", "")),
                str(chunk.get("text", "")),
            ]
        )
        digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]
        return f"chunk_{digest}"

    def _create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """텍스트 임베딩을 생성합니다."""
        return self.embedding_generator.embed_texts(texts)

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

    def search(
        self,
        query: str,
        top_k: int = 10,
        org_name: str | None = None,
        doc_types: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """문서를 검색합니다."""
        query_embedding = self._create_query_embedding(query)
        filters: list[dict[str, Any]] = []
        if org_name:
            filters.append({"org": org_name})
        if doc_types:
            filters.append({"type": {"$in": doc_types}})

        where: dict[str, Any] | None = None
        if len(filters) == 1:
            where = filters[0]
        elif len(filters) > 1:
            where = {"$and": filters}

        try:
            kwargs: dict[str, Any] = {
                "query_embeddings": [query_embedding],
                "n_results": top_k,
            }
            if where is not None:
                kwargs["where"] = where
            response = self.collection.query(**kwargs)
            results = self._parse_search_results(response)
            self.last_search_results = results  # 검색 결과 저장
            return results
        except Exception as e:
            print(f"검색 오류: {e}")
            return []

    def count_chunks_by_type(self) -> dict[str, int]:
        """청크 타입별 개수를 반환합니다."""
        if self.count == 0:
            return {}
        data = self.collection.get(include=["metadatas"])
        counts: dict[str, int] = {}
        for md in data.get("metadatas", []):
            t = (md or {}).get("type", "unknown")
            counts[t] = counts.get(t, 0) + 1
        return counts

    def _create_query_embedding(self, query: str) -> list[float]:
        """쿼리 임베딩을 생성합니다."""
        return self.embedding_generator.embed_query(query)

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
