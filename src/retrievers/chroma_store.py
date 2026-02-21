from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

from .vectorstore import (
    OpenAIEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    VectorStore,
)


def _has_openai_api_key() -> bool:
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        pass
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _resolve_auto_model() -> str:
    return "text-embedding-3-small" if _has_openai_api_key() else "kosimcse"


def _lock_path(persist_dir: Path, collection_name: str) -> Path:
    return persist_dir / f"{collection_name}.embedding.lock.json"


def _read_locked_model(persist_dir: Path, collection_name: str) -> str | None:
    path = _lock_path(persist_dir, collection_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        model = str(data.get("model", "")).strip()
        return model or None
    except Exception:
        return None


def _write_locked_model(persist_dir: Path, collection_name: str, model: str) -> None:
    persist_dir.mkdir(parents=True, exist_ok=True)
    path = _lock_path(persist_dir, collection_name)
    payload = {"model": model}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_model_for_build(*, persist_dir: Path, collection_name: str, model: str) -> str:
    requested = (model or "auto").strip()
    resolved = _resolve_auto_model() if requested == "auto" else requested
    locked = _read_locked_model(persist_dir, collection_name)
    if locked and locked != resolved:
        raise RuntimeError(
            "이 컬렉션은 다른 임베딩 모델로 이미 고정되어 있습니다. "
            f"collection={collection_name}, locked_model={locked}, requested_model={resolved}. "
            "동일 모델을 사용하거나, 새 collection 이름을 쓰거나, 기존 lock/컬렉션을 삭제하세요."
        )
    return resolved


def _resolve_model_for_search(*, persist_dir: Path, collection_name: str, model: str) -> str:
    requested = (model or "auto").strip()
    locked = _read_locked_model(persist_dir, collection_name)
    if requested == "auto":
        if locked:
            return locked
        raise RuntimeError(
            "embedding lock 파일이 없어 auto를 안전하게 해석할 수 없습니다. "
            f"collection={collection_name}. "
            "--model을 명시하거나 인덱스를 다시 생성해 lock 파일을 만드세요."
        )
    if locked and requested != locked:
        raise RuntimeError(
            "검색 모델이 컬렉션 고정 모델과 다릅니다. "
            f"collection={collection_name}, locked_model={locked}, requested_model={requested}."
        )
    return requested


def _build_provider(model: str):
    if not model:
        model = "auto"
    if model == "auto":
        model = _resolve_auto_model()

    # 팀 표준: OpenAI 또는 KoSimCSE sentence-transformers 지원
    if model.startswith("sentence-transformers:"):
        st_model = model.split(":", 1)[1].strip() or "BM-K/KoSimCSE-roberta-multitask"
        return SentenceTransformerEmbeddingProvider(model=st_model)
    if model == "kosimcse":
        return SentenceTransformerEmbeddingProvider(model="BM-K/KoSimCSE-roberta-multitask")
    return OpenAIEmbeddingProvider(model=model)


def build_chroma_index(
    *,
    input_dir: Path,
    persist_dir: Path,
    collection_name: str = "rfp_b",
    model: str = "auto",
    batch_size: int = 128,
) -> int:
    resolved_model = _resolve_model_for_build(
        persist_dir=persist_dir, collection_name=collection_name, model=model
    )
    store = VectorStore(
        persist_dir=persist_dir,
        collection_name=collection_name,
        embedding_provider=_build_provider(resolved_model),
    )
    total = store.add_documents_from_jsonl_dir(input_dir=input_dir, batch_size=batch_size)
    _write_locked_model(persist_dir, collection_name, resolved_model)
    print(
        f"INGEST OK | chroma_index | {input_dir} -> {persist_dir} | collection={collection_name} | model={resolved_model} | chunks={total}"
    )
    return total


def search_chroma(
    *,
    query: str,
    persist_dir: Path,
    collection_name: str = "rfp_b",
    model: str = "auto",
    top_k: int = 5,
    fetch_k: int | None = None,
    org: str | None = None,
    doc_type: str | None = None,
    source: str | None = None,
) -> List[Dict[str, object]]:
    resolved_model = _resolve_model_for_search(
        persist_dir=persist_dir, collection_name=collection_name, model=model
    )
    store = VectorStore(
        persist_dir=persist_dir,
        collection_name=collection_name,
        embedding_provider=_build_provider(resolved_model),
    )
    results = store.search(
        query,
        top_k=top_k,
        fetch_k=fetch_k,
        org=org,
        source=source,
        doc_type=doc_type,
    )
    return [
        {
            "chunk_id": str(r.metadata.get("chunk_id", "")),
            "source_path": str(r.metadata.get("source_path", r.metadata.get("source", ""))),
            "source": str(r.metadata.get("source", "")),
            "org": str(r.metadata.get("org", "")),
            "type": str(r.metadata.get("type", "")),
            "chunk_index": r.metadata.get("chunk_index", ""),
            "score": float(r.score),
            "text": r.text,
        }
        for r in results
    ]
