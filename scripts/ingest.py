"""RFP 문서 인덱싱 스크립트.

data/files/ 내의 원본 PDF/HWP 파일을 직접 파싱하여 Chroma DB에 저장한다.
CSV/XLSX는 사용하지 않는다 — Source of Truth는 원본 파일뿐이다.

실행: uv run python scripts/ingest.py
      uv run python scripts/ingest.py --reset   (DB 초기화 후 재인덱싱)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from langchain_core.documents import Document

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.parsers.chunker import chunk_documents
from src.parsers.hwp_loader import load_hwp
from src.parsers.pdf_loader import load_pdf
from src.parsers.text_cleaner import clean_documents
from src.retrievers.embeddings import get_embeddings
from src.utils.config import load_config


def load_all_files(files_dir: str | Path) -> list[Document]:
    """data/files/ 디렉토리의 PDF/HWP 파일을 파싱하여 Document 리스트로 반환한다."""
    files_dir = Path(files_dir)
    if not files_dir.exists():
        print(f"  [ERROR] 디렉토리가 없습니다: {files_dir}")
        return []

    pdf_files = sorted(files_dir.glob("*.pdf"))
    hwp_files = sorted(files_dir.glob("*.hwp"))

    print(f"       발견: PDF {len(pdf_files)}개, HWP {len(hwp_files)}개")

    documents: list[Document] = []

    # PDF 파싱
    for pdf_path in pdf_files:
        try:
            docs = load_pdf(pdf_path)
            documents.extend(docs)
            print(f"       ✓ [PDF] {pdf_path.name} → {len(docs)}페이지")
        except Exception as e:
            print(f"       ✗ [PDF] {pdf_path.name} → 실패: {e}")

    # HWP 파싱
    for hwp_path in hwp_files:
        try:
            docs = load_hwp(hwp_path)
            total_chars = sum(len(d.page_content) for d in docs)
            documents.extend(docs)
            print(f"       ✓ [HWP] {hwp_path.name} → {total_chars:,}자")
        except Exception as e:
            print(f"       ✗ [HWP] {hwp_path.name} → 실패: {e}")

    return documents


def reset_db(persist_dir: str) -> None:
    """ChromaDB 디렉토리를 완전히 삭제한다."""
    path = Path(persist_dir)
    if path.exists():
        shutil.rmtree(path)
        print(f"       DB 삭제 완료: {persist_dir}")
    else:
        print(f"       DB 디렉토리 없음 (스킵): {persist_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RFP 문서 인덱싱")
    parser.add_argument("--reset", action="store_true", help="DB 초기화 후 재인덱싱")
    args = parser.parse_args()

    config = load_config()
    vs_cfg = config.get("vectorstore", {})
    collection_name = vs_cfg.get("collection_name", "rfp_docs")
    persist_dir = str(
        Path(project_root / vs_cfg.get("persist_directory", "./chroma_db")).resolve()
    )

    start_time = time.time()

    # DB 리셋
    if args.reset:
        print("[0/4] DB 초기화 중...")
        reset_db(persist_dir)

    # 1) 원본 파일 파싱 (PDF + HWP)
    files_dir = project_root / "data" / "files"
    print(f"[1/4] 원본 파일 파싱: {files_dir}")
    all_documents = load_all_files(files_dir)
    print(f"       → 전체 {len(all_documents)}개 문서 로드 완료")

    if not all_documents:
        print("[ERROR] 로드된 문서가 없습니다. 종료합니다.")
        return

    # 1.5) 텍스트 클리닝
    print("[1.5/4] 텍스트 클리닝 중...")
    all_documents = clean_documents(all_documents)
    print(f"       → {len(all_documents)}개 문서 클리닝 완료")

    # 2) 청킹
    print("[2/4] 청킹 중...")
    chunks = chunk_documents(all_documents)
    print(f"       → {len(chunks)}개 청크 생성 완료")

    # 3) 임베딩 + Chroma DB 저장
    print("[3/4] 임베딩 생성 및 Chroma DB 저장 중...")
    print(f"       collection: {collection_name}")
    print(f"       persist_dir: {persist_dir}")

    embeddings = get_embeddings()

    from langchain_chroma import Chroma

    vectorstore = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )

    # 기존 컬렉션 비우기 (--reset이 아닌 경우)
    if not args.reset:
        existing = vectorstore._collection.count()
        if existing > 0:
            print(f"       기존 {existing}개 문서 삭제 중...")
            all_ids = vectorstore._collection.get()["ids"]
            if all_ids:
                vectorstore._collection.delete(ids=all_ids)

    # 배치 단위로 추가 (OpenAI 임베딩 rate limit 대응)
    batch_size = 50
    total = len(chunks)
    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        vectorstore.add_documents(batch)
        done = min(i + batch_size, total)
        print(f"       → {done}/{total} 청크 인덱싱 완료")

    elapsed = time.time() - start_time
    final_count = vectorstore._collection.count()
    print(f"[4/4] 인덱싱 완료! Chroma DB에 {final_count}개 문서 저장됨")
    print(f"       저장 위치: {persist_dir}")
    print(f"       소요 시간: {elapsed:.1f}초")


if __name__ == "__main__":
    main()
