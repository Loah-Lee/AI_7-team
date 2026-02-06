"""문서 청킹 전략."""

from __future__ import annotations

import re

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.utils.config import load_config

# 섹션 제목 패턴: 숫자/로마자 등으로 시작하는 제목 라인
_SECTION_PATTERNS = [
    # "제1장 ...", "제1절 ...", "제1조 ..."
    re.compile(r"^(제\s*\d+\s*[장절조편항][\s.:]\s*.+)$", re.MULTILINE),
    # "1. ...", "1.1 ...", "1.1.1 ..."
    re.compile(r"^(\d+(?:\.\d+)*\.?\s+\S.+)$", re.MULTILINE),
    # "I. ...", "II. ...", "가. ...", "나. ..."
    re.compile(r"^([IVXivx]+\.\s+\S.+)$", re.MULTILINE),
    re.compile(r"^([가-힣]\.\s+\S.+)$", re.MULTILINE),
    # "[별표 1]", "[붙임 1]" 등 첨부 섹션
    re.compile(r"^(\[.+\]\s*.*)$", re.MULTILINE),
]


# TOC/표지 탐지 패턴
_TOC_DOT_PATTERN = re.compile(r"[·…]{3,}|\.{5,}")
_TOC_KW_PATTERN = re.compile(r"목\s*차|차\s*례|Table\s+of\s+Contents", re.IGNORECASE)


def _is_toc_chunk(text: str, page: int | None = None) -> bool:
    """청크가 목차 또는 표지인지 판별한다."""
    stripped = text.strip()

    # 짧은 표지 페이지 (page 1이고 300자 미만)
    if page == 1 and len(stripped) < 300:
        return True

    # 목차 키워드가 앞부분에 등장 (공백 무관하게 매칭)
    if _TOC_KW_PATTERN.search(stripped[:200]):
        return True

    # 점선(···) 패턴이 3회 이상 → 목차 특유의 항목···페이지번호 형태
    if len(_TOC_DOT_PATTERN.findall(stripped)) >= 3:
        return True

    return False


def _extract_section_title(text: str) -> str:
    """청크 텍스트에서 가장 처음 등장하는 섹션 제목을 추출한다."""
    for pattern in _SECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            title = match.group(1).strip()
            # 너무 긴 제목은 잘라서 반환
            if len(title) > 80:
                title = title[:80] + "…"
            return title
    return ""


def _extract_metadata_from_filename(source: str) -> dict[str, str]:
    """파일명에서 기관명과 사업명을 추출한다.

    파일명 패턴: '기관명_사업명.ext'
    예: '고려대학교_차세대 포털·학사 정보시스템 구축사업.pdf'
    → institution='고려대학교', project_name='차세대 포털·학사 정보시스템 구축사업'
    """
    # 확장자 제거
    name = source.rsplit(".", 1)[0] if "." in source else source

    # 첫 번째 _ 기준으로 분리
    if "_" in name:
        institution, project_name = name.split("_", 1)
        return {
            "institution": institution.strip(),
            "project_name": project_name.strip(),
        }
    return {}


def chunk_documents(
    documents: list[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    """문서 리스트를 청킹하여 반환한다.

    Args:
        documents: 원본 Document 리스트.
        chunk_size: 청크 크기. None이면 설정 파일 값 사용.
        chunk_overlap: 청크 오버랩. None이면 설정 파일 값 사용.

    Returns:
        청킹된 Document 리스트.
    """
    config = load_config()
    chunking_cfg = config.get("chunking", {})

    if chunk_size is None:
        chunk_size = chunking_cfg.get("chunk_size", 1000)
    if chunk_overlap is None:
        chunk_overlap = chunking_cfg.get("chunk_overlap", 200)

    separators = chunking_cfg.get("separators", ["\n\n", "\n", ". ", " "])

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators,
    )

    chunks = splitter.split_documents(documents)

    # 파일명 → 기관명/사업명 매핑 캐시
    filename_meta_cache: dict[str, dict[str, str]] = {}

    # 각 청크에 section title 메타데이터 추가 + page 인덱스 보정
    source_counters: dict[str, int] = {}
    for chunk in chunks:
        src = chunk.metadata.get("source", "")

        # page 메타데이터가 없는 청크(HWP 등)에 chunk 인덱스를 page로 부여
        if chunk.metadata.get("page") is None:
            source_counters[src] = source_counters.get(src, 0) + 1
            chunk.metadata["page"] = source_counters[src]

        # 파일명에서 기관명/사업명 추출하여 메타데이터에 추가
        if src not in filename_meta_cache:
            filename_meta_cache[src] = _extract_metadata_from_filename(src)
        for key, val in filename_meta_cache[src].items():
            chunk.metadata[key] = val

        # TOC/표지 탐지
        page = chunk.metadata.get("page")
        if _is_toc_chunk(chunk.page_content, page):
            chunk.metadata["is_toc"] = True

        # 섹션 제목 추출
        section = _extract_section_title(chunk.page_content)
        if section:
            chunk.metadata["section"] = section

    return chunks
