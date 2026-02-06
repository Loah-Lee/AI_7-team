"""벡터스토어 관리."""

from __future__ import annotations

from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.retrievers.embeddings import get_embeddings
from src.utils.config import load_config


def get_vectorstore(
    collection_name: str | None = None,
    persist_directory: str | None = None,
) -> Chroma:
    """기존 Chroma 벡터스토어를 로드한다.

    Args:
        collection_name: 컬렉션 이름. None이면 설정 파일 값 사용.
        persist_directory: 영속 디렉토리. None이면 설정 파일 값 사용.

    Returns:
        Chroma 인스턴스.
    """
    config = load_config()
    vs_cfg = config.get("vectorstore", {})

    if collection_name is None:
        collection_name = vs_cfg.get("collection_name", "rfp_docs")
    if persist_directory is None:
        persist_directory = vs_cfg.get("persist_directory", "./chroma_db")

    return Chroma(
        collection_name=collection_name,
        embedding_function=get_embeddings(),
        persist_directory=str(Path(persist_directory).resolve()),
    )


def get_unique_institutions() -> list[str]:
    """Chroma DB에서 중복 없는 기관명 리스트를 반환한다."""
    vs = get_vectorstore()
    col = vs._collection
    if col.count() == 0:
        return []
    all_meta = col.get(include=["metadatas"])
    institutions = set()
    for m in all_meta["metadatas"]:
        if m and "institution" in m:
            inst = m["institution"]
            if inst:
                institutions.add(inst)
    return sorted(institutions)


def build_vectorstore(
    documents: list[Document],
    collection_name: str | None = None,
    persist_directory: str | None = None,
) -> Chroma:
    """문서로부터 Chroma 벡터스토어를 빌드한다.

    Args:
        documents: 청킹된 Document 리스트.
        collection_name: 컬렉션 이름.
        persist_directory: 영속 디렉토리.

    Returns:
        빌드된 Chroma 인스턴스.
    """
    config = load_config()
    vs_cfg = config.get("vectorstore", {})

    if collection_name is None:
        collection_name = vs_cfg.get("collection_name", "rfp_docs")
    if persist_directory is None:
        persist_directory = vs_cfg.get("persist_directory", "./chroma_db")

    return Chroma.from_documents(
        documents=documents,
        embedding=get_embeddings(),
        collection_name=collection_name,
        persist_directory=str(Path(persist_directory).resolve()),
    )
