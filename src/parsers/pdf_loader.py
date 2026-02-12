#!/usr/bin/env python3
"""PDF 로더."""

from __future__ import annotations

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
            with pdfplumber.open(pdf_path) as pdf:
                parts.append(f"- **페이지 수**: {len(pdf.pages)}\n")
                parts.append("\n## 문서 내용\n\n")

                for page_num, page in enumerate(pdf.pages[:MAX_PAGES], 1):
                    try:
                        page_text = page.extract_text()
                        if page_text:
                            page_text = normalize_newlines(page_text)
                            parts.append(f"### 페이지 {page_num}\n")
                            parts.append(f"{page_text}\n\n")
                    except Exception:
                        continue

        except Exception as e:
            parts.append(f"\n*문서 변환 중 오류: {e}*\n")

        return "".join(parts)
