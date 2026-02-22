from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import numpy as np

_ORG_ALIASES = {
    # main 브랜치 ORG_ALIASES 취지를 반영한 최소 별칭
    "한국농어촌공사": "한국농어촌공사",
    "농어촌공사": "한국농어촌공사",
    "krc": "한국농어촌공사",
    "고려대학교": "고려대학교",
    "고려대": "고려대학교",
}


def _iter_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    denom = np.linalg.norm(vec)
    if denom == 0:
        return vec
    return vec / denom


def _extract_org_from_source(source_path: str) -> str:
    s = unicodedata.normalize("NFC", source_path or "")
    # 파일명 prefix를 기관명으로 가정: "기관_문서명.md"
    if "_" in s:
        return s.split("_", 1)[0].strip()
    return ""


def _normalize_text_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").strip()


def _normalize_org_name(text: str) -> str:
    s = _normalize_text_nfc(text)
    if not s:
        return ""

    s = s.replace("(주)", "").replace("주식회사", "").strip()
    s_compact = re.sub(r"\s+", "", s).lower()
    for alias, canonical in _ORG_ALIASES.items():
        if re.sub(r"\s+", "", alias).lower() == s_compact:
            return canonical
    return s


def _extract_doc_type(text: str, metadata: Dict[str, object] | None) -> str:
    m = metadata or {}
    meta = m.get("meta") if isinstance(m.get("meta"), dict) else {}
    file_type = str(meta.get("파일형식", "")).strip().lower() if isinstance(meta, dict) else ""
    if file_type:
        return file_type
    t = text.lower()
    if "제안요청서" in t:
        return "rfp"
    if "입찰" in t:
        return "bid"
    return "doc"


class EmbeddingProvider:
    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> List[float]:
        raise NotImplementedError


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self.model = model
        from .dense_openai import _get_client

        self._client = _get_client()

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(model=self.model, input=list(texts))
        data = getattr(response, "data", []) or []
        out: List[List[float]] = []
        for item in data:
            vec = np.array(item.embedding, dtype=np.float32)
            out.append(_l2_normalize(vec).tolist())
        return out

    def embed_query(self, text: str) -> List[float]:
        embs = self.embed_documents([text])
        return embs[0] if embs else []

@dataclass(frozen=True)
class SearchResult:
    id: str
    text: str
    score: float
    metadata: Dict[str, object]


