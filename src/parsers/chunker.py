#!/usr/bin/env python3
"""
청킹 모듈

문서를 검색 가능한 청크로 분할합니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Chunk:
    """문서 청크 데이터 클래스.

    Attributes:
        text: 청크 텍스트
        source: 소스 파일명
        org: 기관명
        chunk_type: 청크 타입 (csv, pdf, hwp)
        metadata: 추가 메타데이터
    """
    text: str
    source: str
    org: str
    chunk_type: str = "unknown"
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리로 변환합니다.

        Returns:
            청크 딕셔너리
        """
        return {
            "text": self.text,
            "source": self.source,
            "org": self.org,
            "type": self.chunk_type,
            **self.metadata
        }


class MarkdownChunker:
    """마크다운 문서를 청크로 분할하는 클래스."""

    def __init__(
        self,
        chunk_by_section: bool = True,
        min_chunk_length: int = 50,
        max_chunk_length: int = 2000,
        overlap: int = 100
    ):
        """청커를 초기화합니다.

        Args:
            chunk_by_section: 섹션 단위로 청킹 여부
            min_chunk_length: 최소 청크 길이
            max_chunk_length: 최대 청크 길이
            overlap: 청크 간 중복 길이
        """
        self.chunk_by_section = chunk_by_section
        self.min_chunk_length = min_chunk_length
        self.max_chunk_length = max_chunk_length
        self.overlap = overlap

    def chunk_markdown(
        self,
        markdown: str,
        source: str,
        org: str,
        chunk_type: str = "csv"
    ) -> list[Chunk]:
        """마크다운을 청크로 분할합니다.

        Args:
            markdown: 마크다운 텍스트
            source: 소스 파일명
            org: 기관명
            chunk_type: 청크 타입

        Returns:
            청크 리스트
        """
        if self.chunk_by_section:
            return self._chunk_by_section(markdown, source, org, chunk_type)
        else:
            return self._chunk_by_size(markdown, source, org, chunk_type)

    def _chunk_by_section(
        self,
        markdown: str,
        source: str,
        org: str,
        chunk_type: str
    ) -> list[Chunk]:
        """섹션 단위로 청킹합니다.

        Args:
            markdown: 마크다운 텍스트
            source: 소스 파일명
            org: 기관명
            chunk_type: 청크 타입

        Returns:
            청크 리스트
        """
        sections = markdown.split('## ')
        chunks = []

        for section in sections:
            section = section.strip()
            if len(section) >= self.min_chunk_length:
                # 섹션 헤더가 있으면 다시 붙이기
                if section and not section.startswith('#'):
                    section = '## ' + section

                chunk = Chunk(
                    text=section,
                    source=source,
                    org=org,
                    chunk_type=chunk_type
                )
                chunks.append(chunk)

        return chunks

    def _chunk_by_size(
        self,
        markdown: str,
        source: str,
        org: str,
        chunk_type: str
    ) -> list[Chunk]:
        """크기 단위로 청킹합니다.

        Args:
            markdown: 마크다운 텍스트
            source: 소스 파일명
            org: 기관명
            chunk_type: 청크 타입

        Returns:
            청크 리스트
        """
        chunks = []
        start = 0

        while start < len(markdown):
            end = start + self.max_chunk_length

            # 가능하면 문장 경계에서 자르기
            if end < len(markdown):
                # 문장 종결 패턴 찾기
                sentence_end = re.search(r'[.!?]\s+\n', markdown[end-50:end])
                if sentence_end:
                    end = end - 50 + sentence_end.end()

            chunk_text = markdown[start:end].strip()

            if len(chunk_text) >= self.min_chunk_length:
                chunk = Chunk(
                    text=chunk_text,
                    source=source,
                    org=org,
                    chunk_type=chunk_type
                )
                chunks.append(chunk)

            start = end - self.overlap if end < len(markdown) else end

        return chunks

    def chunk_csv_row(
        self,
        markdown: str,
        source: str,
        org: str
    ) -> list[Chunk]:
        """CSV 행 마크다운을 청킹합니다.

        Args:
            markdown: 마크다운 텍스트
            source: 소스 파일명
            org: 기관명

        Returns:
            청크 리스트
        """
        sections = markdown.split('## ')
        chunks = []
        valid_sections = [s for s in sections if len(s.strip()) >= self.min_chunk_length]

        for section in valid_sections:
            chunk = Chunk(
                text=f"## {section}",
                source=source or 'csv',
                org=org,
                chunk_type="csv"
            )
            chunks.append(chunk)

        return chunks

    def chunk_document(
        self,
        content: str,
        filename: str,
        org: str,
        is_pdf: bool
    ) -> list[Chunk]:
        """문서 내용을 청킹합니다.

        Args:
            content: 문서 내용
            filename: 파일명
            org: 기관명
            is_pdf: PDF 여부

        Returns:
            청크 리스트
        """
        sections = content.split('## ') if content.startswith('#') else [content]
        chunks = []
        valid_sections = [s for s in sections if len(s.strip()) >= self.min_chunk_length]

        for section in valid_sections:
            chunk = Chunk(
                text=f"## {section}" if not section.startswith('##') else section,
                source=filename,
                org=org,
                chunk_type="pdf" if is_pdf else "hwp"
            )
            chunks.append(chunk)

        return chunks
