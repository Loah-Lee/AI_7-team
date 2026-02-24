#!/usr/bin/env python3
"""입찰메이트 v17 - 벡터 저장소."""

from __future__ import annotations

import sys
import hashlib
import math
import re
from pathlib import Path
from typing import Any

import chromadb

# 설정
sys.path.insert(0, 'src')
from src.utils.config import (
    HYBRID_LEXICAL_MIN_HITS,
    HYBRID_LEXICAL_PREFILTER_K,
    HYBRID_RERANK_TOP_MULTIPLIER,
    KEYWORD_SCAN_LIMIT,
    OPENAI_API_KEY,
    ORG_ALIASES,
)

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
        try:
            self.count = self.collection.count()
        except Exception as exc:
            # 손상된 세그먼트(hnsw writer)로 count 조회가 실패하면 컬렉션을 재생성한다.
            print(
                f"⚠️ Chroma 컬렉션 상태 오류 감지, '{collection_name}' 컬렉션을 재생성합니다: {exc}"
            )
            try:
                self.client.delete_collection(collection_name)
            except Exception:
                pass
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            self.count = self.collection.count()
        self.org_registry: dict[str, OrgInfo] = {}
        self.last_search_results: list[dict[str, Any]] = []
        self.last_hybrid_stats: dict[str, Any] = {
            "semantic_count": 0,
            "keyword_count": 0,
            "keyword_used": False,
            "keyword_reason": "",
            "lexical_prefilter_k": 0,
            "reranked_count": 0,
            "fallback_used": False,
        }

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

    @staticmethod
    def _normalize_sequence(value: Any) -> list[Any]:
        """Chroma 응답 필드를 list 형태로 정규화합니다."""
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if hasattr(value, "tolist"):
            try:
                converted = value.tolist()
            except Exception:
                converted = None
            if isinstance(converted, list):
                return converted
            if converted is not None:
                return [converted]
        if isinstance(value, str):
            return [value]
        try:
            return list(value)
        except TypeError:
            return [value]

    @staticmethod
    def _normalize_vector(value: Any) -> list[float] | None:
        """벡터 값을 list[float] 형태로 정규화합니다."""
        if value is None:
            return None
        raw = VectorStore._normalize_sequence(value)
        if not raw:
            return None
        try:
            return [float(item) for item in raw]
        except Exception:
            return None

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

    def search_keyword(
        self,
        query: str,
        top_k: int = 10,
        org_name: str | None = None,
        doc_types: list[str] | None = None,
        scan_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """간단한 키워드 중첩 기반 검색(벡터 보조용)."""
        q_tokens = self._keyword_tokens(query)
        if not q_tokens or top_k <= 0:
            return []

        where = self._build_where_filter(org_name=org_name, doc_types=doc_types)
        effective_scan_limit = scan_limit if scan_limit and scan_limit > 0 else min(
            KEYWORD_SCAN_LIMIT,
            max(top_k * 12, 200),
        )

        try:
            kwargs: dict[str, Any] = {"include": ["documents", "metadatas"]}
            if where is not None:
                kwargs["where"] = where
            kwargs["limit"] = effective_scan_limit
            data = self.collection.get(**kwargs)
        except Exception:
            return []

        ids = self._normalize_sequence(data.get("ids"))
        docs = self._normalize_sequence(data.get("documents"))
        metas = self._normalize_sequence(data.get("metadatas"))
        scored: list[dict[str, Any]] = []
        for idx, doc in enumerate(docs):
            text = str(doc or "")
            lowered = text.lower()
            normalized = re.sub(r"[^0-9a-zA-Z가-힣]+", "", lowered)
            overlap = sum(1 for token in q_tokens if token in lowered or token in normalized)
            if overlap <= 0:
                continue
            metadata = metas[idx] if idx < len(metas) else {}
            lexical_score = float(overlap) / float(max(len(q_tokens), 1))
            scored.append(
                {
                    "id": str(ids[idx]) if idx < len(ids) else "",
                    "text": text,
                    "metadata": metadata or {},
                    "score": float(overlap),
                    "lexical_score": lexical_score,
                }
            )

        scored.sort(
            key=lambda x: (x.get("lexical_score", 0.0), x.get("score", 0.0)),
            reverse=True,
        )
        return scored[:top_k]

    @staticmethod
    def _keyword_tokens(query: str) -> list[str]:
        raw = (query or "").lower()
        tokens = re.findall(r"[0-9a-zA-Z가-힣]{2,}", raw)
        req_codes = re.findall(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", raw, flags=re.IGNORECASE)
        stopwords = {
            "무엇", "무엇인가", "무엇인가요", "알려줘", "알려주세요", "해주세요", "관련",
            "문서", "질문", "기준", "각각", "비교", "그리고", "또한", "있나요", "있습니까",
        }
        output: list[str] = []
        for token in tokens:
            if token in stopwords:
                continue
            if token.isdigit() and len(token) <= 3:
                continue
            output.append(token)

        for code in req_codes:
            compact = re.sub(r"[^0-9a-zA-Z가-힣]+", "", code.lower())
            if compact:
                output.append(compact)
        return output

    def search_hybrid(
        self,
        query: str,
        top_k: int = 10,
        org_name: str | None = None,
        doc_types: list[str] | None = None,
        keyword_ratio: float = 0.5,
    ) -> list[dict[str, Any]]:
        """렉시컬 후보 추출 후 벡터 재정렬하는 하이브리드 검색."""
        if top_k <= 0:
            return []

        precision_query = self._is_precision_query(query)
        lexical_prefilter_k = min(
            HYBRID_LEXICAL_PREFILTER_K,
            max(top_k, top_k * HYBRID_RERANK_TOP_MULTIPLIER, HYBRID_LEXICAL_MIN_HITS),
        )
        lexical_scan_limit = min(KEYWORD_SCAN_LIMIT, max(lexical_prefilter_k * 12, 240))
        lexical = self.search_keyword(
            query,
            top_k=lexical_prefilter_k,
            org_name=org_name,
            doc_types=doc_types,
            scan_limit=lexical_scan_limit,
        )
        reranked = self._rerank_lexical_candidates(
            query,
            lexical,
            top_k=top_k,
            precision_query=precision_query,
        )

        semantic: list[dict[str, Any]] = []
        keyword_reason = "lexical_prefilter"
        lexical_hits = len(lexical)
        max_lexical = max((float(item.get("lexical_score", 0.0)) for item in lexical), default=0.0)
        lexical_weak = lexical_hits < HYBRID_LEXICAL_MIN_HITS or (
            max_lexical < 0.2 and not precision_query
        )

        if lexical_weak:
            keyword_reason = "lexical_weak" if lexical else "lexical_empty"
            semantic_k = max(top_k, min(top_k * 2, top_k + 12))
            semantic = self.search(
                query,
                top_k=semantic_k,
                org_name=org_name,
                doc_types=doc_types,
            )
            if precision_query and reranked:
                merged = self._merge_dedup_results([reranked, semantic], top_k=top_k)
                keyword_reason = "precision_boost_with_semantic_fallback"
            else:
                merged = self._merge_dedup_results([semantic, reranked], top_k=top_k)
        else:
            merged = reranked[:top_k]
            if len(merged) < top_k:
                semantic = self.search(
                    query,
                    top_k=max(top_k, top_k + 4),
                    org_name=org_name,
                    doc_types=doc_types,
                )
                merged = self._merge_dedup_results([merged, semantic], top_k=top_k)
                keyword_reason = "semantic_fill"

        self.last_hybrid_stats = {
            "semantic_count": len(semantic),
            "keyword_count": lexical_hits,
            "keyword_used": bool(lexical),
            "keyword_reason": keyword_reason,
            "lexical_prefilter_k": lexical_prefilter_k,
            "reranked_count": len(reranked),
            "fallback_used": bool(semantic),
        }
        self.last_search_results = merged
        return merged

    @staticmethod
    def _build_where_filter(
        org_name: str | None = None,
        doc_types: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """기관/문서타입 필터를 Chroma where 형식으로 구성합니다."""
        filters: list[dict[str, Any]] = []
        if org_name:
            filters.append({"org": org_name})
        if doc_types:
            filters.append({"type": {"$in": doc_types}})
        if len(filters) == 1:
            return filters[0]
        if len(filters) > 1:
            return {"$and": filters}
        return None

    @staticmethod
    def _result_dedup_key(item: dict[str, Any]) -> tuple[str, str, int | None, str, str]:
        md = item.get("metadata", {}) or {}
        return (
            str(md.get("source", "")),
            str(md.get("org", "")),
            md.get("page"),
            str(md.get("type", "")),
            str(md.get("section", "")),
        )

    def _merge_dedup_results(self, groups: list[list[dict[str, Any]]], top_k: int) -> list[dict[str, Any]]:
        """우선순위 순서대로 결과를 병합하되 문서 중복을 제거합니다."""
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int | None, str, str]] = set()
        for group in groups:
            for item in group:
                key = self._result_dedup_key(item)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= top_k:
                    return merged
        return merged

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """두 벡터의 cosine similarity를 계산합니다."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for a, b in zip(vec_a, vec_b):
            dot += float(a) * float(b)
            norm_a += float(a) * float(a)
            norm_b += float(b) * float(b)
        if norm_a <= 0.0 or norm_b <= 0.0:
            return 0.0
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

    def _fetch_candidates_by_ids(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """후보 ID 목록의 문서/메타/임베딩을 조회합니다."""
        if not ids:
            return {}
        try:
            response = self.collection.get(
                ids=ids,
                include=["documents", "metadatas", "embeddings"],
            )
        except Exception:
            return {}

        fetched_ids = self._normalize_sequence(response.get("ids"))
        documents = self._normalize_sequence(response.get("documents"))
        metadatas = self._normalize_sequence(response.get("metadatas"))
        embeddings = self._normalize_sequence(response.get("embeddings"))
        output: dict[str, dict[str, Any]] = {}
        for idx, doc_id in enumerate(fetched_ids):
            key = str(doc_id)
            metadata = metadatas[idx] if idx < len(metadatas) else {}
            if not isinstance(metadata, dict):
                metadata = {}
            output[key] = {
                "text": str(documents[idx]) if idx < len(documents) else "",
                "metadata": metadata,
                "embedding": self._normalize_vector(embeddings[idx] if idx < len(embeddings) else None),
            }
        return output

    def _rerank_lexical_candidates(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int,
        precision_query: bool,
    ) -> list[dict[str, Any]]:
        """렉시컬 후보를 벡터 유사도로 재정렬합니다."""
        if not candidates or top_k <= 0:
            return []

        query_embedding: list[float] = []
        try:
            query_embedding = self._create_query_embedding(query)
        except Exception:
            query_embedding = []

        candidate_ids = [str(item.get("id", "")).strip() for item in candidates if str(item.get("id", "")).strip()]
        candidate_payload = self._fetch_candidates_by_ids(candidate_ids)
        max_lex = max((float(item.get("lexical_score", 0.0)) for item in candidates), default=1.0)
        if max_lex <= 0.0:
            max_lex = 1.0

        reranked: list[dict[str, Any]] = []
        for item in candidates:
            candidate_id = str(item.get("id", "")).strip()
            payload = candidate_payload.get(candidate_id, {})
            payload_text = payload.get("text")
            if payload_text is None:
                payload_text = item.get("text", "")
            doc_text = str(payload_text)
            metadata = payload.get("metadata")
            if not isinstance(metadata, dict):
                metadata = item.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            lexical_score = float(item.get("lexical_score", 0.0))
            lexical_norm = lexical_score / max_lex if max_lex > 0 else lexical_score

            vector_norm = 0.0
            embedding = self._normalize_vector(payload.get("embedding"))
            if query_embedding and embedding:
                cosine = self._cosine_similarity(query_embedding, embedding)
                vector_norm = max(0.0, min(1.0, (cosine + 1.0) / 2.0))

            if precision_query:
                final_score = (lexical_norm * 0.65) + (vector_norm * 0.35)
            else:
                final_score = (lexical_norm * 0.35) + (vector_norm * 0.65)

            reranked.append(
                {
                    "id": candidate_id,
                    "text": doc_text,
                    "metadata": metadata,
                    "score": final_score,
                    "lexical_score": lexical_score,
                    "vector_score": vector_norm,
                }
            )

        reranked.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return reranked[:top_k]

    @staticmethod
    def _is_precision_query(query: str) -> bool:
        """요구사항 코드/문자셋/평가 기준 등 정밀 키워드 질의 여부를 판단합니다."""
        q = (query or "").lower()
        if re.search(r"[a-z]{2,5}\s*[-_ ]?\s*\d{2,3}", q, flags=re.IGNORECASE):
            return True
        precision_tokens = ["utf", "charset", "문자셋", "인코딩", "협상", "배점", "적격", "평가"]
        return any(token in q for token in precision_tokens)

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

    def get_indexed_sources(self, doc_types: list[str] | None = None) -> set[str]:
        """특정 문서 타입으로 인덱싱된 source 파일명 집합을 반환합니다."""
        if self.count == 0:
            return set()

        kwargs: dict[str, Any] = {"include": ["metadatas"]}
        if doc_types:
            normalized = [str(doc_type).lower() for doc_type in doc_types if doc_type]
            if not normalized:
                return set()
            if len(normalized) == 1:
                kwargs["where"] = {"type": normalized[0]}
            else:
                kwargs["where"] = {"type": {"$in": normalized}}

        data = self.collection.get(**kwargs)
        sources: set[str] = set()
        for md in data.get("metadatas", []):
            source = str((md or {}).get("source", "")).strip()
            if source:
                sources.add(source)
        return sources

    def collect_org_stats(self) -> dict[str, dict[str, bool]]:
        """컬렉션 메타데이터에서 기관별 문서 타입 존재 여부를 집계합니다."""
        if self.count == 0:
            return {}
        data = self.collection.get(include=["metadatas"])
        stats: dict[str, dict[str, bool]] = {}
        for md in data.get("metadatas", []):
            meta = md or {}
            org = str(meta.get("org", "")).strip()
            if not org:
                continue
            item = stats.setdefault(org, {"has_pdf": False, "has_hwp": False})
            doc_type = str(meta.get("type", "")).lower()
            if doc_type == "pdf":
                item["has_pdf"] = True
            if doc_type == "hwp":
                item["has_hwp"] = True
        return stats

    def _create_query_embedding(self, query: str) -> list[float]:
        """쿼리 임베딩을 생성합니다."""
        return self.embedding_generator.embed_query(query)

    def _parse_search_results(self, response: dict) -> list[dict[str, Any]]:
        """검색 응답을 파싱합니다."""
        results = []
        if response['documents'] and response['documents'][0]:
            for i, doc in enumerate(response['documents'][0]):
                score: float | None = None
                if response.get("distances") and response["distances"][0]:
                    try:
                        distance = float(response["distances"][0][i])
                        score = 1.0 - distance
                    except (TypeError, ValueError, IndexError):
                        score = None
                results.append({
                    'text': doc,
                    'metadata': response['metadatas'][0][i] if response.get('metadatas') else {},
                    'score': score,
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