class VectorStore:
    def __init__(
        self,
        *,
        persist_dir: Path,
        collection_name: str = "rfp_b_oai",
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        try:
            import chromadb  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("chromadb가 설치되지 않았습니다. pip install chromadb") from exc

        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._embedder = embedding_provider or OpenAIEmbeddingProvider()

    def add_documents(self, docs: Sequence[Dict[str, object]], batch_size: int = 128) -> int:
        ids: List[str] = []
        texts: List[str] = []
        metas: List[Dict[str, object]] = []
        seen: set[str] = set()
        total = 0

        def flush() -> None:
            nonlocal ids, texts, metas, total
            if not ids:
                return
            embs = self._embedder.embed_documents(texts)
            try:
                self._collection.upsert(ids=ids, documents=texts, metadatas=metas, embeddings=embs)
            except Exception as exc:
                msg = str(exc)
                if "dimension" in msg.lower():
                    cur_dim = len(embs[0]) if embs else -1
                    raise RuntimeError(
                        "Chroma 컬렉션 임베딩 차원이 기존 인덱스와 다릅니다. "
                        f"collection={self.collection_name}, current_dim={cur_dim}. "
                        "기존 컬렉션을 삭제하거나(또는 persist-dir 변경) 다른 collection 이름을 사용하세요."
                    ) from exc
                raise
            total += len(ids)
            ids, texts, metas = [], [], []

        for d in docs:
            source_path = _normalize_text_nfc(str(d.get("source_path", "")))
            text = str(d.get("text", "")).strip()
            chunk_id = str(d.get("chunk_id", "")).strip()
            chunk_index = int(d.get("chunk_index", -1))
            metadata = d.get("metadata") if isinstance(d.get("metadata"), dict) else None
            if not source_path or not text or chunk_index < 0:
                continue

            rid = str(d.get("id", "")).strip() or hashlib.sha1(
                f"{source_path}::{chunk_index}::{chunk_id}".encode("utf-8")
            ).hexdigest()
            if rid in seen:
                continue
            seen.add(rid)

            org = _normalize_org_name(str(d.get("org", ""))) or _normalize_org_name(
                _extract_org_from_source(source_path)
            )
            doc_type = str(d.get("type", "")).strip() or _extract_doc_type(text, metadata)
            meta = {
                "source": source_path,
                "source_path": source_path,
                "org": org,
                "type": doc_type,
                "chunk_index": chunk_index,
                "chunk_id": chunk_id,
            }

            ids.append(rid)
            texts.append(text)
            metas.append(meta)

            if len(ids) >= batch_size:
                flush()

        flush()
        return total

    def add_documents_from_jsonl_dir(self, input_dir: Path, batch_size: int = 128) -> int:
        docs: List[Dict[str, object]] = []
        for path in sorted(input_dir.rglob("*.jsonl")):
            for row in _iter_jsonl(path):
                docs.append(
                    {
                        "source_path": str(row.get("source_path", "")),
                        "text": str(row.get("text", "")),
                        "chunk_id": str(row.get("chunk_id", "")),
                        "chunk_index": int(row.get("chunk_index", -1)),
                        "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else None,
                    }
                )
        return self.add_documents(docs, batch_size=batch_size)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        fetch_k: int | None = None,
        org: str | None = None,
        source: str | None = None,
        doc_type: str | None = None,
    ) -> List[SearchResult]:
        q = _normalize_text_nfc(query)
        if not q:
            return []

        org = _normalize_org_name(org or "") or None
        source = _normalize_text_nfc(source or "") or None
        doc_type = _normalize_text_nfc(doc_type or "") or None

        qvec = self._embedder.embed_query(q)
        where: Dict[str, object] | None = None
        where_terms: Dict[str, object] = {}
        if org:
            where_terms["org"] = org
        if source:
            where_terms["source"] = source
        if doc_type:
            where_terms["type"] = doc_type
        if where_terms:
            where = where_terms

        n_results = max(top_k * 5, top_k)
        if fetch_k is not None:
            try:
                n_results = max(n_results, int(fetch_k))
            except Exception:
                pass

        try:
            out = self._collection.query(
                query_embeddings=[qvec],
                n_results=n_results,
                where=where,
            )
        except Exception as exc:
            msg = str(exc)
            if "dimension" in msg.lower():
                raise RuntimeError(
                    "Chroma 검색 임베딩 차원이 컬렉션과 다릅니다. "
                    f"collection={self.collection_name}. "
                    "인덱싱과 동일한 임베딩 provider/model을 사용했는지 확인하세요."
                ) from exc
            raise
        ids = (out.get("ids") or [[]])[0]
        docs = (out.get("documents") or [[]])[0]
        metas = (out.get("metadatas") or [[]])[0]
        dists = (out.get("distances") or [[]])[0]

        results: List[SearchResult] = []
        for rid, doc, meta, dist in zip(ids, docs, metas, dists):
            m = meta if isinstance(meta, dict) else {}
            m_org = _normalize_org_name(str(m.get("org", "")))
            m_source = _normalize_text_nfc(str(m.get("source", "")))
            m_type = _normalize_text_nfc(str(m.get("type", "")))
            # where 필터가 적용되어도 안정성을 위해 재검증
            if org and m_org != org:
                continue
            if source and m_source != source:
                continue
            if doc_type and m_type != doc_type:
                continue
            results.append(
                SearchResult(
                    id=str(rid),
                    text=str(doc),
                    score=1.0 - float(dist),
                    metadata=m,
                )
            )
            if len(results) >= top_k:
                break
        return results

    def get_ranking(
        self,
        query: str,
        *,
        top_k: int = 20,
        org_registry: Dict[str, Dict[str, object]] | None = None,
    ) -> List[Dict[str, object]]:
        results = self.search(query, top_k=top_k)
        counts: Dict[str, int] = {}
        for r in results:
            org = str(r.metadata.get("org", "")).strip()
            if org:
                counts[org] = counts.get(org, 0) + 1

        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        out: List[Dict[str, object]] = []
        for org, cnt in ranked:
            extra = (org_registry or {}).get(org, {})
            out.append({"org": org, "hits": cnt, **extra})
        return out
