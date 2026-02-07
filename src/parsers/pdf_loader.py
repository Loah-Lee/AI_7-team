"""PDF 문서 로더 (pymupdf4llm 기반 Markdown 변환 추출).

pymupdf4llm의 to_markdown(page_chunks=True)를 사용하여
테이블 구조를 Markdown 형식으로 보존한다.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from langchain_core.documents import Document


def load_pdf(file_path: str | Path) -> list[Document]:
    """PDF 파일을 로드하여 LangChain Document 리스트로 반환한다.

    pymupdf4llm을 사용하여 테이블을 Markdown 테이블로 변환하고,
    페이지별 Document를 생성한다.

    Args:
        file_path: PDF 파일 경로.

    Returns:
        페이지별 Document 리스트.
    """
    import pymupdf4llm

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    # page_chunks=True → 페이지별 dict 리스트 반환
    page_chunks = pymupdf4llm.to_markdown(
        str(file_path),
        page_chunks=True,
        show_progress=False,
    )

    source_name = unicodedata.normalize("NFC", file_path.name)
    documents: list[Document] = []

    for chunk in page_chunks:
        text = chunk["text"].strip()
        page_num = chunk["metadata"]["page"]  # pymupdf4llm은 1-indexed

        if not text:
            continue

        # pymupdf4llm 아티팩트 정리: 연속 빈 줄 축소
        text = re.sub(r"\n{3,}", "\n\n", text)

        documents.append(
            Document(
                page_content=text,
                metadata={
                    "source": source_name,
                    "file_type": "pdf",
                    "page": page_num,
                },
            )
        )

    return documents
