#!/usr/bin/env python3
"""PDF 로더."""

from __future__ import annotations

from typing import Any
from pathlib import Path

import pdfplumber
import sys
sys.path.insert(0, 'src')

from src.utils.config import MAX_PAGES, MIN_SECTION_LENGTH
from src.utils.helpers import normalize_newlines, remove_josa


class PDFMarkdownConverter:
    """PDF 문서를 마크다운으로 변환하는 클래스."""

    @staticmethod
    def extract_org_name(filename: str) -> str:
        """파일명에서 기관명을 추출합니다."""
        parts = filename.replace('.hwp', '').replace('.pdf', '').replace('.hwpx', '').split('_')
        if parts:
            return remove_josa(parts[0].strip())
        return Path(filename).stem

    @staticmethod
    def split_markdown_sections(markdown: str) -> list[str]:
        """마크다운을 섹션 단위로 분할합니다."""
        return markdown.split('## ')

    @staticmethod
    def filter_valid_sections(sections: list[str]) -> list[str]:
        """유효한 섹션만 필터링합니다."""
        return [s for s in sections if len(s.strip()) > MIN_SECTION_LENGTH]

    @staticmethod
    def _sanitize_cell(cell: Any) -> str:
        """표 셀 텍스트를 정리합니다."""
        if cell is None:
            return ""
        return normalize_newlines(str(cell)).replace("\n", " ").strip()

    @classmethod
    def _table_to_markdown(cls, table: list[list[Any]]) -> str:
        """pdfplumber 표를 마크다운 표로 변환합니다."""
        if not table:
            return ""

        cleaned_rows = [[cls._sanitize_cell(cell) for cell in row] for row in table if row]
        cleaned_rows = [row for row in cleaned_rows if any(cell for cell in row)]
        if not cleaned_rows:
            return ""

        col_count = max(len(row) for row in cleaned_rows)
        normalized = [row + [""] * (col_count - len(row)) for row in cleaned_rows]

        header = normalized[0]
        if not any(header):
            header = [f"col_{i+1}" for i in range(col_count)]
            body = normalized
        else:
            body = normalized[1:]

        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * col_count) + " |",
        ]
        for row in body:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    def extract_pages(
        self,
        pdf_path: str | Path,
        max_pages: int | None = None,
        include_tables: bool = True
    ) -> list[dict[str, Any]]:
        """PDF를 페이지 단위로 추출합니다."""
        path = Path(pdf_path)
        pages: list[dict[str, Any]] = []
        limit = MAX_PAGES if max_pages is None else max_pages

        try:
            with pdfplumber.open(path) as pdf:
                source_pages = pdf.pages if limit <= 0 else pdf.pages[:limit]
                for page_num, page in enumerate(source_pages, 1):
                    page_text = normalize_newlines(page.extract_text() or "").strip()

                    table_markdowns: list[str] = []
                    if include_tables:
                        raw_tables = page.extract_tables() or []
                        for idx, table in enumerate(raw_tables, 1):
                            md_table = self._table_to_markdown(table)
                            if md_table:
                                table_markdowns.append(f"#### 표 {idx}\n{md_table}")

                    parts: list[str] = []
                    if page_text:
                        parts.append(page_text)
                    if table_markdowns:
                        parts.append("\n\n".join(table_markdowns))

                    content = "\n\n".join(parts).strip()
                    if not content:
                        continue

                    pages.append({
                        "page": page_num,
                        "text": page_text,
                        "tables": table_markdowns,
                        "table_count": len(table_markdowns),
                        "content": content,
                    })
        except Exception:
            return []

        return pages

    def convert(self, pdf_path: str | Path, org_name: str | None = None) -> str:
        """PDF를 마크다운으로 변환합니다."""
        path = Path(pdf_path)
        filename = path.name
        org_name = org_name or self.extract_org_name(filename)

        parts = [f"# {org_name}\n"]
        parts.append("## 원본 문서 정보\n")
        parts.append(f"- **파일명**: {filename}\n")
        parts.append("- **파일 형식**: PDF\n")

        try:
            with pdfplumber.open(path) as pdf:
                total_pages = len(pdf.pages)
        except Exception:
            total_pages = 0

        pages = self.extract_pages(path, max_pages=MAX_PAGES, include_tables=True)
        if pages:
            if total_pages:
                shown_pages = total_pages if MAX_PAGES <= 0 else min(total_pages, MAX_PAGES)
            else:
                shown_pages = len(pages)
            parts.append(f"- **페이지 수**: {total_pages or '확인 불가'}\n")
            parts.append(f"- **추출 페이지 수**: {shown_pages}\n")
            parts.append("\n## 문서 내용\n\n")
            for page in pages:
                parts.append(f"### 페이지 {page['page']}\n")
                parts.append(f"{page['content']}\n\n")
        else:
            parts.append("\n*문서 내용 추출 실패*\n")

        return "".join(parts)
