#!/usr/bin/env python3
"""입찰메이트 v17 - 벡터 저장소."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI

# 설정
sys.path.insert(0, 'src')
from src.utils.config import (
    CHROMA_COLLECTION,
    CHUNK_HASH_MOD,
    EMBEDDING_MODEL,
    OPENAI_API_KEY,
    ORG_ALIASES,
    PROJECT_ROOT,
)

# 파서는 import 방식을 사용
from src.parsers.csv_loader import CSVMarkdownConverter
from src.graph.state import OrgInfo


_ORG_SUFFIX_RE = re.compile(
    r"(공사|공단|재단|재단법인|사단법인|법인|대학교|대학|병원|의료원|정보원|진흥원|연구원|협회|위원회|조직위원회|사무국|센터|서비스|은행|공항|학교)$"
)
_COMPLEX_QUERY_RE = re.compile(
    r"(비교|차이|각각|동시에|모두|종합|근거|영향|설명해|설명하시오|어떻게\s*다른|무엇이며|요구사항)"
)
_FACTOID_QUERY_RE = re.compile(
    r"(얼마|금액|예산|사업비|비율|퍼센트|마감|일자|날짜|언제|기간|개월|며칠|문의처|연락처|전화)"
)
_CLAUSE_CONNECTOR_RE = re.compile(r"(그리고|또한|및|또는|아울러|동시에)")
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


class VectorStore:
    """마크다운 문서를 저장하고 검색하는 벡터 저장소 클래스."""

    def __init__(self, db_path: str | None = None, collection_name: str | None = None) -> None:
        if db_path is None:
            from src.utils.config import get_default_db_path

            db_path = get_default_db_path()

        self.db_path = db_path
        self.collection_name = (collection_name or CHROMA_COLLECTION).strip() or "chunks"
        self.client = chromadb.PersistentClient(path=db_path)
        self._local_model = None
        self._sentence_transformer_ef = None
        hf_cache_root = Path(PROJECT_ROOT) / ".hf_cache"
        (hf_cache_root / "hub").mkdir(parents=True, exist_ok=True)
        (hf_cache_root / "sentence_transformers").mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(hf_cache_root))
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(hf_cache_root / "hub"))
        os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(hf_cache_root / "sentence_transformers"))
        try:
            self._sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL
            )
        except Exception:
            self._sentence_transformer_ef = None

        self.collection = self._init_collection()
        self.count = self.collection.count()
        self.org_registry: dict[str, OrgInfo] = {}
        self.last_search_results: list[dict[str, Any]] = []
        self.last_retrieval_mode: str = "chroma"

        # 변환기 초기화
        self.csv_converter = CSVMarkdownConverter()

    def _init_collection(self):
        if self._sentence_transformer_ef is not None:
            return self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self._sentence_transformer_ef,
                metadata={"hnsw:space": "cosine"},
            )
        return self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_documents(self, chunks: list[dict[str, str]]) -> None:
        """문서 청크를 추가합니다."""
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        ids = [f"chunk_{i}_{hash(c['text']) % CHUNK_HASH_MOD}" for i, c in enumerate(chunks)]
        metadatas: list[dict[str, Any]] = []
        for chunk in chunks:
            raw_source = str(chunk.get("source", "") or "")
            source = self._normalize_source_value(raw_source)
            source_ext = self._extract_source_ext(raw_source)
            doc_type = str(chunk.get("type", "unknown") or "unknown").strip().lower()

            metadata: dict[str, Any] = {
                "source": source,
                "org": chunk.get("org", ""),
                "type": doc_type,
            }
            if source_ext and "source_ext" not in metadata:
                metadata["source_ext"] = source_ext

            page_raw = chunk.get("page")
            try:
                page = int(page_raw) if page_raw is not None else None
            except Exception:
                page = None
            if page is not None and page > 0:
                metadata["page"] = page

            metadatas.append(metadata)

        if self._sentence_transformer_ef is not None:
            self.collection.add(documents=texts, ids=ids, metadatas=metadatas)
        else:
            vectors = self._create_embeddings(texts)
            self.collection.add(documents=texts, embeddings=vectors, ids=ids, metadatas=metadatas)
        self.count = self.collection.count()

    def _create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """텍스트 임베딩을 생성합니다."""
        use_openai = bool(OPENAI_API_KEY) and EMBEDDING_MODEL.startswith("text-embedding-")
        if use_openai:
            client = OpenAI(api_key=OPENAI_API_KEY)
            embeddings = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            return [e.embedding for e in embeddings.data]

        from sentence_transformers import SentenceTransformer

        if self._local_model is None:
            self._local_model = SentenceTransformer(EMBEDDING_MODEL)
        return self._local_model.encode(texts).tolist()

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

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 2}

    @staticmethod
    def _normalize_source(metadata: dict[str, Any]) -> str:
        if not isinstance(metadata, dict):
            return ""
        for key in ("source", "source_file", "파일명"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _normalize_source_value(value: str | None) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        parsed = Path(raw)
        base_name = parsed.name or raw
        suffix = Path(base_name).suffix.lower()
        if suffix in {".pdf", ".hwp", ".hwpx", ".csv"}:
            return Path(base_name).stem.strip()
        return base_name.strip()

    @staticmethod
    def _extract_source_ext(value: str | None) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        suffix = Path(raw).suffix.lower().lstrip(".")
        if suffix in {"pdf", "hwp", "hwpx", "csv"}:
            return suffix
        return ""

    @staticmethod
    def _extract_page(metadata: dict[str, Any]) -> int | None:
        if not isinstance(metadata, dict):
            return None
        for key in ("page", "page_start", "page_no"):
            value = metadata.get(key)
            try:
                page = int(value)
            except Exception:
                continue
            if page > 0:
                return page
        refs = metadata.get("page_refs")
        if isinstance(refs, list):
            for ref in refs:
                try:
                    page = int(ref)
                except Exception:
                    continue
                if page > 0:
                    return page
        return None

    @staticmethod
    def _dense_score(distance: float | int | None) -> float:
        try:
            d = float(distance)
        except Exception:
            d = 1.0
        if d < 0.0:
            d = 0.0
        return 1.0 / (1.0 + d)

    @classmethod
    def _lexical_score(cls, query: str, text: str, source: str) -> float:
        q_tokens = cls._tokens(query)
        if not q_tokens:
            return 0.0
        t_tokens = cls._tokens(text)
        s_tokens = cls._tokens(source)
        if not t_tokens and not s_tokens:
            return 0.0
        overlap_text = len(q_tokens & t_tokens) / max(len(q_tokens), 1)
        overlap_source = len(q_tokens & s_tokens) / max(len(q_tokens), 1)
        return min(1.0, overlap_text + 0.3 * overlap_source)

    @staticmethod
    def count_unique_sources(results: list[dict[str, Any]]) -> int:
        return len({(r.get("source") or "").strip() for r in results if (r.get("source") or "").strip()})

    @staticmethod
    def _count_org_like_entities(query: str) -> int:
        q = (query or "").strip()
        if not q:
            return 0
        head = q.split("에서", 1)[0] if "에서" in q else q
        parts = re.split(r"\s+(?:과|와|및)\s+", head)
        cnt = 0
        for part in parts:
            token = re.sub(r"[\"'“”‘’\[\]{}()]", "", part).strip()
            if len(token) < 3:
                continue
            if _ORG_SUFFIX_RE.search(token) or token.startswith(
                ("한국", "국립", "국가", "재단법인", "사단법인", "(재)", "(사)")
            ):
                cnt += 1
        return cnt

    @classmethod
    def estimate_query_hardness(cls, query: str) -> int:
        q = (query or "").strip()
        if not q:
            return 0
        score = 0
        token_count = len(_TOKEN_RE.findall(q))
        if len(q) >= 80:
            score += 2
        elif len(q) >= 45:
            score += 1
        if token_count >= 16:
            score += 2
        elif token_count >= 10:
            score += 1
        if _COMPLEX_QUERY_RE.search(q):
            score += 2
        if len(_CLAUSE_CONNECTOR_RE.findall(q)) >= 2:
            score += 1
        if cls._count_org_like_entities(q) >= 2:
            score += 2
        if _FACTOID_QUERY_RE.search(q) and token_count <= 12 and not _COMPLEX_QUERY_RE.search(q):
            score -= 2
        return score

    @classmethod
    def select_dynamic_mode(cls, query: str, hard_threshold: int = 2) -> str:
        threshold = max(1, int(hard_threshold))
        return "chroma" if cls.estimate_query_hardness(query) >= threshold else "hybrid"

    def _query_candidates(self, query: str, n_results: int) -> list[dict[str, Any]]:
        response: dict[str, Any]
        try:
            response = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            query_embedding = self._create_embeddings([query])[0]
            response = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )

        docs = response.get("documents") or [[]]
        metas = response.get("metadatas") or [[]]
        dists = response.get("distances") or [[]]
        rows = []
        for i, doc in enumerate(docs[0] if docs and docs[0] else []):
            metadata = metas[0][i] if metas and metas[0] and i < len(metas[0]) else {}
            distance = dists[0][i] if dists and dists[0] and i < len(dists[0]) else None
            source = self._normalize_source(metadata)
            rows.append(
                {
                    "text": doc,
                    "metadata": metadata if isinstance(metadata, dict) else {},
                    "source": source,
                    "page": self._extract_page(metadata if isinstance(metadata, dict) else {}),
                    "distance": distance,
                }
            )
        return rows

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        mode: str = "chroma",
        hybrid_alpha: float = 0.6,
        dynamic_hard_threshold: int = 2,
        candidate_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """문서를 검색합니다.

        mode:
        - chroma: dense score only
        - hybrid: dense + lexical
        - dynamic: query 난이도에 따라 chroma/hybrid 선택
        """
        if top_k <= 0:
            return []

        selected_mode = (mode or "chroma").strip().lower()
        if selected_mode == "dynamic":
            selected_mode = self.select_dynamic_mode(query, hard_threshold=dynamic_hard_threshold)

        n_results = max(top_k, candidate_k or max(top_k * 4, 40))

        try:
            raw_rows = self._query_candidates(query, n_results=n_results)
        except Exception as e:
            print(f"검색 오류: {e}")
            return []

        alpha = max(0.0, min(1.0, float(hybrid_alpha)))
        ranked: list[dict[str, Any]] = []
        for row in raw_rows:
            dense = self._dense_score(row.get("distance"))
            lexical = self._lexical_score(query, row.get("text", ""), row.get("source", ""))
            score = dense if selected_mode == "chroma" else (alpha * dense + (1.0 - alpha) * lexical)
            ranked.append(
                {
                    "text": row.get("text", ""),
                    "metadata": row.get("metadata", {}),
                    "source": row.get("source", ""),
                    "page": row.get("page"),
                    "score": float(score),
                    "dense_score": float(dense),
                    "lexical_score": float(lexical),
                }
            )

        ranked.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        results = ranked[:top_k]
        self.last_search_results = results
        self.last_retrieval_mode = selected_mode
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
