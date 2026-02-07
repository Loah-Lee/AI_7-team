"""문서 청킹 전략."""

from __future__ import annotations

import re
from typing import Iterator

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.utils.config import load_config

# 마크다운 테이블 행 패턴 (| 로 시작하고 | 로 끝나는 행)
_TABLE_ROW_RE = re.compile(r"^\|.+\|$")
# 테이블 구분선 (|---|---|)
_TABLE_SEP_RE = re.compile(r"^\|[-:\s|]+\|$")

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


_MIN_CHUNK_LENGTH = 50  # 이 길이 미만의 청크는 필터링


def _split_table_and_text(text: str) -> Iterator[tuple[str, bool]]:
    """텍스트를 테이블 블록과 일반 텍스트 블록으로 분리한다.

    소형 텍스트 블록(테이블 앞의 제목 등)은 다음 테이블 블록에 병합하여
    의미 없는 초소형 청크 생성을 방지한다.

    Yields:
        (block_text, is_table) 튜플.
    """
    lines = text.split("\n")
    # 1단계: 원시 블록으로 분리
    raw_blocks: list[tuple[str, bool]] = []
    current_block: list[str] = []
    in_table = False

    for line in lines:
        is_table_line = bool(_TABLE_ROW_RE.match(line.strip()))
        if is_table_line and not in_table:
            if current_block:
                raw_blocks.append(("\n".join(current_block), False))
                current_block = []
            in_table = True
            current_block.append(line)
        elif is_table_line and in_table:
            current_block.append(line)
        elif not is_table_line and in_table:
            if current_block:
                raw_blocks.append(("\n".join(current_block), True))
                current_block = []
            in_table = False
            current_block.append(line)
        else:
            current_block.append(line)

    if current_block:
        raw_blocks.append(("\n".join(current_block), in_table))

    # 2단계: 소형 텍스트 블록을 인접 테이블에 병합
    merged: list[tuple[str, bool]] = []
    for i, (block_text, is_table) in enumerate(raw_blocks):
        stripped = block_text.strip()
        if not stripped:
            continue
        if not is_table and len(stripped) < _MIN_CHUNK_LENGTH:
            # 다음 블록이 테이블이면 헤더로 병합
            if i + 1 < len(raw_blocks) and raw_blocks[i + 1][1]:
                next_text = raw_blocks[i + 1][0]
                raw_blocks[i + 1] = (f"{stripped}\n\n{next_text}", True)
                continue
            # 이전 블록이 테이블이면 끝에 추가
            if merged and merged[-1][1]:
                prev_text = merged[-1][0]
                merged[-1] = (f"{prev_text}\n\n{stripped}", True)
                continue
        merged.append((block_text, is_table))

    yield from merged


def _split_table_by_rows(
    table_text: str, chunk_size: int, header: str = "",
) -> list[str]:
    """마크다운 테이블을 행 경계에서 분할한다.

    테이블이 chunk_size 이하이면 그대로 반환.
    초과 시 헤더(첫 2행)를 유지하면서 행 단위로 분할.
    """
    if len(table_text) <= chunk_size:
        return [table_text]

    lines = table_text.split("\n")
    # 헤더 추출 (첫 행 + 구분선)
    table_header_lines: list[str] = []
    data_lines: list[str] = []
    for i, line in enumerate(lines):
        if i < 2 and (i == 0 or _TABLE_SEP_RE.match(line.strip())):
            table_header_lines.append(line)
        else:
            data_lines.append(line)

    table_header = "\n".join(table_header_lines)
    if header:
        table_header = f"{header}\n{table_header}"

    chunks: list[str] = []
    current: list[str] = []
    current_len = len(table_header) + 1  # +1 for newline

    for line in data_lines:
        line_len = len(line) + 1
        if current_len + line_len > chunk_size and current:
            chunk_text = f"{table_header}\n" + "\n".join(current) if table_header else "\n".join(current)
            chunks.append(chunk_text)
            current = []
            current_len = len(table_header) + 1

        current.append(line)
        current_len += line_len

    if current:
        chunk_text = f"{table_header}\n" + "\n".join(current) if table_header else "\n".join(current)
        chunks.append(chunk_text)

    return chunks


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

    # PDF 문서는 테이블 인식 청킹 적용
    plain_docs: list[Document] = []
    table_chunks: list[Document] = []

    for doc in documents:
        if doc.metadata.get("file_type") == "pdf":
            for block_text, is_table in _split_table_and_text(doc.page_content):
                block_text = block_text.strip()
                if not block_text:
                    continue
                if is_table:
                    # 테이블 블록: 행 경계에서 분할
                    for table_chunk in _split_table_by_rows(block_text, chunk_size):
                        table_chunks.append(
                            Document(
                                page_content=table_chunk,
                                metadata=dict(doc.metadata),
                            )
                        )
                else:
                    # 일반 텍스트: 기존 splitter 사용
                    plain_docs.append(
                        Document(
                            page_content=block_text,
                            metadata=dict(doc.metadata),
                        )
                    )
        else:
            plain_docs.append(doc)

    chunks = splitter.split_documents(plain_docs) + table_chunks

    # 최소 길이 미만의 청크 제거 (페이지 번호 잔여물, 빈 줄 등)
    chunks = [c for c in chunks if len(c.page_content.strip()) >= _MIN_CHUNK_LENGTH]

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
